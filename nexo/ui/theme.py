"""Tema visual de NEXO: colores semánticos compatibles con Termux.

Convención (respeta terminales sin color mediante NO_COLOR / ui.color=False):
- verde  : éxito, líneas añadidas, estados correctos
- rojo   : errores, líneas eliminadas, fallos
- amarillo: advertencias, confirmaciones pendientes, conflictos
- cian   : información, proveedores, comandos
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from rich.console import Console

from nexo.utils.platform import supports_color


@dataclass(frozen=True)
class Theme:
    success: str = "green"
    error: str = "red"
    warning: str = "yellow"
    info: str = "cyan"
    accent: str = "bright_cyan"
    muted: str = "bright_black"
    prompt: str = "bright_green"
    brand: str = "bright_red"      # cromo de marca (logo, prompt, paneles de fase)
    diff_add: str = "green"
    diff_del: str = "red"
    diff_meta: str = "yellow"
    diff_ctx: str = ""            # sin color: contexto intacto
    logo: str = "bright_red"


THEME = Theme()


def make_console(ui_config=None, force_terminal: bool | None = None) -> Console:
    """Crea la consola Rich respetando configuración y capacidades reales."""
    color = True
    width = None
    if ui_config is not None:
        color = bool(getattr(ui_config, "color", True))
        w = int(getattr(ui_config, "width", 0) or 0)
        width = w if w > 0 else None
    if not supports_color():
        color = False
    env_cols = os.environ.get("COLUMNS")
    if width is None and env_cols and env_cols.isdigit():
        width = int(env_cols)
    return Console(
        no_color=not color,
        highlight=False,
        width=width,
        force_terminal=force_terminal,
        soft_wrap=False,
        markup=True,
    )
