"""Aplicación interactiva de NEXO: REPL con comandos y lenguaje natural.

Conecta todos los subsistemas: UI (Rich), entrada (prompt_toolkit),
proveedores, agente, editor con diff, permisos, ejecutor de comandos, Git,
GitHub y memoria SQLite.

Los comandos son reales: cada uno ejecuta su función (nada de placeholders).
El texto sin barra '/' se envía al agente como instrucción en lenguaje natural.
"""
from __future__ import annotations

import os
import shlex
import sys
import time
from typing import Callable, Dict, List, Optional

from nexo import __version__
from nexo.agent.loop import Agent, AgentOutcome
from nexo.config.settings import (
    VALID_PERMISSION_MODES,
    Config,
    ProviderConfig,
    load_config,
    save_config,
    write_example_config,
)
from nexo.editor.engine import ChangeSet, EditError, FileEditor
from nexo.filesystem.ops import FileOpError, FilesystemOps
from nexo.gitops.repo import GitRepo
from nexo.github.client import GitHubClient
from nexo.memory.db import Memory
from nexo.permissions.manager import (
    PROMPT_ALLOW,
    PROMPT_ALLOW_SESSION,
    PROMPT_DENY,
    OperationKind,
    PermissionManager,
)
from nexo.permissions.paths import PathGuard, PathViolation
from nexo.providers.base import ChatMessage, ProviderError
from nexo.providers.registry import PROVIDER_TYPES, ProviderRegistry
from nexo.security.secrets import SecretStore, mask_secret
from nexo.tools.catalog import ToolCatalog
from nexo.tools.executor import CommandExecutor
from nexo.ui.logo import SUBTITLE, TAGLINE, get_logo
from nexo.ui.render import UI
from nexo.ui.theme import THEME, make_console
from nexo.utils.log import setup_logging
from nexo.utils.platform import detect_platform

HELP_TEXT = """COMANDOS DE NEXO (escribe /help <comando> para detalle)

  /help [comando]          Muestra esta ayuda o el detalle de un comando.
  /chat [texto]            Conversa con el modelo (sin herramientas de agente).
  <texto sin barra>        Instrucción en lenguaje natural para el agente.
  /model [list|use|set]    Consultar y seleccionar modelos del proveedor activo.
  /provider ...            Administrar proveedores (list/add/edit/test/use/key/delete).
  /workspace [ruta]        Consultar o cambiar el directorio de trabajo.
  /files [ruta]            Explorar archivos del workspace.
  /create <ruta> [texto]   Crear un archivo nuevo.
  /edit <ruta>             Editar un archivo (bloque viejo -> bloque nuevo, con diff).
  /diff [completo]         Ver el diff de los cambios pendientes.
  /apply                   Aplicar los cambios pendientes revisados.
  /discard                 Descartar los cambios pendientes sin aplicar.
  /undo <ruta>             Revertir un archivo a su última copia de seguridad.
  /permissions ...         Consultar/cambiar modo y autorizaciones.
  /exec <comando>          Ejecutar un comando autorizado en el workspace.
  /git <subcomando>        status|diff|log|branches|branch|init|add|commit|clone|push.
  /github <subcomando>     status|scan|create|remote (usa la CLI oficial gh).
  /history ...             list|show|new|use|delete (conversaciones).
  /tasks ...               list|show|resume (tareas del agente).
  /config ...              show|set|path|example.
  /doctor                  Diagnosticar instalación, configuración y conectividad.
  /clear                   Limpiar la pantalla.
  /exit                    Salir de NEXO.
"""

COMMAND_HELP: Dict[str, str] = {
    "provider": "/provider list | add <nombre> <tipo> <url> <modelo> | edit <nombre> ... | "
                "test <nombre> | use <nombre> | key <nombre> | delkey <nombre> | delete <nombre>\n"
                f"Tipos disponibles: {', '.join(sorted(PROVIDER_TYPES))}. "
                "La clave se pide por entrada oculta y se guarda en secrets.json (0600).",
    "model": "/model            -> modelo actual del proveedor activo\n"
             "/model list       -> modelos disponibles (consulta REAL al proveedor)\n"
             "/model use <modelo> -> cambia el modelo del proveedor activo",
    "permissions": "/permissions                -> modo actual, grants y denegaciones recientes\n"
                   "/permissions mode <seguro|autonomo|estricto>\n"
                   "/permissions revoke <tipo> <objetivo>  /permissions reset",
    "git": "/git status | diff [--staged] | log [n] | branches | branch <nombre> | init | "
           "add [rutas] | commit <mensaje> | clone <url> | push [rama]",
    "github": "/github status          -> estado real de gh y autenticación\n"
              "/github scan            -> escaneo de secretos antes de publicar\n"
              "/github create <nombre> [--public] [--desc texto]  (privado por defecto)\n"
              "/github remote <url>",
    "history": "/history list | show <id> [n] | new [título] | use <id> | delete <id>",
    "tasks": "/tasks list | show <id> | resume <id> [instrucción adicional]",
    "config": "/config show | path | example <ruta> | set <clave> <valor>\n"
              "Claves editables: permission_mode, command_timeout, backups_enabled, "
              "ui.color, ui.animate, agent.max_iterations, agent.max_seconds.",
    "exec": "/exec <comando>  — el usuario autoriza implícitamente lo que teclea, "
            "salvo comandos clasificados como peligrosos (p. ej. rm -rf, git push), "
            "que requieren confirmación explícita según el modo.",
    "edit": "/edit <ruta>  — pide el bloque exacto a sustituir y el bloque nuevo "
            "(entrada multilínea; termina con una línea que solo contenga '.'). "
            "Genera un diff revisable; se aplica con /apply o se descarta con /discard.",
    "create": "/create <ruta> [contenido en una línea]  — sin contenido, pide texto "
              "multilínea (termina con '.' a solas).",
    "workspace": "/workspace          -> workspace actual\n/workspace <ruta>  -> cambiar (debe existir).",
}


def _parse_args(text: str) -> List[str]:
    """Divide una línea de comandos respetando comillas (tolerante a errores)."""
    try:
        return shlex.split(text)
    except ValueError:
        return text.split()


