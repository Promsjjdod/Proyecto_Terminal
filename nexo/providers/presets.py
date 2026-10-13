"""Presets de proveedores y normalización de URLs.

Incluye CleanAPIs como proveedor OpenAI-compatible según su documentación
oficial (https://cleanapis.com/docs): base ``https://www.cleanapis.com/v1``,
listado en ``GET /v1/models``, chat en ``POST /v1/chat/completions``,
autenticación ``Authorization: Bearer <API_KEY>``.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

PRESETS: Dict[str, Dict[str, Any]] = {
    "cleanapis": {
        "type": "openai",
        "base_url": "https://www.cleanapis.com/v1",
        "default_model": "",
        "requires_key": True,
        "note": "CleanAPIs (OpenAI-compatible). La URL base debe terminar en /v1; "
                "la clave se guarda cifrada en pantalla (entrada oculta, secrets.json 0600).",
    },
    "openai": {
        "type": "openai",
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
        "requires_key": True,
        "note": "API oficial de OpenAI.",
    },
    "anthropic": {
        "type": "anthropic",
        "base_url": "https://api.anthropic.com",
        "default_model": "",
        "requires_key": True,
        "note": "API oficial de Anthropic (Messages).",
    },
    "ollama-local": {
        "type": "ollama",
        "base_url": "http://127.0.0.1:11434",
        "default_model": "",
        "requires_key": False,
        "note": "Ollama en tu red local (en Termux apuntá a la IP del PC).",
    },
    "groq": {
        "type": "openai",
        "base_url": "https://api.groq.com/openai/v1",
        "default_model": "",
        "requires_key": True,
        "note": "Groq (OpenAI-compatible).",
    },
    "openrouter": {
        "type": "openai",
        "base_url": "https://openrouter.ai/api/v1",
        "default_model": "",
        "requires_key": True,
        "note": "OpenRouter (OpenAI-compatible).",
    },
    "custom": {
        "type": "custom",
        "base_url": "",
        "default_model": "",
        "requires_key": False,
        "note": "Endpoint HTTP genérico con plantilla configurable.",
    },
}

# Sufijos que NO deben formar parte de la URL base (son endpoints concretos).
_ENDPOINT_SUFFIXES = ("/chat/completions", "/completions", "/messages", "/api/chat")


def normalize_base_url(url: str, ptype: str = "openai") -> Tuple[str, str]:
    """Normaliza la URL base. Devuelve (url_normalizada, aviso).

    Regla clave (documentada por CleanAPIs y OpenAI): la base termina en
    ``/v1``; si el usuario pega la URL completa del endpoint de chat, se
    recorta y se informa del ajuste (nunca se acepta en silencio).
    """
    cleaned = (url or "").strip().rstrip("/")
    aviso = ""
    if not cleaned:
        return cleaned, aviso
    lowered = cleaned.lower()
    for suffix in _ENDPOINT_SUFFIXES:
        if lowered.endswith(suffix):
            cleaned = cleaned[: -len(suffix)].rstrip("/")
            aviso = (f"URL recortada a la base del proveedor: '{cleaned}' "
                     f"(se eliminó '{suffix}'; la base no debe incluir el endpoint de chat).")
            break
    return cleaned, aviso


def capabilities_from_meta(meta: Dict[str, Any]) -> Dict[str, Any]:
    """Extrae capacidades SOLO si la API las informa en los metadatos.

    Acepta el formato anidado ``{"capabilities": {...}}`` y alias planos
    comunes (``supports_tools``, ``tool_calling``, ``tools``, ``vision``…).
    Si no hay nada, devuelve {} (NEXO no inventa capacidades).
    """
    caps: Dict[str, Any] = {}
    if not isinstance(meta, dict):
        return caps
    nested = meta.get("capabilities")
    if isinstance(nested, dict):
        caps.update(nested)
    alias = {
        "supports_tools": "tools", "tool_calling": "tools", "tools": "tools",
        "supports_vision": "images", "vision": "images", "images": "images",
        "supports_streaming": "streaming", "streaming": "streaming",
    }
    for key, target in alias.items():
        if key in meta and target not in caps:
            caps[target] = meta[key]
    for key in ("context_length", "max_context", "context_window"):
        if key in meta and "context" not in caps:
            caps["context"] = meta[key]
    # Solo valores concretos informados por la API.
    return {k: v for k, v in caps.items() if v is not None}


def preset_config_kwargs(name: str) -> Optional[Dict[str, Any]]:
    """Datos de preset para armar un ProviderConfig (None si no existe)."""
    preset = PRESETS.get(name)
    if preset is None:
        return None
    return {
        "type": preset["type"],
        "base_url": preset["base_url"],
        "model": preset["default_model"],
    }
