"""Pruebas del ciclo del agente con proveedores simulados (sin APIs reales)."""
from __future__ import annotations

import json
import os

import pytest

from nexo.agent.loop import Agent, parse_tool_call
from nexo.config.settings import AgentLimits, ProviderConfig
from nexo.providers.base import TransportError
from nexo.providers.registry import ProviderRegistry
from tests.conftest import FakeProvider


def tool_json(action: str, **args) -> str:
    return "```json\n" + json.dumps({"action": action, "args": args}) + "\n```"


@pytest.fixture
def agent_stack(stack, nexo_home, workspace):
    cfg = stack["config"]
    reg = ProviderRegistry(cfg, stack["secrets"])
    return {"stack": stack, "registry": reg, "cfg": cfg}


def make_agent(agent_stack, responses, limits=None, on_event=None):
    cfg = agent_stack["cfg"]
    cfg.set_provider(ProviderConfig(name="fake", type="ollama", model="m", stream=False))
    cfg.active_provider = "fake"
    fake = FakeProvider(cfg.get_provider("fake"), responses=responses)
    registry = agent_stack["registry"]
    registry.get = lambda name=None: fake   # inyección del proveedor simulado
    agent = Agent(registry, agent_stack["stack"]["catalog"], agent_stack["stack"]["memory"],
                  limits or AgentLimits(max_iterations=8, max_seconds=60),
                  on_event=on_event)
    return agent, fake


# ---------------------------------------------------------------- parsing de llamadas
def test_parse_tool_call_fenced():
    text = "Voy a leer el archivo.\n```json\n{\"action\": \"read_file\", \"args\": {\"path\": \"a.txt\"}}\n```"
    action, args = parse_tool_call(text)
    assert action == "read_file" and args == {"path": "a.txt"}


def test_parse_tool_call_bare_json():
    action, args = parse_tool_call('Pienso... {"action": "list_dir", "args": {}} luego nada')
    assert action == "list_dir" and args == {}


def test_parse_tool_call_invalid_json_ignored():
    assert parse_tool_call("```json\n{roto}\n``` texto normal") is None


def test_parse_tool_call_no_action_is_conversation():
    assert parse_tool_call("Hola, ¿en qué te ayudo?") is None


def test_parse_tool_call_args_missing_defaults_empty():
    action, args = parse_tool_call('{"action": "finish"}')
    assert action == "finish" and args == {}


# -------------------------------------------------------------------- ciclo completo
def test_conversation_without_tools(agent_stack):
    agent, fake = make_agent(agent_stack, ["¡Hola! Soy NEXO."])
    outcome = agent.run("hola")
    assert outcome.status == "conversacion"
    assert outcome.reply == "¡Hola! Soy NEXO."
    assert outcome.success


def test_agent_creates_archivo_y_termina(agent_stack):
    responses = [
        "PLAN:\n1. Crear archivo\n2. Verificar\n" + tool_json("create_file", path="hola.txt", content="contenido\n"),
        tool_json("read_file", path="hola.txt"),
        tool_json("finish", summary="Creé hola.txt y verifiqué su contenido leyendo el archivo.", success=True),
    ]
    agent, fake = make_agent(agent_stack, responses)
    outcome = agent.run("crea hola.txt con 'contenido'")
    assert outcome.status == "terminada" and outcome.success
    assert outcome.iterations == 3
    assert outcome.plan == ["Crear archivo", "Verificar"]
    path = os.path.join(agent_stack["stack"]["workspace"], "hola.txt")
    assert os.path.exists(path)
    assert open(path, encoding="utf-8").read() == "contenido\n"
    # La verificación real ocurrió: la herramienta read_file devolvió el contenido.
    tool_results = [m for call in fake.calls for m in call if m.role == "user"
                    and "[RESULTADO read_file]" in m.content]
    assert tool_results and "contenido" in tool_results[-1].content


def test_agent_emits_only_terminal_progress_not_iteration_estimates(agent_stack):
    responses = [
        tool_json("list_dir", path="."),
        tool_json("list_dir", path="."),
        tool_json("finish", summary="Inspección terminada.", success=True),
    ]
    events = []
    agent, _ = make_agent(agent_stack, responses, on_event=lambda kind, value: events.append((kind, value)))
    outcome = agent.run("inspecciona el workspace")
    assert outcome.status == "terminada"
    progress = [value for kind, value in events if kind == "progress"]
    assert progress == ["100"]
    assert all(value == "100" for value in progress)


def test_agent_tool_error_is_reported_to_model(agent_stack):
    responses = [
        tool_json("read_file", path="no-existe.txt"),
        tool_json("finish", summary="El archivo no existe; no pude completar la tarea.", success=False),
    ]
    agent, fake = make_agent(agent_stack, responses)
    outcome = agent.run("lee no-existe.txt")
    assert outcome.status == "terminada" and not outcome.success
    feedback = [m for call in fake.calls for m in call if m.role == "user"
                and "[RESULTADO read_file]" in m.content]
    assert feedback and "ok=False" in feedback[0].content


def test_agent_unknown_tool_feedback(agent_stack):
    responses = [
        tool_json("volar", x=1),
        tool_json("finish", summary="Corregí tras el error.", success=True),
    ]
    agent, fake = make_agent(agent_stack, responses)
    outcome = agent.run("haz algo")
    assert outcome.status == "terminada"
    feedback = [m for call in fake.calls for m in call if m.role == "user"
                and "desconocida" in m.content]
    assert feedback


