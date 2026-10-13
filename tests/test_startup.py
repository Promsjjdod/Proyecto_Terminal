"""Arranque robusto de `nexo`: sin proveedor, workspace inválido, bases corruptas.

Criterio: la sesión queda VIVA, los errores son accionables y no se finge éxito.
Ninguna prueba consume red ni tokens (todo local o simulado).
"""
from __future__ import annotations

import io
import os
import sys

import pytest
from rich.console import Console

from nexo.app import NexoApp
from nexo.config.settings import Config


@pytest.fixture(autouse=True)
def restore_stdin():
    old = sys.stdin
    yield
    sys.stdin = old


def build_app(nexo_home, workspace, capture=True, **cfg_kwargs):
    cfg = Config(config_dir=nexo_home, workspace=workspace, **cfg_kwargs)
    stdout = io.StringIO()
    old = sys.stdout
    if capture:
        sys.stdout = stdout
    try:
        app = NexoApp(config=cfg, interactive=False)
    finally:
        if capture:
            sys.stdout = old
    buf = io.StringIO()
    app.ui.console = Console(file=buf, width=78, force_terminal=False)
    app._buffer = buf
    return app, stdout.getvalue()


def out(app) -> str:
    value = app._buffer.getvalue()
    app._buffer.truncate(0)
    app._buffer.seek(0)
    return value


# ------------------------------------------------------------ sin proveedor activo
def test_boot_without_provider_guides_user(workspace, nexo_home):
    app, startup = build_app(nexo_home, workspace)
    try:
        app._print_status()
        texto = out(app)
        assert "SIN PROVEEDOR" in texto
        assert "/provider" in texto            # guía concreta de incorporación
        assert app.registry.active() is None
        # El resto de la sesión sigue viva y funcional.
        app.cmd_files([])
        assert "Archivos" in out(app)
    finally:
        app._shutdown()


def test_chat_without_provider_is_actionable(workspace, nexo_home):
    app, _ = build_app(nexo_home, workspace)
    try:
        app.cmd_chat(["hola"])
        texto = out(app)
        assert "proveedor" in texto.lower()
        assert "/provider" in texto
    finally:
        app._shutdown()


def test_doctor_without_provider_reports_problems(workspace, nexo_home):
    app, _ = build_app(nexo_home, workspace)
    try:
        app.cmd_doctor([])
        texto = out(app)
        assert "proveedor" in texto.lower()
    finally:
        app._shutdown()


# ------------------------------------------------------------- workspace inválido
def test_missing_workspace_falls_back_with_warning(tmp_path, nexo_home):
    inexistente = str(tmp_path / "workspace-que-no-existe")
    cfg = Config(config_dir=nexo_home, workspace=inexistente)
    stdout = io.StringIO()
    old, sys.stdout = sys.stdout, stdout
    try:
        app = NexoApp(config=cfg, interactive=False)
    finally:
        sys.stdout = old
    try:
        aviso = stdout.getvalue()
        assert "no existe" in aviso
        assert "Arranco con" in aviso or "arranco con" in aviso.lower()
        # Queda en un workspace REAL (cwd o home), nunca en la ruta rota.
        assert os.path.isdir(str(app.guard.workspace))
        assert str(app.guard.workspace) != inexistente
    finally:
        app._shutdown()


# ------------------------------------------------------------ bases de datos rotas
def test_corrupt_memory_db_is_preserved_and_recreated(workspace, nexo_home):
    db = Config(config_dir=nexo_home, workspace=workspace).db_path
    with open(db, "wb") as fh:
        fh.write(b"esto no es sqlite" * 100)
    app, startup = build_app(nexo_home, workspace)
    try:
        assert "dañada" in startup or "nueva" in startup
        preservados = [n for n in os.listdir(nexo_home) if "corrupto" in n]
        assert preservados, "la base dañada debe preservarse, no borrarse"
        # La memoria nueva funciona de verdad.
        cid = app.memory.new_conversation("arranque")
        app.memory.add_message(cid, "user", "hola")
        assert app.memory.get_messages(cid)
    finally:
        app._shutdown()


def test_corrupt_secrets_file_does_not_break_boot(workspace, nexo_home):
    secrets = Config(config_dir=nexo_home, workspace=workspace).secrets_path
    with open(secrets, "w", encoding="utf-8") as fh:
        fh.write("{json roto")
    app, startup = build_app(nexo_home, workspace)
    try:
        assert app.secrets.get("cualquiera") is None
        # Guardar una clave nueva sigue funcionando (recupera el archivo).
        app.secrets.set("p", "k-1234567890")
        assert app.secrets.get("p") == "k-1234567890"
    finally:
        app._shutdown()


def test_corrupt_config_file_falls_back_to_defaults(tmp_path, monkeypatch):
    home = tmp_path / "nexo"
    home.mkdir()
    from nexo.config.settings import CONFIG_FILENAME
    (home / CONFIG_FILENAME).write_text("{config roto", encoding="utf-8")
    from nexo.config.settings import load_config
    cfg = load_config(str(home))
    assert not cfg.active_provider          # defaults sanos, sin traceback


# ------------------------------------------------------------------ REPL completo
def test_repl_boots_prints_header_and_exits(workspace, nexo_home, monkeypatch):
    app, _ = build_app(nexo_home, workspace)
    # La UI vuelve al stdout real para capturar el arranque completo.
    app.ui.console = Console(force_terminal=False, width=78)
    monkeypatch.setattr(sys, "stdin", io.StringIO("/exit\n"))
    stdout = io.StringIO()
    old, sys.stdout = sys.stdout, stdout
    try:
        rc = app.run()
    finally:
        sys.stdout = old
    texto = stdout.getvalue()
    assert rc == 0
    assert "AGENTE DE CÓDIGO" in texto        # encabezado estilo Codex
    assert "SIN CONFIGURAR" in texto
    assert "/menu" in texto                   # accesos rápidos visibles


def test_repl_survives_bad_command(workspace, nexo_home, monkeypatch):
    app, _ = build_app(nexo_home, workspace)
    app.ui.console = Console(force_terminal=False, width=78)
    monkeypatch.setattr(sys, "stdin", io.StringIO(
        "/comando_inexistente\n/view\n/export\n/exit\n"))
    stdout = io.StringIO()
    old, sys.stdout = sys.stdout, stdout
    try:
        rc = app.run()
    finally:
        sys.stdout = old
    texto = stdout.getvalue()
    assert rc == 0                            # la sesión NO se cae
    assert "Desconocido" in texto or "desconocido" in texto
    assert "Uso: /view" in texto
    assert "Uso: /export" in texto


def test_cli_doctor_command_runs(tmp_path, monkeypatch):
    """`nexo doctor` ejecuta de verdad y devuelve código 0 con salida útil."""
    monkeypatch.setenv("HOME", str(tmp_path))
    from nexo.cli import main
    stdout = io.StringIO()
    old, sys.stdout = sys.stdout, stdout
    try:
        rc = main(["doctor"])
    finally:
        sys.stdout = old
    assert rc == 0
    assert "DIAGNÓSTICO" in stdout.getvalue().upper()
