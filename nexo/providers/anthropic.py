"""Proveedor Anthropic (API oficial de Messages). Endpoint: POST {base}/v1/messages.

Streaming SSE con eventos `content_block_delta` / `message_stop`.
"""
from __future__ import annotations

import json
from typing import Dict, Iterator, List

from nexo.providers.base import (
    ChatMessage,
    IncompleteResponseError,
    Provider,
    ProviderError,
)

ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MAX_TOKENS = 2048


class AnthropicProvider(Provider):
    type_name = "anthropic"

    def __init__(self, config, api_key=None, client_factory=None):
        super().__init__(config, api_key=api_key, client_factory=client_factory)
        if not config.base_url:
            config.base_url = "https://api.anthropic.com"

    @property
    def _url_messages(self) -> str:
        return self.config.base_url.rstrip("/") + "/v1/messages"

    @property
    def _url_models(self) -> str:
        return self.config.base_url.rstrip("/") + "/v1/models"

    def requires_api_key(self) -> bool:
        return True

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": ANTHROPIC_VERSION,
        }
        if self._api_key:
            headers["x-api-key"] = self._api_key
        return headers

    def _body(self, messages: List[ChatMessage], stream: bool) -> Dict[str, object]:
        # Anthropic separa el system prompt del historial de mensajes.
        system_parts = [m.content for m in messages if m.role == "system"]
        history = [m for m in messages if m.role != "system"]
        body: Dict[str, object] = {
            "model": self.config.model,
            "max_tokens": self.config.params.get("max_tokens", DEFAULT_MAX_TOKENS),
            "messages": [m.to_dict() for m in history],
            "stream": stream,
        }
        if system_parts:
            body["system"] = "\n\n".join(system_parts)
        for key in ("temperature", "top_p", "top_k", "stop_sequences"):
            if key in self.config.params and self.config.params[key] is not None:
                body[key] = self.config.params[key]
        return body

    def _complete_once(self, messages: List[ChatMessage]) -> str:
        if not self._api_key:
            raise ProviderError(
                "Anthropic requiere API key. Configúrala con `/provider key <nombre>`.",
                provider=self.name)
        response = self._send_json("POST", self._url_messages, self._headers(),
                                   self._body(messages, stream=False))
        data = response.json()
        if data.get("type") == "error":
            raise ProviderError(f"Anthropic: {(data.get('error') or {}).get('message', 'error')}",
                                provider=self.name)
        stop_reason = data.get("stop_reason")
        text = "".join(
            block.get("text", "")
            for block in data.get("content", [])
            if isinstance(block, dict) and block.get("type") == "text"
        )
        if stop_reason == "max_tokens" and not text.strip():
            raise IncompleteResponseError(
                "Anthropic cortó la respuesta por max_tokens.", provider=self.name)
        return text

    def stream(self, messages: List[ChatMessage]) -> Iterator[str]:
        if not self._api_key:
            raise ProviderError(
                "Anthropic requiere API key. Configúrala con `/provider key <nombre>`.",
                provider=self.name)
        with self._open_stream("POST", self._url_messages, self._headers(),
                               self._body(messages, stream=True)) as response:
            got_any = False
            saw_stop = False
            event_type = ""
            for raw_line in response.iter_lines():
                line = raw_line.strip() if isinstance(raw_line, str) else raw_line.decode("utf-8").strip()
                if line.startswith("event:"):
                    event_type = line[len("event:"):].strip()
                    continue
                if not line.startswith("data:"):
                    continue
                payload = line[len("data:"):].strip()
                try:
                    chunk = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                ctype = chunk.get("type", event_type)
                if ctype == "content_block_delta":
                    delta = (chunk.get("delta") or {}).get("text", "")
                    if delta:
                        got_any = True
                        yield delta
                elif ctype == "message_stop":
                    saw_stop = True
                    break
                elif ctype == "error":
                    raise ProviderError(
                        f"Anthropic (stream): {(chunk.get('error') or {}).get('message', 'error')}",
                        provider=self.name)
            if not saw_stop and not got_any:
                raise IncompleteResponseError(
                    "El streaming de Anthropic terminó sin contenido ni message_stop.",
                    provider=self.name)

    def list_models(self) -> List[str]:
        response = self._send_json("GET", self._url_models, self._headers(), {})
        data = response.json()
        return [m.get("id", "") for m in data.get("data", []) if isinstance(m, dict) and m.get("id")]
