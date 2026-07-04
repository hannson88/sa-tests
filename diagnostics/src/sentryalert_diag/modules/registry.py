from __future__ import annotations

from .base import DiagnosticModule
from .generic import PROFILES, CommandDiagnosticModule
from .usb import UsbDiagnosticModule

MODULE_NAMES = ("usb", *PROFILES.keys())


def create_module(name: str, timeout: int = 10) -> DiagnosticModule:
    if name == "usb":
        return UsbDiagnosticModule(timeout)
    if name in PROFILES:
        return CommandDiagnosticModule(name, timeout)
    raise ValueError(f"Unknown diagnostics module: {name}")
