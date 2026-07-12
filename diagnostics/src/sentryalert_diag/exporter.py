from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from .paths import PACKAGE_ROOT, exports_dir, session_root
from .modules.registry import create_module
from .state import utc_now
from .storage_layout import collect_storage_layout, render_storage_layout_report
from .system import read_text, run_command


def _version() -> str:
    return (PACKAGE_ROOT / "VERSION").read_text(encoding="utf-8").strip()


def _sentryalert_version(root: Path) -> str:
    for name in ("package.json", "package-lock.json"):
        package = root / name
        try:
            value = json.loads(package.read_text(encoding="utf-8-sig"))
            version = value.get("version")
            if version:
                return str(version)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    try:
        with (root / "app.js").open("r", encoding="utf-8", errors="replace") as source:
            banner = source.readline(256)
        match = re.fullmatch(r"\s*//\s*v(\d+(?:\.\d+){2,3})\s*", banner)
        if match:
            return match.group(1)
    except OSError:
        pass
    return "unavailable (package metadata absent)"


def _configuration_summary(root: Path) -> dict[str, Any]:
    helper = PACKAGE_ROOT / "helpers" / "config-summary.js"
    result = run_command(["node", str(helper), str(root / "config.js")])
    if result["exit_code"] == 0:
        try:
            return json.loads(result["output"])
        except (ValueError, json.JSONDecodeError):
            pass
    return {
        "available": False,
        "error": result["error"] or "Could not read configuration summary",
    }


def _inventory(config: dict[str, Any]) -> dict[str, Any]:
    timeout = int(config["command_timeout_seconds"])
    sentryalert_root = Path(str(config["sentryalert_root"]))
    commands = {
        "kernel": ["uname", "-a"],
        "hardware": ["lscpu"],
        "block_devices": ["lsblk", "--json", "-O", "-b"],
        "mounts": ["findmnt", "--json"],
        "usb_devices": ["lsusb"],
        "usb_tree": ["lsusb", "-t"],
        "disk_usage": ["df", "-P", "-T"],
    }
    return {
        "collected_at": utc_now(),
        "package_version": _version(),
        "sentryalert_version": _sentryalert_version(sentryalert_root),
        "os_release": read_text("/etc/os-release"),
        "commands": {
            name: run_command(arguments, timeout) for name, arguments in commands.items()
        },
        "storage_layout": collect_storage_layout(timeout),
        "configuration": _configuration_summary(sentryalert_root),
    }


def _summary(state: dict[str, Any], inventory: dict[str, Any]) -> str:
    delivery = state.get("telegram_delivery", {})
    lines = [
        f"SentryAlert {str(state.get('module', 'unknown')).title()} Diagnostics",
        "=" * 48,
        "",
        f"Session: {state.get('session_id', 'unknown')}",
        f"Status: {state.get('status', 'unknown')}",
        f"Started: {state.get('start_timestamp', 'unknown')}",
        f"Completed: {state.get('completed_at', 'unknown')}",
        f"Powered-on runtime: {state.get('runtime_consumed_seconds', 0):.1f} seconds",
        f"Target runtime: {state.get('runtime_target_seconds', 0)} seconds",
        f"Detected events: {state.get('event_count', 0)}",
        f"Snapshots: {state.get('snapshot_count', 0)}",
        f"Package version: {inventory.get('package_version', 'unknown')}",
        f"SentryAlert version: {inventory.get('sentryalert_version', 'unknown')}",
        f"Telegram delivery at bundle creation: {delivery.get('status', 'not attempted')}",
        "",
        "This bundle is observational. Diagnostics did not modify SentryAlert",
        "or the subsystem being investigated.",
        "",
        "Privacy note: hardware and USB identifiers may be present because they",
        "are useful when comparing affected systems. Telegram credentials are",
        "never included.",
        "",
    ]
    return "\n".join(lines)


def _read_json_lines(path: Path) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip():
                value = json.loads(line)
                if isinstance(value, dict):
                    values.append(value)
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    return values


