"""Fixtures comunes para las pruebas de NEXO (proveedores simulados, sin APIs de pago)."""
from __future__ import annotations

import os
import sys
from typing import Callable, Iterator, List, Optional

import httpx
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from nexo.config.settings import Config, ProviderConfig
from nexo.editor.engine import FileEditor
from nexo.filesystem.ops import FilesystemOps
from nexo.gitops.repo import GitRepo
from nexo.github.client import GitHubClient
from nexo.memory.db import Memory
from nexo.permissions.manager import PermissionManager
from nexo.permissions.paths import PathGuard
from nexo.providers.base import ChatMessage, Provider
from nexo.security.secrets import SecretStore
from nexo.tools.catalog import ToolCatalog
from nexo.tools.executor import CommandExecutor


@pytest.fixture
def workspace(tmp_path) -> str:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return str(ws)


@pytest.fixture
def nexo_home(tmp_path, monkeypatch) -> str:
    home = tmp_path / "nexo-home"
    home.mkdir()
    monkeypatch.setenv("NEXO_HOME", str(home))
    return str(home)


@pytest.fixture
def guard(workspace) -> PathGuard:
    return PathGuard(workspace)


@pytest.fixture
def make_config(workspace, nexo_home) -> Callable[..., Config]:
    def _make(permission_mode: str = "autonomo", **kwargs) -> Config:
        cfg = Config(config_dir=nexo_home, workspace=workspace,
                     permission_mode=permission_mode, **kwargs)
        cfg.ensure_dirs()
        return cfg
    return _make


class FakeProvider(Provider):
    """Proveedor simulado con respuestas guionizadas (no toca la red)."""

    type_name = "fake"

    def __init__(self, config: ProviderConfig, responses: Optional[List[str]] = None,
                 error: Optional[Exception] = None, api_key: Optional[str] = None):
        super().__init__(config, api_key=api_key)
        self.responses = list(responses or ["(sin respuestas)"])
        self.error = error
        self.calls: List[List[ChatMessage]] = []

    def _complete_once(self, messages: List[ChatMessage]) -> str:
        self.calls.append(list(messages))
        if self.error is not None:
            raise self.error
        if len(self.calls) > len(self.responses):
            return self.responses[-1]
        return self.responses[len(self.calls) - 1]

    def stream(self, messages: List[ChatMessage]) -> Iterator[str]:
        text = self._complete_once(messages)
        # Emite por palabras para simular streaming real.
        for word in text.split(" "):
            yield word + " "

    def list_models(self) -> List[str]:
        if self.error is not None:
            raise self.error
        return ["fake-model-a", "fake-model-b"]


def mock_client_factory(handler: Callable[[httpx.Request], httpx.Response]):
    """Fábrica de httpx.Client con MockTransport (pruebas de proveedores HTTP)."""
    transport = httpx.MockTransport(handler)
    return lambda: httpx.Client(transport=transport, timeout=5.0)


@pytest.fixture
def stack(workspace, nexo_home):
    """Pila completa de componentes conectados para pruebas de integración."""
    cfg = Config(config_dir=nexo_home, workspace=workspace, permission_mode="autonomo")
    cfg.ensure_dirs()
    secrets = SecretStore(cfg.secrets_path)
    memory = Memory(cfg.db_path)
    guard = PathGuard(workspace)
    permissions = PermissionManager(guard, mode="autonomo")
    fs = FilesystemOps(guard, cfg.backups_dir, cfg.backups_enabled)
    editor = FileEditor(fs, guard)
    executor = CommandExecutor(guard, permissions, default_timeout=10.0, memory=memory)
    catalog = ToolCatalog(guard, fs, editor, executor, permissions, memory=memory)
    git = GitRepo(guard, permissions, timeout=10.0, memory=memory)
    github = GitHubClient(guard, permissions, memory=memory)
    yield {
        "config": cfg, "secrets": secrets, "memory": memory, "guard": guard,
        "permissions": permissions, "fs": fs, "editor": editor,
        "executor": executor, "catalog": catalog, "workspace": workspace,
        "git": git, "github": github,
    }
    memory.close()
