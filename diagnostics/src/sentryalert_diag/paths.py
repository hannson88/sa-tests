from __future__ import annotations

import os
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = Path(os.environ.get("SENTRYALERT_DIAG_DATA_ROOT", "/mutable/diagnostics"))
MODULE_ROOT = DATA_ROOT / "usb-diag"
STATE_PATH = MODULE_ROOT / "state.json"
PREVIOUS_STATE_PATH = MODULE_ROOT / "state.previous.json"
EXPORTS_DIR = MODULE_ROOT / "exports"
CONFIG_PATH = DATA_ROOT / "config.json"


def session_root(session_id: str) -> Path:
    return MODULE_ROOT / "sessions" / session_id

