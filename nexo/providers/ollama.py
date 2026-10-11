"""Proveedor Ollama (local). API: POST /api/chat, streaming NDJSON."""
from __future__ import annotations

import json
from typing import Dict, Iterator, List

from nexo.providers.base import (
    ChatMessage,
    IncompleteResponseError,
    ModelNotFoundError,
    Provider,
    ProviderError,
)


class OllamaProvider(Provider):
    type_name = "ollama"

    def __init__(self, config, api_key=None, client_factory=None):
        super().__init__(config, api_key=api_key, client_factory=client_factory)
        if not config.base_url:
            config.base_url = "http://127.0.0.1:11434"

    @property
    def _url_chat(self) -> str:
        return self.config.base_url.rstrip("/") + "/api/chat"

    @property
    def _url_tags(self) -> str:
        return self.config.base_url.rstrip("/") + "/api/tags"

    def requires_api_key(self) -> bool:
        return False  # Ollama local no requiere clave

    def _body(self, messages: List[ChatMessage], stream: bool) -> Dict[str, object]:
        body: Dict[str, object] = {
            "model": self.config.model,
            "messages": [m.to_dict() for m in messages],
            "stream": stream,
        }
        options = {k: v for k, v in self.config.params.items() if v is not None}
        if options:
            body["options"] = options
        return body

    def _complete_once(self, messages: List[ChatMessage]) -> str:
        response = self._send_json("POST", self._url_chat,
                                   {"Content-Type": "application/json"},
                                   self._body(messages, stream=False))
        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise ProviderError(f"{self.name} devolvió JSON inválido.", provider=self.name) from exc
        if isinstance(data, dict) and data.get("error"):
            raise ModelNotFoundError(f"Ollama: {data['error']}", provider=self.name)
        content = (data.get("message") or {}).get("content", "")
        if data.get("done") is False:
            raise IncompleteResponseError("Ollama terminó la respuesta sin done=true.",
                                          provider=self.name)
        return content

    def stream(self, messages: List[ChatMessage]) -> Iterator[str]:
        with self._open_stream("POST", self._url_chat,
                               {"Content-Type": "application/json"},
                               self._body(messages, stream=True)) as response:
            got_any = False
            done_seen = False
            for raw_line in response.iter_lines():
                line = raw_line.strip() if isinstance(raw_line, str) else raw_line.decode("utf-8").strip()
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if chunk.get("error"):
                    raise ModelNotFoundError(f"Ollama: {chunk['error']}", provider=self.name)
                content = (chunk.get("message") or {}).get("content", "")
                if content:
                    got_any = True
                    yield content
                if chunk.get("done"):
                    done_seen = True
                    break
            if not got_any and not done_seen:
                raise IncompleteResponseError(
                    "El streaming de Ollama terminó sin contenido ni confirmación.",
                    provider=self.name,
                )

    def list_models(self) -> List[str]:
        response = self._send_json("GET", self._url_tags, {}, {})
        data = response.json()
        models = [m.get("name", "") for m in data.get("models", [])]
        return [m for m in models if m]