class NexoApp:
    """Aplicación principal de NEXO TERMINAL."""

    def __init__(self, config: Optional[Config] = None, force_terminal: Optional[bool] = None,
                 interactive: Optional[bool] = None):
        self.config = config or load_config()
        self.config.ensure_dirs()
        self.interactive = sys.stdin.isatty() if interactive is None else interactive
        self.ui = UI(make_console(self.config.ui, force_terminal=force_terminal),
                     animate=self.config.ui.animate)
        self.log = setup_logging(self.config.logs_dir)

        self.secrets = SecretStore(self.config.secrets_path)
        self.memory = Memory(self.config.db_path)
        self.registry = ProviderRegistry(self.config, self.secrets)

        workspace = self.config.workspace or os.getcwd()
        self._build_workspace(workspace)

        self.pending_changes: Optional[ChangeSet] = None
        self.conversation_id: Optional[int] = None
        self._session: object = None
        self._running = False

    # ------------------------------------------------------------------ montaje
    def _build_workspace(self, workspace: str) -> None:
        """(Re)construye los componentes ligados al workspace autorizado."""
        workspace = os.path.expanduser(workspace)
        if not os.path.isdir(workspace):
            raise FileNotFoundError(f"El workspace no existe o no es un directorio: {workspace}")
        self.config.workspace = os.path.abspath(workspace)
        self.guard = PathGuard(self.config.workspace)
        self.permissions = PermissionManager(
            self.guard,
            mode=self.config.permission_mode,
            ask_user=self._ask_permission if self.interactive else None,
            allowed_commands=self.config.allowed_commands,
            denied_commands=self.config.denied_commands,
        )
        self.fs = FilesystemOps(self.guard, self.config.backups_dir, self.config.backups_enabled)
        self.editor = FileEditor(self.fs, self.guard)
        self.executor = CommandExecutor(
            self.guard, self.permissions,
            default_timeout=self.config.command_timeout,
            max_output_chars=self.config.agent_limits.max_output_chars,
            memory=self.memory,
        )
        self.git = GitRepo(self.guard, self.permissions, timeout=self.config.command_timeout,
                           memory=self.memory)
        self.github = GitHubClient(self.guard, self.permissions, memory=self.memory)
        self.catalog = ToolCatalog(
            self.guard, self.fs, self.editor, self.executor, self.permissions,
            memory=self.memory, max_read_chars=self.config.agent_limits.max_file_read_chars,
        )
        self.agent = Agent(
            self.registry, self.catalog, self.memory, self.config.agent_limits,
            on_delta=self._on_model_delta, on_event=self._on_agent_event,
        )

    # ---------------------------------------------------------------- permisos UI
    def _ask_permission(self, kind: OperationKind, target: str, reason: str) -> str:
        """Pregunta al usuario por una operación sensible (callback de permisos)."""
        self.ui.separator()
        self.ui.panel(
            "AUTORIZACIÓN REQUERIDA",
            f"Operación : {kind.value}\nObjetivo  : {target}\nMotivo    : {reason}\n"
            f"Modo      : {self.permissions.mode}\n"
            f"Workspace : {self.guard.workspace}",
            style=THEME.warning,
        )
        answer = self._prompt(
            "[1] permitir una vez  [2] permitir iguales en sesión  [3] denegar  (3): ",
            choices={"1": PROMPT_ALLOW, "2": PROMPT_ALLOW_SESSION, "3": PROMPT_DENY},
            default=PROMPT_DENY,
        )
        self.log.info("permiso %s para %s (%s)", answer, target, kind.value)
        return answer

    # -------------------------------------------------------------------- entrada
    def _prompt(self, message: str, choices: Optional[Dict[str, str]] = None,
                default: str = "", password: bool = False, multiline: bool = False) -> str:
        """Lee entrada del usuario (prompt_toolkit si hay TTY; si no, input())."""
        if not self.interactive:
            try:
                line = sys.stdin.readline()
            except (OSError, ValueError) as exc:  # stdin capturado/cerrado (p. ej. pytest)
                raise EOFError(str(exc)) from exc
            if not line:
                raise EOFError
            answer = line.rstrip("\n")
        else:
            try:
                from prompt_toolkit import prompt as pt_prompt

                answer = pt_prompt(message, is_password=password, multiline=multiline)
            except (ImportError, OSError, EOFError):
                if password:  # sin prompt_toolkit: fallback sin eco
                    import getpass
                    answer = getpass.getpass(message)
                else:
                    answer = input(message)
        answer = (answer or "").strip()
        if choices:
            return choices.get(answer, default or answer)
        return answer

    def _prompt_multiline(self, message: str) -> str:
        """Entrada multilínea guiada: termina con una línea que solo contiene '.'."""
        self.ui.muted(message + " (termina con una línea que solo contenga '.')")
        if self.interactive:
            try:
                from prompt_toolkit import prompt as pt_prompt

                return pt_prompt("> ", multiline=True).rstrip()
            except (ImportError, OSError, EOFError):
                pass
        lines: List[str] = []
        while True:
            try:
                line = input()
            except EOFError:
                break
            if line.strip() == ".":
                break
            lines.append(line)
        return "\n".join(lines)

    # ------------------------------------------------------------------- eventos
    def _on_model_delta(self, delta: str) -> None:
        self.ui.stream_write(delta)

    def _on_agent_event(self, kind: str, message: str) -> None:
        if kind == "iteration":
            self.ui.muted(f"[{message}]")
        elif kind == "tool":
            self.ui.info(f"Herramienta: {message}")
        elif kind == "plan":
            self.ui.text(message, style=THEME.warning)
        if self.interactive:
            self.ui.stream_end()  # corta el streaming anterior antes del evento

    # ============================================================== ciclo principal
    def run(self) -> int:
        """Bucle interactivo principal. Devuelve código de salida."""
        self._running = True
        self._print_banner()
        self._print_status()
        while self._running:
            try:
                user_input = self._read_command_line()
            except (EOFError, KeyboardInterrupt):
                self.ui.text("")
                self.cmd_exit([])
                break
            if not user_input:
                continue
            try:
                self.dispatch(user_input)
            except PathViolation as exc:
                self.ui.error(str(exc))
            except (FileOpError, EditError, ProviderError) as exc:
                self.ui.error(str(exc))
            except KeyboardInterrupt:
                self.ui.warn("Interrumpido.")
            except Exception as exc:  # error inesperado: informado y registrado
                self.log.exception("Error no controlado")
                self.ui.error(f"Error interno: {type(exc).__name__}: {exc}")
        self._shutdown()
        return 0

    def _read_command_line(self) -> str:
        prompt_text = f"nexo:{os.path.basename(str(self.guard.workspace))}> "
        if not self.interactive:
            sys.stdout.write(prompt_text)
            sys.stdout.flush()
            line = sys.stdin.readline()
            if not line:
                raise EOFError
            return line.strip()
        from prompt_toolkit import PromptSession
        from prompt_toolkit.history import FileHistory
        from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
        from prompt_toolkit.formatted_text import HTML

        if self._session is None:
            history_file = os.path.join(self.config.config_dir, "input_history")
            self._session = PromptSession(
                history=FileHistory(history_file),
                auto_suggest=AutoSuggestFromHistory(),
                completer=_build_completer(),
                complete_while_typing=False,
            )
        styled = HTML(f"<ansibrightgreen>nexo</ansibrightgreen>"
                      f"<ansibrightblack>:</ansibrightblack>"
                      f"<ansicyan>{os.path.basename(str(self.guard.workspace))}</ansicyan>"
                      f"<ansibrightblack>&gt; </ansibrightblack>")
        return (self._session.prompt(styled) or "").strip()  # type: ignore[union-attr]

    def dispatch(self, line: str) -> None:
        """Ejecuta una línea: comando con '/' o instrucción natural."""
        if line.startswith("/"):
            parts = _parse_args(line)
            name = parts[0][1:].lower()
            args = parts[1:]
            handler: Optional[Callable[[List[str]], None]] = getattr(self, f"cmd_{name}", None)
            if handler is None:
                self.ui.error(f"Comando desconocido: /{name}. Usa /help.")
                return
            handler(args)
        else:
            self._run_agent_natural(line)

    def _shutdown(self) -> None:
        try:
            save_config(self.config)
        except OSError as exc:
            self.log.error("No se pudo guardar la configuración: %s", exc)
        self.memory.close()

    # ================================================================= comandos
    def cmd_help(self, args: List[str]) -> None:
        if args and args[0] in COMMAND_HELP:
            self.ui.panel(f"Ayuda: /{args[0]}", COMMAND_HELP[args[0]], style=THEME.info)
            return
        if args:
            self.ui.warn(f"No hay ayuda detallada de '/{args[0]}'. Ayuda general:")
        self.ui.panel("NEXO TERMINAL — Ayuda", HELP_TEXT.strip(), style=THEME.accent)

    def cmd_exit(self, args: List[str]) -> None:
        self.ui.success("Cerrando NEXO. Hasta pronto.")
        self._running = False

    def cmd_clear(self, args: List[str]) -> None:
        self.ui.clear()

    # -------------------------------------------------------------------- chat
    def cmd_chat(self, args: List[str]) -> None:
        text = " ".join(args).strip()
        if not text:
            if self.conversation_id:
                self.ui.info(f"Conversación activa: #{self.conversation_id}. Escribe texto "
                             "para continuarla o /history new para empezar otra.")
            else:
                self.conversation_id = self.memory.new_conversation(
                    "chat", self.config.active_provider, "")
                self.ui.success(f"Conversación #{self.conversation_id} iniciada. Escribe tu mensaje.")
            return
        try:
            provider = self.registry.get()
        except ProviderError as exc:
            self.ui.error(str(exc))
            return
        if self.conversation_id is None or not self.memory.conversation_exists(self.conversation_id):
            self.conversation_id = self.memory.new_conversation(
                text[:40], provider.name, provider.model)
        history = self.memory.get_messages(self.conversation_id,
                                           limit=self.config.history_limit)
        messages = [ChatMessage("system", "Eres NEXO, un asistente de terminal conciso y útil. "
                                          "Respondes en el idioma del usuario.")]
        messages += [ChatMessage(role, content) for role, content in history]
        messages.append(ChatMessage("user", text))
        self.memory.add_message(self.conversation_id, "user", text)
        self.ui.separator(f"{provider.name}/{provider.model}")
        self.ui.stream_start()
        try:
            reply = provider.complete(messages, on_delta=self._on_model_delta)
        except ProviderError as exc:
            self.ui.stream_end()
            self.ui.error(str(exc))
            return
        self.ui.stream_end()
        self.memory.add_message(self.conversation_id, "assistant", reply)

    # ------------------------------------------------------------------- modelos
    def cmd_model(self, args: List[str]) -> None:
        try:
            provider = self.registry.get()
        except ProviderError as exc:
            self.ui.error(str(exc))
            return
        sub = args[0].lower() if args else ""
        if sub == "":
            self.ui.info(f"Proveedor activo: {provider.name} | modelo: {provider.model or '(sin modelo)'}")
            return
        if sub == "list":
            with self.ui.spinner(f"Consultando modelos en {provider.name}…"):
                try:
                    models = provider.list_models()
                except ProviderError as exc:
                    self.ui.error(str(exc))
                    return
            if models:
                self.ui.kv(f"Modelos disponibles en {provider.name} ({len(models)})",
                           [("* " if m == provider.model else "  ") + m for m in models[:60]])
            else:
                self.ui.warn("El proveedor no devolvió modelos.")
            return
        if sub == "use" and len(args) >= 2:
            model = args[1]
            cfg = provider.config
            cfg.model = model
            save_config(self.config)
            self.ui.success(f"Modelo del proveedor '{cfg.name}' cambiado a '{model}'.")
            return
        self.ui.error("Uso: /model | /model list | /model use <modelo>")

    # --------------------------------------------------------------- proveedores
    def cmd_provider(self, args: List[str]) -> None:
        sub = args[0].lower() if args else "list"
        if sub == "list":
            if not self.config.providers:
                self.ui.warn("No hay proveedores configurados. Añade uno: /provider add "
                             "<nombre> <tipo> <url> <modelo>")
                return
            lines = []
            for cfg in self.config.providers:
                marker = "*" if cfg.name == self.config.active_provider else " "
                key = self.secrets.get(cfg.name)
                lines.append(f"{marker} {cfg.masked_summary(bool(key))}")
                lines.append(f"    timeout={cfg.timeout:.0f}s stream={'sí' if cfg.stream else 'no'} "
                             f"reintentos={cfg.retries} params={cfg.params or '{}'}")
                if key:
                    lines.append(f"    clave guardada: {mask_secret(key)}")
            self.ui.panel("Proveedores (* = activo)", "\n".join(lines), style=THEME.info)
            return
        if sub == "add" and len(args) >= 5:
            name, ptype, url, model = args[1], args[2].lower(), args[3], args[4]
            if ptype not in PROVIDER_TYPES:
                self.ui.error(f"Tipo desconocido '{ptype}'. Disponibles: {', '.join(sorted(PROVIDER_TYPES))}")
                return
            cfg = ProviderConfig(name=name, type=ptype, base_url=url, model=model)
            self.registry.add(cfg)
            save_config(self.config)
            self.ui.success(f"Proveedor '{name}' añadido{'; es el activo' if self.config.active_provider == name else ''}.")
            if cfg.type in ("openai", "anthropic", "custom"):
                self.ui.info("Si necesita API key: /provider key " + name)
            return
        if sub == "edit" and len(args) >= 2:
            cfg = self.config.get_provider(args[1])
            if cfg is None:
                self.ui.error(f"Proveedor '{args[1]}' no existe.")
                return
            pairs = args[2:]
            if not pairs:
                self.ui.info(cfg.masked_summary(bool(self.secrets.get(cfg.name))))
                return
            for pair in pairs:
                if "=" not in pair:
                    self.ui.error(f"Par inválido '{pair}'. Usa clave=valor "
                                  "(type, base_url, model, timeout, stream, retries).")
                    continue
                key, _, value = pair.partition("=")
                if key == "type" and value in PROVIDER_TYPES:
                    cfg.type = value
                elif key == "base_url":
                    cfg.base_url = value
                elif key == "model":
                    cfg.model = value
                elif key == "timeout":
                    cfg.timeout = float(value)
                elif key == "stream":
                    cfg.stream = value.lower() in ("1", "true", "si", "sí", "yes")
                elif key == "retries":
                    cfg.retries = int(value)
                else:
                    self.ui.warn(f"Campo no editable o valor inválido: {pair}")
            save_config(self.config)
            self.ui.success(f"Proveedor '{cfg.name}' actualizado.")
            return
        if sub == "key" and len(args) >= 2:
            name = args[1]
            if self.config.get_provider(name) is None:
                self.ui.error(f"Proveedor '{name}' no existe.")
                return
            try:
                value = self._prompt(f"API key para '{name}' (entrada oculta): ", password=True)
            except EOFError:
                return
            if not value:
                self.ui.warn("Entrada vacía; no se guardó nada.")
                return
            self.registry.set_key(name, value)
            self.ui.success(f"Clave guardada para '{name}' en {self.config.secrets_path} (0600).")
            return
        if sub == "delkey" and len(args) >= 2:
            removed = self.registry.delete_key(args[1])
            self.ui.success("Clave eliminada." if removed else "No había clave guardada para ese proveedor.")
            return
        if sub == "test" and len(args) >= 2:
            name = args[1]
            with self.ui.spinner(f"Probando conexión REAL con '{name}'…"):
                try:
                    result = self.registry.test(name)
                except ProviderError as exc:
                    self.ui.error(str(exc))
                    return
            if result.ok:
                self.ui.success(f"{result.message} (latencia {result.latency_ms:.0f} ms)")
                if result.models:
                    self.ui.info("Modelos: " + ", ".join(result.models[:10]) +
                                 ("…" if len(result.models) > 10 else ""))
            else:
                self.ui.error(result.message)
            return
        if sub == "use" and len(args) >= 2:
            try:
                self.registry.set_active(args[1])
            except ProviderError as exc:
                self.ui.error(str(exc))
                return
            save_config(self.config)
            cfg = self.config.get_provider(args[1])
            self.ui.success(f"Proveedor activo: {args[1]} (modelo {cfg.model if cfg else '?'}). "
                            "NEXO usará este modelo; no lo cambiará en silencio.")
            return
        if sub == "delete" and len(args) >= 2:
            name = args[1]
            if self.config.get_provider(name) is None:
                self.ui.error(f"Proveedor '{name}' no existe.")
                return
            try:
                answer = self._prompt(f"¿Eliminar proveedor '{name}' y su clave? [s/N]: ",
                                      choices={"s": "y", "S": "y"}, default="n")
            except EOFError:
                answer = "n"
            if answer != "y":
                self.ui.info("Cancelado.")
                return
            self.registry.remove(name)
            save_config(self.config)
            self.ui.success(f"Proveedor '{name}' eliminado.")
            return
        self.ui.error("Uso: /provider list|add|edit|test|use|key|delkey|delete … (/help provider)")

    # ------------------------------------------------------------------ workspace
    def cmd_workspace(self, args: List[str]) -> None:
        if not args:
            self.ui.info(f"Workspace autorizado: {self.guard.workspace}")
            self.ui.muted(f"Modo de permisos: {self.permissions.mode} | "
                          f"Git: {'repositorio' if self.git.is_repo() else 'sin repo'}")
            return
        new_path = " ".join(args)
        try:
            self._build_workspace(new_path)
        except FileNotFoundError as exc:
            self.ui.error(str(exc))
            return
        save_config(self.config)
        self.ui.success(f"Workspace cambiado a: {self.guard.workspace}")
        self.ui.warn("Los grants de sesión anteriores se descartaron (nuevo workspace).")

    # --------------------------------------------------------------------- files
    def cmd_files(self, args: List[str]) -> None:
        path = args[0] if args else "."
        try:
            entries, truncated = self.fs.list_dir(path)
        except (FileOpError, PathViolation) as exc:
            self.ui.error(str(exc))
            return
        self.ui.panel(f"Archivos en '{path}' ({len(entries)})", "\n".join(entries) or "(vacío)")
        if truncated:
            self.ui.warn("Lista truncada (hay más entradas).")

    # -------------------------------------------------------------------- create
    def cmd_create(self, args: List[str]) -> None:
        if not args:
            self.ui.error("Uso: /create <ruta> [contenido]")
            return
        path = args[0]
        content = " ".join(args[1:]) if len(args) > 1 else self._prompt_multiline("Contenido del archivo:")
        existed = self.fs.exists(path)
        decision = self.permissions.check_write(path, overwrite=existed)
        if not decision.allowed:
            self.ui.error(f"Permiso denegado: {decision.reason}")
            return
        try:
            changes = ChangeSet()
            if existed:
                changes.add(self.editor.plan_write(path, content))
            else:
                changes.add(self.editor.plan_create(path, content))
            self.pending_changes = changes
        except (EditError, PathViolation) as exc:
            self.ui.error(str(exc))
            return
        self.ui.render_diffs(changes.diffs(), changes.summary())
        self.ui.warn("Cambio pendiente: revisa el diff y aplica con /apply o descarta con /discard.")

    # ---------------------------------------------------------------------- edit
    def cmd_edit(self, args: List[str]) -> None:
        if not args:
            self.ui.error("Uso: /edit <ruta> — guía interactiva de reemplazo de bloque.")
            return
        path = args[0]
        try:
            fc = self.fs.read(path)
        except (FileOpError, PathViolation) as exc:
            self.ui.error(str(exc))
            return
        if fc.binary:
            self.ui.error("Archivo binario: la edición de texto no aplica (no se corromperá).")
            return
        decision = self.permissions.check_write(path, overwrite=True)
        if not decision.allowed:
            self.ui.error(f"Permiso denegado: {decision.reason}")
            return
        self.ui.info(f"Editando '{self.guard.rel(path)}' ({fc.line_count} líneas).")
        old_block = self._prompt_multiline("Bloque EXACTO a sustituir (copiar del archivo):")
        if not old_block:
            self.ui.warn("Bloque vacío; edición cancelada.")
            return
        new_block = self._prompt_multiline("Bloque nuevo:")
        try:
            change = self.editor.plan_edit(path, old_block, new_block)
        except EditError as exc:
            self.ui.error(str(exc))
            if exc.suggestion:
                self.ui.panel("Fragmento similar encontrado (amarillo = atención)",
                              exc.suggestion, style=THEME.warning)
            return
        self.pending_changes = ChangeSet()
        self.pending_changes.add(change)
        self.ui.render_diffs(self.pending_changes.diffs(), self.pending_changes.summary())
        self.ui.warn("Cambio pendiente: aplica con /apply o descarta con /discard.")

    # ---------------------------------------------------------------------- diff
    def cmd_diff(self, args: List[str]) -> None:
        full = bool(args) and args[0].lower() in ("completo", "full", "-f")
        if self.pending_changes:
            diffs = self.pending_changes.diffs(context=10**6 if full else 3)
            self.ui.render_diffs(diffs, self.pending_changes.summary())
            return
        # Sin cambios pendientes: diff de Git si hay repositorio.
        if self.git.is_repo():
            result = self.git.diff()
            if result.ok and result.stdout.strip():
                self.ui.panel("git diff (resumen)", result.stdout.strip())
            elif result.ok:
                self.ui.info("Sin diferencias en Git (working tree limpio).")
            else:
                self.ui.error(result.summary())
            return
        self.ui.info("No hay cambios pendientes. Usa /edit o /create para preparar cambios, "
                     "o /diff dentro de un repo Git.")

    # --------------------------------------------------------------------- apply
    def cmd_apply(self, args: List[str]) -> None:
        if not self.pending_changes:
            self.ui.warn("No hay cambios pendientes que aplicar.")
            return
        # Re-verificación de permisos en el momento de aplicar (las rutas pueden
        # haber cambiado de estado desde la planificación).
        for change in self.pending_changes.changes:
            if change.kind == "delete":
                decision = self.permissions.check_delete(change.rel)
            else:
                decision = self.permissions.check_write(change.rel, overwrite=change.existed)
            if not decision.allowed:
                self.ui.error(f"Permiso denegado al aplicar '{change.rel}': {decision.reason}")
                self.ui.warn("Cambios pendientes NO aplicados (siguen disponibles para /diff).")
                return
        report = self.editor.commit(self.pending_changes, verify=True)
        if report.success:
            for rel in report.applied:
                backup = report.backups.get(rel, "")
                self.memory.record_file_change(rel, "apply", backup)
            self.ui.success("Cambios aplicados y verificados.")
            self.ui.panel("Resultado", report.summary(), style=THEME.success)
            self.pending_changes = None
        else:
            self.ui.error("La aplicación FALLÓ; se revirtió todo (sin cambios parciales).")
            self.ui.panel("Detalle", report.summary(), style=THEME.error)

    def cmd_discard(self, args: List[str]) -> None:
        if not self.pending_changes:
            self.ui.warn("No hay cambios pendientes.")
            return
        n = len(self.pending_changes)
        self.pending_changes = None
        self.ui.success(f"{n} cambio(s) pendiente(s) descartado(s). No se tocó ningún archivo.")

    # ---------------------------------------------------------------------- undo
    def cmd_undo(self, args: List[str]) -> None:
        if not args:
            self.ui.error("Uso: /undo <ruta>  (restaura la última copia de seguridad)")
            return
        path = args[0]
        backups = self.editor.list_backups(path)
        if not backups:
            self.ui.warn(f"No hay copias de seguridad para '{path}'.")
            return
        decision = self.permissions.check_write(path, overwrite=True)
        if not decision.allowed:
            self.ui.error(f"Permiso denegado: {decision.reason}")
            return
        try:
            message = self.editor.undo(path)
        except FileOpError as exc:
            self.ui.error(str(exc))
            return
        self.memory.record_file_change(path, "undo", backups[-1])
        self.ui.success(message)

    # --------------------------------------------------------------- permissions
    def cmd_permissions(self, args: List[str]) -> None:
        sub = args[0].lower() if args else ""
        if sub == "mode" and len(args) >= 2:
            mode = args[1].lower()
            if mode not in VALID_PERMISSION_MODES:
                self.ui.error(f"Modo inválido '{mode}'. Usables: {', '.join(VALID_PERMISSION_MODES)}")
                return
            self.permissions.set_mode(mode)
            self.config.permission_mode = mode
            save_config(self.config)
            self.ui.success(f"Modo de permisos: {mode}.")
            return
        if sub == "revoke" and len(args) >= 3:
            try:
                kind = OperationKind(args[1])
            except ValueError:
                self.ui.error(f"Tipo de operación inválido: {args[1]}")
                return
            target = " ".join(args[2:])
            if self.permissions.revoke(kind, target):
                self.ui.success(f"Autorización revocada: {kind.value} -> {target}")
            else:
                self.ui.warn("No existía esa autorización.")
            return
        if sub == "reset":
            n = self.permissions.revoke_all()
            self.ui.success(f"{n} autorización(es) de sesión revocada(s).")
            return
        grants = self.permissions.grants
        lines = [
            f"Modo actual: {self.permissions.mode}",
            "  seguro   -> pide autorización para escrituras/comandos; sensible siempre pregunta",
            "  autonomo -> trabaja solo dentro del workspace (con límites); sensible pregunta",
            "  estricto -> pregunta antes de cada escritura y cada comando",
            f"Workspace: {self.guard.workspace}",
            f"Escrituras autónomas usadas: {self.permissions.autonomous_writes_used}"
            f"/{self.permissions.autonomous_write_limit}",
            f"Comandos permitidos (allowlist): {self.config.allowed_commands or '[]'}",
            f"Comandos denegados (blocklist): {self.config.denied_commands or '[]'}",
            "",
            f"Autorizaciones de sesión ({len(grants)}):",
        ]
        lines += [f"  - {kind} -> {target}" for kind, target in grants[:20]] or ["  (ninguna)"]
        if self.permissions.denials:
            lines.append("")
            lines.append("Últimas denegaciones:")
            for d in self.permissions.denials[-5:]:
                lines.append(f"  - {d.kind.value} {d.target}: {d.reason}")
        self.ui.panel("Permisos", "\n".join(lines), style=THEME.warning)

    # ---------------------------------------------------------------------- exec
    def cmd_exec(self, args: List[str]) -> None:
        if not args:
            self.ui.error("Uso: /exec <comando>")
            return
        command = " ".join(args)
        # Lo que el usuario teclea explícitamente queda autorizado por el propio
        # acto de teclearlo, SALVO comandos clasificados como peligrosos: esos
        # siguen el flujo normal de autorización del administrador de permisos.
        from nexo.permissions.manager import classify_command

        classification = classify_command(command, self.config.allowed_commands,
                                          self.config.denied_commands)
        temp_grant_key = ""
        if classification.level != "peligroso":
            temp_grant_key = " ".join(shlex.split(command))
            self.permissions.grant(classification.kind, temp_grant_key)
        self.ui.command_echo(command)
        result = self.executor.run(command)
        if temp_grant_key:
            self.permissions.revoke(classification.kind, temp_grant_key)
        if not result.authorized:
            self.ui.error(f"Comando no autorizado ({result.classification}): {result.denial_reason}")
            return
        style = THEME.success if result.ok else THEME.error
        body = result.summary(max_chars=8000)
        self.ui.panel(f"Salida (código {result.exit_code}, {result.duration_ms:.0f} ms"
                      f"{', TRUNCADA' if result.truncated else ''}"
                      f"{', TIMEOUT' if result.timed_out else ''})", body, style=style)

    # ----------------------------------------------------------------------- git
    def cmd_git(self, args: List[str]) -> None:
        if not args:
            self.ui.error(COMMAND_HELP["git"])
            return
        if not self.git.available():
            self.ui.error("git no está instalado. En Termux: `pkg install git`.")
            return
        sub = args[0].lower()
        result = None
        if sub == "status":
            result = self.git.status()
        elif sub == "diff":
            result = self.git.diff(staged="--staged" in args)
        elif sub == "log":
            n = 10
            if len(args) > 1 and args[1].isdigit():
                n = int(args[1])
            result = self.git.log(n)
        elif sub == "branches":
            result = self.git.branches()
        elif sub == "branch" and len(args) >= 2:
            result = self.git.create_branch(args[1])
        elif sub == "init":
            result = self.git.ensure_repo()
        elif sub == "add":
            result = self.git.add(args[1:] or None)
        elif sub == "commit" and len(args) >= 2:
            result = self.git.commit(" ".join(args[1:]))
        elif sub == "clone" and len(args) >= 2:
            result = self.git.clone(args[1], args[2] if len(args) > 2 else ".")
        elif sub == "push":
            branch = args[1] if len(args) >= 2 else None
            result = self.git.push(branch=branch, set_upstream=True)
        else:
            self.ui.error(COMMAND_HELP["git"])
            return
        if result.denied:
            self.ui.error(f"Operación Git denegada: {result.reason}")
        elif result.ok:
            self.ui.panel(f"git {result.command}", result.stdout.strip() or "(sin salida)")
        else:
            self.ui.error(f"git {result.command} falló (código {result.exit_code}).")
            if result.stderr.strip():
                self.ui.panel("stderr", result.stderr.strip(), style=THEME.error)
            if result.reason:
                self.ui.warn(result.reason)

    # -------------------------------------------------------------------- github
    def cmd_github(self, args: List[str]) -> None:
        sub = args[0].lower() if args else "status"
        if sub == "status":
            result = self.github.auth_status()
            (self.ui.success if result.ok else self.ui.warn)(result.message)
            return
        if sub == "scan":
            with self.ui.spinner("Escaneando archivos antes de publicar…"):
                scan = self.github.scan_before_publish()
            (self.ui.success if scan.clean else self.ui.warn)(scan.report())
            return
        if sub == "create" and len(args) >= 2:
            name = args[1]
            public = "--public" in args
            desc = ""
            if "--desc" in args:
                i = args.index("--desc")
                desc = " ".join(args[i + 1:])
            if public:
                try:
                    confirm = self._prompt("Vas a crear un repositorio PÚBLICO. ¿Confirmas? [s/N]: ",
                                           choices={"s": "y", "S": "y"}, default="n")
                except EOFError:
                    confirm = "n"
                if confirm != "y":
                    self.ui.info("Cancelado.")
                    return
            result = self.github.create_repo(name, private=not public, description=desc)
            (self.ui.success if result.ok else self.ui.error)(result.message)
            if result.url:
                self.ui.info(f"URL: {result.url}")
            return
        if sub == "remote" and len(args) >= 2:
            result = self.github.set_remote(args[1])
            (self.ui.success if result.ok else self.ui.error)(result.message)
            return
        self.ui.error(COMMAND_HELP["github"])

    # ------------------------------------------------------------------- history
    def cmd_history(self, args: List[str]) -> None:
        sub = args[0].lower() if args else "list"
        if sub == "list":
            rows = self.memory.list_conversations()
            if not rows:
                self.ui.info("No hay conversaciones guardadas.")
                return
            lines = []
            for cid, title, provider, model, count, updated in rows:
                marker = "*" if cid == self.conversation_id else " "
                lines.append(f"{marker} #{cid} [{count} msgs] {title or '(sin título)'} "
                             f"— {provider}/{model} — {time.strftime('%Y-%m-%d %H:%M', time.localtime(updated))}")
            self.ui.panel("Conversaciones (* = activa)", "\n".join(lines))
            return
        if sub == "new":
            title = " ".join(args[1:]) or "nueva conversación"
            self.conversation_id = self.memory.new_conversation(title)
            self.ui.success(f"Conversación #{self.conversation_id} creada y activa.")
            return
        if sub == "use" and len(args) >= 2 and args[1].isdigit():
            cid = int(args[1])
            if not self.memory.conversation_exists(cid):
                self.ui.error(f"La conversación #{cid} no existe.")
                return
            self.conversation_id = cid
            self.ui.success(f"Conversación activa: #{cid}")
            return
        if sub == "show" and len(args) >= 2 and args[1].isdigit():
            cid = int(args[1])
            limit = int(args[2]) if len(args) > 2 and args[2].isdigit() else 20
            if not self.memory.conversation_exists(cid):
                self.ui.error(f"La conversación #{cid} no existe.")
                return
            messages = self.memory.get_messages(cid, limit=limit)
            lines = [f"[{role}] {content[:300]}" for role, content in messages]
            self.ui.panel(f"Conversación #{cid} (últimos {len(messages)})", "\n".join(lines) or "(vacía)")
            return
        if sub == "delete" and len(args) >= 2 and args[1].isdigit():
            cid = int(args[1])
            if self.memory.delete_conversation(cid):
                if self.conversation_id == cid:
                    self.conversation_id = None
                self.ui.success(f"Conversación #{cid} eliminada.")
            else:
                self.ui.error(f"La conversación #{cid} no existe.")
            return
        self.ui.error(COMMAND_HELP["history"])

    # --------------------------------------------------------------------- tasks
    def cmd_tasks(self, args: List[str]) -> None:
        sub = args[0].lower() if args else "list"
        if sub == "list":
            tasks = self.memory.list_tasks(limit=20)
            if not tasks:
                self.ui.info("No hay tareas registradas.")
                return
            icon = {"completada": "✔", "fallida": "✖", "en_curso": "▶",
                    "interrumpida": "⏸", "pendiente": "·"}
            lines = [f"{icon.get(t.status, '?')} #{t.id} [{t.status}] {t.title[:60]} "
                     f"({t.iterations} it.)" for t in tasks]
            self.ui.panel("Tareas", "\n".join(lines))
            interrupted = [t for t in tasks if t.status in ("interrumpida", "en_curso", "pendiente")]
            if interrupted:
                self.ui.warn(f"{len(interrupted)} tarea(s) recuperables: /tasks resume <id>")
            return
        if sub == "show" and len(args) >= 2 and args[1].isdigit():
            task = self.memory.get_task(int(args[1]))
            if task is None:
                self.ui.error(f"La tarea #{args[1]} no existe.")
                return
            body = (f"Estado: {task.status}\nIteraciones: {task.iterations}\n"
                    f"Descripción: {task.description[:500]}\n"
                    f"Plan: {'; '.join(task.plan) or '(sin plan)'}\n"
                    f"Resultado: {task.result[:500] or '(ninguno)'}\n"
                    f"Error: {task.error[:300] or '(ninguno)'}")
            self.ui.panel(f"Tarea #{task.id}: {task.title}", body)
            return
        if sub == "resume" and len(args) >= 2 and args[1].isdigit():
            task_id = int(args[1])
            extra = " ".join(args[2:])
            self.ui.info(f"Reanudando tarea #{task_id} con el contexto guardado…")
            outcome = self.agent.resume(task_id, extra=extra)
            self._present_outcome(outcome)
            return
        self.ui.error(COMMAND_HELP["tasks"])

    # -------------------------------------------------------------------- config
    def cmd_config(self, args: List[str]) -> None:
        sub = args[0].lower() if args else "show"
        if sub == "show":
            data = self.config.to_dict()
            data.pop("providers", None)  # se muestra con /provider list
            lines = [f"{k}: {v}" for k, v in data.items()]
            self.ui.panel(f"Configuración ({self.config.config_path})", "\n".join(lines))
            return
        if sub == "path":
            self.ui.info(self.config.config_dir)
            return
        if sub == "example" and len(args) >= 2:
            path = write_example_config(args[1])
            self.ui.success(f"Configuración de ejemplo (sin secretos) escrita en: {path}")
            return
        if sub == "set" and len(args) >= 3:
            key, value = args[1], " ".join(args[2:])
            ok = self._config_set(key, value)
            if ok:
                save_config(self.config)
                self.ui.success(f"{key} = {value}")
            return
        self.ui.error(COMMAND_HELP["config"])

    def _config_set(self, key: str, value: str) -> bool:
        try:
            if key == "permission_mode":
                if value not in VALID_PERMISSION_MODES:
                    self.ui.error(f"Modo inválido. Usables: {', '.join(VALID_PERMISSION_MODES)}")
                    return False
                self.config.permission_mode = value
                self.permissions.set_mode(value)
            elif key == "command_timeout":
                self.config.command_timeout = float(value)
                self.executor.default_timeout = float(value)
            elif key == "backups_enabled":
                self.config.backups_enabled = value.lower() in ("1", "true", "si", "sí")
                self.fs.backups_enabled = self.config.backups_enabled
            elif key == "ui.color":
                self.config.ui.color = value.lower() in ("1", "true", "si", "sí")
                self.ui.console = make_console(self.config.ui)
            elif key == "ui.animate":
                self.config.ui.animate = value.lower() in ("1", "true", "si", "sí")
                self.ui.animate = self.config.ui.animate and self.ui.console.is_terminal
            elif key == "agent.max_iterations":
                self.config.agent_limits.max_iterations = max(1, int(value))
                self.agent.limits = self.config.agent_limits
            elif key == "agent.max_seconds":
                self.config.agent_limits.max_seconds = max(5.0, float(value))
                self.agent.limits = self.config.agent_limits
            elif key == "workspace":
                self._build_workspace(value)
            else:
                self.ui.error(f"Clave no editable: {key}. Ver /help config.")
                return False
            return True
        except (ValueError, FileNotFoundError) as exc:
            self.ui.error(f"Valor inválido para {key}: {exc}")
            return False

    # -------------------------------------------------------------------- doctor
    def cmd_doctor(self, args: List[str]) -> None:
        report = run_diagnostics(self.config, self.secrets, self.memory,
                                 workspace=str(self.guard.workspace))
        style = THEME.success if report["ok"] else THEME.warning
        self.ui.panel("Diagnóstico de NEXO", "\n".join(report["lines"]), style=style)

    # --------------------------------------------------------------------- agente
    def _run_agent_natural(self, text: str) -> None:
        """Instrucción en lenguaje natural -> ciclo completo del agente."""
        provider = self.registry.active()
        if provider is None:
            self.ui.error("No hay proveedor activo utilizable. Configura uno con "
                          "/provider add y selecciónalo con /provider use <nombre>.")
            return
        if self.conversation_id is None:
            self.conversation_id = self.memory.new_conversation(
                text[:40], provider.name, provider.model)
        self.ui.separator(f"agente · {provider.name}/{provider.model} · modo {self.permissions.mode}")
        self.ui.stream_start()
        outcome = self.agent.run(text, conversation_id=self.conversation_id)
        self.ui.stream_end()
        self._present_outcome(outcome)

    def _present_outcome(self, outcome: AgentOutcome) -> None:
        meta = (f"[{outcome.iterations} iteración(es), {outcome.seconds:.1f}s"
                f"{f', tarea #{outcome.task_id}' if outcome.task_id else ''}]")
        if outcome.status == "conversacion":
            # El texto ya se mostró por streaming; solo el meta.
            self.ui.muted(meta)
            return
        if outcome.status == "terminada":
            (self.ui.success if outcome.success else self.ui.warn)(
                ("Tarea terminada. " if outcome.success else "Tarea terminada con problemas. ") + meta)
            self.ui.panel("Resumen del agente", outcome.reply, style=THEME.success if outcome.success else THEME.warning)
            return
        if outcome.status == "necesita_usuario":
            if outcome.reply:
                self.ui.model_output(outcome.reply)
            self.ui.warn("El agente necesita tu input:")
            self.ui.panel("Pregunta", outcome.question, style=THEME.warning)
            try:
                answer = self._prompt_multiline("Tu respuesta:")
            except EOFError:
                return
            if answer:
                follow = self.agent.resume(outcome.task_id or 0,
                                           extra=f"Respuesta del usuario a tu pregunta: {answer}") \
                    if outcome.task_id else AgentOutcome("fallida", reply="Sin tarea que reanudar.", success=False)
                self._present_outcome(follow)
            return
        if outcome.status in ("limite_iteraciones", "limite_tiempo"):
            self.ui.warn(outcome.reply)
            return
        # fallida
        self.ui.error(f"La tarea falló: {outcome.reply}")

    # -------------------------------------------------------------------- banner
    def _print_banner(self) -> None:
        self.ui.banner(get_logo(self.ui.width), TAGLINE, SUBTITLE)
        self.ui.muted(f"NEXO v{__version__} — agente de IA para terminal (Termux/Android)")

    def _print_status(self) -> None:
        platform = detect_platform()
        provider = self.registry.active()
        provider_text = (f"{provider.name}/{provider.model or '?'}"
                         if provider else "SIN PROVEEDOR (usa /provider add)")
        lines = [
            f"Workspace : {self.guard.workspace}",
            f"Proveedor : {provider_text}",
            f"Permisos  : {self.permissions.mode}",
            f"Entorno   : {platform.describe()}",
        ]
        problems = self.config.validate()
        if problems:
            lines.append("Avisos    : " + "; ".join(problems))
        self.ui.panel("Estado", "\n".join(lines),
                      style=THEME.success if provider else THEME.warning)
        if not provider:
            self.ui.info("Escribe /help para ver los comandos.")


