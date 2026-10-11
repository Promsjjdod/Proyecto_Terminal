"""Pruebas de la capa de archivos: atomicidad, copias, papelera, binarios y EOL."""
from __future__ import annotations

import os

import pytest

from nexo.filesystem.ops import FileOpError
from nexo.permissions.paths import PathViolation


def test_write_and_read_text(stack, workspace):
    fs = stack["fs"]
    fs.write_text("hola.txt", "línea 1\nlínea 2\n")
    fc = fs.read("hola.txt")
    assert fc.text == "línea 1\nlínea 2\n"
    assert fc.encoding == "utf-8" and fc.eol == "\n" and not fc.binary
    assert fc.line_count == 2


def test_atomic_write_leaves_no_temp_files(stack, workspace):
    fs = stack["fs"]
    fs.write_text("atomic.txt", "v1")
    leftovers = [n for n in os.listdir(workspace) if ".nexo-tmp-" in n]
    assert leftovers == []
    assert open(os.path.join(workspace, "atomic.txt"), encoding="utf-8").read() == "v1"


def test_write_creates_parent_dirs(stack):
    fs = stack["fs"]
    fs.write_text("a/b/c/deep.txt", "profundo")
    assert fs.read("a/b/c/deep.txt").text == "profundo"


def test_eol_preserved(stack):
    fs = stack["fs"]
    fs.write_text("crlf.txt", "uno\ndos\n", eol="\r\n")
    raw = open(os.path.join(fs.guard.workspace, "crlf.txt"), "rb").read()
    assert raw == b"uno\r\ndos\r\n"
    fc = fs.read("crlf.txt")
    assert fc.eol == "\r\n"
    assert fc.text == "uno\ndos\n"   # la lectura normaliza a \n


def test_encoding_latin1_fallback(stack):
    fs = stack["fs"]
    path = os.path.join(stack["workspace"], "latin.txt")
    with open(path, "wb") as fh:
        fh.write("caña".encode("latin-1"))
    fc = fs.read("latin.txt")
    assert not fc.binary
    assert fc.encoding == "latin-1"
    assert fc.text == "caña"


def test_binary_detection_and_no_corruption(stack):
    fs = stack["fs"]
    data = bytes(range(256)) * 10
    path = os.path.join(stack["workspace"], "img.bin")
    with open(path, "wb") as fh:
        fh.write(data)
    fc = fs.read("img.bin")
    assert fc.binary and fc.text is None
    # Escritura íntegra de bytes: sin corrupción.
    fs.write_atomic("img.bin", data + b"\x00\x01")
    assert open(path, "rb").read() == data + b"\x00\x01"


def test_backup_and_restore(stack):
    fs = stack["fs"]
    fs.write_text("doc.txt", "versión 1")
    backup = fs.backup("doc.txt")
    assert backup is not None and backup.exists()
    fs.write_text("doc.txt", "versión 2")
    assert fs.read("doc.txt").text == "versión 2"
    fs.restore("doc.txt")
    assert fs.read("doc.txt").text == "versión 1"


def test_restore_without_backup_fails(stack):
    fs = stack["fs"]
    fs.write_text("nuevo.txt", "x")
    with pytest.raises(FileOpError):
        fs.restore("nuevo.txt")


def test_backups_disabled(stack):
    fs = stack["fs"]
    fs.backups_enabled = False
    fs.write_text("a.txt", "x")
    assert fs.backup("a.txt") is None


def test_delete_goes_to_trash_and_is_recoverable(stack, workspace):
    fs = stack["fs"]
    fs.write_text("borrar.txt", "contenido importante")
    trash_path = fs.delete("borrar.txt")
    assert not os.path.exists(os.path.join(workspace, "borrar.txt"))
    assert trash_path.exists()
    # Recuperación manual desde la papelera (lo usa /undo tras borrados).
    with open(trash_path, "rb") as fh:
        data = fh.read()
    fs.write_atomic("borrar.txt", data)
    assert fs.read("borrar.txt").text == "contenido importante"


def test_read_outside_workspace_blocked(stack):
    fs = stack["fs"]
    with pytest.raises(PathViolation):
        fs.read("../../etc/passwd")
    with pytest.raises(PathViolation):
        fs.write_text("../fuga.txt", "x")


def test_list_dir(stack, workspace):
    fs = stack["fs"]
    fs.mkdir("carpeta")
    fs.write_text("carpeta/a.txt", "a")
    fs.write_text("b.txt", "b")
    entries, truncated = fs.list_dir(".")
    assert not truncated
    assert any(e.endswith("carpeta/") for e in entries)
    assert "b.txt" in entries


def test_list_dir_limit(stack):
    fs = stack["fs"]
    for i in range(12):
        fs.write_text(f"f{i:02d}.txt", "x")
    entries, truncated = fs.list_dir(".", limit=5)
    assert truncated and len(entries) == 5


def test_read_directory_raises(stack):
    fs = stack["fs"]
    fs.mkdir("dir")
    with pytest.raises(FileOpError):
        fs.read("dir")


def test_read_size_limit(stack):
    fs = stack["fs"]
    fs.write_text("grande.txt", "x" * 1000)
    with pytest.raises(FileOpError):
        fs.read("grande.txt", max_bytes=100)
