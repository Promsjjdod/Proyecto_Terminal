"""Panel de fases del agente, adaptable a Termux y fiel al trabajo real.

La tubería presenta las etapas observables del agente. No estima porcentajes a
partir del número de iteraciones: solo muestra 100% cuando la operación informa
una verificación terminal explícita.
"""
from __future__ import annotations

from typing import List, Optional

from rich.text import Text

from nexo.ui.theme import THEME

STAGES: List[str] = ["ANALIZAR", "PLAN", "WRITE", "SAVE", "CHECK", "BUILD", "RUN", "FIX", "EXPORT"]
_STAGE_INDEX = {name: i for i, name in enumerate(STAGES)}


class PhaseTracker:
    """Estado efímero de la tarea actual, alimentado por eventos reales."""

    def __init__(self) -> None:
        self.current: Optional[str] = None
        self.done: List[str] = []
        self.percent: int = 0
        self.note: str = ""

    def set_phase(self, name: str, note: str = "") -> bool:
        """Avanza a una fase conocida. Devuelve True solo si cambió."""
        if name not in _STAGE_INDEX:
            return False
        if self.current == name:
            if self.percent >= 100:
                self.percent = 0
                self.note = note
                return True
            if not note or note == self.note:
                return False
            self.note = note
            return True
        if self.current and self.current != name and self.current not in self.done:
            self.done.append(self.current)
        if name in self.done:
            self.done.remove(name)
        self.current = name
        self.percent = 0
        self.note = note
        return True

    def set_progress(self, percent: int, note: str = "") -> None:
        """Registra progreso explícito comunicado por una operación real."""
        self.percent = max(0, min(100, int(percent)))
        if note:
            self.note = note

    def reset(self) -> None:
        self.current = None
        self.done = []
        self.percent = 0
        self.note = ""

    def pipeline_text(self, width: int = 80) -> Text:
        """Renderiza las etapas en filas compactas para pantallas de teléfono."""
        if width < 40:
            rows = [STAGES[:2], STAGES[2:5], STAGES[5:7], STAGES[7:]]
        else:
            rows = [STAGES[:4], STAGES[4:]]
        text = Text()
        for row_index, row in enumerate(rows):
            if row_index:
                text.append("\n")
            text.append("› ", style=THEME.brand)
            for i, stage in enumerate(row):
                if i:
                    text.append(" › ", style=THEME.muted)
                if stage == self.current:
                    text.append(stage, style=f"bold {THEME.warning}")
                elif stage in self.done:
                    text.append(stage, style=THEME.success)
                else:
                    text.append(stage, style=THEME.muted)
        return text

    def bar_text(self, width: int = 24) -> Text:
        """Estado honesto: actividad sin porcentaje estimado o verificación real."""
        text = Text()
        if self.percent >= 100:
            text.append("✔ ", style=THEME.success)
            if "tarea terminada" in self.note:
                label = "TAREA · completada · 100%"
            elif "verificado" in self.note:
                label = f"{self.current or 'OPERACIÓN'} · verificado · 100%"
            else:
                label = f"{self.current or 'OPERACIÓN'} · completado · 100%"
            text.append(label, style=f"bold {THEME.success}")
        elif self.current and self.percent > 0:
            filled = int(max(4, width) * self.percent / 100)
            text.append("▶ ", style=THEME.warning)
            text.append("█" * filled + "░" * (max(4, width) - filled), style=THEME.success)
            text.append(f" {self.percent}%", style=f"bold {THEME.success}")
        elif self.current:
            text.append("▶ ", style=THEME.warning)
            text.append(f"{self.current} · en curso", style=f"bold {THEME.warning}")
        else:
            text.append("· En espera", style=THEME.muted)
        if self.note and self.percent < 100:
            text.append(f" · {self.note}", style=THEME.muted)
        return text

    def render(self, ui) -> None:
        """Dibuja la secuencia de trabajo y su estado actual en una caja estable."""
        body = Text()
        body.append(self.pipeline_text(ui.width))
        body.append("\n")
        body.append(self.bar_text())
        from rich.panel import Panel

        ui.console.print(Panel(body, title="FLUJO DE TRABAJO", title_align="left",
                               border_style=THEME.brand, expand=True,
                               padding=(0, 1) if not ui.small_screen else (0, 0)))
