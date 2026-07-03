from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .atomic import atomic_write_json
from .paths import CONFIG_PATH, PACKAGE_ROOT


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as source:
        value = json.load(source)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def load_config() -> dict[str, Any]:
    defaults = _read_json(PACKAGE_ROOT / "config" / "default.json")
    if CONFIG_PATH.exists():
        defaults.update(_read_json(CONFIG_PATH))
    return defaults


def ensure_config() -> None:
    if CONFIG_PATH.exists():
        return
    atomic_write_json(CONFIG_PATH, _read_json(PACKAGE_ROOT / "config" / "default.json"))

