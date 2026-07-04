from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any


def validate_bundle(path: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    required = {"state.json", "inventory.json", "SUMMARY.txt", "REPORT.txt", "CONTRACT.json", "MANIFEST.sha256"}
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            errors.extend(f"missing {name}" for name in sorted(required - names))
            manifest: dict[str, str] = {}
            if "MANIFEST.sha256" in names:
                for line in archive.read("MANIFEST.sha256").decode("utf-8", errors="replace").splitlines():
                    digest, separator, name = line.partition("  ")
                    if separator:
                        manifest[name] = digest
                for name, expected in manifest.items():
                    if name not in names:
                        errors.append(f"manifest entry missing: {name}")
                    elif hashlib.sha256(archive.read(name)).hexdigest() != expected:
                        errors.append(f"checksum mismatch: {name}")
            if not any(name.endswith("/logs/events.jsonl") for name in names):
                errors.append("missing events.jsonl")
            if not any(name.endswith("/logs/samples.jsonl") for name in names):
                warnings.append("missing samples.jsonl")
            if "state.json" in names:
                state = json.loads(archive.read("state.json"))
                if state.get("event_count", 0) and not any(name.endswith("/logs/events.jsonl") for name in names):
                    errors.append("state reports events but event log is absent")
    except (OSError, zipfile.BadZipFile, ValueError, json.JSONDecodeError) as exception:
        errors.append(str(exception))
    return {"valid": not errors, "errors": errors, "warnings": warnings}
