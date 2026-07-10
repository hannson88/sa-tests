from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any


MAX_OUTPUT_BYTES = 512 * 1024
SECRET_PATTERNS = (
    re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{20,}\b"),
    re.compile(
        r"(?i)\b(telegramAPIToken|telegramChatID|authorization|password|secret)"
        r"(\s*[:=]\s*['\"]?)([^'\"\s,}]+)"
    ),
)


def redact_text(value: str) -> str:
    value = SECRET_PATTERNS[0].sub("[REDACTED_TOKEN]", value)
    return SECRET_PATTERNS[1].sub(r"\1\2[REDACTED]", value)


def run_command(
    arguments: list[str],
    timeout: int = 10,
    extra_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    try:
        result = subprocess.run(
            arguments,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "LC_ALL": "C", **(extra_env or {})},
        )
        output = redact_text(result.stdout[-MAX_OUTPUT_BYTES:])
        error = redact_text(result.stderr[-65536:])
        return {
            "command": arguments,
            "exit_code": result.returncode,
            "output": output,
            "error": error,
        }
    except (OSError, subprocess.TimeoutExpired) as exception:
        return {
            "command": arguments,
            "exit_code": None,
            "output": "",
            "error": str(exception),
        }


def read_text(path: str, maximum_bytes: int = 1024 * 1024) -> str | None:
    try:
        with Path(path).open("rb") as source:
            return source.read(maximum_bytes).decode("utf-8", errors="replace")
    except OSError:
        return None
