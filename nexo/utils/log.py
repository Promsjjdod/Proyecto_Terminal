"""Registro (logging) sin secretos: redacta claves antes de escribir."""
from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

from nexo.security.secrets import redact_text

_DEFAULT_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


class RedactingFormatter(logging.Formatter):
    """Formateador que elimina secretos de cada línea registrada."""

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        return redact_text(super().format(record))


def setup_logging(log_dir: str | os.PathLike, level: int = logging.INFO) -> logging.Logger:
    """Configura el log global de NEXO en `log_dir/nexo.log` con rotación."""
    os.makedirs(log_dir, exist_ok=True)
    root = logging.getLogger("nexo")
    root.setLevel(level)
    # Evita duplicar handlers si se llama varias veces (p. ej. en tests).
    if not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        handler = RotatingFileHandler(
            os.path.join(log_dir, "nexo.log"), maxBytes=512_000, backupCount=2, encoding="utf-8"
        )
        handler.setFormatter(RedactingFormatter(_DEFAULT_FORMAT))
        root.addHandler(handler)
    root.propagate = False
    return root