def _report(state: dict[str, Any], session: Path, config: dict[str, Any]) -> str:
    module_name = str(state.get("module", "usb"))
    contract = create_module(module_name, int(config["command_timeout_seconds"])).contract()
    events = _read_json_lines(session / "logs" / "events.jsonl")
    samples = _read_json_lines(session / "logs" / "samples.jsonl")
    known = [event for event in events if event.get("classification") == "known"]
    candidates = [event for event in events if event.get("classification") == "candidate"]
    markers = [event for event in events if event.get("classification") == "user_marker"]
    lines = [
        str(contract["title"]),
        "=" * len(str(contract["title"])),
        "",
        f"Result: {'EVENTS REQUIRE REVIEW' if events else 'NO MATCHING EVENTS DETECTED'}",
        f"Known errors: {len(known)}",
        f"Unclassified suspicious events: {len(candidates)}",
        f"User-marked incidents: {len(markers)}",
        f"Samples collected: {len(samples)}",
        "",
        "Source coverage",
        "---------------",
    ]
    coverage = samples[-1].get("coverage", {}) if samples else {}
    for source in contract.get("sources", []):
        name = str(source["name"])
        value = coverage.get(name, {})
        status = "available" if value.get("available") else "UNAVAILABLE"
        lines.append(f"- {name}: {status} — {value.get('detail', 'not reported')}")
    lines.extend(["", "Event timeline", "--------------"])
    if not events:
        lines.append("No known or suspicious events were detected during this session.")
    for event in events:
        lines.append(
            f"{event.get('timestamp', 'unknown')} [{str(event.get('classification', 'event')).upper()}] "
            f"{event.get('source', 'unknown')}: {event.get('message', '')}"
        )
    lines.extend([
        "",
        "Interpretation note",
        "-------------------",
        "A clean result means no matching event was observed in the available sources.",
        "It is not proof that no fault occurred when a required source is unavailable.",
        "",
    ])
    return "\n".join(lines)


def create_bundle(state: dict[str, Any], config: dict[str, Any]) -> Path:
    module_name = str(state.get("module", "usb"))
    output_dir = exports_dir(module_name)
    output_dir.mkdir(parents=True, exist_ok=True)
    session_id = str(state["session_id"])
    session = session_root(session_id, module_name)
    inventory = _inventory(config)
    filename = f"{module_name}-diag-{session_id}.zip"
    final_path = output_dir / filename
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{filename}.", suffix=".tmp", dir=output_dir
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    manifest: dict[str, str] = {}

    def add_bytes(archive: zipfile.ZipFile, name: str, payload: bytes) -> None:
        archive.writestr(name, payload)
        manifest[name] = hashlib.sha256(payload).hexdigest()

    try:
        with zipfile.ZipFile(
            temporary_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
        ) as archive:
            add_bytes(
                archive,
                "state.json",
                json.dumps(state, indent=2, sort_keys=True).encode("utf-8") + b"\n",
            )
            add_bytes(
                archive,
                "inventory.json",
                json.dumps(inventory, indent=2, sort_keys=True).encode("utf-8") + b"\n",
            )
            add_bytes(archive, "SUMMARY.txt", _summary(state, inventory).encode("utf-8"))
            add_bytes(archive, "REPORT.txt", _report(state, session, config).encode("utf-8"))
            add_bytes(
                archive,
                "STORAGE_LAYOUT.txt",
                render_storage_layout_report(inventory["storage_layout"]).encode("utf-8"),
            )
            add_bytes(
                archive,
                "CONTRACT.json",
                json.dumps(
                    create_module(module_name, int(config["command_timeout_seconds"])).contract(),
                    indent=2,
                    sort_keys=True,
                ).encode("utf-8") + b"\n",
            )
            if session.exists():
                for path in sorted(session.rglob("*")):
                    if path.is_file():
                        payload = path.read_bytes()
                        add_bytes(archive, f"session/{path.relative_to(session)}", payload)
            add_bytes(
                archive,
                "MANIFEST.sha256",
                "".join(f"{digest}  {name}\n" for name, digest in sorted(manifest.items())).encode(
                    "utf-8"
                ),
            )
        with temporary_path.open("rb") as bundle:
            os.fsync(bundle.fileno())
        os.replace(temporary_path, final_path)
        directory = os.open(output_dir, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return final_path
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
