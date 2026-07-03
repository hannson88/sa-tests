from __future__ import annotations

import hashlib
import json
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from .paths import EXPORTS_DIR, PACKAGE_ROOT, session_root
from .state import utc_now
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
        "configuration": _configuration_summary(sentryalert_root),
    }


def _summary(state: dict[str, Any], inventory: dict[str, Any]) -> str:
    delivery = state.get("telegram_delivery", {})
    lines = [
        "SentryAlert USB Compatibility Diagnostics",
        "==========================================",
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
        "This bundle is observational. Diagnostics did not modify USB gadget",
        "configuration, backing storage, mounts, partitions, or SentryAlert.",
        "",
        "Privacy note: hardware and USB identifiers may be present because they",
        "are useful when comparing affected systems. Telegram credentials are",
        "never included.",
        "",
    ]
    return "\n".join(lines)


def create_bundle(state: dict[str, Any], config: dict[str, Any]) -> Path:
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    session_id = str(state["session_id"])
    session = session_root(session_id)
    inventory = _inventory(config)
    filename = f"usb-diag-{session_id}.zip"
    final_path = EXPORTS_DIR / filename
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{filename}.", suffix=".tmp", dir=EXPORTS_DIR
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
        directory = os.open(EXPORTS_DIR, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return final_path
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
