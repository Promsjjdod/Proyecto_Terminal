"""Panel de fases y progreso del agente, inspirado en las referencias Codex.

Muestra el pipeline PLAN → EJECUTAR → VERIFICAR (→ EXPORTAR) con la fase
activa resaltada y una barra de progreso con porcentaje, como en la imagen
de referencia (`:: WRITE → SAVE → CHECK` + barra verde 100%).
"""
from __future__ import annotations

from typing import List, Optional

from rich.text import Text

from nexo.ui.theme import THEME

STAGES: List[str] = ["PLAN", "EJECUTAR", "VERIFICAR", "EXPORTAR"]
_STAGE_INDEX = {name: i for i, name in enumerate(STAGES)}


class PhaseTracker:
    """Estado de fases del ciclo en curso (no persistente)."""

    def __init__(self) -> None:
        self.current: Optional[str] = None
        self.done: List[str] = []
        self.percent: int = 0
        self.note: str = ""

    def set_phase(self, name: str, note: str = "") -> bool:
        """Avanza a una fase. Devuelve True si cambió."""
        if name not in _STAGE_INDEX:
            return False
        if self.current == name and not note:
            return False
        if self.current and self.current != name and self.current not in self.done:
            self.done.append(self.current)
        self.current = name
        if note:
            self.note = note
        return True

    def set_progress(self, percent: int, note: str = "") -> None:
        self.percent = max(0, min(100, int(percent)))
        if note:
            self.note = note

    def reset(self) -> None:
        self.current = None
        self.done = []
        self.percent = 0
        self.note = ""

    # ------------------------------------------------------------- renderizado
    def pipeline_text(self) -> Text:
        """Línea `:: PLAN → EJECUTAR → VERIFICAR` con la fase activa resaltada."""
        text = Text(":: ", style=THEME.brand)
        for i, stage in enumerate(STAGES):
            if i:
                text.append(" → ", style=THEME.muted)
            if stage == self.current:
                text.append(stage, style=f"bold {THEME.warning}")
            elif stage in self.done:
                text.append(stage, style=THEME.success)
            else:
                text.append(stage, style=THEME.muted)
        return text

    def bar_text(self, width: int = 24) -> Text:
        """Barra de progreso con porcentaje y nota (verde = avance)."""
        filled = int(width * self.percent / 100)
        bar = "█" * filled + "░" * (width - filled)
        text = Text()
        if self.current:
            text.append("✔ " if self.percent >= 100 else "▶ ", style=THEME.success)
            text.append(f"{self.current} ", style=f"bold {THEME.success}")
        text.append(bar, style=THEME.success)
        text.append(f" {self.percent:3d}%", style=f"bold {THEME.success}")
        if self.note:
            text.append(f" {self.note}", style=THEME.muted)
        return text

    def render(self, ui) -> None:
        """Caja de fases como en la referencia (borde de marca, dos líneas)."""
        body = Text()
        body.append(self.pipeline_text())
        body.append("\n")
        body.append(self.bar_text(max(12, min(28, ui.width // 3))))
        from rich.panel import Panel

        ui.console.print(Panel(body, border_style=THEME.brand, expand=True,
                               padding=(0, 1) if not ui.small_screen else (0, 0)))
