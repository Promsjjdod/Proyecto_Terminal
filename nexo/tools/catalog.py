"""Catálogo de herramientas que el agente puede invocar.

Cada herramienta está conectada a implementaciones reales (editor, sistema de
archivos, ejecutor de comandos) y pasa SIEMPRE por el administrador de
permisos. El agente no puede eludir los permisos: las herramientas son la
única vía de acción y todas validan rutas, clasifican comandos y solicitan
autorización cuando el modo lo exige.
"""
from __future__ import annotations

import fnmatch
import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List

from nexo.editor.diff import compute_diff
from nexo.editor.engine import ChangeSet, EditError, FileEditor
from nexo.filesystem.ops import FileOpError, FilesystemOps
from nexo.permissions.manager import PermissionManager
from nexo.permissions.paths import PathGuard, PathViolation
from nexo.tools.executor import CommandExecutor

# Especificaciones de herramientas (nombre -> descripción/args) para el prompt.
TOOL_SPECS: List[Dict[str, Any]] = [
    {"name": "read_file",
     "description": "Lee un archivo de texto del workspace (con números de línea).",
     "args": {"path": "str", "offset": "int opcional (línea inicial, 1-based)", "limit": "int opcional (máx líneas)"}},
    {"name": "list_dir",
     "description": "Lista archivos y directorios del workspace.",
     "args": {"path": "str opcional (relativa al workspace, por defecto '.')"}},
    {"name": "search",
     "description": "Busca un patrón (regex) en archivos de texto del workspace.",
     "args": {"pattern": "str regex", "path": "str opcional (directorio)", "glob": "str opcional (p.ej. '*.py')"}},
    {"name": "create_file",
     "description": "Crea un archivo nuevo con el contenido indicado. Falla si ya existe.",
     "args": {"path": "str", "content": "str"}},
    {"name": "write_file",
     "description": "Escribe/sobrescribe un archivo completo (preserva codificación y EOL).",
     "args": {"path": "str", "content": "str"}},
    {"name": "edit_file",
     "description": "Reemplazo preciso de un bloque de texto por otro. old_block debe existir exactamente una vez (salvo replace_all). Conserva el resto del archivo intacto.",
     "args": {"path": "str", "old_block": "str exacto", "new_block": "str", "replace_all": "bool opcional"}},
    {"name": "delete_file",
     "description": "Elimina un archivo (va a papelera recuperable con undo_file).",
     "args": {"path": "str"}},
    {"name": "undo_file",
     "description": "Revierte un archivo a su última copia de seguridad.",
     "args": {"path": "str"}},
    {"name": "export_file",
     "description": "Exporta un archivo del workspace al almacenamiento compartido (por defecto la carpeta Descargas de Android). Operación sensible: requiere autorización. Si el destino existe, devuelve las opciones replace/version/cancel (usá on_exists para reintentar).",
     "args": {"path": "str (archivo dentro del workspace)", "destination": "str opcional ('downloads' o ruta revisada)", "on_exists": "str opcional: ask|replace|version|cancel"}},
    {"name": "run_command",
     "description": "Ejecuta un comando shell en el workspace (sujeto a permisos, timeout y límites de salida).",
     "args": {"command": "str", "timeout": "float opcional (segundos)"}},
    {"name": "ask_user",
     "description": "Pregunta al usuario cuando falta información o hay ambigüedad. Detiene el ciclo hasta obtener respuesta.",
     "args": {"question": "str"}},
    {"name": "finish",
     "description": "Termina la tarea con un resumen honesto: qué se hizo, qué se verificó y qué falta.",
     "args": {"summary": "str", "success": "bool"}},
]

TOOL_NAMES = [t["name"] for t in TOOL_SPECS]


@dataclass
class ToolResult:
    ok: bool
    output: str
    action: str = ""
    needs_user: bool = False
    question: str = ""
    finished: bool = False
    finish_success: bool = True
    data: Dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.data is None:
            self.data = {}


