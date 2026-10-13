"""Pruebas de integración del REPL (no interactivo): los comandos hacen trabajo real."""
from __future__ import annotations

import io
import json
import os

import pytest
from rich.console import Console

from nexo.app import NexoApp
from nexo.config.settings import AgentLimits, Config, ProviderConfig
from nexo.permissions.manager import OperationKind
from nexo.tools.executor import CommandResult
from tests.conftest import FakeProvider


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


def out(app) -> str:
    value = app._buffer.getvalue()   # type: ignore[attr-defined]
    app._buffer.truncate(0)          # type: ignore[attr-defined]
    app._buffer.seek(0)              # type: ignore[attr-defined]
    return value


def install_fake_provider(app, responses):
    cfg = ProviderConfig(name="fake", type="ollama", base_url="http://x",
                         model="m", stream=False)
    app.config.set_provider(cfg)
    app.config.active_provider = "fake"
    fake = FakeProvider(cfg, responses=responses)
    app.registry.get = lambda name=None: fake     # type: ignore[assignment]
    app.registry.active = lambda: fake            # type: ignore[assignment]
    return fake


def tool_json(action: str, **args) -> str:
    return "```json\n" + json.dumps({"action": action, "args": args}) + "\n```"


# ------------------------------------------------------------------- comandos base
def test_help_lists_commands(app):
    app.dispatch("/help")
    texto = out(app)
    for cmd in ("/menu", "/view", "/export", "/provider", "/workspace", "/files",
                "/create", "/edit", "/diff", "/apply", "/undo", "/permissions",
                "/exec", "/git", "/github", "/history", "/tasks", "/config",
                "/doctor", "/clear", "/exit"):
        assert cmd in texto


def test_help_command_detail(app):
    app.dispatch("/help provider")
    texto = out(app)
    assert "onboard" in texto and "key" in texto


def test_unknown_command(app):
    app.dispatch("/noexiste")
    assert "desconocido" in out(app)


def test_interactive_start_clears_visible_terminal(app, monkeypatch):
    terminal_output = io.StringIO()
    app.interactive = True
    app.ui.console = Console(file=terminal_output, width=72, force_terminal=True)
    monkeypatch.setattr(app, "_read_command_line", lambda: (_ for _ in ()).throw(EOFError()))
    monkeypatch.setattr(app, "_shutdown", lambda: None)
    app.run()
    assert "\x1b[2J" in terminal_output.getvalue()


def test_workspace_show(app, workspace):
    app.dispatch("/workspace")
    assert workspace in out(app).replace('\n', '')


def test_workspace_change(app, tmp_path, workspace):
    nuevo = tmp_path / "otro-ws"
    nuevo.mkdir()
    app.dispatch(f"/workspace {nuevo}")
    texto = out(app)
    assert "cambiado" in texto
    assert str(app.guard.workspace) == str(nuevo)
    # Fuera del workspace real:
    app.dispatch("/workspace /ruta/inexistente")
    assert "no existe" in out(app)


def test_files_listing(app):
    app.fs.write_text("sub/carpeta.txt", "x")
    app.dispatch("/files")
    assert "sub/" in out(app)
    app.dispatch("/files sub")
    texto = out(app)
    assert os.path.join("sub", "carpeta.txt") in texto or "carpeta.txt" in texto


def test_agent_change_summary_uses_net_applied_diff(app):
    app.fs.write_text("cambio.py", "conservar\nviejo\n")
    app.catalog.reset_task_tracking()
    result = app.catalog.execute("write_file", {
        "path": "cambio.py", "content": "conservar\nnuevo\n"
    })
    assert result.ok
    summary = app.catalog.task_change_summary()
    assert summary["created"] == 0
    assert summary["modified"] == 1
    assert summary["deleted"] == 0
    assert summary["added"] == 1
    assert summary["removed"] == 1
    assert summary["files"][0]["path"] == "cambio.py"


def test_agent_renders_verified_file_diff_immediately(app):
    app._on_agent_event("tool", {"action": "create_file", "path": "live.py"})
    pending = out(app)
    assert "en curso" in pending and "100%" not in pending
    result = app.catalog.execute("create_file", {
        "path": "live.py", "content": "print('visible')\n"
    })
    assert result.ok and "diff" in result.data
    app._on_agent_event("tool_result", result)
    output = out(app)
    assert "SAVE 100%" in output and "verificado en disco" in output
    assert "LIVE CODE" in output and "strip:" in output
    assert "live.py" in output and "print('visible')" in output


def test_startup_shows_session_dashboard(app):
    app._print_status()
    output = out(app)
    assert "PANEL DE SESIÓN" in output
    assert "ENGINE" in output and "WORKSPACE" in output
    assert "no comprobada" in output


