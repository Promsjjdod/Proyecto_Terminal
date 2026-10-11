"""Registro de proveedores: instancia y gestiona proveedores según la configuración.

Las claves API nunca viven en `Config`: se leen del `SecretStore` en el momento
de instanciar cada proveedor y no se registran ni se imprimen.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Type

from nexo.config.settings import Config, ProviderConfig
from nexo.providers.anthropic import AnthropicProvider
from nexo.providers.base import Provider, ProviderError
from nexo.providers.custom_http import CustomHTTPProvider
from nexo.providers.ollama import OllamaProvider
from nexo.providers.openai_compat import OpenAICompatProvider

PROVIDER_TYPES: Dict[str, Type[Provider]] = {
    "ollama": OllamaProvider,
    "openai": OpenAICompatProvider,
    "anthropic": AnthropicProvider,
    "custom": CustomHTTPProvider,
}


def create_provider(cfg: ProviderConfig, api_key: Optional[str] = None,
                    client_factory=None) -> Provider:
    """Fábrica de proveedores por tipo. Lanza ProviderError si el tipo es desconocido."""
    cls = PROVIDER_TYPES.get(cfg.type)
    if cls is None:
        raise ProviderError(
            f"Tipo de proveedor desconocido: '{cfg.type}'. "
            f"Tipos disponibles: {', '.join(sorted(PROVIDER_TYPES))}.",
            provider=cfg.name,
        )
    return cls(cfg, api_key=api_key, client_factory=client_factory)


class ProviderRegistry:
    """Gestiona los proveedores configurados y el proveedor activo."""

    def __init__(self, config: Config, secret_store, client_factory=None):
        self.config = config
        self.secrets = secret_store
        self._client_factory = client_factory

    # -------------------------------------------------------------- instancias
    def names(self) -> List[str]:
        return self.config.provider_names()

    def get_config(self, name: str) -> Optional[ProviderConfig]:
        return self.config.get_provider(name)

    def get(self, name: Optional[str] = None) -> Provider:
        """Instancia el proveedor indicado (o el activo). Lanza ProviderError."""
        target = name or self.config.active_provider
        if not target:
            raise ProviderError(
                "No hay proveedor activo. Configura uno con `/provider add` y "
                "selecciónalo con `/provider use <nombre>`."
            )
        cfg = self.config.get_provider(target)
        if cfg is None:
            available = ", ".join(self.names()) or "ninguno"
            raise ProviderError(
                f"El proveedor '{target}' no existe en la configuración. Disponibles: {available}."
            )
        key = self.secrets.get(cfg.name) if self.secrets else None
        provider = create_provider(cfg, api_key=key, client_factory=self._client_factory)
        if provider.requires_api_key() and not key:
            raise ProviderError(
                f"El proveedor '{cfg.name}' requiere API key y no está guardada. "
                "Añádela con `/provider key <nombre>`."
            )
        return provider

    def active(self) -> Optional[Provider]:
        """Proveedor activo o None si no hay ninguno utilizable."""
        try:
            return self.get()
        except ProviderError:
            return None

    # ----------------------------------------------------------------- gestión
    def add(self, cfg: ProviderConfig, api_key: Optional[str] = None) -> None:
        if cfg.type not in PROVIDER_TYPES:
            raise ProviderError(
                f"Tipo de proveedor desconocido: '{cfg.type}'. "
                f"Disponibles: {', '.join(sorted(PROVIDER_TYPES))}."
            )
        exists = self.config.get_provider(cfg.name) is not None
        self.config.set_provider(cfg)
        if api_key:
            self.secrets.set(cfg.name, api_key)
        elif exists is False and cfg.name in self.secrets.names():
            pass  # conserva clave previa si se reedita
        if not self.config.active_provider:
            self.config.active_provider = cfg.name

    def remove(self, name: str) -> bool:
        removed = self.config.delete_provider(name)
        if removed:
            self.secrets.delete(name)
        return removed

    def set_active(self, name: str) -> None:
        if self.config.get_provider(name) is None:
            raise ProviderError(f"El proveedor '{name}' no existe.")
        self.config.active_provider = name

    def set_key(self, name: str, api_key: str) -> None:
        if self.config.get_provider(name) is None:
            raise ProviderError(f"El proveedor '{name}' no existe.")
        if not api_key.strip():
            raise ProviderError("La API key no puede estar vacía.")
        self.secrets.set(name, api_key.strip())

    def delete_key(self, name: str) -> bool:
        return self.secrets.delete(name)

    def test(self, name: str):
        """Prueba REAL de conexión contra el proveedor (sin simular)."""
        provider = self.get(name)
        return provider.test_connection()
