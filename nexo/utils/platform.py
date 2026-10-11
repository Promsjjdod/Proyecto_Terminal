"""Detección de plataforma (Termux/Android) y capacidades del entorno."""
from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass


@dataclass
class PlatformInfo:
    is_termux: bool
    is_android: bool
    arch: str
    python_version: str
    has_git: bool
    has_gh: bool
    home: str

    def describe(self) -> str:
        entorno = "Termux (Android)" if self.is_termux else (
            "Android" if self.is_android else sys.platform
        )
        return (
            f"{entorno} | {self.arch} | Python {self.python_version} | "
            f"git={'sí' if self.has_git else 'no'} gh={'sí' if self.has_gh else 'no'}"
        )


def detect_platform() -> PlatformInfo:
    prefix = os.environ.get("PREFIX", "")
    is_termux = "com.termux" in prefix or os.path.isdir("/data/data/com.termux")
    is_android = is_termux or "android" in sys.platform.lower() or os.path.isdir("/system/bin")
    return PlatformInfo(
        is_termux=is_termux,
        is_android=is_android,
        arch=os.uname().machine if hasattr(os, "uname") else "desconocida",
        python_version=sys.version.split()[0],
        has_git=shutil.which("git") is not None,
        has_gh=shutil.which("gh") is not None,
        home=os.path.expanduser("~"),
    )


def supports_color() -> bool:
    """Comprueba si la terminal admite color (respeta NO_COLOR y TERM=dumb)."""
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("NEXO_NO_COLOR"):
        return False
    term = os.environ.get("TERM", "")
    if term in ("dumb", ""):
        return False
    return True
