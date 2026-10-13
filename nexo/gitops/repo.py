"""Operaciones Git reales sobre el workspace.

Todas las operaciones de escritura pasan por el administrador de permisos
(usando la clasificación de comandos: `git push`/`reset` son peligrosos,
`git add`/`commit` modificadores). Git se invoca SIN shell (lista de
argumentos), dentro del workspace, y la salida se captura y limita.

NEXO no afirma tener credenciales ni control remoto: si git no está
autenticado o falta `git`, el error real se informa tal cual.
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from typing import List, Optional

from nexo.permissions.manager import PermissionManager
from nexo.permissions.paths import PathGuard


@dataclass
class GitResult:
    ok: bool
    command: str
    stdout: str = ""
    stderr: str = ""
    exit_code: Optional[int] = None
    denied: bool = False
    reason: str = ""

    def summary(self) -> str:
        head = f"$ git {self.command}"
        if self.denied:
            return f"{head}\nDENEGADO: {self.reason}"
        out = self.stdout.strip()
        err = self.stderr.strip()
        parts = [head, f"(código {self.exit_code})"]
        if out:
            parts.append(out)
        if err:
            parts.append("[stderr] " + err)
        return "\n".join(parts)


class GitRepo:
    """Fachada Git para el workspace autorizado."""

    MAX_OUTPUT = 100_000

    def __init__(self, guard: PathGuard, permissions: PermissionManager,
                 timeout: float = 60.0, memory=None):
        self.guard = guard
        self.permissions = permissions
        self.timeout = timeout
        self.memory = memory

    # ------------------------------------------------------------------- base
    @staticmethod
    def available() -> bool:
        return shutil.which("git") is not None

    def _run(self, args: List[str], needs_permission: bool = True) -> GitResult:
        cmd_str = " ".join(args)
        if not self.available():
            return GitResult(False, cmd_str, reason="git no está instalado o no está en PATH.",
                             denied=True)
        if needs_permission:
            decision, _ = self.permissions.check_command("git " + cmd_str)
            if not decision.allowed:
                return GitResult(False, cmd_str, denied=True, reason=decision.reason)
        try:
            proc = subprocess.run(
                ["git"] + args,
                cwd=str(self.guard.workspace),
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=self.timeout, stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired:
            return GitResult(False, cmd_str, stderr=f"Timeout tras {self.timeout}s.")
        except OSError as exc:
            return GitResult(False, cmd_str, stderr=f"No se pudo ejecutar git: {exc}")
        result = GitResult(proc.returncode == 0, cmd_str,
                           stdout=proc.stdout[: self.MAX_OUTPUT],
                           stderr=proc.stderr[: self.MAX_OUTPUT],
                           exit_code=proc.returncode)
        if self.memory and args:
            self.memory.log_operation("git", cmd_str[:200],
                                      f"exit={proc.returncode}", success=result.ok)
        return result

    # ------------------------------------------------------------- consultas
    def is_repo(self) -> bool:
        return (self.guard.workspace / ".git").exists() or self._run(
            ["rev-parse", "--git-dir"], needs_permission=False).ok

    def status(self, short: bool = True) -> GitResult:
        return self._run(["status", "--short" if short else "", "--branch"])

    def diff(self, staged: bool = False, path: Optional[str] = None) -> GitResult:
        args = ["diff", "--stat"]
        if staged:
            args.append("--staged")
        if path:
            args += ["--", path]
        return self._run(args, needs_permission=False)

    def log(self, n: int = 10) -> GitResult:
        return self._run(
            ["log", f"--max-count={max(1, min(n, 100))}",
             "--pretty=format:%h %ad %an %s", "--date=short"],
            needs_permission=False)

    def branches(self) -> GitResult:
        return self._run(["branch", "--all", "--verbose"], needs_permission=False)

    def current_branch(self) -> str:
        result = self._run(["rev-parse", "--abbrev-ref", "HEAD"], needs_permission=False)
        return result.stdout.strip() if result.ok else ""

    def remotes(self) -> GitResult:
        return self._run(["remote", "-v"], needs_permission=False)

    def ensure_repo(self) -> GitResult:
        """Inicializa el repositorio si aún no lo es."""
        if self.is_repo():
            return GitResult(True, "rev-parse", stdout="El workspace ya es un repositorio Git.")
        return self._run(["init", "-b", "main"])

    # ------------------------------------------------------------- modificaciones
    def create_branch(self, name: str, checkout: bool = True) -> GitResult:
        if not name or any(c in name for c in (" ", "~", "^", ":", "?", "*", "[", "\\")):
            return GitResult(False, f"branch {name}", denied=True,
                             reason="Nombre de rama inválido (caracteres no permitidos por Git).")
        if not checkout:
            return self._run(["branch", name])
        # `git switch -c` no puede descartar cambios locales (a diferencia de
        # `git checkout -b`), por eso es la vía preferida y no requiere
        # autorización de comando peligroso. Fallback para git antiguo.
        result = self._run(["switch", "-c", name])
        if not result.ok and not result.denied and "unknown" in (result.stderr or "").lower():
            result = self._run(["checkout", "-b", name])
        return result

    def add(self, paths: Optional[List[str]] = None) -> GitResult:
        args = ["add", "--"] + (paths if paths else ["."])
        return self._run(args)

    def commit(self, message: str) -> GitResult:
        if not message.strip():
            return GitResult(False, "commit", denied=True,
                             reason="El mensaje de commit no puede estar vacío.")
        return self._run(["commit", "-m", message.strip()])

    def clone(self, url: str, dest: str = ".") -> GitResult:
        """Clona un repositorio dentro del workspace (requiere autorización)."""
        if not (url.startswith("https://") or url.startswith("http://")
                or url.startswith("git@") or url.startswith("ssh://")):
            return GitResult(False, f"clone {url}", denied=True,
                             reason="URL de clonado inválida (usa https:// o git@...).")
        target = self.guard.resolve(dest) if dest != "." else self.guard.workspace / _repo_name(url)
        if target.exists() and any(target.iterdir()):
            return GitResult(False, f"clone {url}", denied=True,
                             reason=f"El destino ya existe y no está vacío: {target}")
        return self._run(["clone", "--", url, str(target)])

    def push(self, remote: str = "origin", branch: Optional[str] = None,
             set_upstream: bool = False) -> GitResult:
        """Publicar cambios: operación sensible (Git + red)."""
        args = ["push"]
        if set_upstream:
            args += ["--set-upstream"]
        args.append(remote)
        if branch:
            args.append(branch)
        result = self._run(args)
        if not result.ok and not result.denied and "authentication" in (result.stderr or "").lower():
            result.reason = ("Git no pudo autenticarse en el remoto. Configura credenciales "
                             "(p. ej. `gh auth login` o un helper de credenciales) y reintenta.")
        return result

    def pull(self, remote: str = "origin", branch: Optional[str] = None) -> GitResult:
        args = ["pull", remote]
        if branch:
            args.append(branch)
        return self._run(args)


def _repo_name(url: str) -> str:
    name = url.rstrip("/").rsplit("/", 1)[-1]
    if name.endswith(".git"):
        name = name[:-4]
    return name or "repositorio"
