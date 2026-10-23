"""Provider-neutral model invocation boundary for routed background reasoning."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from jarvis.ai_provider import (
    gemini_credential_ref,
    require_provider_api_key,
    resolve_target_api_key,
)
from jarvis.chatgpt_plan import ChatGPTPlanSessionManager
from jarvis.hands.provider_adapters import (
    StructuredOutputClient,
    StructuredOutputTelemetry,
    build_chatgpt_plan_structured_output_client,
    build_structured_output_client,
)
from jarvis.model_routing.budget import PaidBudgetDenied, PaidOutcomeUnknown
from jarvis.model_routing.local_residency import LocalModelResidencyManager
from jarvis.model_routing.models import ModelTarget
from jarvis.model_routing.ollama import OllamaStructuredOutputAdapter
from jarvis.model_routing.pricing import PaidExposure
from jarvis.model_routing.registry import ModelAdapterRegistry


def _required_text(value: object, *, field: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


@dataclass(frozen=True, slots=True)
class ModelInvocationContext:
    work_id: str
    routing_request_id: str
    decision_id: str
    attempt_id: str
    correlation_key: str

    def __post_init__(self) -> None:
        for field_name in (
            "work_id",
            "routing_request_id",
            "decision_id",
            "attempt_id",
            "correlation_key",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field=field_name),
            )


@dataclass(frozen=True, slots=True)
class ScopedModelInvocationContext:
    scope_kind: str
    scope_id: str
    routing_request_id: str
    decision_id: str
    attempt_id: str
    correlation_key: str

    def __post_init__(self):
        if self.scope_kind not in {"voice", "hands", "memory"}:
            raise ValueError("Invalid invocation scope")
        for name in (
            "scope_id",
            "routing_request_id",
            "decision_id",
            "attempt_id",
            "correlation_key",
        ):
            _required_text(getattr(self, name), field=name)


class RoutedInferenceFailure(RuntimeError):
    def __init__(self, failure):
        self.failure = failure
        super().__init__(f"Routed inference unavailable: {failure.kind.value}")


StructuredClientFactory = Callable[[str, str], StructuredOutputClient]


def _default_client_factory(
    provider: str,
    model: str,
    *,
    credential_ref: str | None = None,
    max_output_tokens: int | None = None,
) -> StructuredOutputClient:
    options = {}
    if credential_ref is not None:
        options["credential_ref"] = credential_ref
    if max_output_tokens is not None:
        options["max_output_tokens"] = max_output_tokens
    return build_structured_output_client(
        provider=provider,
        model=model,
        provider_retries=False,
        **options,
    )


class StructuredOutputModelAdapter:
    """Invoke one provider family; routing remains entirely outside this adapter."""

    def __init__(
        self,
        *,
        adapter_id: str,
        provider_id: str,
        client_factory: StructuredClientFactory = _default_client_factory,
        target_client_factory: Callable | None = None,
    ) -> None:
        self.adapter_id = _required_text(adapter_id, field="adapter_id").casefold()
        self.provider_id = _required_text(provider_id, field="provider_id").casefold()
        self._client_factory = client_factory
        self._target_client_factory = target_client_factory
        self._clients: dict[tuple, StructuredOutputClient] = {}

    def _client_for(
        self, target: ModelTarget, *, max_output_tokens: int | None = None
    ) -> StructuredOutputClient:
        if target.adapter_id != self.adapter_id:
            raise ValueError("target adapter_id does not match invocation adapter")
        if target.provider_id != self.provider_id:
            raise ValueError("target provider_id does not match invocation adapter")
        default = self._client_factory is _default_client_factory
        generation = None
        if default:
            key = (
                require_provider_api_key(
                    target.provider_id, purpose="routed model invocation"
                )
                if target.registry_version == 1 and target.credential_ref is None
                else resolve_target_api_key(target)
            )
            generation = hashlib.sha256(key.encode()).digest()
        cache_key = (
            target.target_id,
            target.model_id,
            target.credential_ref,
            target.registry_version,
            generation,
            max_output_tokens,
        )
        client = self._clients.get(cache_key)
        if client is None:
            if self._target_client_factory is not None:
                client = self._target_client_factory(
                    target=target, max_output_tokens=max_output_tokens
                )
            elif default:
                client = self._client_factory(
                    target.provider_id,
                    target.model_id,
                    credential_ref=target.credential_ref,
                    max_output_tokens=max_output_tokens,
                )
            else:
                if (
                    target.credential_ref == "JARVIS_GEMINI_PAID_API_KEY"
                    or max_output_tokens is not None
                ):
                    raise PaidBudgetDenied(
                        "Legacy client factory cannot attest Paid credential/output bounds"
                    )
                client = self._client_factory(target.provider_id, target.model_id)
            self._clients[cache_key] = client
        if client.provider_name.strip().casefold() != target.provider_id:
            raise ValueError("structured client provider does not match target")
        if client.model_name.strip() != target.model_id:
            raise ValueError("structured client model does not match target")
        return client

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
        request_context: ModelInvocationContext | ScopedModelInvocationContext,
        max_output_tokens: int | None = None,
    ) -> StructuredOutputTelemetry:
        if not isinstance(target, ModelTarget):
            raise TypeError("target must be a ModelTarget")
        if not isinstance(
            request_context, (ModelInvocationContext, ScopedModelInvocationContext)
        ):
            raise TypeError("request_context must be a ModelInvocationContext")
        client = self._client_for(target, max_output_tokens=max_output_tokens)
        telemetry = getattr(client, "parse_with_telemetry", None)
        if callable(telemetry):
            result = await telemetry(
                system_prompt=system_prompt,
                input_payload=input_payload,
                response_model=response_model,
            )
            if not isinstance(result, StructuredOutputTelemetry):
                raise TypeError("provider telemetry method returned unexpected type")
            return result

        started = time.perf_counter()
        parsed = await client.parse(
            system_prompt=system_prompt,
            input_payload=input_payload,
            response_model=response_model,
        )
        return StructuredOutputTelemetry(
            parsed=parsed,
            usage={},
            usage_observed=False,
            latency_ms=(time.perf_counter() - started) * 1000.0,
        )


class ModelInvoker:
    """Dispatch to the adapter for an already-selected target."""

    def __init__(
        self,
        adapter_registry: ModelAdapterRegistry,
        *,
        paid_budget=None,
        pricing=None,
        clock=time.time,
    ) -> None:
        if not isinstance(adapter_registry, ModelAdapterRegistry):
            raise TypeError("adapter_registry must be a ModelAdapterRegistry")
        self._adapters = adapter_registry
        self.paid_budget = paid_budget
        self.pricing = pricing
        self._clock = clock

    async def invoke_structured(
        self,
        *,
        target: ModelTarget,
        system_prompt: str,
        input_payload: dict[str, Any],
        response_model: type[BaseModel],
        request_context: ModelInvocationContext | ScopedModelInvocationContext,
        exposure: PaidExposure | None = None,
    ) -> BaseModel:
        result = await self.invoke_structured_with_telemetry(
            target=target,
            system_prompt=system_prompt,
            input_payload=input_payload,
            response_model=response_model,
            request_context=request_context,
            exposure=exposure,
        )
        return result.parsed

    async def invoke_structured_with_telemetry(
        self,
        *,
        target,
        system_prompt,
        input_payload,
        response_model,
        request_context,
        exposure=None,
    ) -> StructuredOutputTelemetry:
        if target.credential_ref != "JARVIS_GEMINI_PAID_API_KEY":
            return await self._dispatch_structured(
                target=target,
                system_prompt=system_prompt,
                input_payload=input_payload,
                response_model=response_model,
                request_context=request_context,
            )
        if (
            target.provider_id != "gemini"
            or self.paid_budget is None
            or self.pricing is None
            or not isinstance(exposure, PaidExposure)
        ):
            raise PaidBudgetDenied(
                "Paid inference requires a governor, reviewed pricing and bounded exposure"
            )
        scope = (
            ("work", request_context.work_id)
            if isinstance(request_context, ModelInvocationContext)
            else (request_context.scope_kind, request_context.scope_id)
        )
        if (exposure.scope_kind, exposure.scope_id) != scope:
            raise PaidBudgetDenied("Paid exposure does not match invocation identity")
        if self.paid_budget.store.credential_blocked(target.credential_ref):
            raise PaidBudgetDenied("Paid credential is unavailable")
        free_id = target.target_id.replace(".gemini.paid.", ".gemini.free.")
        pressure = self.paid_budget.store.get_health(free_id)
        if pressure is None or pressure.last_failure_kind not in {
            "quota_exhausted",
            "rate_limited",
        }:
            raise PaidBudgetDenied(
                "No eligible Free pressure authorizes Paid admission"
            )
        if set(exposure.usage_bounds) != {"input_tokens", "output_tokens"}:
            raise PaidBudgetDenied(
                "Structured Paid inference requires priced text-only bounds"
            )
        # A UTF-8 byte bound conservatively covers text tokens; include schema/envelope.
        wire_bytes = (
            len(
                (
                    system_prompt
                    + json.dumps(
                        input_payload, ensure_ascii=False, sort_keys=True, default=str
                    )
                    + json.dumps(response_model.model_json_schema(), ensure_ascii=False)
                ).encode("utf-8")
            )
            + 1024
        )
        if exposure.usage_bounds["input_tokens"] < wire_bytes:
            raise PaidBudgetDenied(
                "Input exposure is smaller than the complete request envelope"
            )
        if sum(exposure.usage_bounds.values()) > target.max_context_tokens:
            raise PaidBudgetDenied("Paid exposure exceeds target context limit")
        adapter = self._adapters.require(target.adapter_id)
        if not isinstance(adapter, StructuredOutputModelAdapter):
            raise PaidBudgetDenied("Adapter cannot attest bounded Paid output")
        bound = exposure.usage_bounds["output_tokens"]
        reservation = self.paid_budget.reserve(
            invocation_id=request_context.attempt_id,
            target=target,
            exposure=exposure,
            pricing=self.pricing,
        )
        try:
            adapter._client_for(target, max_output_tokens=bound)
        except BaseException:
            self.paid_budget.cancel_unsent(reservation.reservation_id)
            raise
        self.paid_budget.mark_dispatched(reservation.reservation_id)
        try:
            result = await self._dispatch_structured(
                target=target,
                system_prompt=system_prompt,
                input_payload=input_payload,
                response_model=response_model,
                request_context=request_context,
                max_output_tokens=bound,
            )
        except BaseException:
            self.paid_budget.settle(
                reservation_id=reservation.reservation_id,
                usage={},
                usage_complete=False,
                event_id=request_context.attempt_id + ":unavailable",
            )
            raise
        usage, complete = _paid_structured_usage(result)
        self.paid_budget.settle(
            reservation_id=reservation.reservation_id,
            usage=usage,
            usage_complete=complete,
            event_id=request_context.attempt_id + ":result",
        )
        return result

    async def invoke_scoped_structured(
        self, *, router, request, system_prompt, input_payload, response_model, exposure
    ):
        from jarvis.chatgpt_plan import ChatGPTPlanError
        from jarvis.model_routing.cost import estimate_usage_cost_usd
        from jarvis.model_routing.eligibility import TargetHealthEligibility
        from jarvis.model_routing.gemini import (
            GeminiFallbackConfig,
            gemini_paid_fallback_allowed,
        )
        from jarvis.model_routing.health import (
            TargetHealthRecord,
            apply_provider_failure,
        )
        from jarvis.model_routing.models import (
            ResponseContractResult,
            RoutingAttemptKind,
            ScopedRoutingAttempt,
            ScopedRoutingRequest,
        )
        from jarvis.provider_resilience import (
            ProviderFailureKind,
            classify_provider_failure,
        )

        if (
            not isinstance(request, ScopedRoutingRequest)
            or not isinstance(exposure, PaidExposure)
            or (request.scope_kind, request.scope_id)
            != (exposure.scope_kind, exposure.scope_id)
        ):
            raise ValueError("Scoped request and exposure identities must match")
        selection = router.route(request)
        store = router.routing_store
        decision = selection.decision
        registry = selection.registry or router.target_registry
        binding = hashlib.sha256(
            json.dumps(
                {
                    "prompt": system_prompt,
                    "payload": input_payload,
                    "schema": response_model.model_json_schema(),
                    "exposure": exposure.to_payload(),
                },
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            ).encode()
        ).hexdigest()
        if not store.claim_scoped_invocation(
            decision_id=decision.decision_id, binding_digest=binding
        ):
            raise PaidOutcomeUnknown(
                "Scoped inference already dispatched or outcome unknown; automatic replay blocked"
            )
        previous_failure = None
        previous_target = None
        total_limit = min(3, decision.fallback_budget + 1)
        for ordinal, target_id in enumerate(
            decision.ordered_target_ids[:total_limit], 1
        ):
            target = registry.require(target_id)
            now = float(self._clock())
            if target.credential_ref == "JARVIS_GEMINI_PAID_API_KEY":
                free = next(
                    (
                        t
                        for t in registry.all()
                        if t.target_id
                        == target.target_id.replace(".gemini.paid.", ".gemini.free.")
                    ),
                    None,
                )
                pressure = None if free is None else store.get_health(free.target_id)
                if previous_failure is not None:
                    eligible = gemini_paid_fallback_allowed(
                        previous_failure, source_target=previous_target
                    )
                else:
                    eligible = (
                        pressure is not None
                        and pressure.last_failure_kind
                        in {"quota_exhausted", "rate_limited"}
                        and pressure.state is TargetHealthEligibility.COOLDOWN
                    )
                if not eligible:
                    raise PaidBudgetDenied(
                        "Selected Paid target has no eligible Free pressure"
                    )
            lease = None
            health = store.get_health(target_id)
            if (
                target.provider_id == "gemini"
                and target.credential_ref == gemini_credential_ref("free")
                and health is not None
                and health.state is TargetHealthEligibility.COOLDOWN
            ):
                lease = store.claim_free_recovery(
                    target_id=target_id,
                    operation_id=request.routing_request_id,
                    now_epoch=now,
                    lease_seconds=60,
                )
                if lease is None:
                    previous_target = target
                    previous_failure = None
                    continue
            attempt_id = f"{decision.decision_id}:{ordinal}"
            context = ScopedModelInvocationContext(
                request.scope_kind,
                request.scope_id,
                request.routing_request_id,
                decision.decision_id,
                attempt_id,
                attempt_id,
            )
            started = float(self._clock())
            result = None
            failure = None
            error = None
            try:
                result = await self.invoke_structured_with_telemetry(
                    target=target,
                    system_prompt=system_prompt,
                    input_payload=input_payload,
                    response_model=response_model,
                    request_context=context,
                    exposure=exposure,
                )
            except (Exception, asyncio.CancelledError) as exc:  # noqa: BLE001 - normalize provider errors and preserve cancellation exposure
                error = exc
                failure = classify_provider_failure(exc, provider=target.provider_id)
                if gemini_paid_fallback_allowed(failure, source_target=target):
                    config = (
                        self.paid_budget.config
                        if self.paid_budget is not None
                        else GeminiFallbackConfig()
                    )
                    store.record_pressure(
                        target=target,
                        failure=failure,
                        config=config,
                        now_epoch=float(self._clock()),
                    )
                elif (
                    target.credential_ref == "JARVIS_GEMINI_PAID_API_KEY"
                    and failure.kind is ProviderFailureKind.BALANCE_EXHAUSTED
                ):
                    store.disable_paid_credential(
                        failure=failure, now_epoch=float(self._clock())
                    )
                elif isinstance(exc, Exception) and not isinstance(
                    exc, PaidBudgetDenied
                ):
                    old = store.get_health(target_id)
                    mutation = apply_provider_failure(
                        old or TargetHealthRecord(target_id),
                        failure,
                        now_epoch=float(self._clock()),
                    )
                    if old is None:
                        store.create_health(mutation.record)
                    else:
                        store.save_health(mutation.record, expected_version=old.version)
            ended = float(self._clock())
            attempts = store.list_scoped_attempts(decision.decision_id)
            store.record_scoped_attempt(
                ScopedRoutingAttempt(
                    scope_kind=request.scope_kind,
                    scope_id=request.scope_id,
                    attempt_id=attempt_id,
                    decision_id=decision.decision_id,
                    target_id=target_id,
                    attempt_ordinal=len(attempts) + 1,
                    started_at_epoch=started,
                    ended_at_epoch=ended,
                    kind=RoutingAttemptKind.PRIMARY
                    if ordinal == 1
                    else RoutingAttemptKind.FALLBACK,
                    latency_ms=0 if result is None else result.latency_ms,
                    failure_class=(
                        "paid_admission_denied"
                        if isinstance(error, PaidBudgetDenied)
                        else None
                        if failure is None
                        else failure.kind.value
                    ),
                    provider_id=target.provider_id,
                    model_id=target.model_id,
                    usage={} if result is None else result.usage,
                    usage_observed=False if result is None else result.usage_observed,
                    estimated_cost_usd=None
                    if result is None
                    else estimate_usage_cost_usd(
                        target, _paid_structured_usage(result)[0]
                    ),
                    response_contract_result=ResponseContractResult.VALID
                    if result is not None
                    else ResponseContractResult.UNKNOWN,
                    correlation_key=attempt_id,
                )
            )
            if result is not None:
                if lease is not None:
                    store.complete_free_recovery(lease, now_epoch=ended)
                store.finish_scoped_invocation(decision_id=decision.decision_id)
                return result
            if lease is not None:
                store.release_free_recovery(lease)
            if not isinstance(error, Exception):
                raise error
            if isinstance(error, PaidBudgetDenied):
                raise error
            if target.credential_ref == "JARVIS_GEMINI_PAID_API_KEY":
                raise RoutedInferenceFailure(failure) from None
            if not gemini_paid_fallback_allowed(failure, source_target=target) and not (
                target.provider_id == "chatgpt_plan"
                and isinstance(error, ChatGPTPlanError)
            ):
                raise RoutedInferenceFailure(failure) from None
            previous_failure, previous_target = failure, target
        raise PaidBudgetDenied("No eligible bounded inference target remains")

    async def _dispatch_structured(
        self,
        *,
        target: ModelTarget,
        system_prompt: str,
        input_payload: dict[str, Any],
        response_model: type[BaseModel],
        request_context: ModelInvocationContext | ScopedModelInvocationContext,
        max_output_tokens: int | None = None,
    ) -> StructuredOutputTelemetry:
        adapter = self._adapters.require(target.adapter_id)
        options = (
            {}
            if max_output_tokens is None
            else {"max_output_tokens": max_output_tokens}
        )
        telemetry = getattr(adapter, "invoke_structured_with_telemetry", None)
        if callable(telemetry):
            result = await telemetry(
                target=target,
                system_prompt=system_prompt,
                input_payload=input_payload,
                response_model=response_model,
                request_context=request_context,
                **options,
            )
            if not isinstance(result, StructuredOutputTelemetry):
                raise TypeError(
                    "model adapter telemetry method returned unexpected type"
                )
            return result

        started = time.perf_counter()
        parsed = await adapter.invoke_structured(
            target=target,
            system_prompt=system_prompt,
            input_payload=input_payload,
            response_model=response_model,
            request_context=request_context,
        )
        return StructuredOutputTelemetry(
            parsed=parsed,
            usage={},
            usage_observed=False,
            latency_ms=(time.perf_counter() - started) * 1000.0,
        )


def build_default_model_adapter_registry(
    *,
    ollama_residency_manager: LocalModelResidencyManager | None = None,
    chatgpt_plan_session_manager: ChatGPTPlanSessionManager | None = None,
) -> ModelAdapterRegistry:
    """Register approved provider families without activating unused runtimes."""

    adapters = [
        StructuredOutputModelAdapter(
            adapter_id="gemini",
            provider_id="gemini",
        ),
        StructuredOutputModelAdapter(
            adapter_id="openai",
            provider_id="openai",
        ),
        OllamaStructuredOutputAdapter(
            residency_manager=ollama_residency_manager,
        ),
    ]
    if chatgpt_plan_session_manager is not None:

        def _chatgpt_plan_client_factory(
            provider: str,
            model: str,
        ) -> StructuredOutputClient:
            if provider.strip().casefold() != "chatgpt_plan":
                raise ValueError("ChatGPT-plan adapter received a different provider")
            return build_chatgpt_plan_structured_output_client(
                model=model,
                session_manager=chatgpt_plan_session_manager,
                provider_retries=False,
            )

        adapters.append(
            StructuredOutputModelAdapter(
                adapter_id="chatgpt_plan",
                provider_id="chatgpt_plan",
                client_factory=_chatgpt_plan_client_factory,
            )
        )
    return ModelAdapterRegistry(tuple(adapters))


def _paid_structured_usage(
    result: StructuredOutputTelemetry,
) -> tuple[dict[str, int], bool]:
    """Price full generated tokens including thought; cache discounts are conservative."""
    usage = result.usage
    incoming, output, total = (
        usage.get(k) for k in ("input_tokens", "output_tokens", "total_tokens")
    )
    if (
        not result.usage_observed
        or incoming is None
        or output is None
        or usage.get("tool_use_tokens", 0) > 0
    ):
        return {}, False
    if total is not None and total >= incoming + output:
        generated = max(total - incoming, output + usage.get("reasoning_tokens", 0))
    elif "reasoning_tokens" in usage:
        generated = output + usage["reasoning_tokens"]
    else:
        return {}, False
    return {"input_tokens": incoming, "output_tokens": generated}, True
