"""Pruebas del motor de edición: creación, reemplazo preciso, transacciones, undo."""
from __future__ import annotations

import os

import pytest

from nexo.editor.engine import ChangeSet, EditError
from nexo.filesystem.ops import FileOpError

PY_SAMPLE = '''def suma(a, b):
    """Suma dos números."""
    return a + b


def resta(a, b):
    return a - b
'''


@pytest.fixture
def sample(stack):
    stack["fs"].write_text("app.py", PY_SAMPLE)
    return stack


# -------------------------------------------------------------------- creación
def test_plan_create_new_file(stack):
    editor = stack["editor"]
    changes = ChangeSet()
    changes.add(editor.plan_create("nuevo.txt", "contenido\n"))
    report = editor.commit(changes)
    assert report.success
    assert report.added == 1
    with open(os.path.join(stack["workspace"], "nuevo.txt"), encoding="utf-8") as fh:
        assert fh.read() == "contenido\n"


def test_plan_create_existing_fails(sample):
    editor = sample["editor"]
    with pytest.raises(EditError, match="ya existe"):
        editor.plan_create("app.py", "x")


def test_plan_write_overwrite_preserves_eol_and_encoding(sample):
    editor = sample["editor"]
    fs = sample["fs"]
    fs.write_text("crlf.txt", "uno\r\ndos\r\n", eol="\n")  # se normaliza al escribir
    # Forzamos CRLF real en disco:
    fs.write_text("crlf.txt", "uno\ndos\n", eol="\r\n")
    changes = ChangeSet()
    changes.add(editor.plan_write("crlf.txt", "uno\nTRES\ndos\n"))
    report = editor.commit(changes)
    assert report.success
    raw = open(os.path.join(fs.guard.workspace, "crlf.txt"), "rb").read()
    assert raw == "uno\r\nTRES\r\ndos\r\n".encode("utf-8")


# ----------------------------------------------------------------------- edición
def test_edit_file_precise_replacement(sample):
    editor = sample["editor"]
    changes = ChangeSet()
    changes.add(editor.plan_edit("app.py", "    return a + b", "    return b + a"))
    report = editor.commit(changes)
    assert report.success and report.added == 1 and report.removed == 1
    nuevo = open(os.path.join(sample["workspace"], "app.py"), encoding="utf-8").read()
    # El cambio se aplica...
    assert "return b + a" in nuevo
    # ...y el contenido ajeno permanece intacto.
    assert "def resta(a, b):" in nuevo and '"""Suma dos números."""' in nuevo


def test_edit_file_block_not_found_raises_with_suggestion(sample):
    editor = sample["editor"]
    with pytest.raises(EditError) as info:
        # Bloque "desactualizado": el docstring real dice "Suma", no "Resta".
        editor.plan_edit(
            "app.py",
            'def suma(a, b):\n    """Resta dos números."""\n    return a + b',
            "def suma(a, b):\n    return a + b",
        )
    assert "Conflicto" in str(info.value)
    assert info.value.suggestion is not None
    assert "Suma dos números" in info.value.suggestion


def test_edit_file_multiple_matches_requires_context(sample):
    editor = sample["editor"]
    with pytest.raises(EditError, match="2 veces"):
        editor.plan_edit("app.py", "def ", "def funcion_")
    # Con replace_all sí se aplican todas.
    changes = ChangeSet()
    changes.add(editor.plan_edit("app.py", "def ", "def fn_", replace_all=True))
    report = editor.commit(changes)
    assert report.success
    contenido = open(os.path.join(sample["workspace"], "app.py"), encoding="utf-8").read()
    assert contenido.count("def fn_") == 2


def test_edit_binary_file_rejected(stack):
    editor = stack["editor"]
    with open(os.path.join(stack["workspace"], "datos.bin"), "wb") as fh:
        fh.write(bytes(range(256)))
    with pytest.raises(EditError, match="binario"):
        editor.plan_edit("datos.bin", "\x00\x01", "\x02")


def test_plan_write_binary_replaces_exact_bytes(stack):
    editor = stack["editor"]
    data = bytes(range(256)) * 4
    with open(os.path.join(stack["workspace"], "d.bin"), "wb") as fh:
        fh.write(b"antiguo")
    changes = ChangeSet()
    changes.add(editor.plan_write_binary("d.bin", data))
    report = editor.commit(changes)
    assert report.success
    with open(os.path.join(stack["workspace"], "d.bin"), "rb") as fh:
        assert fh.read() == data


