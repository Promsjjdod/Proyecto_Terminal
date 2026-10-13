"""Pruebas de proveedores con HTTP simulado (MockTransport): sin APIs de pago.

Cubre: respuestas normales, streaming (SSE y NDJSON), errores de autenticación,
modelos inexistentes, límites de servicio, timeouts, reintentos, respuestas
vacías/incompletas y el registro de proveedores.
"""
from __future__ import annotations

import json

import httpx
import pytest

from nexo.config.settings import Config, ProviderConfig
from nexo.providers.anthropic import AnthropicProvider
from nexo.providers.base import (
    AuthenticationError,
    ChatMessage,
    IncompleteResponseError,
    ModelNotFoundError,
    ProviderError,
    RateLimitError,
    RequestTimeoutError,
    TransportError,
)
from nexo.providers.custom_http import CustomHTTPProvider, extract_by_key
from nexo.providers.ollama import OllamaProvider
from nexo.providers.openai_compat import OpenAICompatProvider
from nexo.providers.registry import ProviderRegistry, create_provider
from nexo.security.secrets import SecretStore
from tests.conftest import mock_client_factory

MSGS = [ChatMessage("user", "hola")]


# ----------------------------------------------------------------------- OpenAI
def openai_provider(handler, **cfg_kwargs) -> OpenAICompatProvider:
    cfg = ProviderConfig(name="oai", type="openai",
                         base_url="https://api.test/v1", model="gpt-test",
                         retries=0, **cfg_kwargs)
    return OpenAICompatProvider(cfg, api_key="sk-test", client_factory=mock_client_factory(handler))


def test_openai_complete_success():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "gpt-test" and body["stream"] is False
        assert request.headers["Authorization"] == "Bearer sk-test"
        return httpx.Response(200, json={"choices": [
            {"message": {"content": "hola mundo"}, "finish_reason": "stop"}]})

    p = openai_provider(handler)
    assert p.complete(MSGS) == "hola mundo"


def test_openai_stream_sse():
    sse = (
        'data: {"choices":[{"delta":{"content":"Ho"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"la"}}]}\n\n'
        "data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["stream"] is True
        return httpx.Response(200, content=sse.encode(),
                              headers={"content-type": "text/event-stream"})

    p = openai_provider(handler, stream=True)
    deltas = []
    text = p.complete(MSGS, on_delta=deltas.append)
    assert text.strip() == "Ho la" or text.replace(" ", "") == "Hola"
    assert deltas  # streaming real por fragmentos


def test_openai_auth_error():
    def handler(request):
        return httpx.Response(401, json={"error": {"message": "clave inválida"}})

    p = openai_provider(handler)
    with pytest.raises(AuthenticationError, match="clave inválida"):
        p.complete(MSGS)


def test_openai_model_not_found():
    def handler(request):
        return httpx.Response(404, json={"error": {"message": "model 'gpt-test' not found"}})

    p = openai_provider(handler)
    with pytest.raises(ModelNotFoundError):
        p.complete(MSGS)


def test_openai_rate_limit_retry_after():
    def handler(request):
        return httpx.Response(429, json={"error": {"message": "cuota excedida"}},
                              headers={"retry-after": "7"})

    p = openai_provider(handler)
    with pytest.raises(RateLimitError) as info:
        p.complete(MSGS)
    assert info.value.retry_after == 7.0


def test_openai_server_error_with_retries():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(500, json={"error": "boom"})

    cfg = ProviderConfig(name="oai", type="openai", base_url="https://api.test/v1",
                         model="m", retries=2)
    p = OpenAICompatProvider(cfg, client_factory=mock_client_factory(handler))
    with pytest.raises(TransportError):
        p.complete(MSGS)
    assert calls["n"] == 3   # 1 intento + 2 reintentos


def test_openai_timeout():
    def handler(request):
        raise httpx.ConnectTimeout("sin respuesta")

    p = openai_provider(handler)
    with pytest.raises(RequestTimeoutError):
        p.complete(MSGS)


def test_openai_connection_refused():
    def handler(request):
        raise httpx.ConnectError("conexión rechazada")

    p = openai_provider(handler)
    with pytest.raises(TransportError):
        p.complete(MSGS)


def test_openai_empty_response_is_incomplete():
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "   "}}]})

    p = openai_provider(handler)
    with pytest.raises(IncompleteResponseError):
        p.complete(MSGS)


