"""Exportación de archivos generados al almacenamiento compartido (Descargas).

Flujo seguro (inspirado en el pedido del usuario y en las restricciones del
proyecto):

1. El origen vive DENTRO del workspace autorizado (o se exporta contenido
   generado por el agente, que se valida antes de escribir).
2. El destino puede ser la carpeta Descargas de Android
   (``~/storage/downloads`` en Termux, o ``/storage/emulated/0/Download``)
   o una ruta explícita revisada por el usuario.
3. Exportar fuera del workspace es una operación SENSIBLE: requiere
   autorización explícita y específica del administrador de permisos.
4. Si el destino existe: NUNCA se sobrescribe en silencio. Se ofrece
   reemplazar, crear otra versión (nombre-1.ext) o cancelar.
5. La escritura es atómica (temporal + replace en el mismo directorio) y se
   VERIFICA releyendo: una generación truncada no se guarda como completa.
6. Si el almacenamiento compartido no está concedido, se explica el
   procedimiento legítimo de Termux (`termux-setup-storage`). Sin root.
"""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from nexo.permissions.manager import OperationKind, PermissionManager
from nexo.permissions.paths import PathGuard

DOWNLOAD_ALIASES = ("downloads", "descargas", "download", "descarga")


@dataclass
class ExportResult:
    ok: bool
    path: str = ""                  # ruta real de salida (si se escribió)
    message: str = ""
    needs_choice: bool = False      # el destino existe: hay que decidir
    choices: List[str] = field(default_factory=list)
    existed: bool = False

    @property
    def success(self) -> bool:
        return self.ok


def resolve_destination(destination: str, home: Optional[str] = None) -> Path:
    """Resuelve alias de destino a una ruta real de directorio.

    - ``downloads``/``descargas``: ~/storage/downloads si existe (Termux con
      storage configurado); si no, /storage/emulated/0/Download.
    - Ruta explícita: se expande tal cual (la autorización se pide aparte).
    """
    home = home or os.path.expanduser("~")
    target = (destination or "").strip()
    if target.lower() in DOWNLOAD_ALIASES or target == "":
        termux_downloads = Path(home) / "storage" / "downloads"
        if termux_downloads.is_dir():
            return termux_downloads
        return Path("/storage/emulated/0/Download")
    return Path(os.path.expanduser(target))


