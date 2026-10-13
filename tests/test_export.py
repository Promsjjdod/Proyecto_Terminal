"""Exportación a Descargas: autorización, sobrescrituras, verificación y errores."""
from __future__ import annotations

import os

import pytest

from nexo.permissions.manager import PROMPT_ALLOW, PROMPT_DENY, OperationKind
from nexo.permissions.paths import PathViolation
from nexo.tools.exporter import Exporter, resolve_destination, versioned_path


@pytest.fixture
def fake_storage(tmp_path, monkeypatch):
    """Simula ~/storage/downloads de Termux dentro de un home temporal."""
    home = tmp_path / "home"
    (home / "storage" / "downloads").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    return home / "storage" / "downloads"


@pytest.fixture
def exporter(stack):
    stack["permissions"].set_mode("autonomo")
    return Exporter(stack["guard"], stack["permissions"], memory=stack["memory"])


# -------------------------------------------------------------------- destinos
def test_resolve_destination_alias_termux(fake_storage):
    dest = resolve_destination("downloads")
    assert str(dest).endswith(os.path.join("storage", "downloads"))


def test_resolve_destination_alias_without_termux(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "sin-storage"))
    dest = resolve_destination("descargas")
    assert str(dest) == "/storage/emulated/0/Download"


def test_resolve_destination_explicit(tmp_path):
    dest = resolve_destination(str(tmp_path / "otra"))
    assert dest == tmp_path / "otra"


def test_versioned_path(tmp_path):
    target = tmp_path / "index.html"
    target.write_text("1", encoding="utf-8")
    v1 = versioned_path(target)
    assert v1.name == "index-1.html"
    v1.write_text("2", encoding="utf-8")
    assert versioned_path(target).name == "index-2.html"


# ------------------------------------------------------------------ flujo felice
def test_export_file_writes_and_verifies(stack, exporter, fake_storage):
    stack["fs"].write_text("pagina.html", "<h1>hola</h1>")
    stack["permissions"].ask_user = lambda *a: PROMPT_ALLOW
    result = exporter.export_file("pagina.html", destination="downloads")
    assert result.ok
    destino = fake_storage / "pagina.html"
    assert destino.exists() and destino.read_text(encoding="utf-8") == "<h1>hola</h1>"
    assert result.path == str(destino)
    assert "verificado" in result.message
    ops = stack["memory"].recent_operations(5)
    assert any(k == "export" and ok for _, k, _, _, ok in ops)


def test_export_requires_explicit_authorization(stack, exporter, fake_storage):
    """Exportar fuera del workspace es sensible: sin autorización no se escribe."""
    stack["fs"].write_text("secreto.txt", "x")
    stack["permissions"].ask_user = None        # sin interfaz -> deniega
    result = exporter.export_file("secreto.txt")
    assert not result.ok
    assert not (fake_storage / "secreto.txt").exists()
    assert "denegada" in result.message.lower() or "Denegada" in result.message


def test_export_denied_by_user(stack, exporter, fake_storage):
    stack["fs"].write_text("a.txt", "x")
    stack["permissions"].ask_user = lambda *a: PROMPT_DENY
    result = exporter.export_file("a.txt")
    assert not result.ok and not (fake_storage / "a.txt").exists()


def test_export_missing_storage_explains_termux(stack, exporter, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "sin"))
    monkeypatch.setattr(
        "nexo.tools.exporter.resolve_destination",
        lambda destination: tmp_path / "storage" / "Download",
    )
    stack["fs"].write_text("b.txt", "x")
    stack["permissions"].ask_user = lambda *a: PROMPT_ALLOW
    result = exporter.export_file("b.txt", destination="downloads")
    assert not result.ok
    assert "termux-setup-storage" in result.message
    assert "root" in result.message.lower()


# -------------------------------------------------------------- sobrescrituras
def test_export_existing_never_silent(stack, exporter, fake_storage):
    stack["fs"].write_text("c.txt", "nuevo")
    (fake_storage / "c.txt").write_text("viejo", encoding="utf-8")
    stack["permissions"].ask_user = lambda *a: PROMPT_ALLOW
    result = exporter.export_file("c.txt", on_exists="ask")
    assert result.needs_choice and not result.ok
    assert (fake_storage / "c.txt").read_text(encoding="utf-8") == "viejo"
    assert result.choices == ["replace", "version", "cancel"]


def test_export_replace_version_cancel(stack, exporter, fake_storage):
    stack["fs"].write_text("d.txt", "nuevo")
    (fake_storage / "d.txt").write_text("viejo", encoding="utf-8")
    stack["permissions"].ask_user = lambda *a: PROMPT_ALLOW

    cancel = exporter.export_file("d.txt", on_exists="cancel")
    assert not cancel.ok and (fake_storage / "d.txt").read_text() == "viejo"

    version = exporter.export_file("d.txt", on_exists="version")
    assert version.ok and version.path.endswith("d-1.txt")
    assert (fake_storage / "d.txt").read_text() == "viejo"

    replace = exporter.export_file("d.txt", on_exists="replace")
    assert replace.ok and (fake_storage / "d.txt").read_text() == "nuevo"


# --------------------------------------------------------------- contenido generado
def test_export_content_ok_and_empty_rejected(stack, exporter, fake_storage):
    stack["permissions"].ask_user = lambda *a: PROMPT_ALLOW
    result = exporter.export_content("<p>hola</p>", "salida.html")
    assert result.ok and (fake_storage / "salida.html").exists()

    vacio = exporter.export_content("   \n ", "vacio.txt")
    assert not vacio.ok and "vacío" in vacio.message
    assert not (fake_storage / "vacio.txt").exists()


def test_export_verify_detects_corruption(stack, exporter, fake_storage, monkeypatch):
    """Si la relectura no coincide, NUNCA se reporta como exportado."""
    stack["permissions"].ask_user = lambda *a: PROMPT_ALLOW
    monkeypatch.setattr(
        exporter, "_write_and_verify",
        lambda dest, data: "el contenido releído no coincide con el generado")
    result = exporter.export_content("datos", "roto.txt")
    assert not result.ok
    assert "no coincide" in result.message
    ops = stack["memory"].recent_operations(3)
    assert any(k == "export" and not ok for _, k, _, _, ok in ops)


# ------------------------------------------------------------------------ varios
def test_export_source_outside_workspace_blocked(stack, exporter):
    stack["permissions"].ask_user = lambda *a: PROMPT_ALLOW
    with pytest.raises(PathViolation):
        exporter.export_file("../../etc/passwd")


def test_export_directory_rejected(stack, exporter):
    (stack["guard"].workspace / "carpeta").mkdir()
    stack["permissions"].ask_user = lambda *a: PROMPT_ALLOW
    result = exporter.export_file("carpeta")
    assert not result.ok and "directorio" in result.message


def test_export_preview_marks_truncation():
    contenido = "\n".join(f"línea {i}" for i in range(30))
    preview = Exporter.preview_text(contenido, max_lines=5, max_width=20)
    assert "25 líneas más" in preview
    assert preview.count("\n") <= 6


def test_export_kind_is_sensitive():
    assert OperationKind.EXPORT_OUTSIDE in __import__(
        "nexo.permissions.manager", fromlist=["SENSITIVE_KINDS"]).SENSITIVE_KINDS