def test_openai_stream_without_done_is_incomplete():
    def handler(request):
        return httpx.Response(200, content=b"data: {\"choices\":[]}\n\n",
                              headers={"content-type": "text/event-stream"})

    p = openai_provider(handler, stream=True)
    with pytest.raises(IncompleteResponseError):
        p.complete(MSGS, on_delta=lambda d: None)


def test_openai_list_models():
    def handler(request):
        assert request.url.path.endswith("/models")
        return httpx.Response(200, json={"data": [{"id": "a"}, {"id": "b"}]})

    p = openai_provider(handler)
    assert p.list_models() == ["a", "b"]


# ----------------------------------------------------------------------- Ollama
def ollama_provider(handler, **cfg_kwargs) -> OllamaProvider:
    cfg = ProviderConfig(name="oll", type="ollama", base_url="http://127.0.0.1:11434",
                         model="llama-test", retries=0, **cfg_kwargs)
    return OllamaProvider(cfg, client_factory=mock_client_factory(handler))


def test_ollama_complete_success():
    def handler(request):
        body = json.loads(request.content)
        assert body["model"] == "llama-test" and body["stream"] is False
        return httpx.Response(200, json={
            "message": {"role": "assistant", "content": "respuesta local"},
            "done": True})

    p = ollama_provider(handler)
    assert p.complete(MSGS) == "respuesta local"


def test_ollama_stream_ndjson():
    ndjson = "\n".join([
        json.dumps({"message": {"content": "uno "}, "done": False}),
        json.dumps({"message": {"content": "dos"}, "done": False}),
        json.dumps({"message": {"content": ""}, "done": True}),
    ])

    def handler(request):
        return httpx.Response(200, content=ndjson.encode(),
                              headers={"content-type": "application/x-ndjson"})

    p = ollama_provider(handler, stream=True)
    deltas = []
    text = p.complete(MSGS, on_delta=deltas.append)
    assert "uno" in text and "dos" in text
    assert len(deltas) == 2


def test_ollama_model_not_installed():
    def handler(request):
        return httpx.Response(200, json={
            "error": "model 'llama-test' not found, try pulling it first"})

    p = ollama_provider(handler)
    with pytest.raises(ModelNotFoundError, match="not found"):
        p.complete(MSGS)


def test_ollama_incomplete_stream():
    def handler(request):
        # Stream cortado: sin done y sin contenido.
        return httpx.Response(200, content=b"\n\n",
                              headers={"content-type": "application/x-ndjson"})

    p = ollama_provider(handler, stream=True)
    with pytest.raises(IncompleteResponseError):
        p.complete(MSGS, on_delta=lambda d: None)


def test_ollama_list_models():
    def handler(request):
        return httpx.Response(200, json={"models": [{"name": "llama3.2"}, {"name": "qwen2"}]})

    p = ollama_provider(handler)
    assert p.list_models() == ["llama3.2", "qwen2"]


def test_ollama_connection_refused():
    def handler(request):
        raise httpx.ConnectError("ollama no está corriendo")

    p = ollama_provider(handler)
    with pytest.raises(TransportError):
        p.complete(MSGS)


# -------------------------------------------------------------------- Anthropic
def anthropic_provider(handler, key="sk-ant-test", **cfg_kwargs) -> AnthropicProvider:
    cfg = ProviderConfig(name="ant", type="anthropic", base_url="https://api.test",
                         model="claude-test", retries=0, **cfg_kwargs)
    return AnthropicProvider(cfg, api_key=key, client_factory=mock_client_factory(handler))


