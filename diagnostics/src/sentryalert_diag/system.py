from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any


MAX_OUTPUT_BYTES = 512 * 1024


def run_command(arguments: list[str], timeout: int = 10) -> dict[str, Any]:
    try:
        result = subprocess.run(
            arguments,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "LC_ALL": "C"},
        )
        output = result.stdout[-MAX_OUTPUT_BYTES:]
        error = result.stderr[-65536:]
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
