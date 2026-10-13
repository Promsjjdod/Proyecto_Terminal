"""Proveedor compatible con la API de OpenAI (OpenAI, Groq, OpenRouter,
vLLM, LM Studio, Together, etc.). Endpoint: POST {base}/chat/completions."""
from __future__ import annotations

import json
from typing import Any, Callable, Dict, Iterator, List, Optional

from nexo.providers.base import (
    ChatMessage,
    IncompleteResponseError,
    ModelReply,
    Provider,
    ProviderError,
    normalize_tool_calls,
)


class OpenAICompatProvider(Provider):
    type_name = "openai"

    def __init__(self, config, api_key=None, client_factory=None):
        super().__init__(config, api_key=api_key, client_factory=client_factory)
        if not config.base_url:
            config.base_url = "https://api.openai.com/v1"

    @property
    def _url_chat(self) -> str:
        return self.config.base_url.rstrip("/") + "/chat/completions"

    @property
    def _url_models(self) -> str:
        return self.config.base_url.rstrip("/") + "/models"

    def requires_api_key(self) -> bool:
        # Servicios locales como vLLM/LM Studio pueden no exigir clave.
        return False

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        # Cabeceras extra configuradas por el usuario (pueden completar, no
        # sustituir la autenticación derivada de la clave del almacén).
        for key, value in self.config.headers.items():
            if key.lower() == "authorization" and self._api_key:
                continue
            headers[key] = value
        return headers

    def _native_tool_protocol(self) -> bool:
        return True

    def _body(self, messages: List[ChatMessage], stream: bool,
              tools: Optional[List[Dict]] = None) -> Dict[str, object]:
        body: Dict[str, object] = {
            "model": self.config.model,
            "messages": [m.to_dict() for m in messages],
            "stream": stream,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        for key in ("temperature", "top_p", "max_tokens", "stop", "presence_penalty",
                    "frequency_penalty"):
            if key in self.config.params and self.config.params[key] is not None:
                body[key] = self.config.params[key]
        return body

    def _complete_once(self, messages: List[ChatMessage]) -> str:
        if not self.config.model:
            raise ProviderError("No hay modelo configurado para este proveedor.",
                                provider=self.name)
        response = self._send_json("POST", self._url_chat, self._headers(),
                                   self._body(messages, stream=False))
        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            raise IncompleteResponseError("La respuesta no incluye 'choices'.",
                                          provider=self.name)
        choice = choices[0]
        finish = choice.get("finish_reason")
        content = (choice.get("message") or {}).get("content") or ""
        if finish == "length" and not content.strip():
            raise IncompleteResponseError(
                "La respuesta se cortó por límite de tokens (finish_reason=length).",
                provider=self.name)
        return content

    def stream(self, messages: List[ChatMessage]) -> Iterator[str]:
        if not self.config.model:
            raise ProviderError("No hay modelo configurado para este proveedor.",
                                provider=self.name)
        with self._open_stream("POST", self._url_chat, self._headers(),
                               self._body(messages, stream=True)) as response:
            got_any = False
            saw_done = False
            for raw_line in response.iter_lines():
                line = raw_line.strip() if isinstance(raw_line, str) else raw_line.decode("utf-8").strip()
                if not line or not line.startswith("data:"):
                    continue
                payload = line[len("data:"):].strip()
                if payload == "[DONE]":
                    saw_done = True
                    break
                try:
                    chunk = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                for choice in chunk.get("choices") or []:
                    delta = (choice.get("delta") or {}).get("content")
                    if delta:
                        got_any = True
                        yield delta
            if not saw_done and not got_any:
                raise IncompleteResponseError(
                    "El streaming terminó sin contenido ni marcador [DONE].",
                    provider=self.name)

    def list_models_meta(self) -> List[Dict]:
        """Metadatos CRUDOS de GET /v1/models (ids exactos + capacidades si existen)."""
        response = self._send_json("GET", self._url_models, self._headers(), {})
        data = response.json()
        items = data.get("data") or []
        return [i for i in items if isinstance(i, dict) and i.get("id")]

    def list_models(self) -> List[str]:
        return [m["id"] for m in self.list_models_meta()]

    # ------------------------------------------------------- tool calling nativo
    def chat(self, messages: List[ChatMessage],
             tools: Optional[List[Dict]] = None,
             on_delta: Optional[Callable[[str], None]] = None) -> ModelReply:
        """Ciclo de generación con tool calling nativo (formato OpenAI/CleanAPIs).

        - Sin streaming: parsea `message.tool_calls` y `finish_reason`.
        - Con streaming: acumula deltas de contenido y de `tool_calls`
          (los argumentos llegan fragmentados; solo son JSON válido al final).
        """
        if tools is not None and not self._native_tool_protocol():
            tools = None
        use_stream = on_delta is not None and self.config.stream
        if not use_stream:
            response = self._send_json("POST", self._url_chat, self._headers(),
                                       self._body(messages, stream=False, tools=tools))
            data = response.json()
            choices = data.get("choices") or []
            if not choices:
                raise IncompleteResponseError("La respuesta no incluye 'choices'.",
                                              provider=self.name)
            choice = choices[0]
            message = choice.get("message") or {}
            content = message.get("content") or ""
            tool_calls = normalize_tool_calls(message.get("tool_calls") or [])
            return ModelReply(content=content, tool_calls=tool_calls,
                              finish_reason=str(choice.get("finish_reason") or "stop"))

        # Streaming con acumulación de tool_calls por índice.
        acc_content: List[str] = []
        acc_calls: Dict[int, Dict[str, Any]] = {}
        finish_reason = "stop"
        with self._open_stream("POST", self._url_chat, self._headers(),
                               self._body(messages, stream=True, tools=tools)) as response:
            saw_done = False
            for raw_line in response.iter_lines():
                line = raw_line.strip() if isinstance(raw_line, str) else raw_line.decode("utf-8").strip()
                if not line or not line.startswith("data:"):
                    continue
                payload = line[len("data:"):].strip()
                if payload == "[DONE]":
                    saw_done = True
                    break
                try:
                    chunk = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                for choice in chunk.get("choices") or []:
                    delta = choice.get("delta") or {}
                    piece = delta.get("content")
                    if piece:
                        acc_content.append(piece)
                        if on_delta:
                            on_delta(piece)
                    for tc in delta.get("tool_calls") or []:
                        idx = tc.get("index", 0)
                        slot = acc_calls.setdefault(idx, {"id": "", "name": "", "args": []})
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            slot["name"] += fn["name"]
                        if fn.get("arguments"):
                            slot["args"].append(fn["arguments"])
                    if choice.get("finish_reason"):
                        finish_reason = str(choice["finish_reason"])
            if not saw_done and not acc_content and not acc_calls:
                raise IncompleteResponseError(
                    "El streaming terminó sin contenido ni marcador [DONE].",
                    provider=self.name)
        raw_calls = [
            {"id": slot["id"] or f"call_{idx}", "type": "function",
             "function": {"name": slot["name"], "arguments": "".join(slot["args"])}}
            for idx, slot in sorted(acc_calls.items())
        ]
        return ModelReply(content="".join(acc_content),
                          tool_calls=normalize_tool_calls(raw_calls),
                          finish_reason=finish_reason)