def test_agent_change_summary_omits_created_then_deleted_file(app):
    app.catalog.reset_task_tracking()
    assert app.catalog.execute("create_file", {
        "path": "temporal.txt", "content": "línea\n"
    }).ok
    app.permissions.grant(OperationKind.DELETE_FILE, "temporal.txt")
    assert app.catalog.execute("delete_file", {"path": "temporal.txt"}).ok
    summary = app.catalog.task_change_summary()
    assert summary["files"] == []
    assert summary["created"] == summary["modified"] == summary["deleted"] == 0


def test_agent_summary_records_test_runner_result(app, monkeypatch):
    monkeypatch.setattr(app.executor, "run", lambda command, timeout=None: CommandResult(
        command=command, exit_code=0, stdout="2 passed", authorized=True))
    app.catalog.reset_task_tracking()
    result = app.catalog.execute("run_command", {"command": "python -m pytest -q"})
    assert result.ok
    tests = app.catalog.task_change_summary()["tests"]
    assert tests == [{"runner": "pytest", "exit_code": 0,
                      "timed_out": False, "authorized": True}]


def test_run_command_tool_reports_nonzero_exit_as_failure(app, monkeypatch):
    monkeypatch.setattr(app.executor, "run", lambda command, timeout=None: CommandResult(
        command=command, exit_code=2, stderr="falló", authorized=True))
    result = app.catalog.execute("run_command", {"command": "python -m pytest"})
    assert not result.ok
    assert "código=2" in result.output


# ------------------------------------------------------- flujo create/diff/apply/undo
def test_create_diff_apply_undo_flow(app, workspace):
    app.dispatch("/create notas.md contenido inicial")
    texto = out(app)
    assert "+ contenido inicial" in texto.replace("|", "") or "contenido inicial" in texto
    assert "pendiente" in texto

    app.dispatch("/diff")
    assert "notas.md" in out(app)

    ruta = os.path.join(workspace, "notas.md")
    assert not os.path.exists(ruta)          # aún NO aplicado
    app.dispatch("/apply")
    assert os.path.exists(ruta)
    assert open(ruta, encoding="utf-8").read() == "contenido inicial"
    texto = out(app)
    assert "aplicados" in texto.lower()

    # Edición posterior + undo
    app.dispatch("/create notas.md contenido nuevo")
    app.dispatch("/apply")
    assert open(ruta, encoding="utf-8").read() == "contenido nuevo"
    app.dispatch("/undo notas.md")
    assert open(ruta, encoding="utf-8").read() == "contenido inicial"
    assert "restaurado" in out(app).lower()


def test_discard_pending_changes(app, workspace):
    app.dispatch("/create temp.txt x")
    out(app)
    app.dispatch("/discard")
    assert "descartado" in out(app)
    assert not os.path.exists(os.path.join(workspace, "temp.txt"))
    app.dispatch("/apply")
    assert "No hay cambios pendientes" in out(app)


def test_apply_without_pending(app):
    app.dispatch("/apply")
    assert "No hay cambios" in out(app)


# -------------------------------------------------------------------------- exec
def test_exec_runs_command(app):
    app.dispatch("/exec echo ejecutado-por-nexo")
    texto = out(app)
    assert "ejecutado-por-nexo" in texto
    assert "código 0" in texto


def test_exec_dangerous_denied_without_ask(app):
    app.dispatch("/exec rm -rf /alguna-cosa")
    assert "no autorizado" in out(app).lower() or "DENEGADO" in out(app)


def test_exec_error_code(app):
    app.dispatch("/exec ls /no-existe-xyz")
    texto = out(app)
    assert "código" in texto and "código 0" not in texto


# --------------------------------------------------------------------- permissions
def test_permissions_show_and_mode_switch(app):
    app.dispatch("/permissions")
    texto = out(app)
    assert "autonomo" in texto and "Workspace" in texto
    app.dispatch("/permissions mode estricto")
    assert "estricto" in out(app)
    assert app.permissions.mode == "estricto"
    app.dispatch("/permissions mode inexistente")
    assert "inválido" in out(app)
    app.dispatch("/permissions reset")
    assert "revocada" in out(app)


# ----------------------------------------------------------------------- provider
def test_provider_add_list_use(app):
    app.dispatch("/provider add local ollama http://127.0.0.1:11434 llama3.2")
    texto = out(app)
    assert "añadido" in texto
    app.dispatch("/provider list")
    texto = out(app)
    assert "local" in texto and "llama3.2" in texto and "*" in texto
    app.dispatch("/provider use local")
    assert "activo" in out(app)
    app.dispatch("/provider edit local model=nuevo-modelo timeout=30")
    assert "actualizado" in out(app)
    assert app.config.get_provider("local").model == "nuevo-modelo"
    app.dispatch("/provider delete local")
    # Pide confirmación; en no-interactivo stdin vacío -> deniega por defecto.
    texto = out(app)
    assert "Cancelado" in texto or "eliminado" in texto


