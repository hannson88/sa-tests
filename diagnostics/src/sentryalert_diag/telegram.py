from __future__ import annotations

from pathlib import Path
from typing import Any

from .paths import PACKAGE_ROOT
from .system import run_command


def deliver(bundle: Path, config: dict[str, Any]) -> dict[str, Any]:
    if not config.get("telegram_enabled", True):
        return {"status": "disabled"}
    helper = PACKAGE_ROOT / "helpers" / "telegram-send.js"
    sentryalert_config = Path(str(config["sentryalert_root"])) / "config.js"
    result = run_command(
        ["node", str(helper), str(sentryalert_config), str(bundle)],
        timeout=180,
    )
    if result["exit_code"] == 0:
        return {"status": "sent", "detail": result["output"].strip()}
    return {
        "status": "failed",
        "error": (result["error"] or result["output"] or "Telegram upload failed")[-2000:],
    }

