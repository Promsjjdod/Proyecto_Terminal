"""Pruebas de la memoria SQLite: conversaciones, tareas, auditoría e historial."""
from __future__ import annotations

from nexo.memory.db import Memory


def test_conversation_lifecycle(tmp_path):
    mem = Memory(tmp_path / "t.db")
    cid = mem.new_conversation("mi chat", provider="ollama", model="llama")
    assert mem.conversation_exists(cid)
    mem.add_message(cid, "user", "hola")
    mem.add_message(cid, "assistant", "hola, ¿qué necesitas?")
    messages = mem.get_messages(cid)
    assert messages == [("user", "hola"), ("assistant", "hola, ¿qué necesitas?")]
    rows = mem.list_conversations()
    assert rows[0][0] == cid and rows[0][4] == 2
    mem.set_conversation_title(cid, "título nuevo")
    assert mem.list_conversations()[0][1] == "título nuevo"
    assert mem.delete_conversation(cid)
    assert not mem.conversation_exists(cid)
    # Los mensajes se borran en cascada.
    assert mem.get_messages(cid) == []
    mem.close()


def test_messages_limit_returns_last(tmp_path):
    mem = Memory(tmp_path / "t.db")
    cid = mem.new_conversation()
    for i in range(30):
        mem.add_message(cid, "user", f"mensaje-{i}")
    last = mem.get_messages(cid, limit=5)
    assert len(last) == 5
    assert last[-1][1] == "mensaje-29" and last[0][1] == "mensaje-25"
    mem.close()


def test_messages_redact_secrets(tmp_path):
    mem = Memory(tmp_path / "t.db")
    cid = mem.new_conversation()
    mem.add_message(cid, "user", "mi clave es sk-ant-abcdefghijklmnopqrstuvwxyz123456")
    stored = mem.get_messages(cid)[0][1]
    assert "sk-ant-" not in stored
    assert "[REDACTADO]" in stored
    mem.close()


def test_task_lifecycle(tmp_path):
    mem = Memory(tmp_path / "t.db")
    tid = mem.create_task("refactorizar módulo", "detalle de la tarea",
                          plan=["leer", "editar", "probar"])
    task = mem.get_task(tid)
    assert task.status == "pendiente" and task.plan == ["leer", "editar", "probar"]

    mem.update_task(tid, status="en_curso", iterations=2)
    assert mem.get_task(tid).status == "en_curso"

    mem.update_task(tid, status="interrumpida", error="límite de tiempo")
    interrupted = mem.interrupted_tasks()
    assert [t.id for t in interrupted] == [tid]

    mem.update_task(tid, status="completada", result="todo listo",
                    plan=["leer", "editar", "probar", "verificar"])
    task = mem.get_task(tid)
    assert task.status == "completada" and task.result == "todo listo"
    assert task.plan[-1] == "verificar"
    assert mem.interrupted_tasks() == []
    statuses = [t.status for t in mem.list_tasks()]
    assert statuses == ["completada"]
    assert mem.list_tasks(status="fallida") == []
    mem.close()


def test_operations_audit(tmp_path):
    mem = Memory(tmp_path / "t.db")
    mem.log_operation("exec", "ls -la", "exit=0", success=True)
    mem.log_operation("edit", "a.py", "falló verificación", success=False)
    ops = mem.recent_operations(10)
    assert len(ops) == 2
    assert ops[0][1] == "edit"           # más reciente primero
    assert ops[0][4] is False
    mem.close()


def test_operations_redact_secrets(tmp_path):
    mem = Memory(tmp_path / "t.db")
    mem.log_operation("auth", "curl -H 'Authorization: Bearer ghp_0123456789abcdefghijAB'", "")
    target = mem.recent_operations(1)[0][2]
    assert "ghp_0123456789" not in target
    mem.close()


def test_file_history(tmp_path):
    mem = Memory(tmp_path / "t.db")
    mem.record_file_change("src/a.py", "edit", "/backups/a.py.bak")
    mem.record_file_change("src/b.py", "delete", "")
    all_changes = mem.file_changes()
    assert len(all_changes) == 2
    only_a = mem.file_changes("src/a.py")
    assert len(only_a) == 1 and only_a[0][1] == "src/a.py"
    mem.close()


def test_stats(tmp_path):
    mem = Memory(tmp_path / "t.db")
    cid = mem.new_conversation()
    mem.add_message(cid, "user", "x")
    mem.create_task("t")
    stats = mem.stats()
    assert stats["conversations"] == 1 and stats["messages"] == 1 and stats["tasks"] == 1
    mem.close()


def test_reopen_persists(tmp_path):
    path = tmp_path / "t.db"
    mem = Memory(path)
    cid = mem.new_conversation("persistente")
    mem.add_message(cid, "user", "recuérdame")
    mem.close()
    mem2 = Memory(path)
    assert mem2.conversation_exists(cid)
    assert mem2.get_messages(cid) == [("user", "recuérdame")]
    mem2.close()
