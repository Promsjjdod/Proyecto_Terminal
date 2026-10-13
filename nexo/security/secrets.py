"""Almacén de claves API y redacción de secretos.

Las claves se guardan en un archivo JSON independiente (`secrets.json`) con
permisos 0600, separado de la configuración visible. Nunca deben aparecer en
logs ni en la salida de la terminal: `redact_text` limpia patrones conocidos.
"""
from __future__ import annotations

import json
import os
import re
from typing import Dict, Optional

# Patrones de secretos conocidos para redacción de texto libre.
_REDACTION_PATTERNS = [
    re.compile(r"(?i)\b(sk-[A-Za-z0-9_\-]{8,})\b"),                 # OpenAI / Anthropic modernas
    re.compile(r"(?i)\b(sk-ant-[A-Za-z0-9_\-]{8,})\b"),             # Anthropic
    re.compile(r"(?i)\b(cc-[A-Za-z0-9_\-]{8,})\b"),                 # CleanAPIs
    re.compile(r"(?i)\b(ghp_[A-Za-z0-9]{20,})\b"),                  # GitHub PAT
    re.compile(r"(?i)\b(gho_[A-Za-z0-9]{20,})\b"),                  # GitHub OAuth
    re.compile(r"(?i)\b(github_pat_[A-Za-z0-9_]{20,})\b"),          # GitHub fine-grained
    re.compile(r"(?i)\b(xox[baprs]-[A-Za-z0-9\-]{8,})\b"),          # Slack
    re.compile(r"(?i)\b(AKIA[0-9A-Z]{16})\b"),                      # AWS access key
    re.compile(r"(?i)\b(eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,})\b"),  # JWT
]

_REDACTED = "[REDACTADO]"


def redact_text(text: str, extra_secrets: Optional[Dict[str, str]] = None) -> str:
    """Sustituye secretos conocidos por `[REDACTADO]`.

    `extra_secrets` permite añadir valores literales (p. ej. claves cargadas
    del almacén) que deben limpiarse aunque no coincidan con un patrón.
    """
    out = text
    for pattern in _REDACTION_PATTERNS:
        out = pattern.sub(_REDACTED, out)
    if extra_secrets:
        for value in extra_secrets.values():
            if value and len(value) >= 6 and value in out:
                out = out.replace(value, _REDACTED)
    return out


def mask_secret(value: str, keep: int = 4) -> str:
    """Devuelve una máscara legible de una clave: `sk-a…Wxyz`."""
    if not value:
        return ""
    if len(value) <= keep * 2:
        return "*" * len(value)
    return f"{value[:keep]}…{value[-keep:]} ({len(value)} caracteres)"


class SecretStore:
    """Almacén JSON de claves con permisos restringidos (0600).

    Uso típico::

        store = SecretStore("/ruta/.nexo/secrets.json")
        store.set("mi-proveedor", "sk-...")
        store.get("mi-proveedor")
    """

    def __init__(self, path: str | os.PathLike):
        self.path = str(path)
        self._cache: Dict[str, str] = {}
        self._load()

    # ------------------------------------------------------------------ carga
    def _load(self) -> None:
        self._cache = {}
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                self._cache = {str(k): str(v) for k, v in data.items()}
        except (json.JSONDecodeError, OSError):
            # Un almacén corrupto no debe tumbar la app: se ignora y se avisa
            # desde /doctor (que comprueba integridad por separado).
            self._cache = {}

    # ------------------------------------------------------------------- API
    def get(self, name: str) -> Optional[str]:
        return self._cache.get(name)

    def set(self, name: str, value: str) -> None:
        self._cache[name] = value
        self._flush()

    def delete(self, name: str) -> bool:
        existed = name in self._cache
        self._cache.pop(name, None)
        if existed:
            self._flush()
        return existed

    def names(self) -> list[str]:
        return sorted(self._cache)

    def keys(self) -> Dict[str, str]:
        """Copia interna de las claves (no imprimir)."""
        return dict(self._cache)

    def is_valid(self) -> bool:
        """True si el archivo no existe (aún) o es JSON válido."""
        if not os.path.exists(self.path):
            return True
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                json.load(fh)
            return True
        except (json.JSONDecodeError, OSError):
            return False

    # -------------------------------------------------------------- interno
    def _flush(self) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self._cache, fh, indent=2, ensure_ascii=False)
        try:
            os.chmod(tmp, 0o600)
        except OSError:  # pragma: no cover - sistemas sin POSIX
            pass
        os.replace(tmp, self.path)