def test_agent_ask_user_pauses(agent_stack):
    responses = [tool_json("ask_user", question="¿Qué nombre quieres para el archivo?")]
    agent, fake = make_agent(agent_stack, responses)
    outcome = agent.run("crea un archivo")
    assert outcome.status == "necesita_usuario" and outcome.needs_user
    assert outcome.question == "¿Qué nombre quieres para el archivo?"
    # La tarea quedó interrumpida y es recuperable.
    task = agent_stack["stack"]["memory"].get_task(outcome.task_id)
    assert task.status == "interrumpida"
    assert agent_stack["stack"]["memory"].interrupted_tasks()


def test_agent_iteration_limit(agent_stack):
    responses = [tool_json("list_dir", path=".")] * 10
    agent, fake = make_agent(agent_stack, responses,
                             limits=AgentLimits(max_iterations=3, max_seconds=60))
    outcome = agent.run("lista para siempre")
    assert outcome.status == "limite_iteraciones" and not outcome.success
    assert outcome.iterations == 3
    assert "resume" in outcome.reply   # ofrece recuperación honesta


def test_agent_time_limit(agent_stack):
    responses = [tool_json("list_dir", path=".")] * 50
    agent, fake = make_agent(agent_stack, responses,
                             limits=AgentLimits(max_iterations=50, max_seconds=0.0))
    outcome = agent.run("tarea lenta")
    assert outcome.status == "limite_tiempo" and not outcome.success


def test_agent_provider_error_is_honest(agent_stack):
    cfg = agent_stack["cfg"]
    cfg.set_provider(ProviderConfig(name="fake", type="ollama", model="m", stream=False))
    cfg.active_provider = "fake"
    broken = FakeProvider(cfg.get_provider("fake"),
                          error=TransportError("servidor caído", provider="fake"))
    agent_stack["registry"].get = lambda name=None: broken
    agent = Agent(agent_stack["registry"], agent_stack["stack"]["catalog"],
                  agent_stack["stack"]["memory"], AgentLimits())
    outcome = agent.run("hola")
    assert outcome.status == "fallida" and "servidor caído" in outcome.reply
    assert outcome.success is False


def test_agent_no_provider_explains(agent_stack):
    agent = Agent(agent_stack["registry"], agent_stack["stack"]["catalog"],
                  agent_stack["stack"]["memory"], AgentLimits())
    outcome = agent.run("hola")
    assert outcome.status == "fallida"
    assert "proveedor" in outcome.reply.lower()


def test_agent_permissions_denied_is_visible(agent_stack):
    """Con permisos denegados (sin ask), la herramienta informa y el agente no elude."""
    stack = agent_stack["stack"]
    stack["permissions"].set_mode("seguro")           # sin ask_user -> deniega escrituras
    responses = [
        tool_json("create_file", path="x.txt", content="x"),
        tool_json("finish", summary="No pude crear el archivo: permiso denegado.", success=False),
    ]
    agent, fake = make_agent(agent_stack, responses)
    outcome = agent.run("crea x.txt")
    feedback = [m for call in fake.calls for m in call if m.role == "user"
                and "PERMISO DENEGADO" in m.content]
    assert feedback
    assert outcome.status == "terminada" and outcome.success is False
    assert not os.path.exists(os.path.join(stack["workspace"], "x.txt"))


def test_agent_resume_continues_task(agent_stack):
    memory = agent_stack["stack"]["memory"]
    responses = [
        tool_json("ask_user", question="¿Continuo?"),
        tool_json("finish", summary="Terminado tras la respuesta del usuario.", success=True),
    ]
    agent, fake = make_agent(agent_stack, responses)
    outcome = agent.run("tarea larga")
    assert outcome.needs_user
    follow = agent.resume(outcome.task_id, extra="Respuesta del usuario: sí, continúa")
    assert follow.status == "terminada" and follow.success
    # El contexto adicional llegó al modelo.
    assert any("sí, continúa" in m.content for call in fake.calls for m in call if m.role == "user")
    task = memory.get_task(outcome.task_id)
    assert task.status == "completada"


def test_agent_streaming_callback(agent_stack):
    deltas = []
    cfg = agent_stack["cfg"]
    cfg.set_provider(ProviderConfig(name="fake", type="ollama", model="m", stream=True))
    cfg.active_provider = "fake"
    fake = FakeProvider(cfg.get_provider("fake"), responses=["respuesta simple"])
    agent_stack["registry"].get = lambda name=None: fake
    agent = Agent(agent_stack["registry"], agent_stack["stack"]["catalog"],
                  agent_stack["stack"]["memory"], AgentLimits(),
                  on_delta=deltas.append)
    outcome = agent.run("di algo")
    assert outcome.status == "conversacion"
    assert "".join(deltas).strip() == "respuesta simple"


def test_agent_records_operations_in_memory(agent_stack):
    memory = agent_stack["stack"]["memory"]
    responses = [
        tool_json("create_file", path="audit.txt", content="1"),
        tool_json("finish", summary="ok", success=True),
    ]
    agent, fake = make_agent(agent_stack, responses)
    agent.run("crea audit.txt")
    ops = memory.recent_operations(10)
    kinds = [k for _, k, _, _, _ in ops]
    assert any(k == "tool:create_file" for k in kinds)
