"""Tool calling nativo (formato OpenAI/CleanAPIs): ciclo real, paralelo, streaming.

Verifica que las llamadas se interpretan como estructuras `tool_calls` (no
texto), que los resultados vuelven con su `tool_call_id`, y que nada se
ejecuta sin pasar por el catálogo (permisos).
"""
from __future__ import annotations

import json
import os

import httpx
import pytest

from nexo.config.settings import ProviderConfig
from nexo.providers.base import ChatMessage, normalize_tool_calls
from nexo.providers.openai_compat import OpenAICompatProvider
from tests.conftest import mock_client_factory

MSGS = [ChatMessage("user", "hola")]


def tool_call(cid, name, args):
    return {"id": cid, "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}


# ------------------------------------------------------------------ normalización
def test_normalize_tool_calls_parses_arguments_string():
    raw = [{"id": "c1", "function": {"name": "read_file",
                                     "arguments": '{"path": "a.txt"}'}}]
    out = normalize_tool_calls(raw)
    assert out[0]["arguments"] == {"path": "a.txt"}
    assert "_arguments_error" not in out[0]


def test_normalize_tool_calls_invalid_json_flagged():
    out = normalize_tool_calls([{"id": "c1", "function": {
        "name": "edit_file", "arguments": '{"path": '}}])
    assert out[0]["arguments"] == {}
    assert "_arguments_error" in out[0]
    assert out[0]["_raw_arguments"] == '{"path": '


def test_normalize_tool_calls_empty_and_garbage():
    assert normalize_tool_calls([]) == []
    assert normalize_tool_calls([None, "x"]) == []


# ------------------------------------------------------------------- chat nativo
def handler_script(responses):
    state = {"i": 0, "bodies": []}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        state["bodies"].append(body)
        idx = state["i"]
        state["i"] += 1
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "m1"}]})
        return httpx.Response(200, json=responses[idx])

    return handler


def test_agent_native_sends_tools_schema(native_agent):
    """El ciclo nativo envía el esquema OpenAI (tools + tool_choice=auto)."""
    agent, registry, stack = native_agent
    handler = handler_script([
        {"choices": [{"finish_reason": "stop", "message": {"content": "listo"}}]},
    ])
    registry._client_factory = mock_client_factory(handler)
    agent.run("hola")
    # La verificación del cuerpo enviado se hace con una llamada directa:
    from nexo.providers.openai_compat import OpenAICompatProvider
    captured = {}

    def capture(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [
            {"finish_reason": "stop", "message": {"content": "ok"}}]})

    p2 = OpenAICompatProvider(stack["config"].get_provider("nat"), api_key="k",
                              client_factory=mock_client_factory(capture))
    from nexo.tools.schema import openai_tools_schema
    p2.chat(MSGS, tools=openai_tools_schema())
    assert captured["body"]["tools"][0]["type"] == "function"
    assert captured["body"]["tool_choice"] == "auto"
    assert len(captured["body"]["tools"]) >= 10


def test_chat_returns_tool_calls_structured():
    resp = {"choices": [{"index": 0, "finish_reason": "tool_calls",
                         "message": {"role": "assistant", "content": None,
                                     "tool_calls": [tool_call("c1", "list_dir", {"path": "."})]}}]}
    p = OpenAICompatProvider(
        ProviderConfig(name="t", type="openai", base_url="http://t/v1", model="m",
                       retries=0, stream=False),
        api_key="k", client_factory=mock_client_factory(handler_script([resp])))
    reply = p.chat(MSGS, tools=[{"type": "function", "function": {"name": "list_dir"}}])
    assert reply.wants_tools
    assert reply.tool_calls[0]["name"] == "list_dir"
    assert reply.tool_calls[0]["id"] == "c1"
    assert reply.finish_reason == "tool_calls"


