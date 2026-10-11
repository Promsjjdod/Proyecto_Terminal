"""Logotipo ASCII de NEXO, con variantes para pantallas pequeñas."""
from __future__ import annotations

LOGO_FULL = r"""
 ██▄   █▄ █▀▀ ▀▄▀ █▄   █ ▄▀▀▄
 █  █  █ █▀▀  █  █  █  █ █  █
 █     █ █▄▄ █▄▄ █   █  ▀▄▄▀
"""

LOGO_SHADOW = r"""
 ███╗   ██╗ ███████╗ ██╗  ██╗  ██████╗
 ████╗  ██║ ██╔════╝ ╚██╗██╔╝ ██╔═══██╗
 ██╔██╗ ██║ █████╗    ╚███╔╝  ██║   ██║
 ██║╚██╗██║ ██╔══╝    ██╔██╗  ██║   ██║
 ██║ ╚████║ ███████╗ ██╔╝ ██╗ ╚██████╔╝
 ╚═╝  ╚═══╝ ╚══════╝ ╚═╝  ╚═╝  ╚═════╝
"""

TAGLINE = "N E X O   T E R M I N A L"
SUBTITLE = "Tu IA · Tu Terminal · Tu Proyecto"


def get_logo(width: int = 80) -> str:
    """Devuelve el logotipo adecuado al ancho disponible."""
    longest = max(len(line) for line in LOGO_SHADOW.splitlines())
    if width >= longest + 4:
        return LOGO_SHADOW
    return LOGO_FULL


LOGO_LINES = LOGO_SHADOW.splitlines()
