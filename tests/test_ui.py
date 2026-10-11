"""Pruebas de la interfaz: colores del diff, pantallas estrechas y salida sin color."""
from __future__ import annotations

import io

from rich.console import Console

from nexo.editor.diff import compute_diff
from nexo.ui.logo import LOGO_FULL, LOGO_SHADOW, get_logo
from nexo.ui.render import UI
from nexo.utils.text import truncate, visible_len, wrap_lines


def make_ui(width: int, color: bool = True) -> tuple[UI, io.StringIO]:
    buf = io.StringIO()
    console = Console(file=buf, width=width, force_terminal=color, no_color=not color,
                      color_system="standard" if color else None)
    return UI(console, animate=False), buf


# ------------------------------------------------------------------- diff a color
def test_diff_renders_green_and_red():
    ui, buf = make_ui(80)
    diff = compute_diff("uno\ndos\ntres\n", "uno\nDOS\ntres\n", "archivo.txt")
    ui.render_diff(diff)
    out = buf.getvalue()
    # ANSI: verde (32) para añadidas, rojo (31) para eliminadas.
    assert "\x1b[32m" in out or "\x1b[92m" in out
    assert "\x1b[31m" in out or "\x1b[91m" in out
    assert "+ DOS" in out
    assert "- dos" in out


def test_diff_line_numbers_shown():
    ui, buf = make_ui(80)
    diff = compute_diff("a\nb\nc\n", "a\nB\nc\n", "f.txt")
    ui.render_diff(diff)
    out = buf.getvalue()
    assert "   2" in out   # número de línea de la fila cambiada


def test_diff_warning_color_for_conflicts():
    ui, buf = make_ui(80)
    diff = compute_diff("a\n", "b\n", "f.txt", conflict_note="bloque desactualizado")
    ui.render_diff(diff)
    out = buf.getvalue()
    assert "bloque desactualizado" in out
    assert "\x1b[33m" in out or "\x1b[93m" in out   # amarillo


def test_diff_binary_message():
    ui, buf = make_ui(80)
    diff = compute_diff(None, None, "imagen.png", is_binary=True)
    ui.render_diff(diff)
    assert "binario" in buf.getvalue()


def test_diff_no_color_mode():
    ui, buf = make_ui(80, color=False)
    diff = compute_diff("a\n", "b\n", "f.txt")
    ui.render_diff(diff)
    out = buf.getvalue()
    assert "\x1b[" not in out
    assert "+ b" in out and "- a" in out


# --------------------------------------------------------------- pantallas pequeñas
def test_small_screen_detection():
    ui, _ = make_ui(40)
    assert ui.small_screen
    ui2, _ = make_ui(100)
    assert not ui2.small_screen


def test_panels_fit_narrow_width():
    ui, buf = make_ui(36)
    ui.panel("Estado", "Workspace: /data/data/com.termux/files/home/proyectos/largo\n"
                       "Proveedor: ollama-local/llama3.2:latest")
    for line in buf.getvalue().splitlines():
        assert visible_len(line) <= 36, f"Línea demasiado ancha ({visible_len(line)}): {line!r}"


def test_long_diff_line_wrapped_not_broken_on_small_screen():
    ui, buf = make_ui(40)
    diff = compute_diff("x = 1\n", "x = " + "9" * 120 + "\n", "f.py")
    ui.render_diff(diff)
    for line in buf.getvalue().splitlines():
        assert visible_len(line) <= 40


def test_kv_panel_narrow():
    ui, buf = make_ui(34)
    ui.kv("Proveedores", ["ollama-local [ollama] http://127.0.0.1:11434 modelo=llama3.2"])
    assert "Proveedores" in buf.getvalue()
    for line in buf.getvalue().splitlines():
        assert visible_len(line) <= 34


# ------------------------------------------------------------------------- logo
def test_logo_adapts_to_width():
    assert get_logo(120) == LOGO_SHADOW
    assert get_logo(30) == LOGO_FULL
    longest = max(len(l) for l in LOGO_FULL.splitlines())
    assert longest <= 34   # cabe en un teléfono en vertical


def test_banner_renders():
    ui, buf = make_ui(44)
    ui.banner(get_logo(44), "N E X O", "Tu IA · Tu Terminal")
    assert "N E X O" in buf.getvalue()


# -------------------------------------------------------------- utilidades de texto
def test_visible_len_ignores_ansi():
    assert visible_len("\x1b[32mverde\x1b[0m") == 5


def test_truncate():
    assert truncate("abcdefghij", 6) == "abcde…"
    assert truncate("corto", 10) == "corto"
    assert truncate("x", 0) == ""


def test_wrap_lines():
    text = "palabra " * 30
    lines = wrap_lines(text.strip(), 20)
    assert all(visible_len(l) <= 20 for l in lines)
    # No se pierden palabras.
    assert sum(len(l.split()) for l in lines) == 30


def test_wrap_long_word_is_cut():
    lines = wrap_lines("x" * 50, 20)
    assert all(visible_len(l) <= 20 for l in lines)


# --------------------------------------------------------------- streaming / varios
def test_streaming_writes_plain_text_without_markup():
    ui, buf = make_ui(80)
    ui.stream_start()
    ui.stream_write("texto [bold]no-marcado[/bold]")
    ui.stream_end()
    out = buf.getvalue()
    assert "[bold]no-marcado[/bold]" in out   # el markup del modelo NO se interpreta


def test_spinner_disabled_without_animation():
    ui, buf = make_ui(80)
    with ui.spinner("trabajando…"):
        pass
    assert "trabajando" in buf.getvalue()


def test_messages_have_icons():
    ui, buf = make_ui(60)
    ui.success("bien")
    ui.error("mal")
    ui.warn("ojo")
    ui.info("dato")
    out = buf.getvalue()
    assert "✔" in out and "✖" in out and "⚠" in out and "ℹ" in out