def test_chat_stream_accumulates_tool_call_fragments():
    sse = (
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c9",'
        '"function":{"name":"read_","arguments":""}}]}}]}\n\n'
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,'
        '"function":{"name":"file","arguments":"{\\"pa"}}]}}]}\n\n'
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,'
        '"function":{"arguments":"th\\": \\"x.txt\\"}"}}]}}]}\n\n'
        'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}\n\n'
        "data: [DONE]\n\n"
    )
    p = OpenAICompatProvider(
        ProviderConfig(name="t", type="openai", base_url="http://t/v1", model="m",
                       retries=0, stream=True),
        api_key="k",
        client_factory=mock_client_factory(
            lambda request: httpx.Response(200, content=sse.encode(),
                                           headers={"content-type": "text/event-stream"})))
    reply = p.chat(MSGS, tools=[{"type": "function", "function": {"name": "read_file"}}],
                   on_delta=lambda d: None)
    assert reply.tool_calls[0]["id"] == "c9"
    assert reply.tool_calls[0]["name"] == "read_file"
    assert reply.tool_calls[0]["arguments"] == {"path": "x.txt"}


def test_chat_parallel_calls_all_returned():
    resp = {"choices": [{"index": 0, "finish_reason": "tool_calls",
                         "message": {"role": "assistant", "content": "",
                                     "tool_calls": [tool_call("a", "list_dir", {}),
                                                    tool_call("b", "read_file", {"path": "f.txt"})]}}]}
    p = OpenAICompatProvider(
        ProviderConfig(name="t", type="openai", base_url="http://t/v1", model="m",
                       retries=0, stream=False),
        api_key="k", client_factory=mock_client_factory(handler_script([resp])))
    reply = p.chat(MSGS, tools=[{"type": "function",
                                 "function": {"name": "list_dir"}},
                                {"type": "function",
                                 "function": {"name": "read_file"}}])
    assert [c["id"] for c in reply.tool_calls] == ["a", "b"]


def test_capabilities_native_and_meta_override():
    cfg = ProviderConfig(name="t", type="openai", model="m")
    p = OpenAICompatProvider(cfg)
    assert p.capabilities()["tool_calling_native"] is True
    cfg.capabilities = {"tools": False}     # la API informó que el modelo no soporta
    assert p.capabilities()["tool_calling_native"] is False
    cfg.capabilities = {"tools": True, "images": False}
    caps = p.capabilities()
    assert caps["tools"] is True and caps["images"] is False


# ------------------------------------------------------------- ciclo del agente
@pytest.fixture
def native_agent(stack, nexo_home):
    from nexo.agent.loop import Agent
    from nexo.config.settings import AgentLimits
    from nexo.providers.registry import ProviderRegistry

    cfg = stack["config"]
    cfg.set_provider(ProviderConfig(name="nat", type="openai", base_url="http://t/v1",
                                    model="m", stream=False))
    cfg.active_provider = "nat"
    registry = ProviderRegistry(cfg, stack["secrets"])
    return Agent(registry, stack["catalog"], stack["memory"],
                 AgentLimits(max_iterations=6, max_seconds=60),
                 use_native_tools=True), registry, stack


def install_native(registry, responses):
    """Inyecta MockTransport con un guion de respuestas por iteración."""
    registry._client_factory = mock_client_factory(handler_script(responses))


def test_agent_native_cycle_executes_and_answers(native_agent, workspace):
    agent, registry, stack = native_agent
    install_native(registry, [
        {"choices": [{"finish_reason": "tool_calls", "message": {
            "content": "Voy a crear el archivo.",
            "tool_calls": [tool_call("c1", "create_file",
                                      {"path": "nat.txt", "content": "nativo"})]}}]},
        {"choices": [{"finish_reason": "tool_calls", "message": {
            "content": None,
            "tool_calls": [tool_call("c2", "read_file", {"path": "nat.txt"})]}}]},
        {"choices": [{"finish_reason": "stop", "message": {
            "content": "Listo: creé nat.txt y verifiqué su contenido ('nativo')."}}]},
    ])
    outcome = agent.run("crea nat.txt y verificalo")
    assert outcome.status == "terminada" and outcome.success
    assert open(os.path.join(workspace, "nat.txt"), encoding="utf-8").read() == "nativo"
    assert [n for n, _ in outcome.tool_log] == ["create_file", "read_file"]