class ToolCatalog:
    """Ejecuta las herramientas del agente sobre el workspace autorizado."""

    def __init__(
        self,
        guard: PathGuard,
        fs: FilesystemOps,
        editor: FileEditor,
        executor: CommandExecutor,
        permissions: PermissionManager,
        memory=None,
        max_read_chars: int = 100_000,
        exporter=None,
    ):
        self.guard = guard
        self.fs = fs
        self.editor = editor
        self.executor = executor
        self.permissions = permissions
        self.memory = memory
        self.max_read_chars = max_read_chars
        self.exporter = exporter
        self.file_ops_count = 0     # escrituras/borrados realizados en la tarea actual
        self._task_file_changes: Dict[str, Dict[str, Any]] = {}
        self._task_tests: List[Dict[str, Any]] = []

    def reset_task_tracking(self) -> None:
        """Inicia un registro efímero para calcular el cambio neto de una tarea."""
        self.file_ops_count = 0
        self._task_file_changes = {}
        self._task_tests = []

    def _record_file_change(self, change) -> None:
        row = self._task_file_changes.get(change.rel)
        if row is None:
            row = {
                "path": change.rel,
                "before_exists": bool(change.existed),
                "before_text": change.old_text,
                "binary": bool(change.binary),
            }
            self._task_file_changes[change.rel] = row
        row["after_exists"] = change.kind != "delete"
        row["after_text"] = change.new_text
        row["binary"] = row["binary"] or bool(change.binary)

    def task_change_summary(self) -> Dict[str, Any]:
        """Resume solo los cambios netos que efectivamente se aplicaron."""
        files: List[Dict[str, Any]] = []
        added = removed = created = modified = deleted = 0
        for path, row in self._task_file_changes.items():
            before_exists = row["before_exists"]
            after_exists = row.get("after_exists", before_exists)
            before_text, after_text = row.get("before_text"), row.get("after_text")
            if not before_exists and not after_exists:
                continue
            if before_exists and after_exists and before_text == after_text and not row["binary"]:
                continue
            if not before_exists and after_exists:
                created += 1
                kind = "creado"
            elif before_exists and not after_exists:
                deleted += 1
                kind = "eliminado"
            else:
                modified += 1
                kind = "modificado"
            diff = compute_diff(before_text, after_text, path, is_binary=row["binary"], context=0)
            added += diff.added
            removed += diff.removed
            files.append({"path": path, "kind": kind,
                          "added": diff.added, "removed": diff.removed})
        return {"files": files, "created": created, "modified": modified,
                "deleted": deleted, "added": added, "removed": removed,
                "tests": list(self._task_tests)}

    # ------------------------------------------------------------------ dispatch
    def execute(self, name: str, args: Dict[str, Any]) -> ToolResult:
        handler = getattr(self, f"_tool_{name}", None)
        if handler is None:
            return ToolResult(False, f"Herramienta desconocida: '{name}'. "
                                     f"Disponibles: {', '.join(TOOL_NAMES)}.", action=name)
        if not isinstance(args, dict):
            return ToolResult(False, f"Argumentos inválidos para '{name}': se esperaba un objeto JSON.",
                              action=name)
        try:
            return handler(args)
        except PathViolation as exc:
            return self._denied(name, str(exc), exc.path)
        except (EditError, FileOpError) as exc:
            output = str(exc)
            suggestion = getattr(exc, "suggestion", None)
            if suggestion:
                output += f"\n\nFragmento similar encontrado en el archivo:\n{suggestion}"
            return ToolResult(False, output, action=name)
        except Exception as exc:  # errores inesperados: informados, nunca silentes
            return ToolResult(False, f"Error interno en '{name}': {type(exc).__name__}: {exc}",
                              action=name)

    def _denied(self, name: str, reason: str, target: str = "") -> ToolResult:
        if self.memory:
            self.memory.log_operation(f"tool_denegada:{name}", target, reason, success=False)
        return ToolResult(False, f"PERMISO DENEGADO para '{name}' ({target}): {reason}", action=name)

    def _log(self, kind: str, target: str, detail: str, success: bool) -> None:
        if self.memory:
            self.memory.log_operation(kind, target, detail, success=success)

    # ---------------------------------------------------------------- herramientas
    def _tool_read_file(self, args: Dict[str, Any]) -> ToolResult:
        path = str(args.get("path", ""))
        decision = self.permissions.check_path(path)
        if not decision.allowed:
            return self._denied("read_file", decision.reason, path)
        offset = int(args.get("offset") or 1)
        limit = int(args.get("limit") or 0)
        fc = self.fs.read(path)
        if fc.binary:
            return ToolResult(True, f"'{fc.path.name}' es binario ({fc.size} bytes). "
                                    "No se muestra contenido de texto.", action="read_file")
        assert fc.text is not None
        lines = fc.text.splitlines()
        total = len(lines)
        start = max(offset - 1, 0)
        end = total if not limit or limit <= 0 else min(start + limit, total)
        shown = lines[start:end]
        numbered = [f"{start + i + 1:>5} | {line}" for i, line in enumerate(shown)]
        body = "\n".join(numbered)
        truncated = False
        if len(body) > self.max_read_chars:
            body = body[: self.max_read_chars]
            truncated = True
        header = f"Archivo {self.guard.rel(fc.path)} ({total} líneas, {fc.encoding}, " \
                 f"EOL={'CRLF' if fc.eol == chr(13) + chr(10) else 'LF'}):"
        if start > 0 or end < total:
            header += f" mostrando líneas {start + 1}-{end}."
        if truncated:
            header += " [contenido truncado por límite]"
        return ToolResult(True, header + "\n" + body, action="read_file")

    def _tool_list_dir(self, args: Dict[str, Any]) -> ToolResult:
        path = str(args.get("path") or ".")
        decision = self.permissions.check_path(path)
        if not decision.allowed:
            return self._denied("list_dir", decision.reason, path)
        entries, truncated = self.fs.list_dir(path)
        body = "\n".join(entries) if entries else "(directorio vacío)"
        if truncated:
            body += "\n… (lista truncada)"
        return ToolResult(True, f"{len(entries)} entrada(s) en '{path}':\n{body}",
                          action="list_dir")

    def _tool_search(self, args: Dict[str, Any]) -> ToolResult:
        pattern = str(args.get("pattern", ""))
        base = str(args.get("path") or ".")
        glob_pat = str(args.get("glob") or "*")
        if not pattern:
            return ToolResult(False, "Falta el argumento 'pattern'.", action="search")
        decision = self.permissions.check_path(base)
        if not decision.allowed:
            return self._denied("search", decision.reason, base)
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            return ToolResult(False, f"Regex inválida: {exc}", action="search")
        root = self.guard.resolve(base)
        matches: List[str] = []
        files_scanned = 0
        max_matches = 200
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames
                           if d not in (".git", "__pycache__", "node_modules", ".venv")]
            for fname in filenames:
                if not fnmatch.fnmatch(fname, glob_pat):
                    continue
                full = os.path.join(dirpath, fname)
                files_scanned += 1
                try:
                    fc = self.fs.read(full, max_bytes=2 * 1024 * 1024)
                except (FileOpError, PathViolation, OSError):
                    continue
                if fc.binary or fc.text is None:
                    continue
                for i, line in enumerate(fc.text.splitlines(), start=1):
                    if regex.search(line):
                        rel = self.guard.rel(full)
                        matches.append(f"{rel}:{i}: {line.strip()[:180]}")
                        if len(matches) >= max_matches:
                            break
                if len(matches) >= max_matches:
                    break
            if len(matches) >= max_matches:
                break
        header = f"{len(matches)} coincidencia(s) en {files_scanned} archivo(s) escaneados"
        if len(matches) >= max_matches:
            header += " (límite alcanzado)"
        return ToolResult(True, header + (":\n" + "\n".join(matches) if matches else "."),
                          action="search")

    def _tool_create_file(self, args: Dict[str, Any]) -> ToolResult:
        return self._apply_single(
            "create_file",
            str(args.get("path", "")),
            lambda p: self.editor.plan_create(p, str(args.get("content", ""))),
            overwrite=False,
        )

    def _tool_write_file(self, args: Dict[str, Any]) -> ToolResult:
        return self._apply_single(
            "write_file",
            str(args.get("path", "")),
            lambda p: self.editor.plan_write(p, str(args.get("content", ""))),
            overwrite=self.fs.exists(str(args.get("path", ""))) if args.get("path") else False,
        )

    def _tool_edit_file(self, args: Dict[str, Any]) -> ToolResult:
        path = str(args.get("path", ""))
        return self._apply_single(
            "edit_file", path,
            lambda p: self.editor.plan_edit(
                p, str(args.get("old_block", "")), str(args.get("new_block", "")),
                replace_all=bool(args.get("replace_all", False))),
            overwrite=True,
        )

    def _apply_single(self, tool: str, path: str,
                      planner: Callable[[str], Any], overwrite: bool) -> ToolResult:
        if not path:
            return ToolResult(False, "Falta el argumento 'path'.", action=tool)
        existed = self.fs.exists(path)
        decision = self.permissions.check_write(path, overwrite=existed and overwrite)
        if not decision.allowed:
            return self._denied(tool, decision.reason, path)
        change = planner(path)
        changes = ChangeSet()
        changes.add(change)
        report = self.editor.commit(changes, verify=True)
        rel = self.guard.rel(path)
        if report.success:
            self.file_ops_count += 1
            self._record_file_change(change)
            d = change.diff(context=0)
            self._log(tool, rel, f"+{d.added} -{d.removed}", success=True)
            backup = report.backups.get(rel, "")
            if backup and self.memory:
                self.memory.record_file_change(rel, tool, backup)
            return ToolResult(True, f"OK: {report.summary()}", action=tool,
                              data={"path": rel, "added": d.added, "removed": d.removed,
                                    "diff": change.diff(context=3)})
        self._log(tool, rel, report.error, success=False)
        return ToolResult(False, f"La edición NO se aplicó (sin cambios parciales).\n{report.summary()}",
                          action=tool)

    def _tool_delete_file(self, args: Dict[str, Any]) -> ToolResult:
        path = str(args.get("path", ""))
        if not path:
            return ToolResult(False, "Falta el argumento 'path'.", action="delete_file")
        decision = self.permissions.check_delete(path)
        if not decision.allowed:
            return self._denied("delete_file", decision.reason, path)
        change = self.editor.plan_delete(path)
        changes = ChangeSet()
        changes.add(change)
        report = self.editor.commit(changes)
        rel = self.guard.rel(path)
        if report.success:
            self.file_ops_count += 1
            self._record_file_change(change)
            self._log("delete_file", rel, "movido a papelera", success=True)
            if self.memory:
                self.memory.record_file_change(rel, "delete", report.backups.get(rel, ""))
            return ToolResult(True, f"OK: '{rel}' eliminado (recuperable con undo_file).",
                              action="delete_file", data={"diff": change.diff(context=3)})
        return ToolResult(False, f"No se pudo eliminar '{rel}': {report.error}",
                          action="delete_file")

    def _tool_undo_file(self, args: Dict[str, Any]) -> ToolResult:
        path = str(args.get("path", ""))
        if not path:
            return ToolResult(False, "Falta el argumento 'path'.", action="undo_file")
        try:
            resolved = self.guard.resolve(path)
        except PathViolation as exc:
            return self._denied("undo_file", str(exc), path)
        decision = self.permissions.check_write(path, overwrite=True)
        if not decision.allowed:
            return self._denied("undo_file", decision.reason, path)
        before = self.fs.read(path) if self.fs.exists(path) else None
        message = self.editor.undo(resolved)
        after = self.fs.read(resolved)
        rel = self.guard.rel(resolved)
        row = self._task_file_changes.get(rel)
        if row is None:
            row = {
                "path": rel,
                "before_exists": before is not None,
                "before_text": before.text if before and not before.binary else None,
                "binary": bool((before and before.binary) or after.binary),
            }
            self._task_file_changes[rel] = row
        row["after_exists"] = True
        row["after_text"] = after.text if not after.binary else None
        row["binary"] = row["binary"] or after.binary
        self._log("undo_file", path, message, success=True)
        diff = compute_diff(
            before.text if before and not before.binary else None,
            after.text if not after.binary else None,
            rel,
            is_binary=bool((before and before.binary) or after.binary),
            context=3,
        )
        return ToolResult(True, f"OK: {message}", action="undo_file",
                          data={"path": rel, "diff": diff})

    def _tool_export_file(self, args: Dict[str, Any]) -> ToolResult:
        if self.exporter is None:
            return ToolResult(False, "Exportación no disponible en este contexto.",
                              action="export_file")
        path = str(args.get("path", ""))
        if not path:
            return ToolResult(False, "Falta el argumento 'path'.", action="export_file")
        destination = str(args.get("destination") or "downloads")
        on_exists = str(args.get("on_exists") or "ask")
        if on_exists not in ("ask", "replace", "version", "cancel"):
            return ToolResult(False,
                              "on_exists inválido: usá ask|replace|version|cancel.",
                              action="export_file")
        result = self.exporter.export_file(path, destination=destination,
                                           on_exists=on_exists)
        if result.needs_choice:
            return ToolResult(False, result.message +
                              " Reintentá con on_exists='replace', 'version' o 'cancel', "
                              "o preguntale al usuario con ask_user primero.",
                              action="export_file", data={"needs_choice": True})
        return ToolResult(result.ok, result.message, action="export_file",
                          data={"path": result.path})

    def _tool_run_command(self, args: Dict[str, Any]) -> ToolResult:
        command = str(args.get("command", ""))
        timeout = args.get("timeout")
        timeout = float(timeout) if timeout else None
        result = self.executor.run(command, timeout=timeout)
        lowered = command.lower()
        runner = next((name for name in ("pytest", "unittest", "tox", "nox")
                       if name in lowered), "")
        if runner:
            self._task_tests.append({
                "runner": runner,
                "exit_code": result.exit_code,
                "timed_out": result.timed_out,
                "authorized": result.authorized,
            })
        return ToolResult(result.ok, result.summary(),
                          action="run_command",
                          data={"exit_code": result.exit_code, "authorized": result.authorized,
                                "timed_out": result.timed_out, "command": command})

    def _tool_ask_user(self, args: Dict[str, Any]) -> ToolResult:
        question = str(args.get("question", "")).strip()
        if not question:
            return ToolResult(False, "La pregunta está vacía.", action="ask_user")
        return ToolResult(True, "", action="ask_user", needs_user=True, question=question)

    def _tool_finish(self, args: Dict[str, Any]) -> ToolResult:
        summary = str(args.get("summary", "")).strip() or "(sin resumen)"
        success = bool(args.get("success", True))
        return ToolResult(True, summary, action="finish", finished=True,
                          finish_success=success)
