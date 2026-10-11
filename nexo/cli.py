"""Punto de entrada de NEXO TERMINAL.

Uso:
    nexo                 -> interfaz interactiva (REPL)
    nexo doctor          -> diagnóstico del entorno/configuración
    nexo version         -> versión
    nexo init-config [ruta]  -> escribe una configuración de ejemplo sin secretos
    nexo run "instrucción"   -> ejecución puntual no interactiva del agente
"""
from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from nexo import __app_name__, __version__


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nexo",
        description=f"{__app_name__} — agente de IA multimodelo para terminal (Termux/Android).",
    )
    parser.add_argument("--version", action="version", version=f"{__app_name__} {__version__}")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("repl", help="Interfaz interactiva (comportamiento por defecto).")
    sub.add_parser("doctor", help="Diagnosticar instalación, configuración y conectividad.")
    sub.add_parser("version", help="Mostrar la versión.")

    init = sub.add_parser("init-config", help="Escribir una configuración de ejemplo sin secretos.")
    init.add_argument("path", nargs="?", default="nexo.config.example.json",
                      help="Ruta destino (por defecto: ./nexo.config.example.json)")

    run = sub.add_parser("run", help="Ejecutar una instrucción del agente sin REPL.")
    run.add_argument("instruction", help="Instrucción en lenguaje natural.")
    run.add_argument("--workspace", default="", help="Workspace (por defecto: el configurado o cwd).")
    run.add_argument("--mode", default="", choices=["", "seguro", "autonomo", "estricto"],
                     help="Modo de permisos para esta ejecución.")
    return parser


def _cmd_doctor() -> int:
    from nexo.app import run_diagnostics
    from nexo.config.settings import load_config
    from nexo.memory.db import Memory
    from nexo.security.secrets import SecretStore
    from nexo.ui.render import UI
    from nexo.ui.theme import THEME, make_console

    config = load_config()
    config.ensure_dirs()
    ui = UI(make_console(config.ui))
    secrets = SecretStore(config.secrets_path)
    memory = Memory(config.db_path)
    try:
        report = run_diagnostics(config, secrets, memory)
    finally:
        memory.close()
    ui.panel("Diagnóstico de NEXO", "\n".join(report["lines"]),  # type: ignore[arg-type]
             style=THEME.success if report["ok"] else THEME.warning)
    return 0 if report["ok"] else 1


def _cmd_init_config(path: str) -> int:
    from nexo.config.settings import write_example_config

    written = write_example_config(path)
    print(f"Configuración de ejemplo (sin secretos) escrita en: {written}")
    print("Cópiala/adapta en ~/.nexo/config.json o usa `nexo` y el comando /provider add.")
    return 0


def _cmd_run(instruction: str, workspace: str, mode: str) -> int:
    from nexo.app import NexoApp
    from nexo.config.settings import load_config

    config = load_config()
    if workspace:
        config.workspace = workspace
    if mode:
        config.permission_mode = mode
    # Ejecución no interactiva: sin callback de pregunta, las operaciones que
    # requieran autorización se DENIEGAN (nunca se permiten en silencio).
    app = NexoApp(config=config, interactive=False)
    app.ui.stream_start()
    outcome = app.agent.run(instruction)
    app.ui.stream_end()
    if outcome.reply:
        app.ui.model_output(outcome.reply)
    app.ui.muted(f"[estado={outcome.status} iteraciones={outcome.iterations} "
                 f"{outcome.seconds:.1f}s]")
    app._shutdown()
    return 0 if outcome.success and outcome.status in ("conversacion", "terminada") else 1


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "doctor":
        return _cmd_doctor()
    if args.command == "version":
        print(f"{__app_name__} {__version__}")
        return 0
    if args.command == "init-config":
        return _cmd_init_config(args.path)
    if args.command == "run":
        return _cmd_run(args.instruction, args.workspace, args.mode)

    # Por defecto: REPL interactivo.
    from nexo.app import NexoApp
    from nexo.config.settings import load_config

    config = load_config()
    try:
        app = NexoApp(config=config)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        print("Corrige el workspace en ~/.nexo/config.json o ejecuta `nexo doctor`.",
              file=sys.stderr)
        return 1
    return app.run()


if __name__ == "__main__":
    raise SystemExit(main())