def _build_completer():
    """Autocompletado de comandos /… con prompt_toolkit."""
    try:
        from prompt_toolkit.completion import WordCompleter
    except ImportError:  # pragma: no cover
        return None
    commands = [
        "/help", "/chat", "/model", "/provider", "/workspace", "/files", "/create",
        "/edit", "/diff", "/apply", "/discard", "/undo", "/permissions", "/exec",
        "/git", "/github", "/history", "/tasks", "/config", "/doctor", "/clear", "/exit",
    ]
    words = commands + [
        "list", "add", "edit", "test", "use", "key", "delkey", "delete", "status",
        "diff", "log", "branches", "branch", "init", "commit", "clone", "push",
        "scan", "create", "remote", "show", "new", "resume", "mode", "revoke",
        "reset", "set", "path", "example", "completo", "--staged", "--public",
    ]
    return WordCompleter(words, sentence=True)


def run_diagnostics(config: Config, secrets: Optional[SecretStore] = None,
                    memory: Optional[Memory] = None, workspace: str = "") -> Dict[str, object]:
    """Diagnóstico real del entorno (usado por /doctor y `nexo doctor`)."""
    lines: List[str] = []
    ok = True

    def check(label: str, good: bool, detail: str, warn_only: bool = False) -> None:
        nonlocal ok
        icon = "✔" if good else ("⚠" if warn_only else "✖")
        if not good and not warn_only:
            ok = False
        lines.append(f"{icon} {label}: {detail}")

    platform = detect_platform()
    check("Entorno", True, platform.describe())
    check("Python", sys.version_info >= (3, 9), f"Python {platform.python_version} "
          f"({'compatible' if sys.version_info >= (3, 9) else 'se requiere >= 3.9'})")

    for module in ("rich", "prompt_toolkit", "httpx"):
        try:
            __import__(module)
            check(f"Dependencia {module}", True, "instalada")
        except ImportError:
            check(f"Dependencia {module}", False, "NO instalada (pip install -r requirements.txt)")

    problems = config.validate()
    check("Configuración", not problems,
          "válida" if not problems else "; ".join(problems))
    check("Archivo de configuración", os.path.exists(config.config_path),
          config.config_path + (" existe" if os.path.exists(config.config_path) else " (aún no creado)"),
          warn_only=True)

    if secrets is not None:
        check("Almacén de claves", secrets.is_valid(),
              f"{config.secrets_path} ({len(secrets.names())} clave(s))")
        mode = None
        if os.path.exists(config.secrets_path):
            mode = os.stat(config.secrets_path).st_mode & 0o777
        if mode is not None:
            check("Permisos del almacén", mode == 0o600,
                  oct(mode) + (" (correcto)" if mode == 0o600 else " — debería ser 0600"),
                  warn_only=mode == 0o600)

    ws = workspace or config.workspace or os.getcwd()
    ws_ok = os.path.isdir(ws)
    check("Workspace", ws_ok, ws + ("" if ws_ok else " — NO existe o no es directorio"))
    if ws_ok:
        writable = os.access(ws, os.W_OK)
        check("Escritura en workspace", writable,
              "sí" if writable else "SIN permiso de escritura (Android/Termux puede requerir "
                                     "`termux-setup-storage` o elegir otra carpeta)", warn_only=writable)

    check("git", platform.has_git, "disponible" if platform.has_git else
          "NO encontrado (en Termux: pkg install git)", warn_only=True)
    check("gh (GitHub CLI)", platform.has_gh, "disponible" if platform.has_gh else
          "NO encontrado (opcional; en Termux: pkg install gh)", warn_only=True)

    if memory is not None:
        stats = memory.stats()
        check("Base de datos", True,
              f"{stats.get('conversations', 0)} conversaciones, {stats.get('tasks', 0)} tareas, "
              f"{stats.get('operations', 0)} operaciones registradas")

    active = config.active_provider
    if active:
        cfg = config.get_provider(active)
        if cfg is None:
            check("Proveedor activo", False, f"'{active}' configurado como activo pero no existe")
        else:
            needs_key = cfg.type in ("anthropic",)
            has_key = bool(secrets and secrets.get(cfg.name))
            check("Proveedor activo", not (needs_key and not has_key),
                  f"{cfg.name} [{cfg.type}] modelo={cfg.model or '?'} clave={'sí' if has_key else 'no'}")
    else:
        check("Proveedor activo", False, "ninguno seleccionado (usa /provider add y /provider use)",
              warn_only=True)

    return {"ok": ok, "lines": lines}
