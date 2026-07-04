from __future__ import annotations

import os
import signal
import time
from pathlib import Path
from typing import Any

from .config import load_config
from .exporter import create_bundle
from .modules.registry import create_module
from .paths import session_root
from .state import (
    append_json_line,
    boot_id,
    load_state,
    save_state,
    state_lock,
    utc_now,
)
from .telegram import deliver


class DiagnosticsRunner:
    def __init__(self) -> None:
        self.config = load_config()
        self.wake_requested = False
        self.shutdown_requested = False
        self.last_snapshot_monotonic: float | None = None
        state = load_state()
        module_name = str(state.get("module", "usb")) if state else "usb"
        self.module = create_module(module_name, int(self.config["command_timeout_seconds"]))

    def _wake(self, _signum: int, _frame: Any) -> None:
        self.wake_requested = True

    def _shutdown(self, _signum: int, _frame: Any) -> None:
        self.shutdown_requested = True
        self.wake_requested = True

    def _snapshot(self, state: dict[str, Any], event: dict[str, Any]) -> None:
        maximum = int(self.config["maximum_snapshots"])
        if int(state.get("snapshot_count", 0)) >= maximum:
            return
        now = time.monotonic()
        cooldown = int(self.config["snapshot_cooldown_seconds"])
        if (
            event.get("classification") != "user_marker"
            and
            self.last_snapshot_monotonic is not None
            and now - self.last_snapshot_monotonic < cooldown
        ):
            return
        directory = session_root(str(state["session_id"]), str(state.get("module", "usb"))) / "snapshots"
        destination = directory / f"{int(time.time())}-{state.get('snapshot_count', 0) + 1}.json"
        self.module.collect_snapshot(event, destination)
        state["snapshot_count"] = int(state.get("snapshot_count", 0)) + 1
        self.last_snapshot_monotonic = now

    def _finalize(self, state: dict[str, Any], reason: str) -> int:
        desired_status = "completed" if reason == "runtime_complete" else "stopped"
        state["enabled"] = True
        state["status"] = "finalizing"
        state["completion_reason"] = reason
        state.setdefault("completed_at", utc_now())
        with state_lock():
            save_state(state)
        try:
            bundle_state = dict(state)
            bundle_state["enabled"] = False
            bundle_state["status"] = desired_status
            bundle_state["telegram_delivery"] = {"status": "pending"}
            bundle = create_bundle(bundle_state, self.config)
        except Exception as exception:  # final evidence must survive delivery/export errors
            state["completion_error"] = str(exception)
            with state_lock():
                save_state(state)
            return 1
        state["export_path"] = str(bundle)
        state["telegram_delivery"] = deliver(bundle, self.config)
        state["enabled"] = False
        state["status"] = desired_status
        state.pop("completion_error", None)
        with state_lock():
            save_state(state)
        return 0

    def run(self) -> int:
        signal.signal(signal.SIGUSR1, self._wake)
        signal.signal(signal.SIGTERM, self._shutdown)
        state = load_state()
        if not state or not state.get("enabled"):
            return 0
        if state.get("status") == "finalizing":
            return self._finalize(
                state, str(state.get("completion_reason", "runtime_complete"))
            )
        if state.get("stop_requested"):
            return self._finalize(state, "user_stop")
        if float(state.get("runtime_consumed_seconds", 0)) >= float(
            state["runtime_target_seconds"]
        ):
            return self._finalize(state, "runtime_complete")

        session_id = str(state["session_id"])
        log_dir = session_root(session_id, str(state.get("module", "usb"))) / "logs"
        sample_log = log_dir / "samples.jsonl"
        event_log = log_dir / "events.jsonl"
        maximum_log = int(self.config["maximum_log_bytes"])
        interval = int(self.config["checkpoint_seconds"])
        previous_monotonic = time.monotonic()
        state["last_boot_id"] = boot_id()
        self.module.check_events()  # establish a baseline before the first collection

        while True:
            cycle_started = time.monotonic()
            processed_marker_ids: set[Any] = set()
            try:
                sample = self.module.collect_sample()
                append_json_line(sample_log, sample, maximum_log)
                events = self.module.check_events()
                pending_markers = list(state.get("pending_markers", []))
                processed_marker_ids = {marker.get("id") for marker in pending_markers}
                state["pending_markers"] = []
                events.extend(pending_markers)
                for event in events:
                    append_json_line(event_log, event, maximum_log)
                    state["event_count"] = int(state.get("event_count", 0)) + 1
                    classification = str(event.get("classification", "candidate"))
                    counter = {
                        "known": "known_event_count",
                        "candidate": "candidate_event_count",
                        "user_marker": "user_marker_count",
                    }.get(classification)
                    if counter:
                        state[counter] = int(state.get(counter, 0)) + 1
                    self._snapshot(state, event)
                state.pop("last_collection_error", None)
            except Exception as exception:
                state["last_collection_error"] = str(exception)

            now = time.monotonic()
            elapsed = max(0.0, now - previous_monotonic)
            previous_monotonic = now
            state["runtime_consumed_seconds"] = float(
                state.get("runtime_consumed_seconds", 0)
            ) + elapsed
            state["last_boot_id"] = boot_id()
            with state_lock():
                current = load_state()
                if current and current.get("session_id") == session_id:
                    state["stop_requested"] = bool(current.get("stop_requested", False))
                    state["pending_markers"] = [
                        marker for marker in current.get("pending_markers", [])
                        if marker.get("id") not in processed_marker_ids
                    ]
                save_state(state)

            if self.shutdown_requested:
                return 0
            if state.get("stop_requested"):
                return self._finalize(state, "user_stop")
            if float(state["runtime_consumed_seconds"]) >= float(
                state["runtime_target_seconds"]
            ):
                return self._finalize(state, "runtime_complete")

            remaining = max(0.0, interval - (time.monotonic() - cycle_started))
            self.wake_requested = False
            end = time.monotonic() + remaining
            while time.monotonic() < end and not self.wake_requested:
                time.sleep(min(0.5, end - time.monotonic()))
            if self.shutdown_requested:
                return 0


def run_daemon() -> int:
    return DiagnosticsRunner().run()
