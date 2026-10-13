"""Ejecutor de comandos shell controlado.

Características:
- Autorización previa vía `PermissionManager` (clasificación informativo /
  modificador / peligroso; nunca ejecuta a ciegas lo que sugiere el modelo).
- Directorio de trabajo SIEMPRE dentro del workspace autorizado.
- Captura progresiva de stdout/stderr con límite de caracteres (evita
  saturar la memoria del teléfono).
- Tiempo máximo de ejecución y cancelación real del proceso y sus hijos
  (grupos de procesos con `start_new_session` + `killpg`).
- No bloquea la interfaz: la lectura de salida ocurre en un hilo separado.
"""
from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Callable, List, Optional

from nexo.permissions.manager import PermissionManager
from nexo.permissions.paths import PathGuard, PathViolation


@dataclass
class CommandResult:
    command: str
    exit_code: Optional[int] = None      # None si fue cancelado/timeout
    stdout: str = ""
    stderr: str = ""
    duration_ms: float = 0.0
    truncated: bool = False
    timed_out: bool = False
    cancelled: bool = False
    authorized: bool = True
    denial_reason: str = ""
    classification: str = ""             # informativo | modificador | peligroso
    cwd: str = ""

    @property
    def ok(self) -> bool:
        return self.authorized and self.exit_code == 0 and not self.timed_out

    def summary(self, max_chars: int = 4000) -> str:
        parts: List[str] = [f"$ {self.command}"]
        if not self.authorized:
            parts.append(f"DENEGADO: {self.denial_reason}")
            return "\n".join(parts)
        parts.append(f"(cwd={self.cwd}, código={self.exit_code}, "
                     f"{self.duration_ms:.0f} ms{', TRUNCADO' if self.truncated else ''}"
                     f"{', TIMEOUT' if self.timed_out else ''})")
        if self.stdout.strip():
            out = self.stdout.strip()
            parts.append("--- stdout ---\n" + (out[:max_chars] + "\n[…]" if len(out) > max_chars else out))
        if self.stderr.strip():
            err = self.stderr.strip()
            parts.append("--- stderr ---\n" + (err[:max_chars] + "\n[…]" if len(err) > max_chars else err))
        return "\n".join(parts)


class _StreamCapper:
    """Acumula la salida de un stream con límite total de caracteres."""

    def __init__(self, max_chars: int, on_chunk: Optional[Callable[[str], None]] = None):
        self.max_chars = max_chars
        self.on_chunk = on_chunk
        self._chunks: List[str] = []
        self._total = 0
        self.truncated = False
        self.lock = threading.Lock()

    def feed(self, data: str) -> None:
        with self.lock:
            if self._total >= self.max_chars:
                self.truncated = True
                return
            room = self.max_chars - self._total
            if len(data) > room:
                data = data[:room]
                self.truncated = True
            self._chunks.append(data)
            self._total += len(data)
        if self.on_chunk and not self.truncated:
            try:
                self.on_chunk(data)
            except Exception:  # pragma: no cover - la UI no debe romper la ejecución
                pass

    def text(self) -> str:
        with self.lock:
            return "".join(self._chunks)


