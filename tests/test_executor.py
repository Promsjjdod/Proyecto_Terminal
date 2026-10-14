"""Pruebas del ejecutor de comandos: salida, códigos, timeout, límites y permisos."""
from __future__ import annotations

import os
import threading
import time

from nexo.permissions.manager import OperationKind


def test_echo_command(stack):
    result = stack["executor"].run("echo hola-nexo")
    assert result.ok
    assert result.exit_code == 0
    assert "hola-nexo" in result.stdout


def test_exit_code_and_stderr(stack):
    result = stack["executor"].run("ls /ruta-que-no-existe-xyz")
    assert not result.ok
    assert result.exit_code != 0
    assert result.stderr.strip()


def test_cwd_is_workspace_and_relative(stack):
    stack["fs"].write_text("marcador.txt", "x")
    result = stack["executor"].run("cat marcador.txt")
    assert result.ok and result.cwd == str(stack["guard"].workspace)


def test_cwd_outside_workspace_denied(stack, workspace):
    result = stack["executor"].run("ls", cwd=os.path.dirname(workspace))
    assert not result.authorized


def test_dangerous_command_denied_without_ask(stack):
    # Modo autónomo (fixture) pero sin callback: los peligrosos se deniegan.
    result = stack["executor"].run("rm -rf carpeta-importante")
    assert not result.authorized
    assert "destructivo" in result.denial_reason or "peligroso" in result.denial_reason.lower() \
        or result.denial_reason


def test_dangerous_command_allowed_with_explicit_grant(stack):
    stack["fs"].mkdir("basura")
    stack["fs"].write_text("basura/x.txt", "x")
    stack["permissions"].grant(OperationKind.EXEC_DANGEROUS, "rm -rf basura")
    result = stack["executor"].run("rm -rf basura")
    assert result.ok
    assert not os.path.exists(os.path.join(stack["workspace"], "basura"))


def test_timeout_kills_hung_process(stack):
    result = stack["executor"].run("sleep 30", timeout=1.0)
    assert result.timed_out
    assert not result.ok
    assert result.duration_ms < 10_000
    assert "timeout" in result.stderr.lower()


def test_timeout_kills_child_processes(stack):
    # Shell que lanza un hijo: el grupo completo debe morir (start_new_session).
    result = stack["executor"].run("sh -c 'sleep 30 & sleep 30'", timeout=1.0)
    assert result.timed_out


def test_cancel_interrupts_running_process(stack):
    results = []
    # La conexión SQLite de la fixture está ligada al hilo que la creó; la
    # prueba aquí la API del ejecutor, no la concurrencia de la base de datos.
    stack["executor"].memory = None
    worker = threading.Thread(
        target=lambda: results.append(stack["executor"].run("sleep 30", timeout=20)),
        daemon=True,
    )
    worker.start()
    deadline = time.monotonic() + 5
    while stack["executor"].running_count() == 0 and time.monotonic() < deadline:
        time.sleep(0.02)
    assert stack["executor"].running_count() == 1
    assert stack["executor"].cancel()
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert len(results) == 1
    assert results[0].cancelled
    assert not results[0].timed_out
    assert not results[0].ok
    assert "cancelado" in results[0].stderr.lower()


def test_output_limit_truncates(stack):
    stack["executor"].max_output_chars = 500
    result = stack["executor"].run("python3 -c \"print('x' * 5000)\"")
    assert result.ok
    assert result.truncated
    assert len(result.stdout) <= 600


def test_progressive_output_callback(stack):
    chunks = []
    result = stack["executor"].run("echo uno; echo dos", on_output=chunks.append)
    assert result.ok
    assert "uno" in "".join(chunks)


def test_empty_command_rejected(stack):
    result = stack["executor"].run("   ")
    assert not result.authorized
    assert "vacío" in result.denial_reason


def test_denied_command_logged_in_memory(stack):
    stack["executor"].run("rm -rf /")
    ops = stack["memory"].recent_operations(5)
    assert any(kind == "exec_denegado" for _, kind, _, _, _ in ops)


def test_env_contains_workspace(stack):
    result = stack["executor"].run("echo $NEXO_WORKSPACE")
    assert result.ok
    assert result.stdout.strip() == str(stack["guard"].workspace)


def test_multiline_script(stack):
    script = "for i in 1 2 3; do echo linea-$i; done"
    result = stack["executor"].run(script)
    assert result.ok
    assert "linea-1" in result.stdout and "linea-3" in result.stdout


def test_summary_format(stack):
    result = stack["executor"].run("echo resumen-ok")
    summary = result.summary()
    assert summary.startswith("$ echo resumen-ok")
    assert "código=0" in summary
    assert "resumen-ok" in summary
