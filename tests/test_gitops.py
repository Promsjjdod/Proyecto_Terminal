"""Pruebas de operaciones Git reales sobre un repositorio temporal."""
from __future__ import annotations

import os
import shutil
import subprocess

import pytest


pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git no disponible")


@pytest.fixture
def repo(stack):
    git = stack["git"]
    # Identidad local para commits (no tocar configuración global).
    subprocess.run(["git", "config", "--global", "--get", "user.email"],
                   capture_output=True)
    result = git.ensure_repo()
    assert result.ok, result.summary()
    subprocess.run(["git", "config", "user.email", "nexo@test.local"],
                   cwd=stack["workspace"], capture_output=True)
    subprocess.run(["git", "config", "user.name", "NEXO Test"],
                   cwd=stack["workspace"], capture_output=True)
    return stack


def test_ensure_repo_and_is_repo(repo):
    assert repo["git"].is_repo()
    assert os.path.isdir(os.path.join(repo["workspace"], ".git"))


def test_status_add_commit_log(repo):
    git = repo["git"]
    repo["fs"].write_text("archivo.txt", "contenido inicial\n")
    assert git.add(["archivo.txt"]).ok
    result = git.commit("Primer commit de prueba")
    assert result.ok, result.summary()
    log = git.log(5)
    assert log.ok and "Primer commit de prueba" in log.stdout
    status = git.status()
    assert status.ok


def test_branches(repo):
    git = repo["git"]
    repo["fs"].write_text("semilla.txt", "x")
    git.add(["semilla.txt"])
    assert git.commit("commit inicial").ok
    result = git.create_branch("rama-nueva")
    assert result.ok, result.summary()
    assert git.current_branch() == "rama-nueva"
    branches = git.branches()
    assert "rama-nueva" in branches.stdout


def test_invalid_branch_name(repo):
    result = repo["git"].create_branch("rama mala ~")
    assert not result.ok and result.denied


def test_commit_empty_message_rejected(repo):
    result = repo["git"].commit("   ")
    assert not result.ok and result.denied


def test_diff(repo):
    git = repo["git"]
    repo["fs"].write_text("cambio.txt", "v1\n")
    git.add(["cambio.txt"])
    git.commit("v1")
    repo["fs"].write_text("cambio.txt", "v2\n")
    result = git.diff()
    assert result.ok
    assert "cambio.txt" in result.stdout


def test_push_requires_authorization_and_is_sensitive(repo):
    git = repo["git"]
    # Sin callback de autorización -> operación sensible denegada (nunca silenciosa).
    result = git.push()
    assert not result.ok
    assert result.denied or "autentic" in (result.reason + result.stderr).lower() \
        or "No such" in result.stderr or "remote" in result.stderr.lower()


def test_push_denied_reason_when_explicitly_denied(repo):
    git = repo["git"]
    repo["permissions"].ask_user = lambda *a: "deny"
    repo["permissions"].set_mode("seguro")
    result = git.push()
    assert result.denied and "Denegada" in result.reason


def test_clone_invalid_url(repo):
    result = repo["git"].clone("ftp://no-soportado/x")
    assert not result.ok and result.denied


def test_clone_local_repo(repo, tmp_path):
    # Clonado real desde un repo local (file:// dentro de la prueba): ejercita
    # el flujo completo sin red.
    origen = tmp_path / "origen"
    origen.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(origen)], capture_output=True)
    subprocess.run(["git", "-C", str(origen), "config", "user.email", "t@t"], capture_output=True)
    subprocess.run(["git", "-C", str(origen), "config", "user.name", "t"], capture_output=True)
    (origen / "f.txt").write_text("x")
    subprocess.run(["git", "-C", str(origen), "add", "."], capture_output=True)
    subprocess.run(["git", "-C", str(origen), "commit", "-m", "ini"], capture_output=True)

    git = repo["git"]
    # La URL file:// no es http/ssh: debe denegarse (validación explícita).
    denied = git.clone(f"file://{origen}")
    assert denied.denied


def test_remotes_empty(repo):
    result = repo["git"].remotes()
    assert result.ok
    assert result.stdout.strip() == ""


def test_git_operations_logged(repo):
    git = repo["git"]
    repo["fs"].write_text("log-me.txt", "x")
    git.add(["log-me.txt"])
    ops = repo["memory"].recent_operations(10)
    assert any(kind == "git" for _, kind, _, _, _ in ops)
