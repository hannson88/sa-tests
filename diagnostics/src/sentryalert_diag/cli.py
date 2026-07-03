from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

from .config import ensure_config, load_config
from .exporter import create_bundle
from .paths import PACKAGE_ROOT, session_root
from .runner import run_daemon
from .state import boot_id, load_state, save_state, state_lock, utc_now
from .telegram import deliver


def require_root() -> None:
    if os.geteuid() != 0 and not os.environ.get("SENTRYALERT_DIAG_ALLOW_NONROOT"):
        raise SystemExit("This command must be run as root.")


def parse_duration(value: str) -> int:
    suffixes = {"m": 60, "h": 3600, "s": 1}
    value = value.strip().lower()
    if value[-1:] in suffixes:
        number, multiplier = value[:-1], suffixes[value[-1]]
    else:
        number, multiplier = value, 1
    try:
        seconds = int(number) * multiplier
    except ValueError as exception:
        raise argparse.ArgumentTypeError("Use a duration such as 30m, 2h, or 24h") from exception
    if seconds <= 0:
        raise argparse.ArgumentTypeError("Duration must be greater than zero")
    return seconds


def systemctl(*arguments: str) -> None:
    if os.environ.get("SENTRYALERT_DIAG_SKIP_SYSTEMD"):
        return
    subprocess.run(["systemctl", *arguments], check=False)


def command_start(args: argparse.Namespace) -> int:
    require_root()
    ensure_config()
    config = load_config()
    target = args.duration or int(config["default_runtime_seconds"])
    package_version = (PACKAGE_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    session_id = uuid.uuid4().hex
    with state_lock():
        current = load_state()
        if current and current.get("enabled"):
            raise SystemExit(f"USB diagnostics are already running ({current.get('session_id')}).")
        root = session_root(session_id)
        (root / "logs").mkdir(parents=True, exist_ok=True)
        (root / "snapshots").mkdir(parents=True, exist_ok=True)
        state = {
            "schema_version": 1,
            "package_version": package_version,
            "module": "usb",
            "enabled": True,
            "status": "running",
            "session_id": session_id,
            "runtime_target_seconds": target,
            "runtime_consumed_seconds": 0.0,
            "start_timestamp": utc_now(),
            "last_checkpoint_at": utc_now(),
            "last_boot_id": boot_id(),
            "event_count": 0,
            "snapshot_count": 0,
            "stop_requested": False,
            "telegram_delivery": {"status": "not_attempted"},
        }
        save_state(state)
    systemctl("start", "sentryalert-diagnostics.service")
    print(f"USB diagnostics started: {session_id}")
    print(f"Powered-on runtime target: {target} seconds")
    return 0


def command_status(_args: argparse.Namespace) -> int:
    state = load_state()
    if not state:
        print("USB diagnostics have not been started.")
        return 1
    print(json.dumps(state, indent=2, sort_keys=True))
    return 0


def command_stop(_args: argparse.Namespace) -> int:
    require_root()
    with state_lock():
        state = load_state(required=True)
        if not state.get("enabled"):
            print("USB diagnostics are not running.")
            return 0
        state["stop_requested"] = True
        save_state(state)
    systemctl("start", "sentryalert-diagnostics.service")
    systemctl("kill", "--signal=SIGUSR1", "sentryalert-diagnostics.service")
    print("Stop requested. The current evidence will be exported.")
    return 0


def command_export(_args: argparse.Namespace) -> int:
    require_root()
    config = load_config()
    state = load_state(required=True)
    bundle = create_bundle(state, config)
    with state_lock():
        state = load_state(required=True)
        state["export_path"] = str(bundle)
        save_state(state)
    print(bundle)
    return 0


def command_resend(_args: argparse.Namespace) -> int:
    require_root()
    config = load_config()
    state = load_state(required=True)
    export_path = state.get("export_path")
    if not export_path or not Path(export_path).is_file():
        export_path = str(create_bundle(state, config))
    result = deliver(Path(export_path), config)
    with state_lock():
        state = load_state(required=True)
        state["export_path"] = export_path
        state["telegram_delivery"] = result
        save_state(state)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") in {"sent", "disabled"} else 1


def command_version(_args: argparse.Namespace) -> int:
    version = (PACKAGE_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    build_date = (PACKAGE_ROOT / "BUILD_DATE").read_text(encoding="utf-8").strip()
    print(f"SentryAlert Diagnostics {version} (build {build_date})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sentryalert-diag")
    subparsers = parser.add_subparsers(dest="command", required=True)
    start = subparsers.add_parser("start")
    start.add_argument("--duration", type=parse_duration)
    start.set_defaults(function=command_start)
    subparsers.add_parser("status").set_defaults(function=command_status)
    subparsers.add_parser("stop").set_defaults(function=command_stop)
    subparsers.add_parser("export").set_defaults(function=command_export)
    subparsers.add_parser("resend").set_defaults(function=command_resend)
    subparsers.add_parser("version").set_defaults(function=command_version)
    subparsers.add_parser("daemon").set_defaults(function=lambda _args: run_daemon())
    return parser


def main() -> int:
    parser = build_parser()
    arguments = parser.parse_args()
    return int(arguments.function(arguments))


if __name__ == "__main__":
    sys.exit(main())