def test_anthropic_complete_success_and_headers():
    def handler(request):
        assert request.headers["x-api-key"] == "sk-ant-test"
        assert request.headers["anthropic-version"] == "2023-06-01"
        body = json.loads(request.content)
        assert body["system"] == "eres útil"
        assert body["messages"] == [{"role": "user", "content": "hola"}]
        return httpx.Response(200, json={
            "content": [{"type": "text", "text": "respuesta claude"}],
            "stop_reason": "end_turn"})

    p = anthropic_provider(handler)
    msgs = [ChatMessage("system", "eres útil"), ChatMessage("user", "hola")]
    assert p.complete(msgs) == "respuesta claude"


def test_anthropic_stream_sse():
    sse = (
        "event: content_block_delta\n"
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"par"}}\n\n'
        "event: content_block_delta\n"
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"te"}}\n\n'
        "event: message_stop\n"
        'data: {"type":"message_stop"}\n\n'
    )

    def handler(request):
        return httpx.Response(200, content=sse.encode(),
                              headers={"content-type": "text/event-stream"})

    p = anthropic_provider(handler, stream=True)
    deltas = []
    text = p.complete(MSGS, on_delta=deltas.append)
    assert text.replace(" ", "") == "parte"
    assert len(deltas) == 2


def test_anthropic_auth_error():
    def handler(request):
        return httpx.Response(401, json={"error": {"message": "invalid x-api-key"}})

    p = anthropic_provider(handler)
    with pytest.raises(AuthenticationError):
        p.complete(MSGS)


def test_anthropic_requires_key():
    p = anthropic_provider(lambda request: httpx.Response(200, json={}), key="")
    assert p.requires_api_key()
    with pytest.raises(ProviderError, match="API key"):
        p.complete(MSGS)


def test_anthropic_overloaded_is_retryable_server_error():
    def handler(request):
        return httpx.Response(529, json={"error": {"message": "overloaded"}})

    p = anthropic_provider(handler)
    with pytest.raises(TransportError):
        p.complete(MSGS)


# ----------------------------------------------------------------------- Custom
def test_custom_http_complete_with_content_key():
    def handler(request):
        body = json.loads(request.content)
        assert body["model"] == "mi-modelo"
        return httpx.Response(200, json={"result": {"reply": "respuesta custom"}})

    cfg = ProviderConfig(name="c", type="custom", base_url="https://api.test/chat",
                         model="mi-modelo", retries=0,
                         params={"content_key": "result.reply"})
    p = CustomHTTPProvider(cfg, client_factory=mock_client_factory(handler))
    assert p.complete(MSGS) == "respuesta custom"


def test_custom_http_sse_stream():
    sse = (
        'data: {"choices":[{"delta":{"content":"A"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"B"}}]}\n\n'
        "data: [DONE]\n\n"
    )

    def handler(request):
        return httpx.Response(200, content=sse.encode(),
                              headers={"content-type": "text/event-stream"})

    cfg = ProviderConfig(name="c", type="custom", base_url="https://api.test/chat",
                         model="m", retries=0,
                         params={"stream_mode": "sse",
                                 "stream_content_key": "choices.0.delta.content"})
    p = CustomHTTPProvider(cfg, client_factory=mock_client_factory(handler))
    deltas = []
    text = p.complete(MSGS, on_delta=deltas.append)
    assert text.replace(" ", "") == "AB"


def test_custom_http_missing_content_key_errors():
    def handler(request):
        return httpx.Response(200, json={"otra_cosa": 1})

    cfg = ProviderConfig(name="c", type="custom", base_url="https://api.test/chat",
                         model="m", retries=0, params={"content_key": "respuesta.texto"})
    p = CustomHTTPProvider(cfg, client_factory=mock_client_factory(handler))
    with pytest.raises(ProviderError, match="No se encontró texto"):
        p.complete(MSGS)


def test_extract_by_key():
    data = {"a": {"b": [{"c": "valor"}]}}
    assert extract_by_key(data, "a.b.0.c") == "valor"
    assert extract_by_key(data, "a.x") is None
    assert extract_by_key(data, "a.b.9.c") is None


# ------------------------------------------------------------------ test_connection
def test_test_connection_ok_reports_models():
    def handler(request):
        return httpx.Response(200, json={"models": [{"name": "llama-test"}]})

    p = ollama_provider(handler)
    result = p.test_connection()
    assert result.ok and "llama-test" in result.models
    assert result.latency_ms >= 0