# ------------------------------------------------------------- diffs del changeset
def test_changeset_diffs_and_summary(sample):
    editor = sample["editor"]
    changes = ChangeSet()
    changes.add(editor.plan_create("extra.md", "# Título\n"))
    changes.add(editor.plan_edit("app.py", "    return a - b", "    return a - b  # resta"))
    diffs = changes.diffs()
    assert len(diffs) == 2
    summary = changes.summary()
    assert summary["files"] == 2
    assert summary["created"] == 1 and summary["modified"] == 1
    assert summary["added"] >= 2


def test_changeset_same_path_last_wins(sample):
    editor = sample["editor"]
    changes = ChangeSet()
    changes.add(editor.plan_edit("app.py", "    return a + b", "    return 1"))
    changes.add(editor.plan_edit("app.py", "    return a - b", "    return 2"))
    # Segunda edición planificada sobre el resultado de la primera.
    assert len(changes) == 1
    report = editor.commit(changes)
    assert report.success


# --------------------------------------------------------------- transaccionalidad
def test_commit_failure_rolls_back_previous_files(sample):
    editor = sample["editor"]
    fs = sample["fs"]
    fs.write_text("otro.txt", "original")

    changes = ChangeSet()
    changes.add(editor.plan_write("otro.txt", "modificado"))
    # Cambio inválido a propósito: ruta fuera del workspace.
    bad = editor.plan_create("valido.txt", "ok")
    bad.path = bad.path.parent.parent / "escape.txt"   # fuerza fallo de PathGuard al escribir
    changes.changes.append(bad)

    report = editor.commit(changes)
    assert not report.success
    assert "otro.txt" in report.rolled_back
    # El primer archivo quedó como estaba: sin modificaciones parciales.
    assert fs.read("otro.txt").text == "original"


def test_backup_created_before_overwrite(sample):
    editor = sample["editor"]
    changes = ChangeSet()
    changes.add(editor.plan_write("app.py", "todo nuevo\n"))
    report = editor.commit(changes)
    assert report.success
    assert "app.py" in report.backups
    assert os.path.exists(report.backups["app.py"])


def test_undo_restores_last_backup(sample):
    editor = sample["editor"]
    changes = ChangeSet()
    changes.add(editor.plan_edit("app.py", "    return a + b", "    return 0"))
    editor.commit(changes)
    assert "return 0" in editor.fs.read("app.py").text
    message = editor.undo("app.py")
    assert "restaurado" in message
    assert editor.fs.read("app.py").text == PY_SAMPLE


def test_delete_is_recoverable_via_undo(sample):
    editor = sample["editor"]
    changes = ChangeSet()
    changes.add(editor.plan_delete("app.py"))
    report = editor.commit(changes)
    assert report.success
    assert not os.path.exists(os.path.join(sample["workspace"], "app.py"))
    # La copia del borrado permite restaurar (plan_delete hace backup antes
    # del commit porque change.existed=True).
    backups = editor.fs.list_backups("app.py")
    assert backups
    editor.fs.restore("app.py")
    assert editor.fs.read("app.py").text == PY_SAMPLE


def test_verify_after_write_detects_tampering(sample, monkeypatch):
    """Si la verificación post-escritura falla, el commit lo reporta."""
    editor = sample["editor"]
    original_write = editor.fs.write_atomic

    def sabotaged_write(path, data):
        result = original_write(path, data)
        # Simula un fallo externo que corrompe lo escrito justo después.
        with open(result, "wb") as fh:
            fh.write(b"contenido corrupto")
        return result

    monkeypatch.setattr(editor.fs, "write_atomic", sabotaged_write)
    changes = ChangeSet()
    changes.add(editor.plan_write("app.py", "esperado\n"))
    report = editor.commit(changes, verify=True)
    assert not report.success
    assert "Verificación fallida" in report.error


def test_undo_without_backup_fails(stack):
    editor = stack["editor"]
    stack["fs"].write_text("sin-copia.txt", "x")
    with pytest.raises(FileOpError):
        editor.undo("sin-copia.txt")
