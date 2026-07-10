from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from ..atomic import atomic_write_json
from ..state import utc_now
from ..system import MAX_OUTPUT_BYTES, read_text, redact_text, run_command
from .base import DiagnosticModule


EVENT_PATTERN = re.compile(
    r"(usb.*(?:reset|disconnect|descriptor|timeout|offline|error)|"
    r"(?:buffer )?i/o error|exfat.*(?:error|failed|corrupt)|"
    r"device.*offline|timed? ?out)",
    re.IGNORECASE,
)
USB_CANDIDATE_PATTERN = re.compile(
    r"(usb|dwc3|gadget|mass.storage|block|sd[a-z]|exfat|mount).{0,80}"
    r"(warn|error|fail|reset|disconnect|timeout|offline|corrupt|read.only|UI_[a-z]\d+)",
    re.IGNORECASE,
)
APP_EVENT_PATTERN = re.compile(r"\bUI_[a-z]\d+\b|usb.{0,80}(error|fail|malfunction)", re.IGNORECASE)
APP_LOG_DIRS = (Path("/root/.pm2/logs"), Path("/mutable/.pm2/logs"), Path("/etc/.pm2/logs"))


class UsbDiagnosticModule(DiagnosticModule):
    name = "usb"
    title = "SentryAlert USB Compatibility Diagnostics"

    def __init__(self, timeout: int = 10) -> None:
        self.timeout = timeout
        self._previous_kernel_lines: list[str] | None = None
        self._previous_app_lines: list[str] | None = None

    def contract(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "module": self.name,
            "title": self.title,
            "collection_levels": {
                "sample": "bounded raw kernel, application, USB, mount, block and system state",
                "event": "known errors and unclassified USB-related warning candidates",
                "snapshot": "full sample plus process, interrupt and kernel-module context",
            },
            "event_severities": ["error", "warning", "notice"],
            "retention": "bounded by maximum_log_bytes and maximum_snapshots",
            "failure_modes": [
                "USB disconnect or reset", "I/O error", "USB timeout",
                "filesystem error", "gadget state failure", "SentryAlert USB UI error",
            ],
            "sources": [
                {"name": "kernel_log", "required": True, "fallback": "journalctl -k"},
                {"name": "application_log", "required": True, "fallback": "PM2 log files"},
                {"name": "usb_gadget_state", "required": True},
                {"name": "mounts_and_block_devices", "required": True},
            ],
        }

    def _command(self, arguments: list[str]) -> dict[str, Any]:
        return run_command(arguments, self.timeout)

    def _kernel_lines(self) -> list[str]:
        result = self._command(["dmesg", "--color=never"])
        if result["exit_code"] != 0:
            result = self._command(["journalctl", "-k", "-b", "--no-pager", "-o", "short-monotonic"])
        return [line for line in result["output"].splitlines() if line.strip()]

    def _app_lines(self) -> tuple[list[str], dict[str, Any]]:
        result = run_command(
            ["pm2", "logs", "SentryAlert", "--nostream", "--raw", "--lines", "500"],
            self.timeout,
            extra_env={"HOME": "/root", "PM2_HOME": "/root/.pm2"},
        )
        lines = (result["output"] + "\n" + result["error"]).splitlines()
        fallback_lines, fallback_result = self._app_log_file_lines()
        if fallback_lines:
            lines.extend(fallback_lines)
            result = {
                **result,
                "fallback": fallback_result,
                "exit_code": 0 if result["exit_code"] == 0 else fallback_result["exit_code"],
                "error": result["error"] if result["exit_code"] == 0 else fallback_result["error"],
            }
        return [line for line in lines if line.strip()][-1000:], result

    def _app_log_file_lines(self) -> tuple[list[str], dict[str, Any]]:
        candidates: list[Path] = []
        for root in APP_LOG_DIRS:
            if root.is_dir():
                candidates.extend(sorted(root.glob("SentryAlert*.log")))
                candidates.extend(sorted(root.glob("sentryalert*.log")))
        lines: list[str] = []
        read_files: list[str] = []
        errors: list[str] = []
        for path in candidates:
            try:
                data = path.read_bytes()[-MAX_OUTPUT_BYTES:]
                lines.extend(redact_text(data.decode("utf-8", errors="replace")).splitlines())
                read_files.append(str(path))
            except OSError as error:
                errors.append(f"{path}: {error}")
        return lines[-1000:], {
            "command": ["read_pm2_log_files"],
            "exit_code": 0 if read_files else 1,
            "output": f"read {len(read_files)} file(s): " + ", ".join(read_files),
            "error": "; ".join(errors) if errors else ("" if read_files else "no PM2 log files found"),
        }

    @staticmethod
    def _new_lines(previous: list[str] | None, current: list[str]) -> list[str]:
        if previous is None:
            return []
        maximum = min(len(previous), len(current))
        overlap = 0
        for size in range(maximum, 0, -1):
            if previous[-size:] == current[:size]:
                overlap = size
                break
        return current[overlap:]

    def collect_sample(self) -> dict[str, Any]:
        configfs = Path("/sys/kernel/config/usb_gadget/sentryalert")
        gadget: dict[str, Any] = {"present": configfs.is_dir()}
        if configfs.is_dir():
            gadget["udc"] = read_text(str(configfs / "UDC"), 4096)
            gadget["state"] = read_text("/sys/class/udc/" + (gadget["udc"] or "").strip() + "/state", 4096)
            luns: list[dict[str, Any]] = []
            for path in sorted(configfs.glob("functions/mass_storage.*/lun.*")):
                luns.append(
                    {
                        "name": path.name,
                        "file": read_text(str(path / "file"), 4096),
                        "forced_eject": read_text(str(path / "forced_eject"), 4096),
                        "ro": read_text(str(path / "ro"), 4096),
                    }
                )
            gadget["luns"] = luns

        kernel_lines = self._kernel_lines()[-1000:]
        app_lines, app_result = self._app_lines()
        matching_kernel = [line for line in kernel_lines if EVENT_PATTERN.search(line)][-100:]
        recent_usb_kernel = [
            line for line in kernel_lines if re.search(r"\busb\b", line, re.IGNORECASE)
        ][-100:]
        return {
            "timestamp": utc_now(),
            "monotonic_seconds": time.monotonic(),
            "uptime": read_text("/proc/uptime", 4096),
            "load_average": read_text("/proc/loadavg", 4096),
            "memory": read_text("/proc/meminfo", 128 * 1024),
            "filesystem": self._command(["df", "-P", "-T"]),
            "mounts": self._command(["findmnt", "--json"]),
            "block_devices": self._command(
                ["lsblk", "--json", "-O", "-b"]
            ),
            "usb_devices": self._command(["lsusb"]),
            "usb_tree": self._command(["lsusb", "-t"]),
            "gadget": gadget,
            "recent_usb_kernel_messages": recent_usb_kernel,
            "matching_kernel_messages": matching_kernel,
            "recent_application_messages": app_lines[-500:],
            "coverage": {
                "kernel_log": {
                    "available": bool(kernel_lines),
                    "detail": "available" if kernel_lines else "dmesg and kernel journal returned no lines",
                },
                "application_log": {
                    "available": app_result["exit_code"] == 0,
                    "detail": app_result["error"] or "available",
                },
                "usb_gadget_state": {
                    "available": configfs.is_dir(),
                    "detail": "available" if configfs.is_dir() else "gadget path not present",
                },
                "mounts_and_block_devices": {"available": True, "detail": "collected"},
            },
        }

    def check_events(self) -> list[dict[str, Any]]:
        kernel = self._kernel_lines()[-4000:]
        app, _result = self._app_lines()
        new_kernel = self._new_lines(self._previous_kernel_lines, kernel)
        new_app = self._new_lines(self._previous_app_lines, app)
        self._previous_kernel_lines = kernel
        self._previous_app_lines = app
        events: list[dict[str, Any]] = []
        for source, lines, known_pattern, candidate_pattern in (
            ("kernel", new_kernel, EVENT_PATTERN, USB_CANDIDATE_PATTERN),
            ("application", new_app, APP_EVENT_PATTERN, USB_CANDIDATE_PATTERN),
        ):
            for line in lines:
                classification = (
                    "known" if known_pattern.search(line)
                    else "candidate" if candidate_pattern.search(line)
                    else None
                )
                if not classification:
                    continue
                events.append({
                "timestamp": utc_now(),
                    "source": source,
                    "classification": classification,
                    "severity": "error" if classification == "known" else "warning",
                    "fingerprint": hashlib.sha256(line.encode("utf-8", errors="replace")).hexdigest(),
                    "message": line,
                })
        return events

    def collect_snapshot(self, reason: dict[str, Any], destination: Path) -> None:
        snapshot = {
            "timestamp": utc_now(),
            "reason": reason,
            "sample": self.collect_sample(),
            "processes": self._command(["ps", "-eo", "pid,ppid,stat,etimes,comm,args"]),
            "interrupts": read_text("/proc/interrupts"),
            "modules": read_text("/proc/modules"),
        }
        atomic_write_json(destination, snapshot)
