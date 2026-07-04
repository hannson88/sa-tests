from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class DiagnosticModule(ABC):
    name: str
    title: str

    @abstractmethod
    def contract(self) -> dict[str, Any]:
        """Describe sources, failure modes, and evidence guarantees."""
        raise NotImplementedError

    @abstractmethod
    def collect_sample(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def check_events(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def collect_snapshot(self, reason: dict[str, Any], destination: Path) -> None:
        raise NotImplementedError
