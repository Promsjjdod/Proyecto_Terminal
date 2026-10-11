"""Protección de rutas: workspace autorizado, traversal y symlinks.

`PathGuard` traduce rutas relativas/absolutas a rutas reales y garantiza que
quedan dentro del workspace autorizado. Bloquea:

- Traversal con `..` que escape del workspace.
- Enlaces simbólicos que apunten fuera del workspace.
- Rutas absolutas fuera del workspace.
- Rutas vacías o con bytes NUL.
"""
from __future__ import annotations

import os
from pathlib import Path


class PathViolation(Exception):
    """Intento de acceder a una ruta fuera del workspace autorizado."""

    def __init__(self, message: str, path: str = ""):
        super().__init__(message)
        self.path = path


class PathGuard:
    """Valida y resuelve rutas dentro de un workspace autorizado."""

    def __init__(self, workspace: str | os.PathLike):
        workspace = os.path.expanduser(str(workspace))
        if not os.path.isabs(workspace):
            workspace = os.path.abspath(workspace)
        # El workspace se resuelve físicamente (symlinks) una sola vez.
        self.workspace = Path(os.path.realpath(workspace))

    # ------------------------------------------------------------------ API
    def resolve(self, path: str | os.PathLike, must_exist: bool = False) -> Path:
        """Resuelve `path` (relativa al workspace o absoluta) a una ruta real segura.

        Lanza `PathViolation` si la ruta escapa del workspace o es inválida.
        """
        raw = str(path)
        if not raw or not raw.strip():
            raise PathViolation("La ruta está vacía.", raw)
        if "\x00" in raw:
            raise PathViolation("La ruta contiene bytes NUL (inválida).", raw)

        candidate = os.path.expanduser(raw)
        if os.path.isabs(candidate):
            base = Path(candidate)
        else:
            base = self.workspace / candidate

        # Normaliza léxicamente primero (abarata y da buenos mensajes).
        base = Path(os.path.normpath(str(base)))

        # Resolución física: si existe, realpath descubre symlinks reales.
        # Si no existe, se resuelve el padre existente y se añade el nombre final,
        # de modo que un symlink intermedio ya creado también se detecta.
        resolved = self._realpath(base)

        if not self.is_inside(resolved):
            raise PathViolation(
                f"Ruta fuera del workspace autorizado ({self.workspace}): {raw}",
                raw,
            )
        if must_exist and not resolved.exists():
            raise PathViolation(f"La ruta no existe: {resolved}", raw)
        return resolved

    def is_inside(self, resolved: str | os.PathLike) -> bool:
        """True si la ruta (ya resuelta) está dentro del workspace."""
        try:
            Path(os.path.realpath(str(resolved))).relative_to(self.workspace)
            return True
        except ValueError:
            return False

    def rel(self, resolved: str | os.PathLike) -> str:
        """Ruta relativa al workspace, para mostrar al usuario."""
        try:
            return str(Path(os.path.realpath(str(resolved))).relative_to(self.workspace))
        except ValueError:
            return str(resolved)

    # ------------------------------------------------------------- interno
    @staticmethod
    def _realpath(base: Path) -> Path:
        """Resuelve symlinks de la parte existente y mantiene el resto."""
        if base.exists():
            return Path(os.path.realpath(str(base)))
        # Encuentra el ancestro existente más profundo y resuelve desde ahí.
        parts = list(base.parts)
        for i in range(len(parts), 0, -1):
            ancestor = Path(*parts[:i])
            if ancestor.exists():
                real = Path(os.path.realpath(str(ancestor)))
                tail = parts[i:]
                return real.joinpath(*tail) if tail else real
        return Path(os.path.realpath(str(base)))
