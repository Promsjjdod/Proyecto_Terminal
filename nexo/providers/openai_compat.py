"""Proveedor compatible con la API de OpenAI (OpenAI, Groq, OpenRouter,
vLLM, LM Studio, Together, etc.). Endpoint: POST {base}/chat/completions."""
from __future__ import annotations

import json
from typing import Dict, Iterator, List

from nexo.providers.base import (
    ChatMessage,
    IncompleteResponseError,
    Provider,
    ProviderError,
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

    def _body(self, messages: List[ChatMessage], stream: bool) -> Dict[str, object]:
        body: Dict[str, object] = {
            "model": self.config.model,
            "messages": [m.to_dict() for m in messages],
            "stream": stream,
        }
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

    def list_models(self) -> List[str]:
        response = self._send_json("GET", self._url_models, self._headers(), {})
        data = response.json()
        items = data.get("data") or []
        return [i.get("id", "") for i in items if isinstance(i, dict) and i.get("id")]
