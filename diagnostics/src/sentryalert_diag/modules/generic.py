from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from ..atomic import atomic_write_json
from ..state import utc_now
from ..system import read_text, run_command
from .base import DiagnosticModule


PROFILES: dict[str, dict[str, Any]] = {
    "app": {
        "title": "SentryAlert Application Diagnostics",
        "failure_modes": ["application crash", "PM2 restart", "uncaught exception", "UI error"],
        "commands": {
            "pm2_status": ["pm2", "jlist"],
            "application_logs": ["pm2", "logs", "SentryAlert", "--nostream", "--raw", "--lines", "500"],
        },
        "pattern": r"\b(error|exception|fatal|crash|restart|UI_[a-z]\d+)\b",
    },
    "storage": {
        "title": "Storage and Filesystem Diagnostics",
        "failure_modes": ["I/O error", "filesystem corruption", "mount loss", "disk full"],
        "commands": {
            "disk_usage": ["df", "-P", "-T"],
            "mounts": ["findmnt", "--json"],
            "block_devices": ["lsblk", "--json", "-O", "-b"],
            "kernel_storage_log": ["journalctl", "-k", "-b", "--no-pager", "-n", "1000"],
        },
        "pattern": r"(i/o error|filesystem|exfat|ext4|mount|read-only|no space|corrupt|blk_update)",
    },
    "camera": {
        "title": "Camera and Recording Diagnostics",
        "failure_modes": ["camera unavailable", "encoder failure", "dropped frame", "recording stopped"],
        "commands": {
            "camera_devices": ["sh", "-c", "ls -l /dev/video* 2>&1"],
            "recording_processes": ["ps", "-eo", "pid,stat,etimes,%cpu,%mem,args"],
            "application_logs": ["pm2", "logs", "SentryAlert", "--nostream", "--raw", "--lines", "500"],
        },
        "pattern": r"(camera|video|ffmpeg|encoder|frame|record).*(error|fail|drop|timeout|stopp)",
    },
    "network": {
        "title": "Network and Delivery Diagnostics",
        "failure_modes": ["interface loss", "DNS failure", "route failure", "Telegram failure"],
        "commands": {
            "addresses": ["ip", "-json", "address"],
            "routes": ["ip", "-json", "route"],
            "dns": ["cat", "/etc/resolv.conf"],
            "network_log": ["journalctl", "-b", "--no-pager", "-n", "1000"],
        },
        "pattern": r"(network|dns|route|telegram|socket|connect).*(error|fail|timeout|unreach|down)",
    },
    "system": {
        "title": "System and Boot Diagnostics",
        "failure_modes": ["service failure", "kernel error", "thermal event", "memory pressure", "reboot"],
        "commands": {
            "failed_services": ["systemctl", "--failed", "--no-pager"],
            "boot_log": ["journalctl", "-b", "--no-pager", "-n", "1500"],
            "temperatures": ["sh", "-c", "for f in /sys/class/thermal/thermal_zone*/temp; do echo \"$f $(cat \"$f\")\"; done"],
        },
        "pattern": r"\b(failed|fatal|panic|oom|out of memory|thermal|overheat|watchdog)\b",
    },
    "performance": {
        "title": "Performance Diagnostics",
        "failure_modes": ["high load", "memory exhaustion", "process stall"],
        "commands": {
            "processes": ["ps", "-eo", "pid,ppid,stat,etimes,%cpu,%mem,comm,args", "--sort=-%cpu"],
            "vmstat": ["vmstat"],
            "pressure": ["sh", "-c", "cat /proc/pressure/* 2>/dev/null"],
        },
        "pattern": r"\b(oom|out of memory|hung task|blocked for more than|watchdog)\b",
    },
}


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


class CommandDiagnosticModule(DiagnosticModule):
    def __init__(self, name: str, timeout: int = 10) -> None:
        self.name = name
        self.profile = PROFILES[name]
        self.title = str(self.profile["title"])
        self.timeout = timeout
        self.previous: dict[str, list[str]] | None = None

    def contract(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "module": self.name,
            "title": self.title,
            "collection_levels": {
                "sample": "bounded raw output from every declared source",
                "event": "new source lines matching the module's suspicious-event classifier",
                "snapshot": "full module sample and process context",
            },
            "event_severities": ["warning", "notice"],
            "retention": "bounded by maximum_log_bytes and maximum_snapshots",
            "failure_modes": self.profile["failure_modes"],
            "sources": [
                {"name": name, "required": True, "command": command}
                for name, command in self.profile["commands"].items()
            ],
        }

    def _collect(self) -> dict[str, dict[str, Any]]:
        return {
            name: run_command(command, self.timeout)
            for name, command in self.profile["commands"].items()
        }

    def collect_sample(self) -> dict[str, Any]:
        sources = self._collect()
        return {
            "timestamp": utc_now(),
            "monotonic_seconds": time.monotonic(),
            "uptime": read_text("/proc/uptime", 4096),
            "load_average": read_text("/proc/loadavg", 4096),
            "memory": read_text("/proc/meminfo", 128 * 1024),
            "sources": sources,
            "coverage": {
                name: {
                    "available": value.get("exit_code") == 0,
                    "detail": value.get("error") or "available",
                }
                for name, value in sources.items()
            },
        }

    def check_events(self) -> list[dict[str, Any]]:
        sources = self._collect()
        current = {
            name: value.get("output", "").splitlines()[-4000:]
            for name, value in sources.items()
        }
        if self.previous is None:
            self.previous = current
            return []
        pattern = re.compile(str(self.profile["pattern"]), re.IGNORECASE)
        events: list[dict[str, Any]] = []
        for source, lines in current.items():
            for line in _new_lines(self.previous.get(source), lines):
                if pattern.search(line):
                    events.append({
                        "timestamp": utc_now(),
                        "source": source,
                        "classification": "candidate",
                        "severity": "warning",
                        "message": line,
                    })
        self.previous = current
        return events

    def collect_snapshot(self, reason: dict[str, Any], destination: Path) -> None:
        atomic_write_json(destination, {
            "timestamp": utc_now(),
            "reason": reason,
            "sample": self.collect_sample(),
            "processes": run_command(["ps", "-eo", "pid,ppid,stat,etimes,%cpu,%mem,args"], self.timeout),
        })
