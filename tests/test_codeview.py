"""Caja de código (/view): lenguaje, ventana, avisos honestos y portapapeles."""
from __future__ import annotations

import io

import pytest
from rich.console import Console

from nexo.config.settings import AgentLimits, Config
from nexo.app import NexoApp
from nexo.ui import codeview
from nexo.ui.render import UI


@pytest.fixture
def app(workspace, nexo_home):
    cfg = Config(config_dir=nexo_home, workspace=workspace, permission_mode="autonomo")
    cfg.agent_limits = AgentLimits(max_iterations=6, max_seconds=30)
    application = NexoApp(config=cfg, interactive=False)
    buf = io.StringIO()
    application.ui.console = Console(file=buf, width=72, force_terminal=False)
    application._buffer = buf   # type: ignore[attr-defined]
    yield application
    application._shutdown()


def make_ui(width: int = 80) -> tuple:
    buf = io.StringIO()
    console = Console(file=buf, width=width, force_terminal=True, color_system="standard")
    return UI(console, animate=False), buf


def test_detect_language():
    assert codeview.detect_language("app.py") == "python"
    assert codeview.detect_language("estilo.CSS") == "css"
    assert codeview.detect_language("index.html") == "html"
    assert codeview.detect_language("sin_ext") == "text"


def test_slice_window_offset_limit():
    text = "\n".join(f"L{i}" for i in range(1, 11))
    window, first, last, v_trunc, h_trunc = codeview.slice_window(text, 3, 4, 0, 60)
    assert window.splitlines()[0] == "L3"
    assert (first, last) == (3, 6)
    assert v_trunc is True and h_trunc is False


def test_slice_window_column_shift():
    text = "x" * 100
    window, first, last, v_trunc, h_trunc = codeview.slice_window(text, 1, None, 20, 40)
    assert len(window) == 40 and h_trunc is True


def test_render_code_header_and_numbers():
    ui, buf = make_ui(90)
    codeview.render_code(ui, "def f():\n    return 1\n", "modulo.py")
    import re
    plain = re.sub(r"\x1b\[[0-9;]*m", "", buf.getvalue())
    assert "python" in plain and "modulo.py" in plain
    assert "2 líneas" in plain
    assert "def f():" in plain       # código visible tras quitar ANSI
    assert " 1 " in plain and " 2 " in plain   # canaleta de números de línea


def test_render_code_window_note_is_honest():
    ui, buf = make_ui(90)
    text = "\n".join(f"linea {i}" for i in range(1, 51))
    codeview.render_code(ui, text, "largo.txt", limit=10)
    out = buf.getvalue()
    assert "mostrando 1-10" in out
    assert "--desde 11" in out          # indica cómo continuar
    assert "Contenido largo" in out


def test_render_code_wide_lines_offer_col_or_wrap():
    ui, buf = make_ui(40)
    codeview.render_code(ui, "y = " + "z" * 200, "ancho.py", wrap=False)
    out = buf.getvalue()
    assert "--col" in out and "--wrap" in out


def test_render_code_empty_file_message():
    ui, buf = make_ui(60)
    codeview.render_code(ui, "", "vacío.txt")
    assert "El archivo está vacío." in buf.getvalue()


def test_copy_to_clipboard_without_tool(monkeypatch):
    import shutil
    monkeypatch.setattr(shutil, "which", lambda name: None)
    mensaje = codeview.copy_to_clipboard("contenido")
    assert mensaje is not None and "termux-api" in mensaje


def test_copy_to_clipboard_uses_termux(monkeypatch):
    calls = {}

    class FakeRun:
        def __call__(self, cmd, input=None, timeout=None, check=None):
            calls["cmd"] = cmd
            calls["input"] = input
            return None

    import shutil
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/termux-clipboard-set")
    monkeypatch.setattr("subprocess.run", FakeRun())
    assert codeview.copy_to_clipboard("hola") is None
    assert calls["cmd"] == ["/usr/bin/termux-clipboard-set"]
    assert calls["input"] == b"hola"


def test_cmd_view_workspace_file(app, workspace):
    import os
    with open(os.path.join(workspace, "v.py"), "w", encoding="utf-8") as fh:
        fh.write("print('hola')\n")
    app.dispatch("/view v.py")
    assert "python · v.py" in out(app)


def test_cmd_view_outside_needs_authorization(app, tmp_path):
    externo = tmp_path / "fuera.txt"
    externo.write_text("texto externo", encoding="utf-8")
    # Sin callback de autorización -> denegado (no filtra contenido).
    app.dispatch(f"/view {externo}")
    texto = out(app)
    assert "denegado" in texto.lower() or "Permiso" in texto
    assert "texto externo" not in texto


def test_cmd_view_missing_file(app):
    app.dispatch("/view no_existe.py")
    assert "error" in out(app).lower() or "no existe" in out(app).lower()


# helper compartido con test_app.py
def out(app) -> str:
    return app._buffer.getvalue() if hasattr(app, "_buffer") else ""
