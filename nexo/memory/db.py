"""Base de datos local SQLite de NEXO.

Almacena (separado del código y de las credenciales):
- Conversaciones y mensajes.
- Tareas del agente con estado y plan (para recuperación de tareas interrumpidas).
- Registro de operaciones ejecutadas (auditoría, texto redactado).
- Historial de modificaciones de archivos (ruta + copia de seguridad).

Los textos registrados pasan por `redact_text` para no persistir secretos.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from nexo.security.secrets import redact_text

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL DEFAULT '',
    provider TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, id);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pendiente',
    plan TEXT NOT NULL DEFAULT '[]',
    result TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    iterations INTEGER NOT NULL DEFAULT 0,
    conversation_id INTEGER,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS operations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    kind TEXT NOT NULL,
    target TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT '',
    success INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS file_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    path TEXT NOT NULL,
    action TEXT NOT NULL,
    backup_path TEXT NOT NULL DEFAULT '',
    task_id INTEGER
);
"""


@dataclass
class TaskRecord:
    id: int
    title: str
    description: str
    status: str            # pendiente | en_curso | completada | fallida | interrumpida
    plan: List[str]
    result: str
    error: str
    iterations: int
    conversation_id: Optional[int]
    created_at: float
    updated_at: float


class Memory:
    """Fachada SQLite de la memoria de NEXO (thread-local no necesaria: uso single-hilo)."""

    def __init__(self, db_path: str | os.PathLike):
        self.db_path = str(db_path)
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA)
        self._conn.execute(
            "INSERT OR IGNORE INTO meta(key, value) VALUES('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        self._conn.commit()

    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error:  # pragma: no cover
            pass

    # ---------------------------------------------------------- conversaciones
    def new_conversation(self, title: str = "", provider: str = "", model: str = "") -> int:
        now = time.time()
        cur = self._conn.execute(
            "INSERT INTO conversations(title, provider, model, created_at, updated_at) "
            "VALUES(?,?,?,?,?)",
            (redact_text(title), provider, model, now, now),
        )
        self._conn.commit()
        return int(cur.lastrowid or 0)

    def list_conversations(self, limit: int = 20) -> List[Tuple[int, str, str, str, int, float]]:
        rows = self._conn.execute(
            "SELECT c.id, c.title, c.provider, c.model, COUNT(m.id), c.updated_at "
            "FROM conversations c LEFT JOIN messages m ON m.conversation_id = c.id "
            "GROUP BY c.id ORDER BY c.updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [(r[0], r[1], r[2], r[3], r[4], r[5]) for r in rows]

    def add_message(self, conversation_id: int, role: str, content: str) -> int:
        now = time.time()
        cur = self._conn.execute(
            "INSERT INTO messages(conversation_id, role, content, created_at) VALUES(?,?,?,?)",
            (conversation_id, role, redact_text(content), now),
        )
        self._conn.execute("UPDATE conversations SET updated_at=? WHERE id=?",
                           (now, conversation_id))
        self._conn.commit()
        return int(cur.lastrowid or 0)

    def get_messages(self, conversation_id: int, limit: Optional[int] = None
                     ) -> List[Tuple[str, str]]:
        """Mensajes (role, content) en orden cronológico; `limit` toma los últimos N."""
        rows = self._conn.execute(
            "SELECT role, content FROM messages WHERE conversation_id=? ORDER BY id",
            (conversation_id,),
        ).fetchall()
        if limit and len(rows) > limit:
            rows = rows[-limit:]
        return [(r[0], r[1]) for r in rows]

    def set_conversation_title(self, conversation_id: int, title: str) -> None:
        self._conn.execute("UPDATE conversations SET title=?, updated_at=? WHERE id=?",
                           (redact_text(title), time.time(), conversation_id))
        self._conn.commit()

    def delete_conversation(self, conversation_id: int) -> bool:
        cur = self._conn.execute("DELETE FROM conversations WHERE id=?", (conversation_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def conversation_exists(self, conversation_id: int) -> bool:
        row = self._conn.execute("SELECT 1 FROM conversations WHERE id=?",
                                 (conversation_id,)).fetchone()
        return row is not None

    # ------------------------------------------------------------------ tareas
    def create_task(self, title: str, description: str = "",
                    conversation_id: Optional[int] = None,
                    plan: Optional[List[str]] = None) -> int:
        now = time.time()
        cur = self._conn.execute(
            "INSERT INTO tasks(title, description, status, plan, conversation_id, "
            "created_at, updated_at) VALUES(?,?, 'pendiente', ?, ?, ?, ?)",
            (redact_text(title), redact_text(description),
             json.dumps(plan or [], ensure_ascii=False), conversation_id, now, now),
        )
        self._conn.commit()
        return int(cur.lastrowid or 0)

    def update_task(self, task_id: int, *, status: Optional[str] = None,
                    result: Optional[str] = None, error: Optional[str] = None,
                    plan: Optional[List[str]] = None,
                    iterations: Optional[int] = None) -> None:
        fields: List[str] = []
        values: List[object] = []
        if status is not None:
            fields.append("status=?")
            values.append(status)
        if result is not None:
            fields.append("result=?")
            values.append(redact_text(result))
        if error is not None:
            fields.append("error=?")
            values.append(redact_text(error))
        if plan is not None:
            fields.append("plan=?")
            values.append(json.dumps(plan, ensure_ascii=False))
        if iterations is not None:
            fields.append("iterations=?")
            values.append(iterations)
        if not fields:
            return
        fields.append("updated_at=?")
        values.append(time.time())
        values.append(task_id)
        self._conn.execute(f"UPDATE tasks SET {', '.join(fields)} WHERE id=?", values)
        self._conn.commit()

    def get_task(self, task_id: int) -> Optional[TaskRecord]:
        row = self._conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return self._row_to_task(row) if row else None

    def list_tasks(self, status: Optional[str] = None, limit: int = 50) -> List[TaskRecord]:
        if status:
            rows = self._conn.execute(
                "SELECT * FROM tasks WHERE status=? ORDER BY updated_at DESC LIMIT ?",
                (status, limit)).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM tasks ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
        return [self._row_to_task(r) for r in rows]

    def interrupted_tasks(self) -> List[TaskRecord]:
        """Tareas que quedaron en curso/pendientes (candidatas a recuperación)."""
        rows = self._conn.execute(
            "SELECT * FROM tasks WHERE status IN ('en_curso','pendiente','interrumpida') "
            "ORDER BY updated_at DESC").fetchall()
        return [self._row_to_task(r) for r in rows]

    @staticmethod
    def _row_to_task(row) -> TaskRecord:
        try:
            plan = json.loads(row[4]) if row[4] else []
        except json.JSONDecodeError:
            plan = []
        return TaskRecord(
            id=row[0], title=row[1], description=row[2], status=row[3], plan=plan,
            result=row[5], error=row[6], iterations=row[7], conversation_id=row[8],
            created_at=row[9], updated_at=row[10],
        )

    # --------------------------------------------------------- auditoría/historial
    def log_operation(self, kind: str, target: str = "", detail: str = "",
                      success: bool = True) -> int:
        cur = self._conn.execute(
            "INSERT INTO operations(ts, kind, target, detail, success) VALUES(?,?,?,?,?)",
            (time.time(), kind, redact_text(target), redact_text(detail), 1 if success else 0),
        )
        self._conn.commit()
        return int(cur.lastrowid or 0)

    def recent_operations(self, limit: int = 20) -> List[Tuple[float, str, str, str, bool]]:
        rows = self._conn.execute(
            "SELECT ts, kind, target, detail, success FROM operations ORDER BY id DESC LIMIT ?",
            (limit,)).fetchall()
        return [(r[0], r[1], r[2], r[3], bool(r[4])) for r in rows]

    def record_file_change(self, path: str, action: str, backup_path: str = "",
                           task_id: Optional[int] = None) -> int:
        cur = self._conn.execute(
            "INSERT INTO file_history(ts, path, action, backup_path, task_id) VALUES(?,?,?,?,?)",
            (time.time(), path, action, backup_path, task_id),
        )
        self._conn.commit()
        return int(cur.lastrowid or 0)

    def file_changes(self, path: Optional[str] = None, limit: int = 30
                     ) -> List[Tuple[float, str, str, str]]:
        if path:
            rows = self._conn.execute(
                "SELECT ts, path, action, backup_path FROM file_history WHERE path=? "
                "ORDER BY id DESC LIMIT ?", (path, limit)).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT ts, path, action, backup_path FROM file_history ORDER BY id DESC LIMIT ?",
                (limit,)).fetchall()
        return [(r[0], r[1], r[2], r[3]) for r in rows]

    # ----------------------------------------------------------------- utilidad
    def stats(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for table in ("conversations", "messages", "tasks", "operations", "file_history"):
            row = self._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            out[table] = int(row[0]) if row else 0
        return out
