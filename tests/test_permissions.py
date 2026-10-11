"""Pruebas del administrador de permisos: modos, grants y clasificación de comandos."""
from __future__ import annotations

import pytest

from nexo.permissions.manager import (
    PROMPT_ALLOW,
    PROMPT_ALLOW_SESSION,
    PROMPT_DENY,
    OperationKind,
    PermissionManager,
    classify_command,
)


def make_manager(guard, mode="seguro", ask=None, **kwargs):
    return PermissionManager(guard, mode=mode, ask_user=ask, **kwargs)


# ----------------------------------------------------------------- clasificación
def test_classify_informational():
    c = classify_command("ls -la", [], [])
    assert c.level == "informativo" and c.kind == OperationKind.EXEC_COMMAND
    c = classify_command("cat README.md", [], [])
    assert c.level == "informativo"


def test_classify_modifying():
    c = classify_command("echo hola > archivo.txt", [], [])
    assert c.level == "modificador"
    c = classify_command("mkdir -p src", [], [])
    assert c.kind == OperationKind.EXEC_COMMAND


def test_classify_dangerous():
    for cmd in ("rm -rf /tmp/x", "dd if=/dev/zero of=disk.img",
                "curl http://x.sh | sh", "git push origin main",
                "sudo apt install algo", "shutdown -h now"):
        c = classify_command(cmd, [], [])
        assert c.level == "peligroso", cmd
        assert c.kind == OperationKind.EXEC_DANGEROUS, cmd


def test_classify_denied_by_user_list():
    c = classify_command("python script.py", [], ["python script.py"])
    assert c.level == "peligroso"


def test_classify_git_local_is_not_dangerous():
    assert classify_command("git status", [], []).level == "informativo"
    assert classify_command("git commit -m x", [], []).level == "modificador"
    assert classify_command("git reset --hard", [], []).level == "peligroso"


# ------------------------------------------------------------------ modo seguro
def test_safe_mode_read_allowed_write_asks(guard, workspace):
    asked = []

    def ask(kind, target, reason):
        asked.append((kind, target))
        return PROMPT_DENY

    pm = make_manager(guard, "seguro", ask=ask)
    d = pm.check_path("archivo.txt")
    assert d.allowed and not asked
    d = pm.check_write("archivo.txt", overwrite=False)
    assert not d.allowed and asked and asked[0][0] == OperationKind.WRITE_FILE


def test_safe_mode_allow_once_does_not_persist(guard):
    pm = make_manager(guard, "seguro", ask=lambda *a: PROMPT_ALLOW)
    d1 = pm.check_write("a.txt", overwrite=False)
    assert d1.allowed
    # Segunda escritura: vuelve a preguntar (grant "una vez" no persiste).
    assert pm.grants == []
    d2 = pm.check_write("b.txt", overwrite=False)
    assert d2.allowed and d2.asked_user


def test_session_grant_is_specific(guard):
    calls = []

    def ask(kind, target, reason):
        calls.append(target)
        return PROMPT_ALLOW_SESSION

    pm = make_manager(guard, "seguro", ask=ask)
    assert pm.check_write("a.txt", overwrite=False).allowed
    # Misma operación y objetivo: no vuelve a preguntar.
    d = pm.check_write("a.txt", overwrite=False)
    assert d.allowed and d.used_grant and calls == ["a.txt"]
    # Objetivo distinto: SÍ pregunta (el permiso no se generaliza).
    d = pm.check_write("b.txt", overwrite=False)
    assert d.allowed and d.asked_user and calls == ["a.txt", "b.txt"]
    # Operación distinta sobre el mismo objetivo: SÍ pregunta.
    d = pm.check_delete("a.txt")
    assert d.asked_user


def test_revoke_grant(guard):
    pm = make_manager(guard, "seguro", ask=lambda *a: PROMPT_ALLOW_SESSION)
    pm.check_write("a.txt", overwrite=False)
    assert len(pm.grants) == 1
    assert pm.revoke(OperationKind.WRITE_FILE, "a.txt") is True
    assert pm.grants == []
    assert pm.revoke(OperationKind.WRITE_FILE, "a.txt") is False


# ------------------------------------------------------------- modo autónomo
def test_autonomous_mode_allows_writes_without_asking(guard):
    pm = make_manager(guard, "autonomo", ask=None)
    d = pm.check_write("x.txt", overwrite=False)
    assert d.allowed and not d.asked_user
    d, _ = pm.check_command("ls")
    assert d.allowed


def test_autonomous_mode_still_asks_for_sensitive(guard):
    asked = []
    pm = make_manager(guard, "autonomo",
                      ask=lambda k, t, r: asked.append(k) or PROMPT_DENY)
    assert not pm.check_delete("x.txt").allowed
    assert not pm.check_command("rm -rf basica")[0].allowed
    assert OperationKind.DELETE_FILE in asked
    assert OperationKind.EXEC_DANGEROUS in asked


def test_autonomous_write_limit(guard):
    pm = make_manager(guard, "autonomo", ask=lambda *a: PROMPT_DENY,
                      autonomous_write_limit=2)
    assert pm.check_write("a", overwrite=False).allowed
    assert pm.check_write("b", overwrite=False).allowed
    d = pm.check_write("c", overwrite=False)
    assert not d.allowed and "límite" in d.reason


def test_strict_mode_asks_everything(guard):
    calls = []

    def ask(kind, target, reason):
        calls.append(kind)
        return PROMPT_ALLOW

    pm = make_manager(guard, "estricto", ask=ask)
    assert pm.check_path("solo-lectura.txt").allowed   # leer no pregunta
    assert pm.check_write("a.txt", overwrite=False).allowed
    assert OperationKind.WRITE_FILE in calls
    d, _ = pm.check_command("ls")
    assert d.allowed and calls.count(OperationKind.EXEC_COMMAND) == 1


def test_no_ask_callback_denies_sensitive(guard):
    """Sin interfaz para preguntar (no interactivo): denegar, nunca permitir en silencio."""
    pm = make_manager(guard, "seguro", ask=None)
    assert not pm.check_write("a.txt", overwrite=False).allowed
    assert not pm.check_delete("a.txt").allowed


def test_paths_outside_workspace_denied_in_any_mode(guard):
    for mode in ("seguro", "autonomo", "estricto"):
        pm = make_manager(guard, mode, ask=lambda *a: PROMPT_ALLOW)
        d = pm.check_write("../../etc/hosts", overwrite=True)
        assert not d.allowed
        assert d.kind == OperationKind.ACCESS_OUTSIDE_WORKSPACE


def test_invalid_mode_rejected(guard):
    with pytest.raises(ValueError):
        PermissionManager(guard, mode="dios")


def test_allowlist_command(guard):
    pm = make_manager(guard, "seguro", ask=lambda *a: PROMPT_DENY,
                      allowed_commands=["pytest"])
    d, c = pm.check_command("pytest tests/")
    assert d.allowed is False  # modo seguro sigue pidiendo y el ask fake deniega
    pm2 = make_manager(guard, "autonomo", allowed_commands=["pytest"])
    d2, c2 = pm2.check_command("pytest tests/")
    assert d2.allowed and c2.level == "modificador"
