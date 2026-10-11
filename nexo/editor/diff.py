"""Cálculo de diferencias estilo Git (unified diff) con numeración de líneas.

Los resultados son datos puros (`DiffResult`); la capa de UI los pinta:
- verde  : líneas añadidas (+)
- rojo   : líneas eliminadas (-)
- amarillo: cabeceras de bloque (hunk) y conflictos marcados
- sin color: contexto
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class DiffLine:
    """Una línea del diff. `tag`: ' ' contexto, '+' añadida, '-' eliminada, '?' conflicto."""

    tag: str
    text: str
    old_no: Optional[int] = None
    new_no: Optional[int] = None


@dataclass
class DiffResult:
    path: str
    lines: List[DiffLine] = field(default_factory=list)
    added: int = 0
    removed: int = 0
    is_binary: bool = False
    is_new: bool = False       # archivo creado (todo verde)
    is_delete: bool = False    # archivo eliminado (todo rojo)
    conflict_note: str = ""    # mensaje de conflicto (se pinta en amarillo)

    @property
    def changed(self) -> bool:
        return bool(self.added or self.removed or self.is_binary or self.conflict_note)

    def plain_text(self, context: int = 3, show_numbers: bool = True) -> str:
        """Diff como texto plano (para logs, pruebas y terminales sin color)."""
        out: List[str] = []
        if self.is_binary:
            out.append(f"--- {self.path} (archivo binario modificado)")
            return "\n".join(out)
        if self.conflict_note:
            out.append(f"! {self.conflict_note}")
        for line in self.lines:
            if show_numbers:
                old = f"{line.old_no:>4}" if line.old_no is not None else "    "
                new = f"{line.new_no:>4}" if line.new_no is not None else "    "
                out.append(f"{line.tag} {old} {new} | {line.text}")
            else:
                out.append(f"{line.tag} {line.text}")
        out.append(f"@@ {self.path}: +{self.added} -{self.removed}")
        return "\n".join(out)


def diff_line_count(result: DiffResult) -> int:
    """Total de líneas mostradas en el diff (para decidir si resumir)."""
    return len(result.lines)


def compute_diff(
    old_text: Optional[str],
    new_text: Optional[str],
    path: str,
    is_binary: bool = False,
    context: int = 3,
    conflict_note: str = "",
) -> DiffResult:
    """Calcula el diff entre `old_text` (None = no existía) y `new_text` (None = se elimina).

    Incluye numeración de líneas original/nueva y recorta el contexto a
    `context` líneas alrededor de cada cambio, como hace Git.
    """
    is_new = old_text is None
    is_delete = new_text is None
    old_lines = (old_text or "").splitlines()
    new_lines = (new_text or "").splitlines()

    if is_binary:
        return DiffResult(path=path, is_binary=True, conflict_note=conflict_note,
                          is_new=is_new, is_delete=is_delete)

    matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
    result = DiffResult(path=path, is_new=is_new, is_delete=is_delete,
                        conflict_note=conflict_note)

    opcodes = matcher.get_opcodes()
    # Agrupa opcodes en hunks separados por más de `context` líneas iguales.
    hunks: List[List[Tuple[str, int, int, int, int]]] = []
    current: List[Tuple[str, int, int, int, int]] = []
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal" and (i2 - i1) > context * 2 and current:
            hunks.append(current)
            current = []
        current.append((tag, i1, i2, j1, j2))
    if current:
        hunks.append(current)

    for hunk in hunks:
        for tag, i1, i2, j1, j2 in hunk:
            if tag == "equal":
                # Recorta contexto largo dentro del hunk.
                length = i2 - i1
                if length > context * 2:
                    for k in range(context):
                        result.lines.append(DiffLine(" ", old_lines[i1 + k], i1 + k + 1, j1 + k + 1))
                    result.lines.append(DiffLine(" ", f"@@ … {length - context * 2} líneas de contexto omitidas … @@", None, None))
                    for k in range(length - context, length):
                        result.lines.append(DiffLine(" ", old_lines[i1 + k], i1 + k + 1, j1 + k + 1))
                else:
                    for k in range(length):
                        result.lines.append(DiffLine(" ", old_lines[i1 + k], i1 + k + 1, j1 + k + 1))
            elif tag == "delete":
                for k in range(i1, i2):
                    result.lines.append(DiffLine("-", old_lines[k], k + 1, None))
                    result.removed += 1
            elif tag == "insert":
                for k in range(j1, j2):
                    result.lines.append(DiffLine("+", new_lines[k], None, k + 1))
                    result.added += 1
            elif tag == "replace":
                for k in range(i1, i2):
                    result.lines.append(DiffLine("-", old_lines[k], k + 1, None))
                    result.removed += 1
                for k in range(j1, j2):
                    result.lines.append(DiffLine("+", new_lines[k], None, k + 1))
                    result.added += 1
    return result


def find_similar_block(old_text: str, missing_block: str, window: int = 200) -> Optional[str]:
    """Detección de conflictos: si un bloque a reemplazar no existe, busca el
    fragmento más parecido en el archivo para sugerirlo al usuario/agente.

    La similitud se calcula a nivel de caracteres (ventanas del mismo número de
    líneas que el bloque), que es más robusta que comparar líneas completas
    cuando solo cambia un token dentro del bloque.
    """
    old_lines = old_text.splitlines()
    block_lines = missing_block.splitlines()
    if not old_lines or not block_lines:
        return None
    block_joined = "\n".join(block_lines)
    n = len(block_lines)
    best_ratio = 0.0
    best: Optional[List[str]] = None
    max_start = max(1, len(old_lines) - n + 1)
    step = max(1, min(n, 8))  # ventanas solapadas pero con paso acotado (rendimiento)
    for start in range(0, max_start, step):
        candidate = old_lines[start : start + n]
        ratio = difflib.SequenceMatcher(
            None, block_joined, "\n".join(candidate), autojunk=False
        ).ratio()
        if ratio > best_ratio:
            best_ratio, best = ratio, candidate
    # Solo sugerir si el parecido es razonable (no ruido).
    if best is not None and best_ratio >= 0.55:
        return "\n".join(best)
    return None
