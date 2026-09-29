"""Local Ollama structured-output adapter for admitted JARVIS model targets."""

from __future__ import annotations

import asyncio
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ValidationError

from jarvis.hands.provider_adapters import (
    StructuredOutputError,
    StructuredOutputTelemetry,
)
from jarvis.model_routing.models import (
    BenchmarkStatus,
    CostProfile,
    ModelLocality,
    ModelTarget,
)
from jarvis.model_routing.registry import ModelAdapterRegistry, ModelTargetRegistry

if TYPE_CHECKING:
    from jarvis.model_routing.invoker import ModelInvocationContext

DEFAULT_OLLAMA_ENDPOINT = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_CONTEXT_TOKENS = 4096
DEFAULT_OLLAMA_NUM_PREDICT = 256
DEFAULT_OLLAMA_KEEP_ALIVE = "5m"
DEFAULT_OLLAMA_TIMEOUT_SECONDS = 30.0

C5_LOCAL_TARGET_ID = "local.ollama.qwen3_5_4b.c5"
C5_LOCAL_MODEL_ID = "qwen3.5:4b"
C5_LOCAL_CAPABILITIES = (
    "bounded_planning",
    "classification_extraction",
    "summarization",
    "structured_output",
)


def build_c5_local_target() -> ModelTarget:
    """Return the owner-machine-admitted C5 local target contract."""

    return ModelTarget(
        target_id=C5_LOCAL_TARGET_ID,
        adapter_id="ollama",
        provider_id="ollama",
        model_id=C5_LOCAL_MODEL_ID,
        locality=ModelLocality.LOCAL,
        capabilities=C5_LOCAL_CAPABILITIES,
        roles=("efficient", "bounded_decision"),
        max_context_tokens=DEFAULT_OLLAMA_CONTEXT_TOKENS,
        supports_structured_output=True,
        supports_tools=False,
        supports_streaming=False,
        latency_class="fast",
        benchmark_status=BenchmarkStatus.ACCEPTED,
        registry_version=1,
        endpoint_ref=DEFAULT_OLLAMA_ENDPOINT,
        credential_ref=None,
        cost_profile=CostProfile(
            profile_id="ollama-local-api-zero-c5",
            version=1,
            effective_from_epoch=0.0,
            input_usd_per_million_tokens=0.0,
            output_usd_per_million_tokens=0.0,
        ),
        enabled=True,
    )


def build_c5_local_target_registry(
    adapter_registry: ModelAdapterRegistry,
) -> ModelTargetRegistry:
    """Build the isolated C5 target pool without changing Work registry digests."""

    if not isinstance(adapter_registry, ModelAdapterRegistry):
        raise TypeError("adapter_registry must be a ModelAdapterRegistry")
    return ModelTargetRegistry(adapter_registry, (build_c5_local_target(),))