def test_agent_native_parallel_calls_one_tool_message_each(native_agent):
    agent, registry, stack = native_agent
    stack["fs"].write_text("p1.txt", "uno")
    stack["fs"].write_text("p2.txt", "dos")
    install_native(registry, [
        {"choices": [{"finish_reason": "tool_calls", "message": {
            "content": "", "tool_calls": [tool_call("a", "read_file", {"path": "p1.txt"}),
                                          tool_call("b", "read_file", {"path": "p2.txt"})]}}]},
        {"choices": [{"finish_reason": "stop", "message": {"content": "Leí ambos."}}]},
    ])
    outcome = agent.run("lee p1 y p2")
    assert outcome.status == "terminada"
    assert [n for n, _ in outcome.tool_log] == ["read_file", "read_file"]


def test_agent_native_invalid_arguments_do_not_execute(native_agent, workspace):
    agent, registry, stack = native_agent
    install_native(registry, [
        {"choices": [{"finish_reason": "tool_calls", "message": {
            "content": "", "tool_calls": [
                {"id": "bad", "type": "function",
                 "function": {"name": "delete_file", "arguments": '{"path": '}}]}}]},
        {"choices": [{"finish_reason": "stop", "message": {
            "content": "La llamada tenía JSON inválido; no borré nada."}}]},
    ])
    outcome = agent.run("borra algo")
    # La llamada se rechazó sin ejecutarse: el agente no "terminó" una acción.
    assert outcome.status == "conversacion"
    assert ("delete_file", False) in outcome.tool_log
    ops = stack["memory"].recent_operations(10)
    assert not any(k == "tool:delete_file" and ok for _, k, _, _, ok in ops)


def test_agent_native_unknown_tool_feedback(native_agent):
    agent, registry, stack = native_agent
    install_native(registry, [
        {"choices": [{"finish_reason": "tool_calls", "message": {
            "content": "", "tool_calls": [tool_call("x", "hackear", {})]}}]},
        {"choices": [{"finish_reason": "stop", "message": {"content": "Corregido."}}]},
    ])
    outcome = agent.run("hacé algo")
    assert outcome.status == "conversacion"
    assert ("hackear", False) in outcome.tool_log


def test_agent_native_ask_user_pauses(native_agent):
    agent, registry, stack = native_agent
    install_native(registry, [
        {"choices": [{"finish_reason": "tool_calls", "message": {
            "content": "", "tool_calls": [tool_call("q", "ask_user",
                                                    {"question": "¿Cuál archivo?"})]}}]},
    ])
    outcome = agent.run("editá un archivo")
    assert outcome.status == "necesita_usuario"
    assert outcome.question == "¿Cuál archivo?"


def test_agent_native_permissions_still_enforced(native_agent, workspace):
    """Sin callback de autorización, una escritura sensible se deniega: el modelo
    recibe el rechazo real y no puede ejecutar por fuera del catálogo."""
    agent, registry, stack = native_agent
    stack["permissions"].set_mode("seguro")     # sin ask_user -> deniega
    install_native(registry, [
        {"choices": [{"finish_reason": "tool_calls", "message": {
            "content": "", "tool_calls": [tool_call("w", "write_file",
                                                    {"path": "x.txt", "content": "x"})]}}]},
        {"choices": [{"finish_reason": "stop", "message": {
            "content": "Permiso denegado; no escribí nada."}}]},
    ])
    outcome = agent.run("escribí x.txt")
    assert not os.path.exists(os.path.join(workspace, "x.txt"))
    assert outcome.status == "terminada"


def test_agent_falls_back_when_model_reports_no_tools(native_agent):
    """Si la API informa tools=False, no se simula agente nativo: se conversa."""
    agent, registry, stack = native_agent
    cfg = registry.config.get_provider("nat")
    cfg.capabilities = {"tools": False}
    install_native(registry, [
        {"choices": [{"finish_reason": "stop", "message": {"content": "Solo converso."}}]},
    ])
    outcome = agent.run("hola")
    assert outcome.status == "conversacion"
    assert outcome.reply == "Solo converso."


def test_agent_native_disabled_uses_json_protocol(native_agent):
    agent, registry, stack = native_agent
    agent.use_native_tools = False
    from tests.conftest import FakeProvider
    fake = FakeProvider(registry.config.get_provider("nat"),
                        responses=["Respuesta sin herramientas."])
    registry.get = lambda name=None: fake
    outcome = agent.run("hola")
    assert outcome.status == "conversacion"
