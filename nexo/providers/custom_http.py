"""Proveedor HTTP personalizado genérico.

Permite conectar cualquier endpoint que hable un formato de conversación
sencillo, configurable en `ProviderConfig`:

- ``base_url``   : URL completa del endpoint de chat (POST).
- ``params``     : puede incluir:
    - ``body``            : plantilla JSON del cuerpo con marcadores
                            ``{model}``, ``{messages}``, ``{system}``, ``{stream}``.
                            Por defecto: ``{"model": ..., "messages": [...]}``.
    - ``content_key``     : ruta separada por puntos al texto de la respuesta
                            (por defecto ``content``; ejemplos: ``choices.0.message.content``,
                            ``message.content``).
    - ``stream_mode``     : ``none`` | ``sse`` | ``ndjson`` (por defecto ``none``).
    - ``stream_content_key``: ruta al delta de texto en cada línea de stream
                            (por defecto ``delta``; en SSE estilo OpenAI:
                            ``choices.0.delta.content``).
- ``headers``    : cabeceras adicionales (la clave API se envía como
                   ``Authorization: Bearer`` si existe, salvo que se indique
                   otra cosa en ``headers``).
"""
from __future__ import annotations

import json
from typing import Any, Dict, Iterator, List

from nexo.providers.base import (
    ChatMessage,
    IncompleteResponseError,
    Provider,
    ProviderError,
)

DEFAULT_BODY_TEMPLATE = json.dumps({
    "model": "{model}",
    "messages": "{messages}",
    "stream": "{stream}",
})


def extract_by_key(data: Any, dotted_key: str) -> Any:
    """Extrae un valor de un JSON anidado usando una ruta 'a.0.b'."""
    current = data
    for part in dotted_key.split("."):
        if part == "":
            continue
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(current, dict):
            current = current.get(part)
        else:
            return None
        if current is None:
            return None
    return current


class CustomHTTPProvider(Provider):
    type_name = "custom"

    def requires_api_key(self) -> bool:
        return bool(self._api_key)

    # ------------------------------------------------------------------ cuerpo
    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        for key, value in self.config.headers.items():
            if key.lower() == "authorization" and self._api_key:
                continue
            headers[key] = value
        return headers

    def _body(self, messages: List[ChatMessage], stream: bool) -> Dict[str, object]:
        template = str(self.config.params.get("body") or DEFAULT_BODY_TEMPLATE)
        system_parts = [m.content for m in messages if m.role == "system"]
        history = [m for m in messages if m.role != "system"]
        # Sustitución explícita de marcadores (no str.format: el JSON de la
        # plantilla y de los mensajes contiene llaves literales). Se admiten
        # marcadores entrecomillados ("{model}") y sin entrecomillar ({messages}).
        values = {
            "model": json.dumps(self.config.model),
            "messages": json.dumps([m.to_dict() for m in history], ensure_ascii=False),
            "system": json.dumps("\n\n".join(system_parts), ensure_ascii=False),
            "stream": json.dumps(bool(stream)),
        }
        rendered = template
        for key, raw_json in values.items():
            rendered = rendered.replace('"{%s}"' % key, raw_json)
        for key, raw_json in values.items():
            inner = raw_json[1:-1] if raw_json.startswith('"') and raw_json.endswith('"') else raw_json
            rendered = rendered.replace("{%s}" % key, inner)
        body = json.loads(rendered)
        if not isinstance(body, dict):
            raise ProviderError("La plantilla 'body' del proveedor custom debe producir un objeto JSON.",
                                provider=self.name)
        return body

    def _content_key(self) -> str:
        return str(self.config.params.get("content_key", "content"))

    def _stream_content_key(self) -> str:
        return str(self.config.params.get("stream_content_key", "delta"))

    def _stream_mode(self) -> str:
        mode = str(self.config.params.get("stream_mode", "none")).lower()
        if mode not in ("none", "sse", "ndjson"):
            raise ProviderError(f"stream_mode inválido: {mode} (usa none|sse|ndjson).",
                                provider=self.name)
        return mode

    # -------------------------------------------------------------------- API
    def _complete_once(self, messages: List[ChatMessage]) -> str:
        if not self.config.base_url:
            raise ProviderError("El proveedor custom necesita una base_url.", provider=self.name)
        url = self.config.base_url
        response = self._send_json("POST", url, self._headers(), self._body(messages, stream=False))
        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise ProviderError(f"{self.name} devolvió una respuesta no-JSON.",
                                provider=self.name) from exc
        content = extract_by_key(data, self._content_key())
        if content is None and isinstance(data, str):
            content = data
        if not isinstance(content, str):
            raise ProviderError(
                f"No se encontró texto en la respuesta (clave configurada: '{self._content_key()}').",
                provider=self.name)
        return content

    def stream(self, messages: List[ChatMessage]) -> Iterator[str]:
        mode = self._stream_mode()
        if mode == "none":
            yield self._complete_once(messages)
            return
        with self._open_stream("POST", self.config.base_url, self._headers(),
                               self._body(messages, stream=True)) as response:
            got_any = False
            for raw_line in response.iter_lines():
                line = raw_line.strip() if isinstance(raw_line, str) else raw_line.decode("utf-8").strip()
                if not line:
                    continue
                if mode == "sse":
                    if not line.startswith("data:"):
                        continue
                    line = line[len("data:"):].strip()
                    if line == "[DONE]":
                        break
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                delta = extract_by_key(chunk, self._stream_content_key())
                if isinstance(delta, str) and delta:
                    got_any = True
                    yield delta
            if not got_any:
                raise IncompleteResponseError(
                    f"El streaming de {self.name} terminó sin contenido.", provider=self.name)

    def list_models(self) -> List[str]:
        # Endpoint genérico: no hay lista estándar de modelos.
        raise ProviderError(f"{self.name} (custom) no expone lista de modelos.",
                            provider=self.name)
