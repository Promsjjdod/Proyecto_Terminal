"""Operaciones de archivo seguras: escritura atómica, copias y papelera.

Principios:
- Las escrituras son atómicas (temporal + ``os.replace`` en el mismo disco):
  un fallo nunca deja el archivo a medias.
- Antes de sobrescribir o borrar se hace copia de seguridad (configurable).
- Los borrados van a una papelera recuperable dentro de los datos de NEXO.
- Todas las rutas pasan por el `PathGuard` (workspace autorizado).
"""
from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from nexo.permissions.paths import PathGuard
from nexo.utils.text import detect_eol, looks_binary


class FileOpError(Exception):
    """Error de operación de archivos (con contexto para el agente/usuario)."""


@dataclass
class FileContent:
    """Contenido leído de un archivo, con metadatos de codificación y EOL."""

    path: Path
    raw: bytes
    text: Optional[str]        # None si es binario
    encoding: str              # utf-8 por defecto; 'latin-1' como respaldo
    eol: str                   # '\n' o '\r\n'
    binary: bool
    size: int

    @property
    def line_count(self) -> int:
        if self.text is None:
            return 0
        return self.text.count("\n") + (1 if self.text and not self.text.endswith("\n") else 0)


class FilesystemOps:
    """Operaciones de bajo nivel sobre el workspace autorizado."""

    def __init__(self, guard: PathGuard, backups_dir: str | os.PathLike,
                 backups_enabled: bool = True):
        self.guard = guard
        self.backups_dir = str(backups_dir)
        self.backups_enabled = backups_enabled

    # ---------------------------------------------------------------- lectura
    def read(self, path: str | os.PathLike, max_bytes: int = 8 * 1024 * 1024) -> FileContent:
        resolved = self.guard.resolve(path, must_exist=True)
        if resolved.is_dir():
            raise FileOpError(f"'{self.guard.rel(resolved)}' es un directorio, no un archivo.")
        size = resolved.stat().st_size
        if size > max_bytes:
            raise FileOpError(
                f"El archivo tiene {size} bytes, supera el límite de lectura de {max_bytes} bytes."
            )
        with open(resolved, "rb") as fh:
            raw = fh.read()
        binary = looks_binary(raw)
        text: Optional[str] = None
        encoding = "utf-8"
        if not binary:
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                try:
                    text = raw.decode("latin-1")
                    encoding = "latin-1"
                except UnicodeDecodeError:  # pragma: no cover - latin-1 nunca falla
                    binary = True
                    text = None
        eol = detect_eol(raw) if text is not None else "\n"
        if text is not None:
            text = text.replace("\r\n", "\n").replace("\r", "\n")
        return FileContent(path=resolved, raw=raw, text=text, encoding=encoding,
                           eol=eol, binary=binary, size=size)

    def exists(self, path: str | os.PathLike) -> bool:
        return self.guard.resolve(path).exists()

    def is_dir(self, path: str | os.PathLike) -> bool:
        return self.guard.resolve(path).is_dir()

    def list_dir(self, path: str | os.PathLike = ".", limit: int = 500) -> Tuple[List[str], bool]:
        """Lista entradas de un directorio (relativas al workspace). Devuelve (entradas, truncado)."""
        resolved = self.guard.resolve(path, must_exist=True)
        if not resolved.is_dir():
            raise FileOpError(f"'{self.guard.rel(resolved)}' no es un directorio.")
        entries: List[str] = []
        for entry in sorted(resolved.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            suffix = "/" if entry.is_dir() else ""
            entries.append(self.guard.rel(entry) + suffix)
            if len(entries) >= limit:
                return entries, True
        return entries, False

    def mkdir(self, path: str | os.PathLike) -> Path:
        resolved = self.guard.resolve(path)
        if resolved.exists() and not resolved.is_dir():
            raise FileOpError(f"Ya existe un archivo con ese nombre: {self.guard.rel(resolved)}")
        resolved.mkdir(parents=True, exist_ok=True)
        return resolved

    # --------------------------------------------------------------- escritura
    def write_atomic(self, path: str | os.PathLike, data: bytes,
                     encoding_note: bool = False) -> Path:
        """Escribe bytes de forma atómica: temporal en el mismo directorio + replace."""
        resolved = self.guard.resolve(path)
        if resolved.is_dir():
            raise FileOpError(f"'{self.guard.rel(resolved)}' es un directorio.")
        resolved.parent.mkdir(parents=True, exist_ok=True)
        tmp = resolved.parent / f".{resolved.name}.nexo-tmp-{os.getpid()}"
        try:
            with open(tmp, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, resolved)
        except OSError as exc:
            # Limpieza: nunca dejar el temporal huérfano.
            try:
                tmp.unlink()
            except OSError:
                pass
            raise FileOpError(f"No se pudo escribir '{self.guard.rel(resolved)}': {exc}") from exc
        return resolved

    def write_text(self, path: str | os.PathLike, text: str,
                   encoding: str = "utf-8", eol: str = "\n") -> Path:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        if eol == "\r\n":
            normalized = normalized.replace("\n", "\r\n")
        return self.write_atomic(path, normalized.encode(encoding))

    def delete(self, path: str | os.PathLike) -> Path:
        """Elimina enviando a la papelera de NEXO (recuperable con `restore`)."""
        resolved = self.guard.resolve(path, must_exist=True)
        trash = Path(self.backups_dir) / "trash"
        trash.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        dest = trash / f"{stamp}_{resolved.name}"
        counter = 1
        while dest.exists():
            dest = trash / f"{stamp}-{counter}_{resolved.name}"
            counter += 1
        shutil.move(str(resolved), str(dest))
        return dest

    # ----------------------------------------------------------------- backups
    def backup(self, path: str | os.PathLike, label: str = "edit") -> Optional[Path]:
        """Copia de seguridad versionada de un archivo existente."""
        if not self.backups_enabled:
            return None
        resolved = self.guard.resolve(path)
        if not resolved.exists() or resolved.is_dir():
            return None
        backups = Path(self.backups_dir) / "files"
        backups.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        rel = self.guard.rel(resolved).replace(os.sep, "__")
        dest = backups / f"{rel}.{label}.{stamp}.bak"
        counter = 1
        while dest.exists():
            dest = backups / f"{rel}.{label}.{stamp}-{counter}.bak"
            counter += 1
        shutil.copy2(str(resolved), str(dest))
        return dest

    def latest_backup(self, path: str | os.PathLike) -> Optional[Path]:
        """Encuentra la copia más reciente de un archivo del workspace."""
        resolved = self.guard.resolve(path)
        rel = self.guard.rel(resolved).replace(os.sep, "__")
        backups = Path(self.backups_dir) / "files"
        if not backups.is_dir():
            return None
        candidates = sorted(backups.glob(f"{rel}.*.bak"))
        return candidates[-1] if candidates else None

    def list_backups(self, path: str | os.PathLike) -> List[Path]:
        resolved = self.guard.resolve(path)
        rel = self.guard.rel(resolved).replace(os.sep, "__")
        backups = Path(self.backups_dir) / "files"
        if not backups.is_dir():
            return []
        return sorted(backups.glob(f"{rel}.*.bak"))

    def restore(self, path: str | os.PathLike, backup: Optional[Path] = None) -> Path:
        """Restaura un archivo desde su copia más reciente (o una indicada)."""
        resolved = self.guard.resolve(path)
        chosen = Path(backup) if backup else self.latest_backup(resolved)
        if chosen is None or not chosen.exists():
            raise FileOpError(f"No hay copias de seguridad disponibles para '{self.guard.rel(resolved)}'.")
        with open(chosen, "rb") as fh:
            data = fh.read()
        self.write_atomic(resolved, data)
        return chosen
