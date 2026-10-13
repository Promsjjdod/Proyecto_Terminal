"""Componentes de renderizado: paneles, diffs coloreados, streaming y estados.

Todo está pensado para pantallas estrechas: se evita el texto amontonado, las
tablas anchas se sustituyen por listas clave-valor y el contenido se ajusta al
ancho real de la terminal.
"""
from __future__ import annotations

import contextlib
from typing import Dict, Iterable, List, Optional

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text

from nexo.editor.diff import DiffResult
from nexo.ui.theme import THEME


class UI:
    """Fachada de presentación de NEXO."""

    def __init__(self, console: Console, animate: bool = True, diff_style: str = "signs"):
        self.console = console
        self.animate = animate and console.is_terminal
        self.diff_style = diff_style if diff_style in ("signs", "blocks") else "signs"
        self._streaming = False

    # ------------------------------------------------------------------ medidas
    @property
    def width(self) -> int:
        try:
            return self.console.width
        except Exception:  # pragma: no cover
            return 80

    @property
    def small_screen(self) -> bool:
        return self.width < 64

    # ----------------------------------------------------------------- mensajes
    def _print(self, text: Text) -> None:
        self.console.print(text, soft_wrap=False)

    def info(self, message: str) -> None:
        self._print(Text.assemble(("ℹ ", THEME.info), (message, "")))

    def success(self, message: str) -> None:
        self._print(Text.assemble(("✔ ", THEME.success), (message, THEME.success)))

    def warn(self, message: str) -> None:
        self._print(Text.assemble(("⚠ ", THEME.warning), (message, THEME.warning)))

    def error(self, message: str) -> None:
        self._print(Text.assemble(("✖ ", THEME.error), (message, THEME.error)))

    def muted(self, message: str) -> None:
        self._print(Text(message, style=THEME.muted))

    def command_echo(self, command: str) -> None:
        self._print(Text.assemble(("$ ", THEME.info), (command, THEME.info)))

    def text(self, message: str, style: str = "") -> None:
        self._print(Text(message, style=style))

    def separator(self, title: str = "") -> None:
        self.console.print(Rule(title=title, style=THEME.muted) if title
                           else Rule(style=THEME.muted))

    def panel(self, title: str, body: str, style: str = THEME.info) -> None:
        content = Text()
        for i, line in enumerate(body.splitlines() or [""]):
            if i:
                content.append("\n")
            content.append(line)
        self.console.print(Panel(content, title=title, title_align="left",
                                 border_style=style, expand=True,
                                 padding=(0, 1) if not self.small_screen else (0, 0)))

    def kv(self, title: str, items: Iterable[object], style: str = THEME.info) -> None:
        """Panel de pares clave-valor (sustituye tablas en pantallas estrechas)."""
        lines: List[str] = []
        for item in items:
            if isinstance(item, dict):
                lines.append(" · " + "  ".join(f"{k}: {v}" for k, v in item.items()))
            else:
                lines.append(f" · {item}")
        self.panel(title, "\n".join(lines) or "(vacío)", style=style)

    # ------------------------------------------------------------------ spinner
    @contextlib.contextmanager
    def spinner(self, message: str):
        """Indicador de progreso discreto (no bloquea; desactivable)."""
        if not self.animate:
            self.muted(message)
            yield
            return
        with self.console.status(Text(message, style=THEME.muted), spinner="dots"):
            yield

    # ----------------------------------------------------------------- streaming
    def stream_start(self) -> None:
        self._streaming = True

    def stream_write(self, delta: str) -> None:
        """Escribe un fragmento de respuesta del modelo sin markup (texto seguro)."""
        self.console.print(Text(delta), end="", soft_wrap=True, highlight=False)
        self._streaming = True

    def stream_end(self) -> None:
        if self._streaming:
            self.console.print()  # salto de línea final
        self._streaming = False

    def model_output(self, text: str) -> None:
        """Salida del modelo en bloque (sin interpretar markup de Rich)."""
        self.console.print(Text(text), highlight=False)

    # --------------------------------------------------------------------- diffs
    def diff_legend(self) -> None:
        """Tira de leyenda del diff (inspirada en `strip: new | changed | same`)."""
        line = Text("strip: ", style=THEME.muted)
        if self.diff_style == "blocks":
            line.append(" new ", style="black on green")
            line.append(" ", style="")
            line.append(" eliminado ", style="white on red")
        else:
            line.append(" +new ", style=THEME.diff_add)
            line.append(" ", style="")
            line.append(" -eliminado ", style=THEME.diff_del)
        line.append(" ", style="")
        line.append(" contexto ", style=THEME.muted)
        line.append(" ", style="")
        line.append(" !atención ", style=THEME.diff_meta)
        self.console.print(line, highlight=False)

    def render_diff(self, diff: DiffResult, max_lines: int = 400) -> None:
        """Pinta un diff estilo Git: verde +, rojo -, amarillo conflictos/meta."""
        header_style = THEME.diff_meta
        self.console.print(Text.assemble(
            ("── ", header_style),
            (diff.path, "bold " + THEME.info),
            (f"  +{diff.added} −{diff.removed}", header_style),
            ("  (nuevo)" if diff.is_new else "  (eliminado)" if diff.is_delete else ""),
        ))
        if diff.is_binary:
            self.warn("Archivo binario: se sustituye íntegro (sin diff de texto).")
            return
        if diff.conflict_note:
            self.warn(diff.conflict_note)
        shown = 0
        for line in diff.lines:
            if shown >= max_lines:
                self.muted(f"… {len(diff.lines) - max_lines} línea(s) más del diff omitidas "
                           "(usa /diff completo para ver todo)")
                break
            self.console.print(self._diff_line_text(line), highlight=False)
            shown += 1
        if not diff.changed:
            self.muted("(sin cambios)")

    def _diff_line_text(self, line) -> Text:
        old_no = f"{line.old_no:>4}" if line.old_no is not None else "    "
        new_no = f"{line.new_no:>4}" if line.new_no is not None else "    "
        prefix = Text(f"{old_no} {new_no} ", style=THEME.muted)
        blocks = self.diff_style == "blocks"
        if line.tag == "+":
            body = Text(f"+ {line.text}" if not blocks else f" {line.text}",
                        style="black on green" if blocks else THEME.diff_add)
        elif line.tag == "-":
            body = Text(f"- {line.text}" if not blocks else f" {line.text}",
                        style="white on red" if blocks else THEME.diff_del)
        elif line.tag == "?":
            body = Text(f"! {line.text}", style=THEME.diff_meta)
        else:
            if line.text.startswith("@@"):
                body = Text(f"  {line.text}", style=THEME.diff_meta)
            else:
                body = Text(f"  {line.text}")
        return Text.assemble(prefix, body)

    def render_diffs(self, diffs: List[DiffResult], summary: Optional[Dict[str, int]] = None) -> None:
        if diffs:
            self.diff_legend()
        for diff in diffs:
            self.render_diff(diff)
        if summary:
            self.separator()
            self.info(
                f"Resumen: {summary.get('files', 0)} archivo(s) — "
                f"{summary.get('created', 0)} nuevo(s), {summary.get('modified', 0)} modificado(s), "
                f"{summary.get('deleted', 0)} eliminado(s); "
                f"+{summary.get('added', 0)} / −{summary.get('removed', 0)} líneas"
                + (f"; {summary['conflicts']} conflicto(s)" if summary.get("conflicts") else "")
            )

    # -------------------------------------------------------------------- varios
    def banner(self, logo: str, tagline: str, subtitle: str) -> None:
        logo_text = Text(logo.rstrip("\n"), style=THEME.logo)
        self.console.print(logo_text, justify="center", highlight=False)
        self.console.print(Text(tagline, style="bold " + THEME.accent), justify="center")
        self.console.print(Text(subtitle, style=THEME.muted), justify="center")
        self.separator()

    def clear(self) -> None:
        self.console.clear()
