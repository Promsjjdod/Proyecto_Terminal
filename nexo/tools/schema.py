"""Esquema de herramientas en formato OpenAI (tool calling nativo).

Genera el array ``tools`` a partir de TOOL_SPECS (una única fuente de verdad:
el catálogo real). Los tipos se derivan de las firmas declaradas y los
argumentos obligatorios están explícitos: el modelo no puede inventar
parámetros que la herramienta no valide.
"""
from __future__ import annotations

from typing import Any, Dict, List

from nexo.tools.catalog import TOOL_SPECS

# Tipo JSON de cada argumento por herramienta (derivado de la implementación).
_ARG_TYPES: Dict[str, Dict[str, str]] = {
    "read_file": {"path": "string", "offset": "integer", "limit": "integer"},
    "list_dir": {"path": "string"},
    "search": {"pattern": "string", "path": "string", "glob": "string"},
    "create_file": {"path": "string", "content": "string"},
    "write_file": {"path": "string", "content": "string"},
    "edit_file": {"path": "string", "old_block": "string", "new_block": "string",
                  "replace_all": "boolean"},
    "delete_file": {"path": "string"},
    "undo_file": {"path": "string"},
    "run_command": {"command": "string", "timeout": "number"},
    "export_file": {"path": "string", "destination": "string",
                    "on_exists": "string"},
    "ask_user": {"question": "string"},
    "finish": {"summary": "string", "success": "boolean"},
}

_REQUIRED: Dict[str, List[str]] = {
    "read_file": ["path"],
    "list_dir": [],
    "search": ["pattern"],
    "create_file": ["path", "content"],
    "write_file": ["path", "content"],
    "edit_file": ["path", "old_block", "new_block"],
    "delete_file": ["path"],
    "undo_file": ["path"],
    "run_command": ["command"],
    "export_file": ["path"],
    "ask_user": ["question"],
    "finish": ["summary"],
}


def openai_tools_schema() -> List[Dict[str, Any]]:
    """Array `tools` listo para enviar en el cuerpo de la petición."""
    tools: List[Dict[str, Any]] = []
    for spec in TOOL_SPECS:
        name = spec["name"]
        types = _ARG_TYPES.get(name, {})
        properties = {
            arg: {"type": types.get(arg, "string"), "description": desc}
            for arg, desc in spec["args"].items()
        }
        tools.append({
            "type": "function",
            "function": {
                "name": name,
                "description": spec["description"],
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": _REQUIRED.get(name, []),
                },
            },
        })
    return tools
