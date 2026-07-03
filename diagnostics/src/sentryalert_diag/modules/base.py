from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class DiagnosticModule(ABC):
    name: str

    @abstractmethod
    def collect_sample(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def check_events(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def collect_snapshot(self, reason: dict[str, Any], destination: Path) -> None:
        raise NotImplementedError

