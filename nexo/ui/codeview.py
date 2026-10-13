"""Visor de código integrado: sintaxis resaltada, números de línea y ventanas.

Inspirado en la caja "LIVE CODE" de las referencias: identificación de
lenguaje/archivo, canaleta de números de línea y código legible en pantallas
estrechas. Usa `rich.syntax.Syntax` (dependencia ya presente vía rich).

Control de líneas largas:
- ``wrap=True``  : envuelve la línea (legible, sin scroll).
- ``wrap=False`` : ventana horizontal ``col..col+ancho`` con indicador de
  cuántas columnas quedan por ver (desplazamiento controlado con /view --col).
"""
from __future__ import annotations

import os
from typing import Optional, Tuple

from rich.syntax import Syntax
from rich.text import Text

from nexo.ui.theme import THEME

LANG_BY_EXT = {
    ".py": "python", ".html": "html", ".htm": "html", ".js": "javascript",
    ".mjs": "javascript", ".ts": "typescript", ".json": "json", ".md": "markdown",
    ".css": "css", ".sh": "bash", ".bash": "bash", ".yml": "yaml", ".yaml": "yaml",
    ".toml": "toml", ".xml": "xml", ".sql": "sql", ".c": "c", ".h": "c",
    ".cpp": "cpp", ".java": "java", ".kt": "kotlin", ".rs": "rust", ".go": "go",
    ".rb": "ruby", ".php": "php", ".txt": "text", ".log": "text",
}


def detect_language(path: str) -> str:
    """Lenguaje por extensión; 'text' si no se reconoce."""
    ext = os.path.splitext(path)[1].lower()
    return LANG_BY_EXT.get(ext, "text")


def slice_window(text: str, offset: int, limit: Optional[int],
                 col: int, width: int) -> Tuple[str, int, int, bool, bool]:
    """Devuelve (texto_ventana, primera_linea, ultima_linea, truncado_vertical, truncado_horizontal)."""
    lines = text.splitlines()
    total = len(lines)
    start = max(offset - 1, 0)
    end = total if not limit or limit <= 0 else min(start + limit, total)
    shown = lines[start:end]
    h_trunc = False
    if col > 0 or any(len(line) > width for line in shown):
        out = []
        for line in shown:
            piece = line[col:col + width] if col > 0 else line
            out.append(piece)
        h_trunc = col > 0 or any(len(line) > width for line in shown)
        shown = out
    return "\n".join(shown), start + 1, end, end < total, h_trunc


def render_code(ui, text: str, path: str, language: Optional[str] = None,
                offset: int = 1, limit: Optional[int] = None,
                col: int = 0, wrap: Optional[bool] = None) -> None:
    """Pinta la caja de código con metadatos, ventana y avisos honestos."""
    lang = language or detect_language(path)
    if wrap is None:
        wrap = ui.small_screen
    width = max(20, ui.width - 8)   # reserva para canaleta de números

    windowed, first, last, v_trunc, h_trunc = slice_window(text, offset, limit, col, width)
    total_lines = text.count("\n") + (1 if text and not text.endswith("\n") else 0)

    header = Text()
    header.append("▐ ", style=THEME.brand)
    header.append(f"{lang}", style=f"bold {THEME.info}")
    header.append(f" · {path}", style="")
    header.append(f" · {total_lines} líneas", style=THEME.muted)
    if first != 1 or last != total_lines:
        header.append(f" · mostrando {first}-{last}", style=THEME.warning)
    if col > 0:
        header.append(f" · cols {col}+", style=THEME.warning)
    ui.console.print(header, highlight=False)

    if not windowed.strip() and not text.strip():
        ui.warn("El archivo está vacío.")
        return

    syntax = Syntax(
        windowed,
        lang if lang != "text" else "text",
        line_numbers=True,
        start_line=first,
        word_wrap=wrap,
        theme="monokai" if ui.console.is_terminal or ui.console.color_system else "none",
        background_color="default",
    )
    ui.console.print(syntax)

    notes = []
    if v_trunc:
        notes.append(f"Contenido largo: se muestran hasta la línea {last}. "
                     f"Continúa con /view {path} --desde {last + 1}.")
    if h_trunc and not wrap:
        rest = max(len(line) for line in text.splitlines()[first - 1:last]) - width - col
        notes.append(f"Líneas más anchas que la pantalla: usa /view {path} --col {col + width} "
                     f"para desplazar (~{max(rest, 1)} cols restantes) o --wrap para envolver.")
    for note in notes:
        ui.warn(note)


def copy_to_clipboard(text: str) -> Optional[str]:
    """Copia usando termux-clipboard-set si existe. Devuelve None si no hay soporte."""
    import shutil
    import subprocess

    tool = shutil.which("termux-clipboard-set")
    if not tool:
        return ("Sin soporte de portapapeles en este entorno. En Termux instalá "
                "`pkg install termux-api` y usá /view <ruta> --copiar.")
    try:
        subprocess.run([tool], input=text.encode("utf-8"), timeout=10, check=True)
        return None
    except (OSError, subprocess.SubprocessError) as exc:
        return f"No se pudo copiar al portapapeles: {exc}"
