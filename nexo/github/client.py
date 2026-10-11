"""Integración con GitHub mediante la CLI oficial `gh`.

Reglas de seguridad:
- NEXO NO pide ni almacena tokens de GitHub: la autenticación se delega en
  `gh auth login` (OAuth/device flow gestionado por la propia CLI).
- Antes de publicar se ejecuta un escaneo de archivos sensibles (.env,
  claves, credenciales, secretos en contenido) y se informa al usuario.
- Publicar (crear repo remoto, push) es operación sensible: siempre requiere
  autorización explícita según el modo de permisos.
- Si `gh` no está instalado o no hay sesión, se explica exactamente cómo
  completar la autorización (sin fingir éxito).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import List, Optional

from nexo.permissions.manager import OperationKind, PermissionManager
from nexo.permissions.paths import PathGuard

# Nombres de archivo que NUNCA deberían publicarse.
SENSITIVE_FILE_PATTERNS = [
    re.compile(r"(^|/)\.env(\..+)?$", re.IGNORECASE),
    re.compile(r"(^|/)secrets?\.(json|ya?ml|toml|txt)$", re.IGNORECASE),
    re.compile(r"(^|/)credentials?(\..+)?$", re.IGNORECASE),
    re.compile(r"\.(pem|key|p12|pfx|keystore|jks)$", re.IGNORECASE),
    re.compile(r"(^|/)id_(rsa|ed25519|ecdsa|dsa)(\.pub)?$", re.IGNORECASE),
    re.compile(r"(^|/)\.netrc$", re.IGNORECASE),
    re.compile(r"(^|/)\.git-credentials$", re.IGNORECASE),
    re.compile(r"(^|/)nexo/secrets\.json$|(^|/)\.nexo/", re.IGNORECASE),
    re.compile(r"(^|/).*token.*\.(json|txt|env)$", re.IGNORECASE),
]

# Patrones de contenido sospechoso (mismos que la redacción de logs).
SENSITIVE_CONTENT_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"),
]

MAX_SCAN_BYTES = 512_000


@dataclass
class PublishScan:
    """Resultado del escaneo previo a publicar."""

    files_scanned: int = 0
    sensitive_files: List[str] = field(default_factory=list)   # por nombre
    secret_hits: List[str] = field(default_factory=list)       # archivo:línea (motivo)

    @property
    def clean(self) -> bool:
        return not self.sensitive_files and not self.secret_hits

    def report(self) -> str:
        if self.clean:
            return f"Escaneo limpio: {self.files_scanned} archivo(s) revisados, sin secretos detectados."
        lines = [f"⚠ ESCANEO DE PUBLICACIÓN ({self.files_scanned} archivos revisados):"]
        if self.sensitive_files:
            lines.append("Archivos sensibles por nombre (NO publicar):")
            lines += [f"  - {f}" for f in self.sensitive_files[:30]]
        if self.secret_hits:
            lines.append("Posibles secretos en el contenido:")
            lines += [f"  - {h}" for h in self.secret_hits[:30]]
        lines.append("Corrige esto antes de publicar (elimina los archivos o añádelos a .gitignore).")
        return "\n".join(lines)


def scan_files_for_secrets(root: str | os.PathLike, files: Optional[List[str]] = None,
                           max_files: int = 2000) -> PublishScan:
    """Escanea archivos (por defecto todos bajo `root`) buscando secretos."""
    scan = PublishScan()
    if files is None:
        collected: List[str] = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d != ".git"]
            for name in filenames:
                collected.append(os.path.join(dirpath, name))
                if len(collected) >= max_files:
                    break
            if len(collected) >= max_files:
                break
        files = collected
    for path in files:
        rel = str(path)
        scan.files_scanned += 1
        for pattern in SENSITIVE_FILE_PATTERNS:
            if pattern.search(rel):
                scan.sensitive_files.append(rel)
                break
        full = path if os.path.isabs(path) else os.path.join(root, path)
        if not os.path.isfile(full):
            continue
        try:
            if os.path.getsize(full) > MAX_SCAN_BYTES:
                continue
            with open(full, "rb") as fh:
                raw = fh.read()
            if b"\x00" in raw[:4096]:
                continue
            text = raw.decode("utf-8", errors="ignore")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            for pattern in SENSITIVE_CONTENT_PATTERNS:
                if pattern.search(line):
                    scan.secret_hits.append(f"{rel}:{i} (coincide con patrón de secreto)")
                    break
            if len(scan.secret_hits) >= 50:
                break
    return scan


@dataclass
class GitHubResult:
    ok: bool
    message: str
    url: str = ""


class GitHubClient:
    """Operaciones con GitHub a través de `gh` (CLI oficial)."""

    def __init__(self, guard: PathGuard, permissions: PermissionManager,
                 timeout: float = 120.0, memory=None):
        self.guard = guard
        self.permissions = permissions
        self.timeout = timeout
        self.memory = memory

    # ------------------------------------------------------------ disponibilidad
    @staticmethod
    def gh_available() -> bool:
        return shutil.which("gh") is not None

    def auth_status(self) -> GitHubResult:
        """Estado REAL de la autenticación (sin simular)."""
        if not self.gh_available():
            return GitHubResult(
                False,
                "La CLI 'gh' no está instalada. En Termux: `pkg install gh` y luego "
                "`gh auth login`. Alternativa: usa git con credenciales HTTPS propias.",
            )
        proc = self._gh(["auth", "status"])
        if proc.returncode == 0:
            return GitHubResult(True, "Sesión de GitHub activa:\n" + (proc.stderr or proc.stdout).strip()[:600])
        return GitHubResult(
            False,
            "GitHub CLI no tiene sesión activa. Para autorizar:\n"
            "  1. `gh auth login`\n"
            "  2. Selecciona GitHub.com, HTTPS, y sigue el device flow en el navegador.\n"
            "Detalle del error:\n" + (proc.stderr or proc.stdout).strip()[:400],
        )

    # --------------------------------------------------------------- operaciones
    def scan_before_publish(self, files: Optional[List[str]] = None) -> PublishScan:
        """Escanea los archivos que se publicarían (por defecto, los tracked+staged)."""
        if files is None:
            files = self._tracked_and_untracked()
        return scan_files_for_secrets(str(self.guard.workspace), files)

    def _tracked_and_untracked(self) -> List[str]:
        proc = self._git(["ls-files", "--cached", "--others", "--exclude-standard"])
        if proc.returncode != 0:
            return []
        return [line for line in proc.stdout.splitlines() if line.strip()]

    def create_repo(self, name: str, private: bool = True,
                    description: str = "", source_push: bool = True) -> GitHubResult:
        """Crea el repositorio en GitHub y (opcionalmente) publica el workspace."""
        decision = self.permissions.check_sensitive(
            OperationKind.GIT_PUBLISH, f"github:create:{name}",
            f"Crear repositorio {'privado' if private else 'PÚBLICO'} '{name}' en GitHub y publicar el workspace.",
        )
        if not decision.allowed:
            return GitHubResult(False, f"Operación denegada: {decision.reason}")

        status = self.auth_status()
        if not status.ok:
            return GitHubResult(False, status.message)

        scan = self.scan_before_publish()
        if not scan.clean:
            return GitHubResult(False, "Publicación bloqueada por el escaneo de seguridad:\n"
                                       + scan.report())

        args = ["repo", "create", name, "--source=.", "--remote=origin"]
        if source_push:
            args.append("--push")
        args.append("--private" if private else "--public")
        if description:
            args += ["--description", description]
        proc = self._gh(args)
        if proc.returncode == 0:
            url = _extract_repo_url(proc.stdout + proc.stderr)
            if self.memory:
                self.memory.log_operation("github:create", name, url, success=True)
            return GitHubResult(True, f"Repositorio creado{' y publicado' if source_push else ''}: {name}",
                                url=url)
        return GitHubResult(False, "gh repo create falló:\n" + (proc.stderr or proc.stdout).strip()[:600])

    def set_remote(self, url: str, name: str = "origin") -> GitHubResult:
        decision = self.permissions.check_sensitive(
            OperationKind.GIT_PUBLISH, f"git:remote:{name}",
            f"Configurar remoto '{name}' -> {url} (prepara la publicación).",
        )
        if not decision.allowed:
            return GitHubResult(False, f"Operación denegada: {decision.reason}")
        proc = self._git(["remote", "remove", name])  # ok si no existe
        proc = self._git(["remote", "add", name, url])
        if proc.returncode == 0:
            return GitHubResult(True, f"Remoto '{name}' configurado: {url}", url=url)
        return GitHubResult(False, "No se pudo configurar el remoto:\n" + proc.stderr.strip()[:400])

    # ------------------------------------------------------------------ interno
    def _gh(self, args: List[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["gh"] + args, cwd=str(self.guard.workspace),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=self.timeout, stdin=subprocess.DEVNULL,
            env={**os.environ, "GH_PROMPT_DISABLED": "1"},
        )

    def _git(self, args: List[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git"] + args, cwd=str(self.guard.workspace),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=self.timeout, stdin=subprocess.DEVNULL,
        )


def _extract_repo_url(text: str) -> str:
    match = re.search(r"https://github\.com/[^\s'\"]+", text)
    return match.group(0) if match else ""
