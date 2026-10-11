"""Permisos: validación de rutas y control de operaciones sensibles."""
from nexo.permissions.paths import PathGuard, PathViolation
from nexo.permissions.manager import (
    PermissionManager,
    PermissionDecision,
    OperationKind,
    PROMPT_ASK,
    PROMPT_ALLOW,
    PROMPT_DENY,
    PROMPT_ALLOW_SESSION,
)

__all__ = [
    "PathGuard",
    "PathViolation",
    "PermissionManager",
    "PermissionDecision",
    "OperationKind",
    "PROMPT_ASK",
    "PROMPT_ALLOW",
    "PROMPT_DENY",
    "PROMPT_ALLOW_SESSION",
]