def versioned_path(dest: Path) -> Path:
    """nombre-1.ext, nombre-2.ext… hasta encontrar uno libre."""
    stem, suffix = dest.stem, dest.suffix
    counter = 1
    while True:
        candidate = dest.with_name(f"{stem}-{counter}{suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


class Exporter:
    """Exporta archivos del workspace (o contenido generado) fuera de él."""

    def __init__(self, guard: PathGuard, permissions: PermissionManager, memory=None):
        self.guard = guard
        self.permissions = permissions
        self.memory = memory

    # ------------------------------------------------------------------ interno
    def _check_destination_dir(self, dest_dir: Path) -> Optional[str]:
        """Devuelve un mensaje de error accionable si el destino no es usable."""
        if not dest_dir.exists():
            if "storage" in str(dest_dir).split(os.sep):
                return (
                    f"El directorio de destino no existe: {dest_dir}. "
                    "En Termux, habilitá el acceso al almacenamiento compartido con "
                    "`termux-setup-storage` (aceptá el diálogo de Android) y reintentá. "
                    "No se requiere root; NEXO no puede conceder ese permiso por vos."
                )
            return f"El directorio de destino no existe: {dest_dir}."
        if not dest_dir.is_dir():
            return f"El destino no es un directorio: {dest_dir}."
        if not os.access(dest_dir, os.W_OK):
            return (
                f"Sin permiso de escritura en {dest_dir}. Android/Termux puede exigir "
                "`termux-setup-storage` o que elijas otra carpeta."
            )
        return None

    def _write_and_verify(self, dest: Path, data: bytes) -> Optional[str]:
        """Escritura atómica fuera del workspace + verificación por relectura."""
        fd, tmp = tempfile.mkstemp(prefix=f".{dest.name}.", suffix=".nexo-tmp",
                                   dir=str(dest.parent))
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, dest)
        except OSError as exc:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            return f"No se pudo escribir en {dest}: {exc}"
        try:
            with open(dest, "rb") as fh:
                if fh.read() != data:
                    return (f"Verificación fallida en {dest}: el contenido releído no "
                            "coincide con el generado. No se reporta como exportado.")
        except OSError as exc:
            return f"No se pudo verificar {dest}: {exc}"
        return None

    def _log(self, target: str, detail: str, success: bool) -> None:
        if self.memory:
            self.memory.log_operation("export", target, detail, success=success)

    # --------------------------------------------------------------------- API
    def export_content(self, content: str, filename: str, destination: str = "downloads",
                       on_exists: str = "ask", encoding: str = "utf-8") -> ExportResult:
        """Exporta contenido generado por el agente (texto) a un destino externo."""
        filename = (filename or "").strip().replace(os.sep, "_")
        if not filename:
            return ExportResult(False, message="Nombre de archivo vacío.")
        if "\x00" in filename:
            return ExportResult(False, message="Nombre de archivo inválido.")
        data = content.encode(encoding)
        if not data.strip():
            return ExportResult(
                False,
                message=("El contenido generado está vacío: no se exporta un archivo "
                         "truncado o vacío como si estuviera completo."),
            )
        dest_dir = resolve_destination(destination)
        return self._export_bytes(data, dest_dir / filename, destination, on_exists)

    def export_file(self, source: str, destination: str = "downloads",
                    on_exists: str = "ask") -> ExportResult:
        """Exporta un archivo EXISTENTE del workspace a un destino externo."""
        resolved = self.guard.resolve(source, must_exist=True)
        if resolved.is_dir():
            return ExportResult(False, message=f"'{source}' es un directorio.")
        with open(resolved, "rb") as fh:
            data = fh.read()
        dest_dir = resolve_destination(destination)
        return self._export_bytes(data, dest_dir / resolved.name, destination, on_exists,
                                  source_rel=self.guard.rel(resolved))

    def _export_bytes(self, data: bytes, dest: Path, destination: str,
                      on_exists: str, source_rel: str = "") -> ExportResult:
        # 1) Destino utilizable (con explicación legítima si falta el permiso).
        problem = self._check_destination_dir(dest.parent)
        if problem:
            self._log(str(dest), problem, success=False)
            return ExportResult(False, message=problem)

        # 2) Autorización explícita y específica (operación sensible).
        decision = self.permissions.check_sensitive(
            OperationKind.EXPORT_OUTSIDE, str(dest),
            f"Exportar {'el archivo ' + source_rel if source_rel else 'contenido generado'} "
            f"fuera del workspace hacia: {dest}",
        )
        if not decision.allowed:
            self._log(str(dest), decision.reason, success=False)
            return ExportResult(False, message=f"Autorización denegada: {decision.reason}")

        # 3) Sobrescritura: nunca silenciosa.
        existed = dest.exists()
        if existed:
            if on_exists == "cancel":
                return ExportResult(False, existed=True,
                                    message=f"Cancelado: '{dest}' ya existe y se decidió no tocarlo.")
            if on_exists == "version":
                dest = versioned_path(dest)
            elif on_exists == "replace":
                pass
            else:  # "ask": el llamador (UI o agente) decide.
                return ExportResult(
                    False, existed=True, needs_choice=True,
                    choices=["replace", "version", "cancel"],
                    message=(f"El destino ya existe: {dest}. Elegí una opción: "
                             "replace (sobrescribir), version (crear nombre alternativo) "
                             "o cancel."),
                )

        # 4) Escritura atómica + verificación real.
        error = self._write_and_verify(dest, data)
        if error:
            self._log(str(dest), error, success=False)
            return ExportResult(False, message=error)
        self._log(str(dest), f"{len(data)} bytes verificados", success=True)
        return ExportResult(
            True, path=str(dest),
            message=(f"Exportado y verificado: {dest} ({len(data)} bytes). "
                     "Podés revisarlo con /view usando la ruta completa."),
            existed=existed,
        )

    # ------------------------------------------------------------------ preview
    @staticmethod
    def preview_text(content: str, max_lines: int = 12, max_width: int = 72) -> str:
        """Vista previa honesta del contenido a exportar (marca el recorte)."""
        lines = content.splitlines()
        shown = [line[:max_width] + ("…" if len(line) > max_width else "")
                 for line in lines[:max_lines]]
        out = "\n".join(shown)
        if len(lines) > max_lines:
            out += f"\n… ({len(lines) - max_lines} líneas más sin mostrar)"
        return out
