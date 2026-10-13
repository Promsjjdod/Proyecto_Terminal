"""Pruebas de protección de rutas: traversal, symlinks y límites del workspace."""
from __future__ import annotations

import os

import pytest

from nexo.permissions.paths import PathGuard, PathViolation


def test_relative_path_resolves_inside(workspace, guard):
    resolved = guard.resolve("proyecto/archivo.py")
    assert str(resolved).startswith(workspace)
    assert guard.is_inside(resolved)


def test_traversal_blocked(guard):
    with pytest.raises(PathViolation):
        guard.resolve("../../etc/passwd")
    with pytest.raises(PathViolation):
        guard.resolve("subdir/../../../etc/shadow")


def test_traversal_that_stays_inside_is_allowed(guard, workspace):
    os.makedirs(os.path.join(workspace, "a", "b"))
    resolved = guard.resolve("a/b/../c.txt")
    assert str(resolved) == os.path.join(workspace, "a", "c.txt")


def test_absolute_path_outside_blocked(guard):
    with pytest.raises(PathViolation):
        guard.resolve("/etc/passwd")


def test_absolute_path_inside_allowed(guard, workspace):
    resolved = guard.resolve(os.path.join(workspace, "ok.txt"))
    assert str(resolved) == os.path.join(workspace, "ok.txt")


def test_symlink_escape_blocked(guard, workspace, tmp_path):
    outside = tmp_path / "fuera"
    outside.mkdir()
    (outside / "secreto.txt").write_text("alto secreto", encoding="utf-8")
    link = os.path.join(workspace, "enlace")
    os.symlink(str(outside), link)
    with pytest.raises(PathViolation):
        guard.resolve("enlace/secreto.txt")
    with pytest.raises(PathViolation):
        guard.resolve("enlace")


def test_symlink_inside_is_allowed(guard, workspace):
    target = os.path.join(workspace, "real.txt")
    with open(target, "w", encoding="utf-8") as fh:
        fh.write("contenido")
    link = os.path.join(workspace, "alias.txt")
    os.symlink(target, link)
    resolved = guard.resolve("alias.txt")
    assert str(resolved) == os.path.realpath(target)


def test_empty_and_nul_paths_blocked(guard):
    with pytest.raises(PathViolation):
        guard.resolve("")
    with pytest.raises(PathViolation):
        guard.resolve("   ")
    with pytest.raises(PathViolation):
        guard.resolve("mal\x00.txt")


def test_must_exist(guard, workspace):
    with pytest.raises(PathViolation):
        guard.resolve("no-existe.txt", must_exist=True)
    open(os.path.join(workspace, "existe.txt"), "w").close()
    guard.resolve("existe.txt", must_exist=True)


def test_rel_presentation(guard, workspace):
    resolved = guard.resolve("carpeta/archivo.md")
    assert guard.rel(resolved) == os.path.join("carpeta", "archivo.md")


def test_workspace_with_symlink_root(tmp_path):
    real = tmp_path / "real-ws"
    real.mkdir()
    link = tmp_path / "link-ws"
    os.symlink(str(real), str(link))
    guard = PathGuard(str(link))
    # El workspace se resuelve físicamente; las rutas internas siguen siendo válidas.
    resolved = guard.resolve("archivo.txt")
    assert str(resolved).startswith(str(real))
