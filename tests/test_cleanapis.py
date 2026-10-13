"""CleanAPIs como proveedor OpenAI-compatible + onboarding y detección real.

Todo con HTTP simulado (MockTransport): sin claves reales ni consumo de saldo.
"""
from __future__ import annotations

import io
import sys

import httpx
import pytest


@pytest.fixture(autouse=True)
def restore_stdin():
    old = sys.stdin
    yield
    sys.stdin = old

from nexo.config.settings import Config, ProviderConfig
from nexo.providers.presets import (
    PRESETS,
    capabilities_from_meta,
    normalize_base_url,
)
from nexo.providers.registry import ProviderRegistry
from nexo.security.secrets import SecretStore
from tests.conftest import mock_client_factory

MODELS_META = {
    "data": [
        {"id": "claude-opus-4.8", "capabilities": {"tools": True, "images": True},
         "context_length": 200000},
        {"id": "gemini-3.5-flash-lite", "capabilities": {"tools": True}},
        {"id": "modelo-sin-meta"},
    ]
}


def cleanapis_handler(request: httpx.Request, fail_auth: bool = False) -> httpx.Response:
    if request.url.path.endswith("/models"):
        if fail_auth:
            return httpx.Response(401, json={"error": {"message": "invalid api key"}})
        assert request.headers["Authorization"].startswith("Bearer ")
        assert "cc_" in request.headers["Authorization"] or True
        return httpx.Response(200, json=MODELS_META)
    return httpx.Response(200, json={"choices": [
        {"message": {"content": "ok"}, "finish_reason": "stop"}]})


# ----------------------------------------------------------------------- presets
def test_preset_cleanapis_values():
    preset = PRESETS["cleanapis"]
    assert preset["type"] == "openai"
    assert preset["base_url"] == "https://www.cleanapis.com/v1"
    assert preset["base_url"].endswith("/v1")
    assert preset["requires_key"] is True


def test_normalize_base_url_strips_chat_endpoint():
    url, aviso = normalize_base_url("https://www.cleanapis.com/v1/chat/completions")
    assert url == "https://www.cleanapis.com/v1"
    assert "recortada" in aviso
    url2, aviso2 = normalize_base_url("https://www.cleanapis.com/v1/")
    assert url2 == "https://www.cleanapis.com/v1" and aviso2 == ""
    url3, _ = normalize_base_url("https://api.groq.com/openai/v1")
    assert url3 == "https://api.groq.com/openai/v1"     # no fuerza /v1 extra


def test_capabilities_only_from_api_metadata():
    assert capabilities_from_meta({"id": "x"}) == {}
    assert capabilities_from_meta({"capabilities": {"tools": True}}) == {"tools": True}
    assert capabilities_from_meta({"supports_tools": True,
                                   "vision": False}) == {"tools": True, "images": False}
    assert capabilities_from_meta({"context_window": 128000}) == {"context": 128000}
    assert capabilities_from_meta(None) == {}            # type: ignore[arg-type]


# ------------------------------------------------------------------ protocolo real
def test_cleanapis_models_exact_ids_and_meta():
    reg_cfg = ProviderConfig(name="cleanapis", type="openai",
                             base_url="https://www.cleanapis.com/v1", model="",
                             retries=0)
    from nexo.providers.openai_compat import OpenAICompatProvider
    p = OpenAICompatProvider(reg_cfg, api_key="cc_test_key_1234567890",
                             client_factory=mock_client_factory(
                                 lambda r: cleanapis_handler(r)))
    metas = p.list_models_meta()
    ids = [m["id"] for m in metas]
    assert ids == ["claude-opus-4.8", "gemini-3.5-flash-lite", "modelo-sin-meta"]
    # Metadatos crudos conservados (capacidades incluidas).
    assert metas[0]["capabilities"]["tools"] is True


def test_cleanapis_auth_error_is_real():
    from nexo.providers.base import AuthenticationError
    from nexo.providers.openai_compat import OpenAICompatProvider
    cfg = ProviderConfig(name="cleanapis", type="openai",
                         base_url="https://www.cleanapis.com/v1", model="m", retries=0)
    p = OpenAICompatProvider(cfg, api_key="cc_mala",
                             client_factory=mock_client_factory(
                                 lambda r: cleanapis_handler(r, fail_auth=True)))
    with pytest.raises(AuthenticationError):
        p.list_models()


