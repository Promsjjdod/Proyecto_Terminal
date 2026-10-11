"""Pruebas de prompts y compactación de contexto para sesiones largas."""
from __future__ import annotations

from nexo.agent.prompts import build_context, build_system_prompt, render_tool_specs


def test_system_prompt_lists_all_tools():
    prompt = build_system_prompt("/data/proyecto", "seguro", "ollama/llama3.2")
    for tool in ("read_file", "list_dir", "search", "create_file", "write_file",
                 "edit_file", "delete_file", "undo_file", "run_command",
                 "ask_user", "finish"):
        assert tool in prompt
    # Reglas clave presentes.
    assert "planificar" in prompt.lower()
    assert "verificar" in prompt.lower()
    assert "/data/proyecto" in prompt
    assert "seguro" in prompt
    # El JSON de ejemplo sobrevive al formateo (llaves escapadas).
    assert '{"action"' in prompt or "{{" not in prompt


def test_render_tool_specs_contains_descriptions():
    specs = render_tool_specs()
    assert "Reemplazo preciso" in specs
    assert "ask_user" in specs


def test_build_context_short_history_untouched():
    history = [("user", "hola"), ("assistant", "adiós")]
    assert build_context(history, max_messages=10) == history


def test_build_context_compacts_old_messages():
    history = [("user", f"mensaje largo número {i} " + "x" * 300) for i in range(50)]
    context = build_context(history, max_messages=10)
    # 1 resumen + 10 recientes.
    assert len(context) == 11
    assert context[0][0] == "system"
    assert "Resumen de contexto anterior" in context[0][1]
    # Los recientes se conservan intactos.
    assert context[-1] == history[-1]
    # El resumen trunca cada mensaje viejo.
    assert "…" in context[0][1]


def test_build_context_zero_limit_no_crash():
    history = [("user", "x")]
    assert build_context(history, max_messages=0) == history
