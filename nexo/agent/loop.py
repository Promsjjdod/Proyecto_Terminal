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
from nexo.providers.base import ChatMessage, ModelReply, ProviderError
from nexo.providers.registry import ProviderRegistry
from nexo.tools.catalog import TOOL_NAMES, ToolCatalog, ToolResult
from nexo.tools.schema import openai_tools_schema

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
        use_native_tools: bool = True,
    ):
        self.registry = registry
        self.catalog = catalog
        self.memory = memory
        self.limits = limits
        self.on_delta = on_delta      # streaming de texto del modelo
        self.on_event = on_event or (lambda kind, msg: None)  # eventos de UI
        self.use_native_tools = use_native_tools

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
        capabilities = provider.capabilities()
        native = bool(self.use_native_tools) and bool(capabilities.get("tool_calling_native"))
        if capabilities.get("tools") is False:
            # La API informó que el modelo NO soporta herramientas: no se
            # simulan capacidades de agente; se avisa y se conversa sin ellas.
            native = False
            self.on_event("warn", f"El modelo {provider.model} no informa soporte de "
                                  "herramientas: se usa modo conversación/agente JSON.")
        if native:
            return self._run_native(provider, user_text, conversation_id, context,
                                    task_title, resume_task_id)
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

        self.catalog.reset_task_tracking()
        plan: List[str] = []
        tool_log: List[Tuple[str, bool]] = []
        last_text = ""
        pending_question = ""
        self.on_event("phase", "PLAN")

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
            self.on_event("phase", "EJECUTAR")
            if action == "export_file":
                self.on_event("phase", "EXPORTAR")

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
                self.on_event("phase", "VERIFICAR")
                self.on_event("progress", "100")
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

    # ------------------------------------------------- tool calling nativo
    def _run_native(self, provider, user_text: str,
                    conversation_id: Optional[int], context: Optional[List[Tuple[str, str]]],
                    task_title: str, resume_task_id: Optional[int]) -> AgentOutcome:
        """Ciclo real de tool calling (formato OpenAI/CleanAPIs).

        Envía el esquema de herramientas, interpreta `tool_calls`
        estructurados (no texto), valida argumentos, ejecuta SOLO mediante el
        catálogo (que aplica permisos), devuelve cada resultado con su
        `tool_call_id` y continúa hasta obtener la respuesta final. Las
        llamadas paralelas de una misma respuesta se ejecutan en orden y se
        responden todas (una mensaje `tool` por id).
        """
        start = time.monotonic()
        system = build_system_prompt(str(self.catalog.guard.workspace),
                                     self.catalog.permissions.mode,
                                     f"{provider.name}/{provider.model or '?'}")
        history = list(context or [])
        if conversation_id and self.memory.conversation_exists(conversation_id):
            history = self.memory.get_messages(conversation_id, limit=40)
        history = build_context(history, max_messages=20)

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

        schema = openai_tools_schema()
        self.catalog.reset_task_tracking()
        plan: List[str] = []
        tool_log: List[Tuple[str, bool]] = []
        tools_executed = 0
        self.on_event("phase", "PLAN")

        for iteration in range(1, self.limits.max_iterations + 1):
            elapsed = time.monotonic() - start
            if elapsed > self.limits.max_seconds:
                self.memory.update_task(task_id, status="interrumpida",
                                        error="Límite de tiempo alcanzado.",
                                        iterations=iteration - 1, plan=plan)
                return AgentOutcome("limite_tiempo",
                                    reply=f"Límite de tiempo alcanzado ({self.limits.max_seconds:.0f}s). "
                                          f"Reanudá con /tasks resume {task_id}.",
                                    plan=plan, iterations=iteration - 1,
                                    seconds=elapsed, task_id=task_id,
                                    tool_log=tool_log, success=False)
            self.on_event("iteration", f"Iteración {iteration}/{self.limits.max_iterations} "
                                       f"(tool calling nativo)")
            self.on_event("progress", str(int((iteration - 1) * 100 / self.limits.max_iterations)))
            try:
                reply: ModelReply = provider.chat(messages, tools=schema,
                                                  on_delta=self.on_delta)
            except ProviderError as exc:
                self.memory.update_task(task_id, status="fallida", error=str(exc),
                                        iterations=iteration, plan=plan)
                return AgentOutcome("fallida", reply=str(exc), plan=plan,
                                    iterations=iteration, seconds=time.monotonic() - start,
                                    task_id=task_id, tool_log=tool_log, success=False)

            if not reply.content and not reply.tool_calls:
                self.memory.update_task(task_id, status="fallida",
                                        error="Respuesta vacía del modelo.",
                                        iterations=iteration, plan=plan)
                return AgentOutcome("fallida",
                                    reply="El modelo devolvió una respuesta vacía "
                                          "(sin texto ni llamadas a herramientas).",
                                    plan=plan, iterations=iteration,
                                    seconds=time.monotonic() - start, task_id=task_id,
                                    tool_log=tool_log, success=False)

            messages.append(ChatMessage("assistant", reply.content or "",
                                        tool_calls=reply.tool_calls or None))
            extracted = _extract_plan(reply.content or "")
            if extracted and not plan:
                plan = extracted
                self.memory.update_task(task_id, plan=plan)
                self.on_event("plan", "Plan: " + " | ".join(plan))

            if not reply.tool_calls:
                # Respuesta final del modelo.
                status = "terminada" if tools_executed else "conversacion"
                self.on_event("phase", "VERIFICAR")
                self.on_event("progress", "100")
                self.memory.update_task(task_id,
                                        status="completada" if tools_executed else "completada",
                                        result=(reply.content or "")[:2000],
                                        iterations=iteration, plan=plan)
                if conversation_id and self.memory.conversation_exists(conversation_id):
                    self.memory.add_message(conversation_id, "assistant", reply.content or "")
                return AgentOutcome(status, reply=reply.content or "", plan=plan,
                                    iterations=iteration, seconds=time.monotonic() - start,
                                    task_id=task_id, tool_log=tool_log, success=True)

            # Ejecutar las llamadas (paralelas del proveedor, en orden seguro).
            self.on_event("phase", "EJECUTAR")
            tool_messages: List[ChatMessage] = []
            interrupted: Optional[AgentOutcome] = None
            for call in reply.tool_calls:
                name = call.get("name", "")
                args = call.get("arguments") or {}
                self.on_event("tool", name)
                if call.get("_arguments_error"):
                    result = ToolResult(
                        False,
                        f"Argumentos JSON inválidos para '{name}' "
                        f"({call['_arguments_error']}): {call.get('_raw_arguments', '')[:300]}. "
                        "Reenviá la llamada con JSON válido.",
                        action=name)
                elif name not in TOOL_NAMES:
                    result = ToolResult(False, f"Herramienta desconocida: '{name}'. "
                                               f"Disponibles: {', '.join(TOOL_NAMES)}.",
                                        action=name)
                else:
                    result = self.catalog.execute(name, args)
                    tools_executed += 1
                    if name == "export_file":
                        self.on_event("phase", "EXPORTAR")
                tool_log.append((name, result.ok))
                self.memory.log_operation(
                    f"tool:{name}",
                    str(args.get("path") or args.get("command") or "")[:200],
                    "ok" if result.ok else "fallo", success=result.ok)

                if result.needs_user:
                    self.memory.update_task(task_id, status="interrumpida",
                                            error=f"Espera respuesta del usuario: {result.question}",
                                            iterations=iteration, plan=plan)
                    interrupted = AgentOutcome("necesita_usuario", question=result.question,
                                               reply=_visible_text(reply.content or ""),
                                               plan=plan, iterations=iteration,
                                               seconds=time.monotonic() - start,
                                               task_id=task_id, tool_log=tool_log,
                                               success=True)
                    break
                if result.finished:
                    self.on_event("phase", "VERIFICAR")
                    self.on_event("progress", "100")
                    self.memory.update_task(
                        task_id,
                        status="completada" if result.finish_success else "fallida",
                        result=result.output[:2000], iterations=iteration, plan=plan)
                    if conversation_id and self.memory.conversation_exists(conversation_id):
                        self.memory.add_message(conversation_id, "assistant", result.output)
                    interrupted = AgentOutcome("terminada", reply=result.output, plan=plan,
                                               iterations=iteration,
                                               seconds=time.monotonic() - start,
                                               task_id=task_id, tool_log=tool_log,
                                               success=result.finish_success)
                    break
                output = result.output[: self.limits.max_output_chars]
                if len(result.output) > self.limits.max_output_chars:
                    output += "\n[salida truncada por límite]"
                tool_messages.append(ChatMessage("tool", f"ok={result.ok}\n{output}",
                                                 tool_call_id=call.get("id", "")))
            if interrupted is not None:
                return interrupted
            messages.extend(tool_messages)

        self.memory.update_task(task_id, status="interrumpida",
                                error="Límite de iteraciones alcanzado.",
                                iterations=self.limits.max_iterations, plan=plan)
        return AgentOutcome(
            "limite_iteraciones",
            reply=(f"Límite de {self.limits.max_iterations} iteraciones alcanzado sin "
                   f"respuesta final. Reanudá con /tasks resume {task_id}."),
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
