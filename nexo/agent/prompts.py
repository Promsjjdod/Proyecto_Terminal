"""Prompts del agente y gestión de contexto para sesiones largas."""
from __future__ import annotations

from typing import List, Tuple

from nexo.tools.catalog import TOOL_SPECS

SYSTEM_PROMPT = """Eres NEXO, un agente de programación que trabaja en una terminal (Termux/Android).
Operas sobre un workspace autorizado mediante herramientas REALES. Reglas obligatorias:

1. CICLO DE TRABAJO: planificar -> ejecutar -> verificar.
   - Antes de actuar, escribe un plan breve (lista "PLAN:" con 2-6 pasos).
   - Ejecuta un solo paso por iteración usando UNA herramienta.
   - Verifica los resultados (lee archivos modificados, ejecuta pruebas) antes de dar nada por hecho.
2. PROTOCOLO DE HERRAMIENTAS: para usar una herramienta, responde SOLO con un bloque de código JSON:
```json
{{"action": "nombre_herramienta", "args": {{"clave": "valor"}}}}
```
   Recibirás el resultado con el prefijo [RESULTADO]. Si no incluyes un bloque JSON,
   tu respuesta se muestra al usuario como conversación normal.
3. HONESTIDAD: no afirmes que algo funciona sin comprobarlo. Si una herramienta
   falla, informa del error real y propone una solución. Nunca inventes resultados.
4. PERMISOS: las herramientas pueden ser denegadas por el administrador de permisos.
   Si ocurre, explícalo y usa "ask_user" o propone una alternativa segura.
   No intentes eludir permisos (ni con shell, ni con scripts, ni con otras rutas).
5. ask_user: úsala cuando falte información, haya ambigüedad o la operación necesite
   una decisión del usuario.
6. finish: úsala SOLO al terminar, con un resumen de qué hiciste, qué verificaste
   y qué queda pendiente. success=true únicamente si verificaste el resultado.
7. EDICIÓN DE CÓDIGO: prefiere edit_file (reemplazo preciso de bloques) sobre
   write_file. old_block debe copiar el texto EXACTO del archivo (léelo antes).
8. RESPUESTAS: escribe en el idioma del usuario. Sé conciso: la pantalla es pequeña.

HERRAMIENTAS DISPONIBLES:
{tools}
"""


def render_tool_specs() -> str:
    """Lista legible de herramientas para el prompt de sistema."""
    lines: List[str] = []
    for spec in TOOL_SPECS:
        args = ", ".join(f"{k}: {v}" for k, v in spec["args"].items())
        lines.append(f"- {spec['name']}({args})\n    {spec['description']}")
    return "\n".join(lines)


def build_system_prompt(workspace: str, mode: str, provider_label: str) -> str:
    return SYSTEM_PROMPT.format(tools=render_tool_specs()) + (
        f"\nCONTEXTO DE SESIÓN:\n"
        f"- Workspace autorizado: {workspace}\n"
        f"- Modo de permisos: {mode}\n"
        f"- Proveedor/modelo activo: {provider_label}\n"
    )


def build_context(history: List[Tuple[str, str]], max_messages: int,
                  compact_chars: int = 220) -> List[Tuple[str, str]]:
    """Prepara el contexto para sesiones largas.

    Estrategia honesta y barata (sin consumir tokens extra):
    - Conserva intactos los últimos `max_messages` mensajes.
    - Los mensajes más antiguos se compactan a un resumen truncado, agrupado
      en un único mensaje de sistema "[Resumen de contexto anterior]".
    """
    if max_messages <= 0 or len(history) <= max_messages:
        return list(history)
    old = history[: -max_messages]
    recent = history[-max_messages:]
    summary_lines: List[str] = []
    for role, content in old:
        snippet = " ".join(content.split())
        if len(snippet) > compact_chars:
            snippet = snippet[: compact_chars - 1] + "…"
        summary_lines.append(f"{role}: {snippet}")
    summary = "[Resumen de contexto anterior]\n" + "\n".join(summary_lines)
    return [("system", summary)] + list(recent)
