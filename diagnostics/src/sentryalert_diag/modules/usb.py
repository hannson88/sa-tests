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
from ..system import read_text, run_command
from .base import DiagnosticModule


EVENT_PATTERN = re.compile(
    r"(usb.*(?:reset|disconnect|descriptor|timeout|offline|error)|"
    r"(?:buffer )?i/o error|exfat.*(?:error|failed|corrupt)|"
    r"device.*offline|timed? ?out)",
    re.IGNORECASE,
)


class UsbDiagnosticModule(DiagnosticModule):
    name = "usb"

    def __init__(self, timeout: int = 10) -> None:
        self.timeout = timeout
        self._known_kernel_lines: set[str] | None = None

    def _command(self, arguments: list[str]) -> dict[str, Any]:
        return run_command(arguments, self.timeout)

    def _kernel_lines(self) -> list[str]:
        result = self._command(["dmesg", "--color=never"])
        if result["exit_code"] != 0:
            result = self._command(["journalctl", "-k", "-b", "--no-pager", "-o", "short-monotonic"])
        return [line for line in result["output"].splitlines() if line.strip()]

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

        kernel_lines = self._kernel_lines()[-500:]
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
        }

    def check_events(self) -> list[dict[str, Any]]:
        lines = self._kernel_lines()
        fingerprints = {
            hashlib.sha256(line.encode("utf-8", errors="replace")).hexdigest(): line
            for line in lines[-4000:]
        }
        if self._known_kernel_lines is None:
            self._known_kernel_lines = set(fingerprints)
            return []
        new_keys = set(fingerprints).difference(self._known_kernel_lines)
        self._known_kernel_lines = set(fingerprints)
        return [
            {
                "timestamp": utc_now(),
                "source": "kernel",
                "fingerprint": key,
                "message": fingerprints[key],
            }
            for key in new_keys
            if EVENT_PATTERN.search(fingerprints[key])
        ]

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
