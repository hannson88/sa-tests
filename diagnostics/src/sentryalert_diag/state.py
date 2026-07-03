from __future__ import annotations

import json
import os
import fcntl
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .atomic import atomic_write_bytes, atomic_write_json
from .paths import PREVIOUS_STATE_PATH, STATE_PATH

LOCK_PATH = STATE_PATH.with_name("state.lock")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def boot_id() -> str:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"


def load_state(required: bool = False) -> dict[str, Any] | None:
    errors: list[str] = []
    for path in (STATE_PATH, PREVIOUS_STATE_PATH):
        try:
            with path.open("r", encoding="utf-8") as source:
                state = json.load(source)
            if not isinstance(state, dict):
                raise ValueError("state is not an object")
            return state
        except (OSError, ValueError, json.JSONDecodeError) as error:
            errors.append(f"{path}: {error}")
    if required:
        raise RuntimeError("No valid diagnostics state found: " + "; ".join(errors))
    return None


def save_state(state: dict[str, Any]) -> None:
    state["last_checkpoint_at"] = utc_now()
    if STATE_PATH.exists():
        try:
            previous = STATE_PATH.read_bytes()
            json.loads(previous)
            atomic_write_bytes(PREVIOUS_STATE_PATH, previous)
        except (OSError, ValueError, json.JSONDecodeError):
            pass
    atomic_write_json(STATE_PATH, state)


@contextmanager
def state_lock():
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(LOCK_PATH, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def append_json_line(path: Path, value: dict[str, Any], maximum_bytes: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size >= maximum_bytes:
        rotated = path.with_suffix(path.suffix + ".1")
        if rotated.exists():
            rotated.unlink()
        os.replace(path, rotated)
    encoded = json.dumps(value, sort_keys=True).encode("utf-8") + b"\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
