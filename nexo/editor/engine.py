"""Motor de edición transaccional de NEXO (sistema CODEX).

Flujo de trabajo:

1. **Planificar**: construir un `ChangeSet` con `plan_create`, `plan_edit`,
   `plan_write`, `plan_delete`. Los conflictos (bloques que no existen,
   coincidencias múltiples) se detectan AQUÍ, antes de tocar disco.
2. **Revisar**: `changeset.diffs()` devuelve diffs estilo Git por archivo y
   `changeset.summary()` un recuento de archivos/líneas.
3. **Aplicar**: `editor.commit(changeset)` hace copias de seguridad, escribe
   de forma atómica y verifica cada archivo. Si algo falla a mitad, revierte
   automáticamente los archivos ya escritos (transacción todo-o-nada).
4. **Revertir**: `editor.undo(path)` restaura la última copia de seguridad.

Los archivos binarios se copian/sustituyen íntegros (bytes) sin decodificar,
de modo que nunca se corrompen. Codificación y EOL originales se preservan.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from nexo.editor.diff import DiffResult, compute_diff, find_similar_block
from nexo.filesystem.ops import FileOpError, FilesystemOps
from nexo.permissions.paths import PathGuard, PathViolation
from nexo.utils.text import normalize_eol


class EditError(Exception):
    """Error de edición detectado antes o durante la aplicación de cambios."""

    def __init__(self, message: str, path: str = "", suggestion: Optional[str] = None):
        super().__init__(message)
        self.path = path
        self.suggestion = suggestion


@dataclass
class PendingChange:
    """Un cambio pendiente sobre un archivo (aún no aplicado)."""

    path: Path                 # ruta resuelta dentro del workspace
    rel: str                   # ruta relativa legible
    kind: str                  # create | write | edit | delete
    old_text: Optional[str]    # None si no existía / binario
    new_text: Optional[str]    # None para delete / binario
    old_bytes: Optional[bytes] = None
    new_bytes: Optional[bytes] = None
    binary: bool = False
    existed: bool = True
    encoding: str = "utf-8"
    eol: str = "\n"
    conflict_note: str = ""
    edit_stats: Dict[str, int] = field(default_factory=dict)  # reemplazos aplicados

    def diff(self, context: int = 3) -> DiffResult:
        if self.binary:
            return compute_diff(None, None, self.rel, is_binary=True,
                                conflict_note=self.conflict_note)
        # is_new/is_delete se derivan de old_text/new_text == None en compute_diff.
        return compute_diff(self.old_text, self.new_text, self.rel,
                            context=context, conflict_note=self.conflict_note)


@dataclass
class CommitReport:
    """Resultado de aplicar un ChangeSet."""

    applied: List[str] = field(default_factory=list)     # rutas relativas escritas
    rolled_back: List[str] = field(default_factory=list) # revertidas tras fallo
    backups: Dict[str, str] = field(default_factory=dict)  # rel -> ruta de copia
    added: int = 0
    removed: int = 0
    error: str = ""

    @property
    def success(self) -> bool:
        return not self.error

    def summary(self) -> str:
        if self.error:
            return (
                f"FALLO: {self.error}\n"
                f"Archivos revertidos: {', '.join(self.rolled_back) or 'ninguno'} "
                f"(no quedaron modificaciones parciales)."
            )
        return (
            f"{len(self.applied)} archivo(s) modificado(s): {', '.join(self.applied)}\n"
            f"Líneas: +{self.added} añadidas, -{self.removed} eliminadas.\n"
            f"Copias de seguridad: {len(self.backups)} (revertibles con /undo)."
        )


class ChangeSet:
    """Conjunto de cambios pendientes, revisable antes de aplicar."""

    def __init__(self) -> None:
        self.changes: List[PendingChange] = []

    def __len__(self) -> int:
        return len(self.changes)

    def __bool__(self) -> bool:
        return bool(self.changes)

    def add(self, change: PendingChange) -> None:
        # Dos cambios sobre la misma ruta: el último gana (se fusiona sobre su resultado).
        for i, existing in enumerate(self.changes):
            if existing.path == change.path:
                self.changes[i] = change
                return
        self.changes.append(change)

    def diffs(self, context: int = 3) -> List[DiffResult]:
        return [c.diff(context=context) for c in self.changes]

    def summary(self) -> Dict[str, int]:
        added = removed = 0
        for d in self.diffs(context=0):
            added += d.added
            removed += d.removed
        return {
            "files": len(self.changes),
            "created": sum(1 for c in self.changes if not c.existed),
            "modified": sum(1 for c in self.changes if c.existed and c.kind != "delete"),
            "deleted": sum(1 for c in self.changes if c.kind == "delete"),
            "added": added,
            "removed": removed,
            "conflicts": sum(1 for c in self.changes if c.conflict_note),
        }


class FileEditor:
    """Fachada de edición: planificación, aplicación transaccional y reversión."""

    def __init__(self, fs: FilesystemOps, guard: PathGuard):
        self.fs = fs
        self.guard = guard

    # ------------------------------------------------------------- planificación
    def plan_create(self, path: str, content: str, eol: str = "\n",
                    encoding: str = "utf-8") -> PendingChange:
        """Planifica la creación de un archivo nuevo. Falla si ya existe."""
        resolved = self.guard.resolve(path)
        if resolved.exists():
            raise EditError(
                f"'{self.guard.rel(resolved)}' ya existe; usa plan_write/plan_edit para modificarlo.",
                self.guard.rel(resolved),
            )
        return PendingChange(
            path=resolved, rel=self.guard.rel(resolved), kind="create",
            old_text=None, new_text=normalize_eol(content, "\n"),
            existed=False, encoding=encoding, eol=eol,
        )

    def plan_write(self, path: str, content: str, create: bool = True) -> PendingChange:
        """Planifica la escritura completa de un archivo (sobrescribe si existe).

        Preserva la codificación y el EOL originales cuando el archivo ya existe.
        """
        resolved = self.guard.resolve(path)
        if not resolved.exists():
            if not create:
                raise EditError(f"'{self.guard.rel(resolved)}' no existe.", self.guard.rel(resolved))
            return self.plan_create(path, content)
        fc = self.fs.read(resolved)
        if fc.binary:
            raise EditError(
                f"'{fc.path.name}' es binario; la edición de texto no aplica. "
                "Usa plan_write_binary para sustituirlo íntegro.",
                self.guard.rel(resolved),
            )
        assert fc.text is not None
        return PendingChange(
            path=resolved, rel=self.guard.rel(resolved), kind="write",
            old_text=fc.text, new_text=normalize_eol(content, "\n"),
            existed=True, encoding=fc.encoding, eol=fc.eol,
        )

    def plan_write_binary(self, path: str, data: bytes) -> PendingChange:
        """Planifica la sustitución íntegra de un archivo binario (bytes exactos)."""
        resolved = self.guard.resolve(path)
        old_bytes: Optional[bytes] = None
        existed = resolved.exists()
        if existed:
            old_bytes = resolved.read_bytes()
        return PendingChange(
            path=resolved, rel=self.guard.rel(resolved), kind="write",
            old_text=None, new_text=None, old_bytes=old_bytes, new_bytes=data,
            binary=True, existed=existed,
        )

    def plan_edit(self, path: str, old_block: str, new_block: str,
                  replace_all: bool = False) -> PendingChange:
        """Planifica un reemplazo preciso de bloque (estilo CODEX).

        Reglas:
        - `old_block` debe aparecer EXACTAMENTE una vez, salvo `replace_all`.
        - Si no aparece, se busca un bloque similar y se reporta como conflicto
          (no se aplica nada: la detección ocurre en tiempo de planificación).
        - Conserva intacto todo el contenido ajeno al cambio.
        """
        resolved = self.guard.resolve(path, must_exist=True)
        fc = self.fs.read(resolved)
        rel = self.guard.rel(resolved)
        if fc.binary or fc.text is None:
            raise EditError(f"'{rel}' es un archivo binario; no se puede editar como texto.", rel)

        old_block_n = normalize_eol(old_block, "\n")
        new_block_n = normalize_eol(new_block, "\n")
        text = fc.text
        count = text.count(old_block_n)

        if count == 0:
            similar = find_similar_block(text, old_block_n)
            note = f"Conflicto en {rel}: el bloque a reemplazar no se encontró en el archivo."
            suggestion = None
            if similar:
                suggestion = similar
                note += " Se encontró un fragmento similar (¿desactualizado?)."
            raise EditError(note, rel, suggestion=suggestion)

        if count > 1 and not replace_all:
            raise EditError(
                f"Conflicto en {rel}: el bloque aparece {count} veces. "
                "Añade más contexto para hacerlo único o usa replace_all=True.",
                rel,
            )

        if replace_all:
            new_text = text.replace(old_block_n, new_block_n)
            replacements = count
        else:
            idx = text.index(old_block_n)
            new_text = text[:idx] + new_block_n + text[idx + len(old_block_n) :]
            replacements = 1

        return PendingChange(
            path=resolved, rel=rel, kind="edit",
            old_text=text, new_text=new_text, existed=True,
            encoding=fc.encoding, eol=fc.eol,
            edit_stats={"replacements": replacements},
        )

    def plan_delete(self, path: str) -> PendingChange:
        """Planifica el borrado (va a la papelera recuperable en el commit)."""
        resolved = self.guard.resolve(path, must_exist=True)
        rel = self.guard.rel(resolved)
        if resolved.is_dir():
            raise EditError(f"'{rel}' es un directorio; el borrado de directorios requiere /exec autorizado.", rel)
        fc = self.fs.read(resolved)
        return PendingChange(
            path=resolved, rel=rel, kind="delete",
            old_text=fc.text, new_text=None, existed=True,
            encoding=fc.encoding, eol=fc.eol, binary=fc.binary,
        )

    # ---------------------------------------------------------------- aplicación
    def commit(self, changes: ChangeSet, verify: bool = True) -> CommitReport:
        """Aplica el ChangeSet de forma transaccional.

        - Copia de seguridad de cada archivo existente antes de tocarlo.
        - Escritura atómica por archivo.
        - Verificación posterior (relectura y comparación).
        - Si CUALQUIER paso falla: revierte los ya aplicados desde sus copias.
        """
        report = CommitReport()
        done: List[PendingChange] = []
        try:
            for change in changes.changes:
                self._apply_one(change, report, verify=verify)
                done.append(change)
        except (EditError, FileOpError, OSError, PathViolation) as exc:
            report.error = str(exc)
            # Reversión: restaura en orden inverso desde las copias tomadas.
            for change in reversed(done):
                try:
                    self._rollback_one(change, report)
                except Exception as rb_exc:  # pragma: no cover - último recurso
                    report.error += f" | ADVERTENCIA: fallo al revertir {change.rel}: {rb_exc}"
            return report
        return report

    def _apply_one(self, change: PendingChange, report: CommitReport, verify: bool) -> None:
        # Copia de seguridad del contenido previo.
        if change.existed and change.path.exists():
            backup = self.fs.backup(change.path, label=change.kind)
            if backup is not None:
                report.backups[change.rel] = str(backup)

        if change.kind == "delete":
            self.fs.delete(change.path)
        elif change.binary:
            assert change.new_bytes is not None
            self.fs.write_atomic(change.path, change.new_bytes)
            if verify:
                actual = change.path.read_bytes()
                if actual != change.new_bytes:
                    raise EditError(f"Verificación fallida en '{change.rel}': el contenido escrito no coincide.", change.rel)
        else:
            assert change.new_text is not None
            data = normalize_eol(change.new_text, change.eol).encode(change.encoding)
            self.fs.write_atomic(change.path, data)
            if verify:
                with open(change.path, "rb") as fh:
                    actual = fh.read()
                if actual != data:
                    raise EditError(f"Verificación fallida en '{change.rel}': el contenido escrito no coincide.", change.rel)

        d = change.diff(context=0)
        report.added += d.added
        report.removed += d.removed
        report.applied.append(change.rel)

    def _rollback_one(self, change: PendingChange, report: CommitReport) -> None:
        backup_path = report.backups.get(change.rel)
        if change.kind == "delete" or not change.existed:
            # Archivo creado en este commit: eliminarlo es la reversión correcta.
            if not change.existed and change.path.exists():
                change.path.unlink()
            elif change.kind == "delete" and backup_path and os.path.exists(backup_path):
                with open(backup_path, "rb") as fh:
                    self.fs.write_atomic(change.path, fh.read())
        elif backup_path and os.path.exists(backup_path):
            with open(backup_path, "rb") as fh:
                self.fs.write_atomic(change.path, fh.read())
        report.rolled_back.append(change.rel)

    # ------------------------------------------------------------- recuperación
    def undo(self, path: str) -> str:
        """Revierte un archivo a su copia de seguridad más reciente."""
        restored = self.fs.restore(path)
        return f"'{self.guard.rel(path)}' restaurado desde {os.path.basename(str(restored))}."

    def list_backups(self, path: str) -> List[str]:
        return [str(b) for b in self.fs.list_backups(path)]

    # ------------------------------------------------------------- verificación
    def verify_matches(self, path: str, expected_text: str) -> bool:
        """Comprueba que el contenido en disco coincide con lo esperado."""
        fc = self.fs.read(path)
        return fc.text == normalize_eol(expected_text, "\n")
