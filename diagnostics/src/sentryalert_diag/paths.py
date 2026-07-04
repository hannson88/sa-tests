from __future__ import annotations

import os
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = Path(os.environ.get("SENTRYALERT_DIAG_DATA_ROOT", "/mutable/diagnostics"))
MODULE_ROOT = DATA_ROOT / "usb-diag"
STATE_PATH = MODULE_ROOT / "state.json"
PREVIOUS_STATE_PATH = MODULE_ROOT / "state.previous.json"
CONFIG_PATH = DATA_ROOT / "config.json"


def module_root(module: str = "usb") -> Path:
    return DATA_ROOT / f"{module}-diag"


def exports_dir(module: str = "usb") -> Path:
    return module_root(module) / "exports"


def session_root(session_id: str, module: str = "usb") -> Path:
    return module_root(module) / "sessions" / session_id
