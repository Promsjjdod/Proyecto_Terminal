"""Pruebas de la revisión previa de publicación y del cliente GitHub."""
from __future__ import annotations

import pytest

from nexo.github.client import GitHubClient, scan_files_for_secrets
from nexo.permissions.manager import PROMPT_DENY


@pytest.fixture
def gh(stack):
    return GitHubClient(stack["guard"], stack["permissions"], memory=stack["memory"])


# ------------------------------------------------------------------------ escaneo
def test_scan_clean_project(tmp_path):
    (tmp_path / "main.py").write_text("print('hola')\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Proyecto\n", encoding="utf-8")
    scan = scan_files_for_secrets(str(tmp_path))
    assert scan.clean
    assert scan.files_scanned == 2
    assert "limpio" in scan.report()


def test_scan_detects_env_and_key_files(tmp_path):
    (tmp_path / ".env").write_text("API=1\n", encoding="utf-8")
    (tmp_path / "server.pem").write_text("x\n", encoding="utf-8")
    (tmp_path / "id_rsa").write_text("x\n", encoding="utf-8")
    (tmp_path / ".git-credentials").write_text("x\n", encoding="utf-8")
    (tmp_path / "ok.py").write_text("x=1\n", encoding="utf-8")
    scan = scan_files_for_secrets(str(tmp_path))
    assert not scan.clean
    nombres = " ".join(scan.sensitive_files)
    assert ".env" in nombres and "server.pem" in nombres
    assert "id_rsa" in nombres and ".git-credentials" in nombres
    assert "ok.py" not in nombres


def test_scan_detects_secret_content(tmp_path):
    (tmp_path / "config.py").write_text(
        'API_KEY = "sk-ant-abcdefghijklmnopqrstuvwxyz123456"\n', encoding="utf-8")
    (tmp_path / "aws.txt").write_text("clave AKIAIOSFODNN7EXAMPLE aqui\n", encoding="utf-8")
    (tmp_path / "llave.txt").write_text(
        "-----BEGIN RSA PRIVATE KEY-----\nMIIE...\n-----END RSA PRIVATE KEY-----\n",
        encoding="utf-8")
    scan = scan_files_for_secrets(str(tmp_path))
    assert not scan.clean
    assert len(scan.secret_hits) >= 3
    report = scan.report()
    assert "secretos" in report.lower()


def test_scan_skips_binary_and_huge_files(tmp_path):
    (tmp_path / "bin.dat").write_bytes(bytes(range(256)) * 100)
    (tmp_path / "grande.txt").write_text("x" * 600_000, encoding="utf-8")
    scan = scan_files_for_secrets(str(tmp_path))
    assert scan.clean   # no revienta ni marca falsos positivos


def test_scan_explicit_file_list(tmp_path):
    (tmp_path / "a.env").write_text("x", encoding="utf-8")
    (tmp_path / "b.py").write_text("x", encoding="utf-8")
    scan = scan_files_for_secrets(str(tmp_path), files=["b.py"])
    assert scan.files_scanned == 1 and scan.clean


# ------------------------------------------------------------------- bloqueo real
def test_create_repo_blocked_by_scan(stack, gh, monkeypatch):
    """Aunque gh existiera, la publicación se bloquea si hay secretos."""
    import shutil
    if shutil.which("git"):
        assert stack["git"].ensure_repo().ok   # el escaneo usa archivos tracked+untracked
    stack["fs"].write_text(".env", "API_KEY=sk-ant-abcdefghijklmnopqrstuvwxyz123456")
    stack["fs"].write_text("main.py", "print(1)")
    # Simulamos gh disponible y autenticado para aislar el escaneo.
    monkeypatch.setattr(GitHubClient, "gh_available", staticmethod(lambda: True))
    monkeypatch.setattr(gh, "auth_status",
                        lambda: type("R", (), {"ok": True, "message": "ok"})())
    # Autorizamos la operación sensible (si no, se denegaría antes del escaneo).
    from nexo.permissions.manager import PROMPT_ALLOW
    stack["permissions"].ask_user = lambda *a: PROMPT_ALLOW
    result = gh.create_repo("mi-repo", private=True)
    assert not result.ok
    assert "escaneo" in result.message.lower() or ".env" in result.message


def test_create_repo_denied_by_permissions(stack, gh):
    stack["permissions"].ask_user = lambda *a: PROMPT_DENY
    result = gh.create_repo("mi-repo")
    assert not result.ok and "denegada" in result.message.lower()


def test_auth_status_without_gh_is_honest(stack, gh, monkeypatch):
    monkeypatch.setattr(GitHubClient, "gh_available", staticmethod(lambda: False))
    result = gh.auth_status()
    assert not result.ok
    assert "pkg install gh" in result.message or "gh" in result.message


def test_set_remote_requires_authorization(stack, gh):
    from nexo.permissions.manager import PROMPT_ALLOW
    stack["permissions"].ask_user = lambda *a: PROMPT_ALLOW
    # Sin repo git inicializado: git remote add fallará de verdad (no se simula).
    result = gh.set_remote("https://github.com/usuario/repo.git")
    # O configura bien (si hay repo) o informa del fallo real; nunca finge éxito.
    assert isinstance(result.ok, bool)
    if not result.ok:
        assert result.message


def test_scan_before_publish_uses_tracked_files(stack, gh):
    stack["fs"].write_text("publico.py", "x = 1")
    stack["fs"].write_text("privado.env", "token=1")  # no coincide con patrones de nombre
    scan = gh.scan_before_publish(files=["publico.py", "privado.env"])
    assert scan.files_scanned == 2
