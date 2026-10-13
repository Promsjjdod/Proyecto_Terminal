"""UX estilo Codex: encabezado, fases, leyenda de diff y modo bloques."""
from __future__ import annotations

import io

from rich.console import Console

from nexo.editor.diff import compute_diff
from nexo.ui.header import header_meta_line, render_header
from nexo.ui.phase import STAGES, PhaseTracker
from nexo.ui.render import UI
from nexo.utils.text import visible_len


def make_ui(width: int, diff_style: str = "signs", color: bool = True):
    buf = io.StringIO()
    console = Console(file=buf, width=width, force_terminal=color,
                      no_color=not color,
                      color_system="standard" if color else None)
    return UI(console, animate=False, diff_style=diff_style), buf


# --------------------------------------------------------------------- encabezado
def test_header_contains_brand_meta_and_quick_commands():
    ui, buf = make_ui(110)
    render_header(ui, "cleanapis/claude-opus", "autonomo", connection="sin comprobar")
    out = buf.getvalue()
    assert "[ AGENTE DE CÓDIGO ]" in out
    assert "cleanapis/claude-opus" in out
    assert "autonomo" in out
    assert "sin comprobar" in out
    for cmd in ("/menu", "/provider", "/help"):
        assert cmd in out
    # Reglas dobles de marca.
    assert out.count("═") >= 2


def test_header_respects_narrow_width():
    ui, buf = make_ui(40)
    render_header(ui, "prov/modelo-largo-nombre", "seguro")
    out = buf.getvalue()
    for line in out.splitlines():
        assert visible_len(line) <= 40, line
    assert "/menu" in out
    # En pantalla estrecha usa el set reducido de accesos rápidos.
    assert "/doctor" not in out
    for cmd in ("/menu", "/chat", "/help"):
        assert cmd in out


def test_header_meta_line_fields():
    meta = header_meta_line("p/m", "cauto", "ok")
    assert meta == "[ AGENTE DE CÓDIGO ]  modelo: p/m  ·  permisos: cauto  ·  red: ok"


# ------------------------------------------------------------------------- fases
def test_phase_tracker_transitions():
    tracker = PhaseTracker()
    assert tracker.set_phase("PLAN") is True
    assert tracker.set_phase("PLAN") is False          # no repinta si no cambia
    assert tracker.set_phase("WRITE") is True
    assert tracker.done == ["PLAN"]
    assert tracker.set_phase("INVENTADA") is False
    tracker.set_progress(42)
    assert tracker.percent == 42
    tracker.set_progress(150)
    assert tracker.percent == 100
    tracker.reset()
    assert tracker.current is None and tracker.percent == 0


def test_phase_pipeline_order_and_bar():
    tracker = PhaseTracker()
    tracker.set_phase("WRITE")
    pipeline = tracker.pipeline_text().plain
    assert pipeline.startswith("› ")
    for stage in STAGES:
        assert stage in pipeline
    tracker.set_progress(50)
    bar = tracker.bar_text(10).plain
    assert "50%" in bar and "█" in bar and "░" in bar
    tracker.set_progress(100)
    assert "✔" in tracker.bar_text(10).plain


def test_phase_render_panel():
    ui, buf = make_ui(80)
    tracker = PhaseTracker()
    tracker.set_phase("WRITE")
    tracker.render(ui)
    out = buf.getvalue()
    assert "ANALIZAR" in out and "WRITE" in out and "CHECK" in out
    assert "en curso" in out and "30%" not in out and "0%" not in out


def test_task_completion_does_not_claim_code_verification():
    tracker = PhaseTracker()
    tracker.set_phase("CHECK")
    tracker.set_progress(100, "tarea terminada")
    status = tracker.bar_text().plain
    assert "TAREA · completada · 100%" in status
    assert "verificado" not in status


def test_repeated_phase_restarts_after_previous_completion():
    tracker = PhaseTracker()
    tracker.set_phase("CHECK")
    tracker.set_progress(100, "comando terminado")
    assert tracker.set_phase("CHECK") is True
    assert tracker.percent == 0
    assert "100%" not in tracker.bar_text().plain


def test_phase_pipeline_fits_narrow_phone_widths():
    tracker = PhaseTracker()
    for width in (32, 36, 40, 48):
        lines = tracker.pipeline_text(width).plain.splitlines()
        assert all(visible_len(line) <= width - 4 for line in lines), (width, lines)


# --------------------------------------------------------------- diffs y leyenda
def test_diff_signs_mode_default_colors():
    ui, buf = make_ui(80)
    diff = compute_diff("a\nb\n", "a\nB\n", "f.txt")
    ui.render_diff(diff)
    out = buf.getvalue()
    assert "\x1b[32m" in out or "\x1b[92m" in out     # verde añadido
    assert "\x1b[31m" in out or "\x1b[91m" in out     # rojo eliminado
    assert "42m" not in out                              # sin fondos en modo signos


def test_diff_blocks_mode_backgrounds():
    ui, buf = make_ui(80, diff_style="blocks")
    diff = compute_diff("a\nb\n", "a\nB\n", "f.txt")
    ui.render_diff(diff)
    out = buf.getvalue()
    assert "42m" in out      # fondo verde (añadida)
    assert "41m" in out      # fondo rojo (eliminada)


def test_diff_legend_shown():
    ui, buf = make_ui(80)
    diff = compute_diff("a\nb\n", "a\nB\n", "f.txt")
    ui.render_diffs([diff])
    out = buf.getvalue()
    assert "strip:" in out
    assert "+new" in out or "-eliminado" in out


def test_diff_legend_blocks_variant():
    ui, buf = make_ui(80, diff_style="blocks")
    ui.diff_legend()
    out = buf.getvalue()
    assert "strip:" in out
    assert "new" in out and "eliminado" in out


def test_diff_new_and_deleted_file_markers():
    ui, buf = make_ui(80)
    nuevo = compute_diff(None, "línea\n", "nuevo.txt")
    borrado = compute_diff("línea\n", None, "borrado.txt")
    ui.render_diffs([nuevo, borrado])
    out = buf.getvalue()
    assert "nuevo.txt" in out and "(nuevo)" in out
    assert "borrado.txt" in out and "(eliminado)" in out
    assert "+ línea" in out        # todo verde en el archivo nuevo
    assert "- línea" in out        # todo rojo en el eliminado
