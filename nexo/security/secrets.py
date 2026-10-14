"""Almacenamiento local de secretos y redacción de credenciales.

Las credenciales se guardan fuera del repositorio, en JSON con permisos 0600.
Las escrituras son atómicas y nunca se sustituyen silenciosamente archivos
JSON corruptos.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Dict, Mapping, Optional

_REDACTION_PATTERNS = (
    re.compile(r"sk-ant-[A-Za-z0-9_-]{12,}", re.IGNORECASE),
    re.compile(r"sk-[A-Za-z0-9_-]{12,}", re.IGNORECASE),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{12,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    # JWT compacto: cabecera, payload y firma en base64url.
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)


def redact_text(text: str, extra_secrets: Optional[Mapping[str, str]] = None) -> str:
    """Oculta tokens conocidos y, opcionalmente, valores de secretos concretos."""
    clean = str(text)
    if extra_secrets:
        values = sorted((str(v) for v in extra_secrets.values() if v), key=len, reverse=True)
        for value in values:
            clean = clean.replace(value, "[REDACTADO]")
    for pattern in _REDACTION_PATTERNS:
        clean = pattern.sub("[REDACTADO]", clean)
    return clean


def mask_secret(secret: str) -> str:
    """Representación breve de una clave sin mostrar su valor completo."""
    if not secret:
        return ""
    if len(secret) < 8:
        return "*****"
    return f"{secret[:4]}…({len(secret)} caracteres)"


class SecretStore:
    """Pequeño almacén JSON persistente protegido con permisos Unix 0600."""

    def __init__(self, path: str | os.PathLike):
        self.path = Path(path).expanduser()
        self._lock = threading.RLock()
        self._valid = True
        self._secrets = self._load()

    def _load(self) -> Dict[str, str]:
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError):
            self._valid = False
            return {}
        if not isinstance(data, dict) or any(not isinstance(k, str) or not isinstance(v, str)
                                             for k, v in data.items()):
            self._valid = False
            return {}
        return data

    def is_valid(self) -> bool:
        """Indica si el archivo existente pudo leerse como un mapa JSON válido."""
        return self._valid

    def get(self, name: str) -> Optional[str]:
        with self._lock:
            return self._secrets.get(name)

    def names(self):
        with self._lock:
            return sorted(self._secrets)

    def set(self, name: str, value: str) -> None:
        if not name or not isinstance(name, str):
            raise ValueError("El nombre del secreto debe ser texto no vacío.")
        if not isinstance(value, str) or not value:
            raise ValueError("El valor del secreto debe ser texto no vacío.")
        with self._lock:
            if not self._valid:
                raise ValueError(f"El archivo de secretos está dañado; no se sobrescribirá: {self.path}")
            updated = dict(self._secrets)
            updated[name] = value
            self._write(updated)
            self._secrets = updated

    def delete(self, name: str) -> bool:
        with self._lock:
            if name not in self._secrets:
                return False
            updated = dict(self._secrets)
            del updated[name]
            self._write(updated)
            self._secrets = updated
            return True

    def _write(self, data: Dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(self.path.parent, 0o700)
        except OSError:
            pass
        fd, temp_name = tempfile.mkstemp(prefix=f".{self.path.name}.", suffix=".tmp",
                                         dir=str(self.path.parent))
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.path)
            try:
                os.chmod(self.path, 0o600)
                dir_fd = os.open(str(self.path.parent), os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except OSError:
                pass
        except BaseException:
            try:
                os.close(fd)
            except OSError:
                pass
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise
