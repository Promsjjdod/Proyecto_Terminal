"""Administrador de permisos de NEXO.

Tres modos de funcionamiento (configurables con `/permissions`):

- ``seguro``   : pide autorización para operaciones importantes (escrituras,
                 borrados, ejecución de comandos, git que publica...).
- ``autonomo`` : trabaja sin preguntar *dentro del workspace*, con límites
                 configurables; lo sensible sigue requiriendo autorización.
- ``estricto`` : pregunta antes de CADA escritura y CADA comando.

Las autorizaciones son específicas por (tipo de operación, objetivo) y
revocables: aprobar borrar ``a.txt`` no autoriza borrar ``b.txt`` ni ejecutar
comandos. Las aprobaciones duran solo la sesión en memoria (no se persisten).
"""
from __future__ import annotations

import shlex
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional, Tuple

from nexo.permissions.paths import PathGuard, PathViolation

# Respuestas posibles del callback de pregunta al usuario.
PROMPT_ASK = "ask"
PROMPT_ALLOW = "allow"            # permite esta operación concreta
PROMPT_ALLOW_SESSION = "session"  # permite operaciones iguales durante la sesión
PROMPT_DENY = "deny"


class OperationKind(str, Enum):
    READ_FILE = "leer_archivo"
    WRITE_FILE = "escribir_archivo"
    OVERWRITE_FILE = "sobrescribir_archivo"
    DELETE_FILE = "eliminar_archivo"
    EXEC_COMMAND = "ejecutar_comando"
    EXEC_DANGEROUS = "ejecutar_comando_peligroso"
    ACCESS_OUTSIDE_WORKSPACE = "acceso_fuera_del_workspace"
    ACCESS_CREDENTIALS = "acceso_credenciales"
    GIT_PUBLISH = "git_publicar"
    GIT_HISTORY = "git_historial"
    SYSTEM_CONFIG = "configuracion_sistema"


#: Operaciones siempre sensibles (nunca automáticas, ni en modo autónomo).
SENSITIVE_KINDS = frozenset(
    {
        OperationKind.DELETE_FILE,
        OperationKind.EXEC_DANGEROUS,
        OperationKind.ACCESS_OUTSIDE_WORKSPACE,
        OperationKind.ACCESS_CREDENTIALS,
        OperationKind.GIT_PUBLISH,
        OperationKind.GIT_HISTORY,
        OperationKind.SYSTEM_CONFIG,
    }
)

#: Comandos cuyo simple nombre ya se considera destructivo/peligroso.
DANGEROUS_COMMANDS = frozenset(
    {
        "rm", "rmdir", "mkfs", "dd", "shred", "chmod", "chown", "chroot",
        "kill", "killall", "pkill", "shutdown", "reboot", "halt", "poweroff",
        "fdisk", "parted", "mount", "umount", "sudo", "su", "doas",
        "curl", "wget",  # pueden descargar y ejecutar; se permiten si el usuario los autoriza
        "git",           # git se clasifica por subcomando (ver classify_command)
    }
)

GIT_DANGEROUS_SUBCOMMANDS = frozenset(
    {"push", "reset", "rebase", "clean", "checkout", "restore", "filter-branch", "gc", "prune"}
)
GIT_PUBLISH_SUBCOMMANDS = frozenset({"push", "publish"})


@dataclass
class CommandClassification:
    """Clasificación de un comando shell: informativo / modifica / peligroso."""

    level: str                 # "informativo" | "modificador" | "peligroso"
    kind: OperationKind        # EXEC_COMMAND o EXEC_DANGEROUS
    reason: str


MODIFYING_PATTERNS = (
    ">", ">>", "<", "|", "tee ", "sed -i", "install ", "mv ", "cp ", "mkdir ",
    "touch ", "git commit", "git add", "npm install", "pip install", "apt install", "pkg install",
)


def classify_command(command: str, allowed: List[str], denied: List[str]) -> CommandClassification:
    """Clasifica un comando sin ejecutarlo.

    Reglas:
    1. Lista de denegación del usuario -> peligroso siempre.
    2. ``rm -rf`` y variantes, escritura a dispositivos, forks de shell con
       pipes a intérpretes -> peligroso.
    3. Redirecciones / utilidades que modifican archivos -> modificador.
    4. Resto -> informativo (lectura).
    """
    cmd = command.strip()
    lowered = cmd.lower()

    if any(denied_pat and denied_pat in cmd for denied_pat in denied):
        return CommandClassification("peligroso", OperationKind.EXEC_DANGEROUS,
                                     "El comando coincide con la lista de denegación del usuario.")

    # Patrones claramente destructivos.
    destructive = [
        "rm -rf", "rm -fr", "rm -r ", "rm -f ", "mkfs", "dd if=", ":(){", "fork bomb",
        "> /dev/sd", "chmod -r 777", "shutdown", "reboot",
    ]
    for pat in destructive:
        if pat in lowered:
            return CommandClassification("peligroso", OperationKind.EXEC_DANGEROUS,
                                         f"El comando contiene un patrón destructivo ('{pat.strip()}').")
    # curl/wget piped a shell: ejecución remota ciega.
    if ("curl" in lowered or "wget" in lowered) and ("| sh" in lowered or "| bash" in lowered
                                                      or "|sh" in lowered or "|bash" in lowered):
        return CommandClassification("peligroso", OperationKind.EXEC_DANGEROUS,
                                     "Descarga y ejecución remota de scripts sin revisar.")

    try:
        tokens = shlex.split(cmd)
    except ValueError:
        tokens = cmd.split()
    head = tokens[0] if tokens else ""
    base = head.rsplit("/", 1)[-1]

    if base == "git" and len(tokens) > 1:
        sub = tokens[1].lstrip("-")
        if sub in GIT_PUBLISH_SUBCOMMANDS:
            return CommandClassification("peligroso", OperationKind.EXEC_DANGEROUS,
                                         "git push publica cambios en el remoto.")
        if sub in GIT_DANGEROUS_SUBCOMMANDS:
            return CommandClassification("peligroso", OperationKind.EXEC_DANGEROUS,
                                         f"git {sub} puede modificar o destruir el historial/árbol de trabajo.")

    if base in DANGEROUS_COMMANDS and not allowed:
        # Sin allowlist configurada, estos comandos se tratan como sensibles.
        if lowered.split() and base in ("rm", "kill", "killall", "pkill", "sudo", "su", "dd", "chmod", "chown"):
            return CommandClassification("peligroso", OperationKind.EXEC_DANGEROUS,
                                         f"'{base}' es un comando sensible del sistema.")

    if allowed and any(cmd.startswith(a) or base == a for a in allowed):
        # En allowlist explícita del usuario: se respeta su clasificación como no peligroso,
        # salvo patrones destructivos ya detectados arriba.
        return CommandClassification("modificador", OperationKind.EXEC_COMMAND,
                                     "Comando permitido explícitamente por el usuario.")

    for pat in MODIFYING_PATTERNS:
        if pat in lowered:
            return CommandClassification("modificador", OperationKind.EXEC_COMMAND,
                                         f"El comando puede modificar archivos ('{pat.strip()}').")

    return CommandClassification("informativo", OperationKind.EXEC_COMMAND,
                                 "El comando parece de solo lectura.")


@dataclass
class PermissionDecision:
    allowed: bool
    kind: OperationKind
    target: str
    reason: str
    asked_user: bool = False
    used_grant: bool = False


@dataclass
class _Grant:
    kind: OperationKind
    target: str            # clave exacta de aprobación (ruta, prefijo de comando...)
    created: float = field(default_factory=time.time)


AskUserFn = Callable[[OperationKind, str, str], str]
"""Firma: (tipo_operación, objetivo, motivo) -> PROMPT_ALLOW|PROMPT_ALLOW_SESSION|PROMPT_DENY."""


class PermissionManager:
    """Decide si una operación puede ejecutarse según modo, grants y sensibilidad."""

    def __init__(
        self,
        guard: PathGuard,
        mode: str = "seguro",
        ask_user: Optional[AskUserFn] = None,
        allowed_commands: Optional[List[str]] = None,
        denied_commands: Optional[List[str]] = None,
        autonomous_write_limit: int = 50,
    ):
        if mode not in ("seguro", "autonomo", "estricto"):
            raise ValueError(f"Modo de permisos inválido: {mode}")
        self.guard = guard
        self.mode = mode
        self.ask_user = ask_user
        self.allowed_commands = list(allowed_commands or [])
        self.denied_commands = list(denied_commands or [])
        self.autonomous_write_limit = autonomous_write_limit
        self._grants: Dict[Tuple[str, str], _Grant] = {}
        self.autonomous_writes_used = 0
        self.denials: List[PermissionDecision] = []

    # ------------------------------------------------------------- consultas
    @property
    def grants(self) -> List[Tuple[str, str]]:
        return sorted((g.kind.value, g.target) for g in self._grants.values())

    def set_mode(self, mode: str) -> None:
        if mode not in ("seguro", "autonomo", "estricto"):
            raise ValueError(f"Modo de permisos inválido: {mode}")
        self.mode = mode

    def grant(self, kind: OperationKind, target: str) -> None:
        self._grants[(kind.value, target)] = _Grant(kind=kind, target=target)

    def revoke(self, kind: OperationKind, target: str) -> bool:
        return self._grants.pop((kind.value, target), None) is not None

    def revoke_all(self) -> int:
        n = len(self._grants)
        self._grants.clear()
        return n

    # ------------------------------------------------------------- decisiones
    def check_path(self, path: str) -> PermissionDecision:
        """Verifica que una ruta de archivo está dentro del workspace."""
        try:
            self.guard.resolve(path)
        except PathViolation as exc:
            decision = PermissionDecision(
                allowed=False,
                kind=OperationKind.ACCESS_OUTSIDE_WORKSPACE,
                target=path,
                reason=str(exc),
            )
            self.denials.append(decision)
            return decision
        return self._evaluate(OperationKind.READ_FILE, path, f"Acceso a {path}")

    def check_write(self, path: str, overwrite: bool) -> PermissionDecision:
        kind = OperationKind.OVERWRITE_FILE if overwrite else OperationKind.WRITE_FILE
        try:
            self.guard.resolve(path)
        except PathViolation as exc:
            decision = PermissionDecision(False, OperationKind.ACCESS_OUTSIDE_WORKSPACE,
                                          path, str(exc))
            self.denials.append(decision)
            return decision
        action = "Sobrescribir" if overwrite else "Crear/escribir"
        return self._evaluate(kind, path, f"{action} archivo: {path}")

    def check_delete(self, path: str) -> PermissionDecision:
        try:
            self.guard.resolve(path)
        except PathViolation as exc:
            decision = PermissionDecision(False, OperationKind.ACCESS_OUTSIDE_WORKSPACE,
                                          path, str(exc))
            self.denials.append(decision)
            return decision
        return self._evaluate(OperationKind.DELETE_FILE, path, f"Eliminar archivo: {path}")

    def check_command(self, command: str) -> Tuple[PermissionDecision, CommandClassification]:
        classification = classify_command(command, self.allowed_commands, self.denied_commands)
        target = self._command_key(command)
        decision = self._evaluate(
            classification.kind,
            target,
            f"Ejecutar comando ({classification.level}): {command}",
            detail=classification.reason,
        )
        return decision, classification

    def check_sensitive(self, kind: OperationKind, target: str, reason: str) -> PermissionDecision:
        """Para operaciones sensibles genéricas (git publicar, credenciales, sistema)."""
        return self._evaluate(kind, target, reason)

    # -------------------------------------------------------------- interno
    def _command_key(self, command: str) -> str:
        """Clave de aprobación para comandos: el comando normalizado completo.

        Aprobar `ls -la` NO aprueba `ls -la /etc` (claves distintas).
        """
        return " ".join(shlex.split(command)) if command.strip() else command

    def _evaluate(self, kind: OperationKind, target: str, reason: str,
                  detail: str = "") -> PermissionDecision:
        grant_key = (kind.value, target)

        # 1) Grant específico existente -> permitido sin preguntar.
        if grant_key in self._grants:
            return PermissionDecision(True, kind, target,
                                      "Operación aprobada previamente en esta sesión.",
                                      used_grant=True)

        sensitive = kind in SENSITIVE_KINDS

        # 2) Modo estricto: todo lo que no sea lectura pregunta.
        if self.mode == "estricto" and kind != OperationKind.READ_FILE:
            return self._ask(kind, target, reason + (f" — {detail}" if detail else ""))

        # 3) Operaciones sensibles: SIEMPRE preguntan (incluso en autónomo).
        if sensitive:
            return self._ask(kind, target, reason + (f" — {detail}" if detail else ""))

        # 4) Modo autónomo: escrituras/comandos normales dentro del límite.
        if self.mode == "autonomo":
            if kind in (OperationKind.WRITE_FILE, OperationKind.OVERWRITE_FILE):
                if self.autonomous_writes_used >= self.autonomous_write_limit:
                    return self._ask(
                        kind, target,
                        reason + " — límite de escrituras autónomas alcanzado.",
                    )
                self.autonomous_writes_used += 1
            return PermissionDecision(True, kind, target,
                                      "Modo autónomo: operación dentro del workspace autorizada.")

        # 5) Modo seguro: lectura automática; escrituras/comandos preguntan.
        if kind == OperationKind.READ_FILE:
            return PermissionDecision(True, kind, target,
                                      "Modo seguro: lectura dentro del workspace permitida.")
        return self._ask(kind, target, reason + (f" — {detail}" if detail else ""))

    def _ask(self, kind: OperationKind, target: str, reason: str) -> PermissionDecision:
        if self.ask_user is None:
            # Sin interfaz de pregunta (p. ej. ejecución no interactiva): denegar
            # por seguridad en lugar de permitir en silencio.
            decision = PermissionDecision(False, kind, target,
                                          "No hay interfaz para solicitar autorización; se deniega por seguridad.")
            self.denials.append(decision)
            return decision
        answer = self.ask_user(kind, target, reason)
        if answer == PROMPT_ALLOW_SESSION:
            self.grant(kind, target)
            return PermissionDecision(True, kind, target, "Autorizada por el usuario para la sesión.",
                                      asked_user=True, used_grant=True)
        if answer == PROMPT_ALLOW:
            return PermissionDecision(True, kind, target, "Autorizada por el usuario (una vez).",
                                      asked_user=True)
        decision = PermissionDecision(False, kind, target,
                                      f"Denegada por el usuario. ({reason})",
                                      asked_user=True)
        self.denials.append(decision)
        return decision