def test_provider_add_invalid_type(app):
    app.dispatch("/provider add x magia http://x m")
    assert "desconocido" in out(app)


# ------------------------------------------------------------------ lenguaje natural
def test_natural_language_agent_creates_file(app, workspace):
    install_fake_provider(app, [
        "PLAN:\n1. Crear\n" + tool_json("create_file", path="agente.txt", content="por el agente"),
        tool_json("finish", summary="Archivo creado y verificado.", success=True),
    ])
    app.dispatch("crea agente.txt")
    texto = out(app)
    assert "terminada" in texto.lower() or "Archivo creado" in texto
    ruta = os.path.join(workspace, "agente.txt")
    assert os.path.exists(ruta)
    assert open(ruta, encoding="utf-8").read() == "por el agente"


def test_natural_language_without_provider_explains(app):
    app.dispatch("haz algo")
    texto = out(app)
    assert "proveedor" in texto.lower()


def test_agent_ask_user_flow_noninteractive(app, monkeypatch):
    install_fake_provider(app, [tool_json("ask_user", question="¿Nombre del archivo?")])
    # Simulamos la respuesta del usuario en la entrada estándar.
    monkeypatch.setattr("sys.stdin", io.StringIO("respuesta.txt\n.\n"))
    app2_responses = [tool_json("finish", summary="Listo con la respuesta.", success=True)]
    fake = app.registry.get()
    fake.responses.extend(app2_responses)
    app.dispatch("crea un archivo")
    texto = out(app)
    assert "¿Nombre del archivo?" in texto
    # La tarea quedó registrada como interrumpida y recuperable.
    tasks = app.memory.interrupted_tasks() + app.memory.list_tasks()
    assert tasks


# ------------------------------------------------------------------------ history
def test_history_commands(app):
    app.dispatch("/history new prueba")
    assert "creada" in out(app)
    app.memory.add_message(app.conversation_id, "user", "hola")
    app.dispatch("/history list")
    assert "prueba" in out(app)
    cid = app.conversation_id
    app.dispatch(f"/history show {cid}")
    assert "hola" in out(app)
    app.dispatch(f"/history delete {cid}")
    assert "eliminada" in out(app)


# -------------------------------------------------------------------------- tasks
def test_tasks_list_after_agent_run(app):
    install_fake_provider(app, ["respuesta simple sin herramientas"])
    app.dispatch("di hola")
    out(app)
    app.dispatch("/tasks")
    texto = out(app)
    assert "#" in texto
    assert "di hola" in texto or "respuesta" in texto.lower()


# ------------------------------------------------------------------------- config
def test_config_show_and_set(app):
    app.dispatch("/config show")
    assert "permission_mode" in out(app)
    app.dispatch("/config set command_timeout 30")
    texto = out(app)
    assert "30" in texto
    assert app.config.command_timeout == 30.0
    app.dispatch("/config set agent.max_iterations 4")
    assert app.config.agent_limits.max_iterations == 4
    app.dispatch("/config set clave.rara 1")
    assert "no editable" in out(app)


def test_config_example(app, tmp_path):
    destino = tmp_path / "ejemplo.json"
    app.dispatch(f"/config example {destino}")
    assert "ejemplo" in out(app).lower()
    data = json.loads(destino.read_text(encoding="utf-8"))
    assert "providers" in data


# ------------------------------------------------------------------------- doctor
def test_doctor_runs(app):
    app.dispatch("/doctor")
    texto = out(app)
    assert "Diagnóstico" in texto
    assert "Workspace" in texto
    assert "Dependencia rich" in texto


# ------------------------------------------------------------------------ git/github
def test_git_status_outside_repo(app):
    app.dispatch("/git status")
    texto = out(app)
    # Fuera de un repo, git informa del fallo real.
    assert "falló" in texto or "fatal" in texto.lower() or "git" in texto.lower()


def test_github_status_honest(app):
    app.dispatch("/github status")
    texto = out(app)
    assert "gh" in texto.lower() or "GitHub" in texto


def test_github_scan(app):
    app.fs.write_text("main.py", "print('hola')")
    app.dispatch("/github scan")
    assert "limpio" in out(app).lower() or "Escaneo" in out(app)


# --------------------------------------------------------------------------- exit
def test_exit_stops_loop(app):
    app._running = True
    app.dispatch("/exit")
    assert app._running is False
    assert "Cerrando" in out(app)


def test_persistence_of_config_after_shutdown(app, nexo_home):
    app.dispatch("/provider add persistente ollama http://x modelo-x")
    out(app)
    app._shutdown()
    from nexo.config.settings import load_config
    recargada = load_config(nexo_home)
    assert recargada.get_provider("persistente") is not None