class OllamaRequestError(RuntimeError):
    """Base local-runtime transport error with provider-resilience metadata."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = True,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


class OllamaConnectionError(OllamaRequestError):
    """The local Ollama runtime could not be reached."""


class OllamaTimeoutError(OllamaRequestError):
    """The local Ollama runtime exceeded the bounded request timeout."""


class OllamaHTTPError(OllamaRequestError):
    """The local Ollama runtime returned an HTTP error."""


def _normalize_loopback_endpoint(value: str | None) -> str:
    raw = str(value or DEFAULT_OLLAMA_ENDPOINT).strip()
    if not raw:
        raise ValueError("Ollama endpoint must not be empty")
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme.casefold() != "http":
        raise ValueError("Ollama endpoint must use http on loopback")
    if parsed.username or parsed.password:
        raise ValueError("Ollama endpoint must not contain credentials")
    host = (parsed.hostname or "").casefold()
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Ollama endpoint must be loopback-only")
    if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
        raise ValueError("Ollama endpoint must be a base loopback URL")
    port = parsed.port or 11434
    if not 1 <= port <= 65535:
        raise ValueError("Ollama endpoint port is invalid")
    if host == "::1":
        return f"http://[::1]:{port}"
    return f"http://{host}:{port}"


def _non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _post_json(
    url: str,
    payload: dict[str, Any],
    *,
    timeout: float,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        raise OllamaHTTPError(
            f"Ollama local runtime returned HTTP {status}",
            status_code=status,
            retryable=status >= 500 or status in {408, 429},
        ) from exc
    except urllib.error.URLError as exc:
        raise OllamaConnectionError(
            "Ollama local runtime connection failed",
            retryable=True,
        ) from exc
    except TimeoutError as exc:
        raise OllamaTimeoutError(
            "Ollama local runtime timed out",
            status_code=504,
            retryable=True,
        ) from exc

    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise StructuredOutputError(
            "Ollama local runtime returned invalid response JSON"
        ) from exc
    if not isinstance(decoded, dict):
        raise StructuredOutputError(
            "Ollama local runtime returned a non-object response"
        )
    return decoded


class OllamaStructuredOutputAdapter:
    """Invoke one admitted localhost Ollama target through ModelInvoker."""

    adapter_id = "ollama"
    provider_id = "ollama"

    def __init__(
        self,
        *,
        endpoint: str = DEFAULT_OLLAMA_ENDPOINT,
        think: bool = False,
        num_ctx: int = DEFAULT_OLLAMA_CONTEXT_TOKENS,
        num_predict: int = DEFAULT_OLLAMA_NUM_PREDICT,
        keep_alive: str = DEFAULT_OLLAMA_KEEP_ALIVE,
        timeout_seconds: float = DEFAULT_OLLAMA_TIMEOUT_SECONDS,
    ) -> None:
        self._endpoint = _normalize_loopback_endpoint(endpoint)
        if not isinstance(think, bool):
            raise TypeError("think must be a bool")
        if isinstance(num_ctx, bool) or not isinstance(num_ctx, int) or num_ctx <= 0:
            raise ValueError("num_ctx must be a positive integer")
        if (
            isinstance(num_predict, bool)
            or not isinstance(num_predict, int)
            or num_predict <= 0
        ):
            raise ValueError("num_predict must be a positive integer")
        normalized_keep_alive = str(keep_alive).strip()
        if not normalized_keep_alive:
            raise ValueError("keep_alive must not be empty")
        timeout_value = float(timeout_seconds)
        if timeout_value <= 0:
            raise ValueError("timeout_seconds must be positive")

        self._think = think
        self._num_ctx = num_ctx
        self._num_predict = num_predict
        self._keep_alive = normalized_keep_alive
        self._timeout_seconds = timeout_value

    def _endpoint_for(self, target: ModelTarget) -> str:
        if target.adapter_id != self.adapter_id:
            raise ValueError("target adapter_id does not match Ollama adapter")
        if target.provider_id != self.provider_id:
            raise ValueError("target provider_id does not match Ollama adapter")
        if target.locality is not ModelLocality.LOCAL:
            raise ValueError("Ollama target must be local")
        if target.credential_ref is not None:
            raise ValueError("Ollama target must not require cloud credentials")
        return _normalize_loopback_endpoint(target.endpoint_ref or self._endpoint)

    async def invoke_structured(
        self,
        *,
        target: ModelTarget,
        system_prompt: str,
        input_payload: dict[str, Any],
        response_model: type[BaseModel],
        request_context: ModelInvocationContext,
    ) -> BaseModel:
        result = await self.invoke_structured_with_telemetry(
            target=target,
            system_prompt=system_prompt,
            input_payload=input_payload,
            response_model=response_model,
            request_context=request_context,
        )
        return result.parsed

    async def invoke_structured_with_telemetry(
        self,
        *,
        target: ModelTarget,
        system_prompt: str,
        input_payload: dict[str, Any],
        response_model: type[BaseModel],
        request_context: ModelInvocationContext,
    ) -> StructuredOutputTelemetry:
        del request_context
        if not isinstance(target, ModelTarget):
            raise TypeError("target must be a ModelTarget")
        if not isinstance(response_model, type) or not issubclass(
            response_model, BaseModel
        ):
            raise TypeError("response_model must be a Pydantic BaseModel type")

        endpoint = self._endpoint_for(target)
        payload = {
            "model": target.model_id,
            "stream": False,
            "messages": [
                {
                    "role": "system",
                    "content": str(system_prompt),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        input_payload,
                        ensure_ascii=False,
                        sort_keys=True,
                        default=str,
                    ),
                },
            ],
            "format": response_model.model_json_schema(),
            "think": self._think,
            "keep_alive": self._keep_alive,
            "options": {
                "temperature": 0,
                "num_ctx": min(self._num_ctx, target.max_context_tokens),
                "num_predict": self._num_predict,
            },
        }

        started = time.perf_counter()
        response = await asyncio.to_thread(
            _post_json,
            f"{endpoint}/api/chat",
            payload,
            timeout=self._timeout_seconds,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000.0

        message = response.get("message")
        if not isinstance(message, dict):
            raise StructuredOutputError("Ollama returned no structured message object")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise StructuredOutputError("Ollama returned no structured output content")
        try:
            parsed = response_model.model_validate_json(content)
        except ValidationError as exc:
            raise StructuredOutputError(
                "Ollama returned invalid structured output"
            ) from exc

        usage: dict[str, int] = {}
        input_tokens = _non_negative_int(response.get("prompt_eval_count"))
        output_tokens = _non_negative_int(response.get("eval_count"))
        if input_tokens is not None:
            usage["input_tokens"] = input_tokens
        if output_tokens is not None:
            usage["output_tokens"] = output_tokens
        if input_tokens is not None or output_tokens is not None:
            usage["total_tokens"] = (input_tokens or 0) + (output_tokens or 0)

        return StructuredOutputTelemetry(
            parsed=parsed,
            usage=usage,
            usage_observed=bool(usage),
            latency_ms=elapsed_ms,
        )
