"""Pruebas de configuración: persistencia, proveedores, validación."""
from __future__ import annotations

import json
import os

from nexo.config.settings import (
    ProviderConfig,
    load_config,
    save_config,
    write_example_config,
)


def test_save_load_roundtrip(make_config):
    cfg = make_config()
    cfg.set_provider(ProviderConfig(name="p1", type="ollama",
                                    base_url="http://127.0.0.1:11434", model="llama3.2"))
    cfg.active_provider = "p1"
    cfg.permission_mode = "estricto"
    cfg.command_timeout = 42.0
    cfg.allowed_commands = ["ls"]
    save_config(cfg)

    loaded = load_config(cfg.config_dir)
    assert loaded.active_provider == "p1"
    assert loaded.permission_mode == "estricto"
    assert loaded.command_timeout == 42.0
    assert loaded.allowed_commands == ["ls"]
    p = loaded.get_provider("p1")
    assert p is not None and p.type == "ollama" and p.model == "llama3.2"


def test_config_never_contains_api_keys(make_config):
    cfg = make_config()
    cfg.set_provider(ProviderConfig(name="p1", type="openai", model="gpt-x",
                                    base_url="https://api.openai.com/v1"))
    save_config(cfg)
    raw = open(cfg.config_path, encoding="utf-8").read()
    assert "key" not in raw.lower() or "api_key" not in raw
    data = json.loads(raw)
    for prov in data["providers"]:
        assert "api_key" not in prov and "key" not in prov


def test_provider_crud(make_config):
    cfg = make_config()
    cfg.set_provider(ProviderConfig(name="a", type="ollama"))
    cfg.set_provider(ProviderConfig(name="b", type="openai"))
    assert cfg.provider_names() == ["a", "b"]
    # editar (mismo nombre) no duplica
    cfg.set_provider(ProviderConfig(name="a", type="ollama", model="nuevo"))
    assert len(cfg.providers) == 2
    cfg.active_provider = "a"
    assert cfg.delete_provider("a") is True
    # al borrar el activo, se reasigna al restante
    assert cfg.active_provider == "b"
    assert cfg.delete_provider("no-existe") is False


def test_validate_detects_problems(make_config):
    cfg = make_config()
    cfg.permission_mode = "modo-raro"
    cfg.active_provider = "fantasma"
    problems = cfg.validate()
    assert any("permission_mode" in p for p in problems)
    assert any("fantasma" in p for p in problems)


def test_corrupt_config_falls_back_to_defaults(nexo_home):
    path = os.path.join(nexo_home, "config.json")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("{esto no es json válido")
    cfg = load_config(nexo_home)
    assert cfg.providers == []
    assert cfg.permission_mode == "seguro"


def test_example_config_has_no_secrets(tmp_path):
    path = write_example_config(tmp_path / "example.json")
    raw = open(path, encoding="utf-8").read()
    assert "sk-" not in raw
    data = json.loads(raw)
    assert data["providers"]
