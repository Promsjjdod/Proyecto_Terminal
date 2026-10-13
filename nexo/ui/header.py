"""Encabezado estilo Codex: logo, regla doble, línea de metadatos y accesos rápidos.

Diseño inspirado en las referencias visuales del proyecto (encabezado de
agente de código), adaptado a la paleta semántica de NEXO y a pantallas
estrechas de teléfono:

    <logo ASCII>
    ══════════════════════════════
    [ AGENTE DE CÓDIGO ]  modelo: proveedor/modelo
    ══════════════════════════════
    /menu /chat /provider /files /diff /tasks /config /help
"""
from __future__ import annotations

from typing import List

from rich.text import Text

from nexo.ui.logo import get_logo
from nexo.ui.theme import THEME
from nexo.utils.text import wrap_lines

QUICK_COMMANDS_WIDE = [
    "/menu", "/chat", "/provider", "/model", "/files", "/view",
    "/diff", "/apply", "/undo", "/export", "/tasks", "/config", "/doctor", "/help",
]
QUICK_COMMANDS_NARROW = [
    "/menu", "/chat", "/provider", "/files", "/diff", "/tasks", "/config", "/help",
]


def header_meta_line(provider_label: str, mode: str, connection: str) -> str:
    """Línea de metadatos del encabezado (modelo, permisos, conexión)."""
    return f"[ AGENTE DE CÓDIGO ]  modelo: {provider_label}  ·  permisos: {mode}  ·  red: {connection}"


def render_header(ui, provider_label: str, mode: str, connection: str = "sin comprobar") -> None:
    """Pinta el encabezado completo respetando el ancho disponible."""
    width = ui.width
    logo = get_logo(width)
    ui.console.print(Text(logo.rstrip("\n"), style=THEME.logo), highlight=False)

    rule = "═" * max(width - 2, 8)
    ui.console.print(Text(rule, style=THEME.brand), highlight=False)
    meta = header_meta_line(provider_label, mode, connection)
    ui.console.print(Text(meta, style=THEME.muted), highlight=False)
    ui.console.print(Text(rule, style=THEME.brand), highlight=False)

    commands = QUICK_COMMANDS_NARROW if ui.small_screen else QUICK_COMMANDS_WIDE
    line = " ".join(commands)
    for wrapped in wrap_lines(line, width):
        ui.console.print(Text(wrapped, style=THEME.muted), highlight=False)
    ui.console.print()


def prompt_tokens(workspace_name: str) -> List[tuple]:
    """Fragmentos con estilo para el prompt interactivo: `nexo@termux ❯`."""
    from nexo.utils.platform import detect_platform

    host = "termux" if detect_platform().is_termux else "nexo"
    return [
        ("nexo", f"bold {THEME.brand}"),
        ("@", THEME.muted),
        (host, THEME.muted),
        (f" {workspace_name} ", THEME.info),
        ("❯ ", f"bold {THEME.brand}"),
    ]