def test_test_connection_failure_is_honest():
    def handler(request):
        raise httpx.ConnectError("no hay servidor")

    p = ollama_provider(handler)
    result = p.test_connection()
    assert not result.ok
    assert "conexión" in result.message.lower() or "Fallo" in result.message


def test_test_connection_model_mismatch_warns():
    def handler(request):
        return httpx.Response(200, json={"models": [{"name": "otro-modelo"}]})

    p = ollama_provider(handler)
    result = p.test_connection()
    assert result.ok and "no aparece" in result.message


# ----------------------------------------------------------------------- registro
def test_registry_add_use_delete(nexo_home, workspace):
    cfg = Config(config_dir=nexo_home, workspace=workspace)
    secrets = SecretStore(cfg.secrets_path)
    reg = ProviderRegistry(cfg, secrets)

    reg.add(ProviderConfig(name="local", type="ollama", base_url="http://x", model="m"))
    assert cfg.active_provider == "local"          # primer proveedor queda activo
    reg.add(ProviderConfig(name="nube", type="openai", base_url="https://y/v1", model="g"),
            api_key="sk-abcdefghij1234567890")
    assert secrets.get("nube") == "sk-abcdefghij1234567890"

    reg.set_active("nube")
    provider = reg.get()
    assert isinstance(provider, OpenAICompatProvider) and provider.has_key

    reg.set_active("local")
    assert isinstance(reg.get(), OllamaProvider)

    assert reg.remove("local")
    assert cfg.active_provider == "nube"           # reasignación al borrar el activo
    assert reg.remove("local") is False


def test_registry_get_without_active_raises(nexo_home, workspace):
    cfg = Config(config_dir=nexo_home, workspace=workspace)
    reg = ProviderRegistry(cfg, SecretStore(cfg.secrets_path))
    with pytest.raises(ProviderError, match="No hay proveedor activo"):
        reg.get()


def test_registry_missing_provider_raises(nexo_home, workspace):
    cfg = Config(config_dir=nexo_home, workspace=workspace)
    reg = ProviderRegistry(cfg, SecretStore(cfg.secrets_path))
    with pytest.raises(ProviderError, match="no existe"):
        reg.get("fantasma")


def test_registry_anthropic_without_key_raises(nexo_home, workspace):
    cfg = Config(config_dir=nexo_home, workspace=workspace)
    secrets = SecretStore(cfg.secrets_path)
    reg = ProviderRegistry(cfg, secrets)
    reg.add(ProviderConfig(name="ant", type="anthropic", model="claude"))
    with pytest.raises(ProviderError, match="requiere API key"):
        reg.get("ant")
    reg.set_key("ant", "sk-ant-abcdefghij1234567890")
    assert isinstance(reg.get("ant"), AnthropicProvider)


def test_registry_rejects_unknown_type(nexo_home, workspace):
    cfg = Config(config_dir=nexo_home, workspace=workspace)
    reg = ProviderRegistry(cfg, SecretStore(cfg.secrets_path))
    with pytest.raises(ProviderError, match="desconocido"):
        reg.add(ProviderConfig(name="x", type="magia"))


def test_create_provider_factory():
    for ptype, cls in [("ollama", OllamaProvider), ("openai", OpenAICompatProvider),
                       ("anthropic", AnthropicProvider), ("custom", CustomHTTPProvider)]:
        p = create_provider(ProviderConfig(name="n", type=ptype))
        assert isinstance(p, cls)


def test_provider_never_switches_model_silently(nexo_home, workspace):
    """NEXO usa el modelo seleccionado por el usuario: el proveedor respeta cfg.model."""
    seen = {}

    def handler(request):
        seen["model"] = json.loads(request.content)["model"]
        return httpx.Response(200, json={"message": {"content": "ok"}, "done": True})

    cfg = ProviderConfig(name="oll", type="ollama", model="modelo-elegido", retries=0,
                         base_url="http://x")
    p = OllamaProvider(cfg, client_factory=mock_client_factory(handler))
    p.complete(MSGS)
    assert seen["model"] == "modelo-elegido"
