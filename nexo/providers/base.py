"""Contrato base de proveedores y tipos de error comunes.

Ningún proveedor simula conexiones exitosas: los errores reales de red,
autenticación, límites de servicio y modelos inexistentes se traducen a
excepciones tipadas que la UI y el agente pueden explicar al usuario.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterator, List, Optional

import httpx

from nexo.config.settings import ProviderConfig


# --------------------------------------------------------------------- errores
class ProviderError(Exception):
    """Error genérico de proveedor (mensaje seguro para mostrar)."""

    def __init__(self, message: str, provider: str = "", retryable: bool = False):
        super().__init__(message)
        self.provider = provider
        self.retryable = retryable


class AuthenticationError(ProviderError):
    """401/403: clave ausente, inválida o sin permisos."""


class ModelNotFoundError(ProviderError):
    """404 u homólogo: el modelo configurado no existe en el proveedor."""


class RateLimitError(ProviderError):
    """429: límite de peticiones del servicio."""

    def __init__(self, message: str, provider: str = "", retry_after: Optional[float] = None):
        super().__init__(message, provider=provider, retryable=True)
        self.retry_after = retry_after


class TransportError(ProviderError):
    """Fallo de red/conexión (DNS, rechazo, TLS, servidor caído)."""

    def __init__(self, message: str, provider: str = ""):
        super().__init__(message, provider=provider, retryable=True)


class RequestTimeoutError(ProviderError):
    """La petición superó el tiempo de espera configurado."""

    def __init__(self, message: str, provider: str = ""):
        super().__init__(message, provider=provider, retryable=True)


class IncompleteResponseError(ProviderError):
    """Respuesta vacía o cortada (finish_reason=length, stream interrumpido...)."""

    def __init__(self, message: str, provider: str = ""):
        super().__init__(message, provider=provider, retryable=True)


# ---------------------------------------------------------------------- tipos
@dataclass
class ChatMessage:
    role: str        # system | user | assistant | tool
    content: str

    def to_dict(self) -> Dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass
class ConnectionTest:
    ok: bool
    message: str
    models: List[str] = field(default_factory=list)
    latency_ms: float = 0.0


# -------------------------------------------------------------------- contrato
class Provider:
    """Proveedor de modelos. Subclases: Ollama, OpenAI, Anthropic, CustomHTTP.

    `client_factory` permite inyectar un httpx.Client (usado en pruebas con
    MockTransport); en producción se crea un cliente real por defecto.
    """

    type_name = "base"

    def __init__(
        self,
        config: ProviderConfig,
        api_key: Optional[str] = None,
        client_factory: Optional[Callable[[], httpx.Client]] = None,
    ):
        self.config = config
        self._api_key = api_key or ""
        self._client_factory = client_factory

    # ------------------------------------------------------------- propiedades
    @property
    def name(self) -> str:
        return self.config.name

    @property
    def model(self) -> str:
        return self.config.model

    @property
    def has_key(self) -> bool:
        return bool(self._api_key)

    def capabilities(self) -> Dict[str, object]:
        """Capacidades reales declaradas por cada proveedor."""
        return {
            "streaming": bool(self.config.stream),
            "requires_api_key": self.requires_api_key(),
            "lists_models": True,
            "tool_calling_native": False,
        }

    def requires_api_key(self) -> bool:
        return False

    # ------------------------------------------------------------------ cliente
    def _client(self) -> httpx.Client:
        if self._client_factory is not None:
            return self._client_factory()
        return httpx.Client(timeout=self.config.timeout)

    def _retry_sleep(self, attempt: int) -> None:
        time.sleep(min(0.5 * (2 ** attempt), 4.0))

    def _send_json(self, method: str, url: str, headers: Dict[str, str],
                   json_body: Dict[str, object]) -> httpx.Response:
        """Petición no-stream con reintentos limitados y clasificación de errores."""
        attempts = max(1, int(self.config.retries) + 1)
        last_error: Optional[ProviderError] = None
        for attempt in range(attempts):
            try:
                with self._client() as client:
                    response = client.request(method, url, headers=headers, json=json_body)
                error = classify_http_status(response.status_code,
                                             self._error_detail(response), self.name)
                if error is None:
                    return response
                if isinstance(error, RateLimitError):
                    retry_after = response.headers.get("retry-after")
                    if retry_after:
                        try:
                            error.retry_after = float(retry_after)
                        except ValueError:
                            pass
                if not error.retryable or attempt + 1 >= attempts:
                    raise error
                last_error = error
            except (httpx.TimeoutException,) as exc:
                last_error = RequestTimeoutError(
                    f"Tiempo de espera agotado ({self.config.timeout}s) contactando {self.name}: {exc}",
                    provider=self.name,
                )
            except httpx.HTTPError as exc:
                last_error = TransportError(
                    f"Error de conexión con {self.name}: {type(exc).__name__}: {exc}",
                    provider=self.name,
                )
            if attempt + 1 < attempts:
                self._retry_sleep(attempt)
        assert last_error is not None
        raise last_error

    def _open_stream(self, method: str, url: str, headers: Dict[str, str],
                     json_body: Dict[str, object]):
        """Abre una respuesta en streaming (context manager de httpx)."""
        client = self._client()
        try:
            request = client.build_request(method, url, headers=headers, json=json_body)
            response = client.send(request, stream=True)
        except httpx.TimeoutException as exc:
            client.close()
            raise RequestTimeoutError(
                f"Tiempo de espera agotado ({self.config.timeout}s) contactando {self.name}: {exc}",
                provider=self.name,
            ) from exc
        except httpx.HTTPError as exc:
            client.close()
            raise TransportError(
                f"Error de conexión con {self.name}: {type(exc).__name__}: {exc}",
                provider=self.name,
            ) from exc

        error = classify_http_status(response.status_code, "", self.name)
        if error is not None:
            response.close()
            client.close()
            raise error

        class _StreamCtx:
            def __enter__(_self):
                return response

            def __exit__(_self, *args):
                response.close()
                client.close()
                return False

        return _StreamCtx()

    @staticmethod
    def _error_detail(response: httpx.Response, max_chars: int = 300) -> str:
        """Extrae un detalle legible del cuerpo de error (sin volcar secretos)."""
        try:
            data = response.json()
            if isinstance(data, dict):
                for key in ("error", "message", "detail"):
                    value = data.get(key)
                    if isinstance(value, dict):
                        value = value.get("message") or str(value)
                    if value:
                        return str(value)[:max_chars]
            return str(data)[:max_chars]
        except Exception:
            return (response.text or "")[:max_chars]


    # ------------------------------------------------------------------- API
    def complete(self, messages: List[ChatMessage],
                 on_delta: Optional[Callable[[str], None]] = None) -> str:
        """Genera una respuesta. Si `on_delta` se pasa y el proveedor soporta
        streaming, se invoca por cada fragmento (salida progresiva)."""
        if on_delta is not None and self.config.stream:
            parts: List[str] = []
            for chunk_text in self.stream(messages):
                parts.append(chunk_text)
                on_delta(chunk_text)
            text = "".join(parts)
        else:
            text = self._complete_once(messages)
        if not text.strip():
            raise IncompleteResponseError(
                f"{self.name} devolvió una respuesta vacía.", provider=self.name
            )
        return text

    def stream(self, messages: List[ChatMessage]) -> Iterator[str]:
        """Itera fragmentos de texto. Por defecto: respuesta única no streamada."""
        yield self._complete_once(messages)

    def _complete_once(self, messages: List[ChatMessage]) -> str:
        raise NotImplementedError

    def test_connection(self) -> ConnectionTest:
        """Prueba real de conexión: lista modelos o completa un saludo mínimo."""
        start = time.monotonic()
        try:
            models = self.list_models()
            latency = (time.monotonic() - start) * 1000
            if self.config.model and models and self.config.model not in models:
                return ConnectionTest(
                    ok=True,
                    message=(
                        f"Conexión correcta, pero el modelo '{self.config.model}' "
                        "no aparece en la lista del proveedor."
                    ),
                    models=models, latency_ms=latency,
                )
            return ConnectionTest(True, f"Conexión correcta ({len(models)} modelo(s) disponibles).",
                                  models=models, latency_ms=latency)
        except ModelNotFoundError:
            # Algunos endpoints no exponen lista de modelos: intentar mini-completado.
            try:
                text = self._complete_once(
                    [ChatMessage("user", "Responde únicamente: OK")]
                )
                latency = (time.monotonic() - start) * 1000
                return ConnectionTest(True, f"Conexión correcta (respuesta: {text[:40]!r}).",
                                      latency_ms=latency)
            except ProviderError as exc2:
                return ConnectionTest(False, f"Fallo: {exc2}")
        except ProviderError as exc:
            return ConnectionTest(False, f"Fallo: {exc}")

    def list_models(self) -> List[str]:
        """Lista de modelos disponibles. Los proveedores que no la soporten
        deben lanzar ModelNotFoundError para que test_connection haga fallback."""
        raise ModelNotFoundError(f"{self.name} no expone lista de modelos.", provider=self.name)


def classify_http_status(status: int, detail: str, provider_name: str) -> Optional[ProviderError]:
    """Traduce códigos HTTP a errores tipados de NEXO (None si 2xx/3xx)."""
    if 200 <= status < 400:
        return None
    if status in (401, 403):
        return AuthenticationError(
            f"Autenticación rechazada por {provider_name} (HTTP {status}): {detail}",
            provider=provider_name,
        )
    if status == 404:
        return ModelNotFoundError(
            f"Recurso o modelo no encontrado en {provider_name} (HTTP 404): {detail}",
            provider=provider_name,
        )
    if status == 429:
        return RateLimitError(
            f"Límite de peticiones alcanzado en {provider_name} (HTTP 429): {detail}",
            provider=provider_name,
        )
    if status >= 500:
        return TransportError(
            f"Error del servidor {provider_name} (HTTP {status}): {detail}",
            provider=provider_name,
        )
    return ProviderError(
        f"Respuesta inesperada de {provider_name} (HTTP {status}): {detail}",
        provider=provider_name,
    )
