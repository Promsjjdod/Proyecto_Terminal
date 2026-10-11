"""Ciclo del agente: controlado, con límites de iteraciones y tiempo.

Fases diferenciadas:
- PLANIFICAR: se extrae el bloque "PLAN:" de la primera respuesta y se guarda
  en la tarea (recuperable con /tasks).
- EJECUTAR: cada llamada a herramienta es un paso; los resultados vuelven al
  modelo como mensajes [RESULTADO].
- VERIFICAR: las escrituras se verifican en el propio commit (relectura) y el
  sistema exige al modelo comprobar antes de usar finish(success=true).

El ciclo detecta: necesidad de información del usuario (ask_user), fallos de
herramienta/proveedor, respuesta sin acción (conversación normal) y límites
(iteraciones/tiempo). Nunca afirma éxito sin verificación.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from nexo.agent.prompts import build_context, build_system_prompt
from nexo.config.settings import AgentLimits
from nexo.memory.db import Memory
from nexo.providers.base import ChatMessage, ProviderError
from nexo.providers.registry import ProviderRegistry
from nexo.tools.catalog import TOOL_NAMES, ToolCatalog, ToolResult

_JSON_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_JSON_DECODER = json.JSONDecoder()


def parse_tool_call(text: str) -> Optional[Tuple[str, Dict]]:
    """Extrae la primera llamada a herramienta válida del texto del modelo.

    Acepta un bloque ```json ...``` o un objeto JSON suelto con clave "action"
    (incluso con objetos anidados). Devuelve None si no hay llamada
    (respuesta conversacional).
    """
    candidates: List[str] = list(_JSON_FENCE.findall(text))
    if not candidates:
        # Escaneo de objetos JSON crudos con el decodificador incremental:
        # soporta anidación ("args": {...}) que una regex simple no cubre.
        idx = 0
        while True:
            pos = text.find("{", idx)
            if pos < 0:
                break
            try:
                obj, end = _JSON_DECODER.raw_decode(text, pos)
            except ValueError:
                idx = pos + 1
                continue
            if isinstance(obj, dict):
                candidates.append(text[pos:end])
            idx = max(end, pos + 1)
    for raw in candidates:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and isinstance(data.get("action"), str):
            args = data.get("args")
            if args is None:
                args = {}
            if not isinstance(args, dict):
                args = {"_invalid": args}
            return data["action"].strip(), args
    return None


@dataclass
class AgentOutcome:
    status: str                    # conversacion | terminada | necesita_usuario | fallida | limite_iteraciones | limite_tiempo
    reply: str = ""                # texto final para el usuario
    question: str = ""             # si necesita_usuario
    plan: List[str] = field(default_factory=list)
    iterations: int = 0
    seconds: float = 0.0
    task_id: Optional[int] = None
    tool_log: List[Tuple[str, bool]] = field(default_factory=list)
    success: bool = True

    @property
    def needs_user(self) -> bool:
        return self.status == "necesita_usuario"


class Agent:
    """Orquesta el ciclo modelo <-> herramientas."""

    def __init__(
        self,
        registry: ProviderRegistry,
        catalog: ToolCatalog,
        memory: Memory,
        limits: AgentLimits,
        on_delta: Optional[Callable[[str], None]] = None,
        on_event: Optional[Callable[[str, str], None]] = None,
    ):
        self.registry = registry
        self.catalog = catalog
        self.memory = memory
        self.limits = limits
        self.on_delta = on_delta      # streaming de texto del modelo
        self.on_event = on_event or (lambda kind, msg: None)  # eventos de UI

    # ------------------------------------------------------------------- ciclo
    def run(self, user_text: str, conversation_id: Optional[int] = None,
            context: Optional[List[Tuple[str, str]]] = None,
            task_title: str = "", resume_task_id: Optional[int] = None) -> AgentOutcome:
        """Ejecuta una tarea/conversación completa con límites configurables."""
        start = time.monotonic()
        try:
            provider = self.registry.get()
        except ProviderError as exc:
            return AgentOutcome("fallida", reply=str(exc), success=False)

        provider_label = f"{provider.name}/{provider.model or '?'}"
        system = build_system_prompt(str(self.catalog.guard.workspace),
                                     self.catalog.permissions.mode, provider_label)

        history = list(context or [])
        if conversation_id and self.memory.conversation_exists(conversation_id):
            history = self.memory.get_messages(conversation_id, limit=40)
        history = build_context(history, max_messages=max(4, self.limits.history_window
                                                          if hasattr(self.limits, "history_window") else 20))

        # Tarea: nueva o reanudada.
        task_id = resume_task_id
        if task_id is None:
            task_id = self.memory.create_task(
                task_title or user_text[:80], user_text, conversation_id=conversation_id)
        self.memory.update_task(task_id, status="en_curso")

        messages: List[ChatMessage] = [ChatMessage("system", system)]
        for role, content in history:
            if role in ("user", "assistant", "system"):
                messages.append(ChatMessage(role, content))
        messages.append(ChatMessage("user", user_text))
        if conversation_id and self.memory.conversation_exists(conversation_id):
            self.memory.add_message(conversation_id, "user", user_text)

        self.catalog.file_ops_count = 0
        plan: List[str] = []
        tool_log: List[Tuple[str, bool]] = []
        last_text = ""
        pending_question = ""

        for iteration in range(1, self.limits.max_iterations + 1):
            elapsed = time.monotonic() - start
            if elapsed > self.limits.max_seconds:
                self.memory.update_task(task_id, status="interrumpida",
                                        error="Límite de tiempo alcanzado.",
                                        iterations=iteration - 1, plan=plan)
                return AgentOutcome("limite_tiempo",
                                    reply=f"Límite de tiempo alcanzado ({self.limits.max_seconds:.0f}s). "
                                          f"Puedes reanudar la tarea con /tasks resume {task_id}.",
                                    plan=plan, iterations=iteration - 1,
                                    seconds=elapsed, task_id=task_id,
                                    tool_log=tool_log, success=False)

            self.on_event("iteration", f"Iteración {iteration}/{self.limits.max_iterations} "
                                       f"({provider_label})")
            try:
                text = provider.complete(messages, on_delta=self.on_delta)
            except ProviderError as exc:
                self.memory.update_task(task_id, status="fallida", error=str(exc),
                                        iterations=iteration, plan=plan)
                return AgentOutcome("fallida", reply=str(exc), plan=plan,
                                    iterations=iteration, seconds=time.monotonic() - start,
                                    task_id=task_id, tool_log=tool_log, success=False)

            last_text = text
            messages.append(ChatMessage("assistant", text))

            # PLANIFICAR: capturar el plan declarado por el modelo.
            extracted_plan = _extract_plan(text)
            if extracted_plan and not plan:
                plan = extracted_plan
                self.memory.update_task(task_id, plan=plan)
                self.on_event("plan", "Plan: " + " | ".join(plan))

            call = parse_tool_call(text)
            if call is None:
                # Sin acción: conversación normal.
                if conversation_id and self.memory.conversation_exists(conversation_id):
                    self.memory.add_message(conversation_id, "assistant", text)
                self.memory.update_task(task_id, status="completada", result=text[:2000],
                                        iterations=iteration, plan=plan)
                return AgentOutcome("conversacion", reply=text, plan=plan,
                                    iterations=iteration, seconds=time.monotonic() - start,
                                    task_id=task_id, tool_log=tool_log, success=True)

            action, args = call
            self.on_event("tool", f"{action}")

            if action not in TOOL_NAMES:
                feedback = (f"[RESULTADO] Herramienta '{action}' desconocida. "
                            f"Disponibles: {', '.join(TOOL_NAMES)}. Responde solo con el bloque JSON.")
                messages.append(ChatMessage("user", feedback))
                tool_log.append((action, False))
                continue

            result: ToolResult = self.catalog.execute(action, args)
            tool_log.append((action, result.ok))
            self.memory.log_operation(f"tool:{action}",
                                      str(args.get("path") or args.get("command") or "")[:200],
                                      "ok" if result.ok else "fallo", success=result.ok)

            if result.needs_user:
                pending_question = result.question
                self.memory.update_task(task_id, status="interrumpida",
                                        error=f"Espera respuesta del usuario: {pending_question}",
                                        iterations=iteration, plan=plan)
                return AgentOutcome("necesita_usuario", question=pending_question,
                                    reply=_visible_text(text), plan=plan, iterations=iteration,
                                    seconds=time.monotonic() - start, task_id=task_id,
                                    tool_log=tool_log, success=True)

            if result.finished:
                summary = result.output
                self.memory.update_task(task_id,
                                        status="completada" if result.finish_success else "fallida",
                                        result=summary[:2000], iterations=iteration, plan=plan)
                if conversation_id and self.memory.conversation_exists(conversation_id):
                    self.memory.add_message(conversation_id, "assistant", summary)
                return AgentOutcome("terminada", reply=summary, plan=plan,
                                    iterations=iteration, seconds=time.monotonic() - start,
                                    task_id=task_id, tool_log=tool_log,
                                    success=result.finish_success)

            # Realimentar al modelo con el resultado de la herramienta.
            output = result.output[: self.limits.max_output_chars]
            if len(result.output) > self.limits.max_output_chars:
                output += "\n[salida truncada por límite]"
            messages.append(ChatMessage("user", f"[RESULTADO {action}] ok={result.ok}\n{output}"))

        # Límite de iteraciones alcanzado sin finish.
        self.memory.update_task(task_id, status="interrumpida",
                                error="Límite de iteraciones alcanzado.",
                                iterations=self.limits.max_iterations, plan=plan)
        return AgentOutcome(
            "limite_iteraciones",
            reply=(f"Límite de {self.limits.max_iterations} iteraciones alcanzado sin terminar. "
                   f"Último mensaje del modelo:\n{_visible_text(last_text)[:800]}\n"
                   f"Puedes reanudar con /tasks resume {task_id}."),
            plan=plan, iterations=self.limits.max_iterations,
            seconds=time.monotonic() - start, task_id=task_id, tool_log=tool_log,
            success=False,
        )

    # ---------------------------------------------------------- recuperación
    def resume(self, task_id: int, extra: str = "") -> AgentOutcome:
        """Reanuda una tarea interrumpida usando su contexto persistido."""
        task = self.memory.get_task(task_id)
        if task is None:
            return AgentOutcome("fallida", reply=f"La tarea {task_id} no existe.", success=False)
        prompt = task.description or task.title
        if task.error:
            prompt += f"\n\n[Estado anterior] {task.error}"
        if task.plan:
            prompt += "\n[Plan previo]\n" + "\n".join(f"- {p}" for p in task.plan)
        if extra:
            prompt += f"\n\n[Instrucción adicional del usuario] {extra}"
        return self.run(prompt, conversation_id=task.conversation_id,
                        task_title=task.title, resume_task_id=task_id)


def _extract_plan(text: str) -> List[str]:
    """Extrae el plan declarado (bloque que empieza por 'PLAN:')."""
    match = re.search(r"PLAN\s*:?\s*\n((?:\s*(?:[-*\d.)]+\s*.+\n?)+))", text, re.IGNORECASE)
    if not match:
        return []
    items: List[str] = []
    for line in match.group(1).splitlines():
        clean = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", line).strip()
        if clean:
            items.append(clean)
    return items[:12]


def _visible_text(text: str) -> str:
    """Texto del modelo sin los bloques JSON de herramientas."""
    return _JSON_FENCE.sub("", text).strip()