class CommandExecutor:
    """Ejecuta comandos autorizados dentro del workspace."""

    def __init__(
        self,
        guard: PathGuard,
        permissions: PermissionManager,
        default_timeout: float = 60.0,
        max_output_chars: int = 200_000,
        memory=None,
    ):
        self.guard = guard
        self.permissions = permissions
        self.default_timeout = default_timeout
        self.max_output_chars = max_output_chars
        self.memory = memory
        self._cancel_events: dict[int, threading.Event] = {}

    def run(
        self,
        command: str,
        cwd: Optional[str] = None,
        timeout: Optional[float] = None,
        on_output: Optional[Callable[[str], None]] = None,
        bypass_ask: bool = False,
    ) -> CommandResult:
        """Ejecuta `command` con autorización, timeout y captura progresiva.

        `bypass_ask` solo tiene sentido cuando el usuario YA autorizó la
        operación de forma explícita e interactiva (p. ej. tecleó el comando
        con /exec): en ese caso se registra la autorización como concedida.
        """
        command = (command or "").strip()
        if not command:
            return CommandResult(command="", authorized=False,
                                 denial_reason="Comando vacío.")

        # 1) Resolución del directorio de trabajo (siempre dentro del workspace).
        try:
            work_dir = self.guard.resolve(cwd if cwd else ".")
        except PathViolation as exc:
            return CommandResult(command=command, authorized=False,
                                 denial_reason=str(exc))
        if not work_dir.is_dir():
            return CommandResult(command=command, authorized=False,
                                 denial_reason=f"El directorio de trabajo no existe: {work_dir}")

        # 2) Autorización.
        decision, classification = self.permissions.check_command(command)
        if not decision.allowed:
            result = CommandResult(command=command, authorized=False,
                                   denial_reason=decision.reason,
                                   classification=classification.level,
                                   cwd=str(work_dir))
            if self.memory:
                self.memory.log_operation("exec_denegado", command, decision.reason, success=False)
            return result

        # 3) Ejecución con captura progresiva y control de timeout.
        timeout_s = float(timeout if timeout is not None else self.default_timeout)
        env = dict(os.environ)
        env["NEXO_WORKSPACE"] = str(self.guard.workspace)

        start = time.monotonic()
        out_cap = _StreamCapper(self.max_output_chars, on_output)
        err_cap = _StreamCapper(self.max_output_chars // 2)
        timed_out = False
        cancelled = False
        exit_code: Optional[int] = None

        try:
            proc = subprocess.Popen(
                command,
                shell=True,
                executable="/bin/sh" if os.path.exists("/bin/sh") else None,
                cwd=str(work_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                start_new_session=True,   # grupo propio: permite matar hijos
            )
        except OSError as exc:
            return CommandResult(command=command, authorized=True, exit_code=-1,
                                 stderr=f"No se pudo iniciar el proceso: {exc}",
                                 classification=classification.level, cwd=str(work_dir))

        cancel_event = threading.Event()
        self._cancel_events[proc.pid] = cancel_event

        def _pump(stream, capper) -> None:
            try:
                for chunk in iter(lambda: stream.read(256), ""):
                    if not chunk:
                        break
                    capper.feed(chunk)
            except (ValueError, OSError):
                pass
            finally:
                try:
                    stream.close()
                except OSError:  # pragma: no cover
                    pass

        t_out = threading.Thread(target=_pump, args=(proc.stdout, out_cap), daemon=True)
        t_err = threading.Thread(target=_pump, args=(proc.stderr, err_cap), daemon=True)
        t_out.start()
        t_err.start()

        try:
            exit_code = proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            self._terminate_tree(proc)
            try:
                exit_code = proc.wait(timeout=5)
            except subprocess.TimeoutExpired:  # pragma: no cover
                exit_code = None
        finally:
            if cancel_event.is_set():
                cancelled = True
            t_out.join(timeout=2)
            t_err.join(timeout=2)
            self._cancel_events.pop(proc.pid, None)

        duration = (time.monotonic() - start) * 1000
        result = CommandResult(
            command=command,
            exit_code=exit_code,
            stdout=out_cap.text(),
            stderr=err_cap.text() + ("\n[timeout: el proceso superó "
                                      f"{timeout_s:.0f}s y fue terminado]" if timed_out else ""),
            duration_ms=duration,
            truncated=out_cap.truncated or err_cap.truncated,
            timed_out=timed_out,
            cancelled=cancelled,
            classification=classification.level,
            cwd=str(work_dir),
        )
        if self.memory:
            self.memory.log_operation(
                "exec", command,
                f"exit={exit_code} dur={duration:.0f}ms", success=result.ok,
            )
        return result

    def cancel(self, pid: Optional[int] = None) -> bool:
        """Cancela un proceso en marcha (o todos si no se indica pid)."""
        targets = ([pid] if pid is not None else list(self._cancel_events.keys()))
        did = False
        for target in targets:
            event = self._cancel_events.get(int(target))
            if event is not None:
                event.set()
                did = True
        return did

    def running_count(self) -> int:
        return len(self._cancel_events)

    @staticmethod
    def _terminate_tree(proc: subprocess.Popen) -> None:
        """Termina el proceso y su grupo (hijos incluidos)."""
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.terminate()
            except OSError:  # pragma: no cover
                pass
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    proc.kill()
                except OSError:  # pragma: no cover
                    pass