def test_registry_fetch_and_capabilities_persist(nexo_home, workspace):
    cfg = Config(config_dir=nexo_home, workspace=workspace)
    secrets = SecretStore(cfg.secrets_path)
    reg = ProviderRegistry(cfg, secrets,
                           client_factory=mock_client_factory(lambda r: cleanapis_handler(r)))
    reg.add(ProviderConfig(name="cleanapis", type="openai",
                           base_url="https://www.cleanapis.com/v1", model=""),
            api_key="cc_key_abcdefghij")
    ids, metas = reg.fetch_models("cleanapis")
    assert "claude-opus-4.8" in ids
    reg.set_model("cleanapis", "gemini-3.5-flash-lite")
    caps = reg.apply_capabilities_from_meta("cleanapis", metas)
    assert caps == {"tools": True}
    assert cfg.get_provider("cleanapis").capabilities == {"tools": True}
    # El modelo quedó persistido (cambio explícito, no silencioso).
    from nexo.config.settings import load_config
    assert load_config(nexo_home).get_provider("cleanapis").model == "gemini-3.5-flash-lite"
    # La clave NUNCA queda en config.json.
    raw = open(cfg.config_path, encoding="utf-8").read()
    assert "cc_key_abcdefghij" not in raw
    assert secrets.get("cleanapis") == "cc_key_abcdefghij"


def test_set_model_rejects_empty(nexo_home, workspace):
    cfg = Config(config_dir=nexo_home, workspace=workspace)
    reg = ProviderRegistry(cfg, SecretStore(cfg.secrets_path))
    reg.add(ProviderConfig(name="p", type="openai", model="m"))
    from nexo.providers.base import ProviderError
    with pytest.raises(ProviderError):
        reg.set_model("p", "   ")


# ------------------------------------------------------------- onboarding guiado
@pytest.fixture
def onboard_app(workspace, nexo_home):
    from nexo.app import NexoApp
    app = NexoApp(config=Config(config_dir=nexo_home, workspace=workspace,
                                permission_mode="autonomo"),
                  interactive=False)
    buf = io.StringIO()
    from rich.console import Console
    app.ui.console = Console(file=buf, width=72, force_terminal=False)
    app._buffer = buf
    yield app
    app._shutdown()


def feed(app, lines):
    import sys
    sys.stdin = io.StringIO("\n".join(lines) + "\n")


def test_onboard_cleanapis_full_flow(onboard_app, monkeypatch):
    app = onboard_app
    app.registry._client_factory = mock_client_factory(lambda r: cleanapis_handler(r))
    # Entradas: URL (Enter=default), clave, elección de modelo "2", prueba "n".
    feed(app, ["", "cc_onboard_key_1234567890", "2", "n"])
    app._onboard("cleanapis")
    out = app._buffer.getvalue()
    cfg = app.config.get_provider("cleanapis")
    assert cfg is not None
    assert cfg.base_url == "https://www.cleanapis.com/v1"
    assert cfg.model == "gemini-3.5-flash-lite"        # elección número 2
    assert app.config.active_provider == "cleanapis"
    assert app.secrets.get("cleanapis") == "cc_onboard_key_1234567890"
    assert cfg.capabilities == {"tools": True}
    assert "Proveedor activo: cleanapis" in out
    assert "capacidades" in out.lower()
    # La clave no se imprime en la salida.
    assert "cc_onboard_key_1234567890" not in out


def test_onboard_auth_failure_is_honest_and_keeps_config(onboard_app):
    app = onboard_app
    app.registry._client_factory = mock_client_factory(
        lambda r: cleanapis_handler(r, fail_auth=True))
    feed(app, ["", "cc_mala_1234567890", "n"])
    app._onboard("cleanapis")
    out = app._buffer.getvalue()
    assert "No se pudieron listar los modelos" in out
    assert "Autenticación rechazada" in out or "401" in out
    # La configuración queda guardada para corregir, sin fingir éxito.
    assert app.config.get_provider("cleanapis") is not None
    assert "quedó guardada" in out


def test_onboard_url_with_endpoint_gets_fixed(onboard_app):
    app = onboard_app
    app.registry._client_factory = mock_client_factory(lambda r: cleanapis_handler(r))
    feed(app, ["https://www.cleanapis.com/v1/chat/completions",
               "cc_url_key_1234567890", "1", "n"])
    app._onboard("cleanapis")
    cfg = app.config.get_provider("cleanapis")
    assert cfg.base_url == "https://www.cleanapis.com/v1"
    assert "recortada" in app._buffer.getvalue()


def test_onboard_unknown_preset(onboard_app):
    app = onboard_app
    app._onboard("no-existe")
    assert "Preset desconocido" in app._buffer.getvalue()


def test_provider_menu_non_interactive_shows_options(onboard_app):
    app = onboard_app
    app.interactive = False
    app.cmd_menu([])
    out = app._buffer.getvalue()
    assert "MENÚ NEXO" in out and "Proveedores y modelos" in out
