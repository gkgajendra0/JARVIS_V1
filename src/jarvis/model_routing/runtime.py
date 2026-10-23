"""Composition of existing routing services shared by inference lanes."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, replace

from jarvis.ai_provider import (
    gemini_credential_ref,
    provider_api_key,
    resolve_ai_role_model,
    resolve_target_api_key,
)
from jarvis.model_routing.budget import PaidBudgetGovernor
from jarvis.model_routing.gemini import GeminiFallbackConfig, build_gemini_role_targets
from jarvis.model_routing.invoker import (
    ModelInvoker,
    build_default_model_adapter_registry,
)
from jarvis.model_routing.pricing import PricingSnapshot, PricingUnavailable
from jarvis.model_routing.registry import ModelTargetRegistry, RoutingStrategyRegistry
from jarvis.model_routing.router import ModelRouter, build_default_work_targets
from jarvis.model_routing.store import ModelRoutingStore
from jarvis.model_routing.strategy import EngineeringStageStrategy


@dataclass(slots=True)
class RoutingRuntime:
    router: ModelRouter
    store: ModelRoutingStore
    invoker: ModelInvoker
    paid_budget: PaidBudgetGovernor
    primary_target_id: str
    config: GeminiFallbackConfig
    prices: dict
    clock: Callable
    pricing_error: str | None = None

    @property
    def work_store(self):
        return self.store.work_store

    def pricing_for(self, target):
        if target.pricing_ref is not None:
            return self.store.get_pricing_snapshot(target.pricing_ref)
        service = "live" if "realtime_voice" in target.capabilities else "structured"
        return self.prices.get((target.model_id, service))

    def targets_for(self, role, model):
        targets = build_gemini_role_targets(
            role=role, model=model, adapter_id="gemini", config=self.config
        )
        result = []
        for target in targets:
            price = self.pricing_for(target)
            if (
                target.credential_ref == gemini_credential_ref("paid")
                and price is not None
            ):
                target = replace(
                    target,
                    cost_profile=price.profile,
                    pricing_ref=self.store.save_pricing_snapshot(price),
                )
            result.append(target)
        return tuple(result)


def _reviewed_prices(path, now):
    if path is None:
        return {}, "pricing_not_configured"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and "prices" in payload:
            if (
                set(payload) != {"schema_version", "prices"}
                or type(payload["schema_version"]) is not int
                or payload["schema_version"] != 1
                or not isinstance(payload["prices"], list)
                or not 1 <= len(payload["prices"]) <= 128
            ):
                raise PricingUnavailable("Invalid reviewed pricing catalog")
            entries = payload["prices"]
        else:
            entries = [payload]
        prices = {}
        for entry in entries:
            price = PricingSnapshot.from_payload(entry)
            price.validate_at(now)
            key = (price.model_id, price.service_key)
            if key in prices:
                raise PricingUnavailable("Ambiguous reviewed model price")
            prices[key] = price
        return prices, None
    except (OSError, ValueError, TypeError):
        return {}, "reviewed_pricing_unavailable"


def build_routing_runtime(
    *,
    work_store,
    provider,
    model,
    config: GeminiFallbackConfig,
    chatgpt_plan_session=None,
    chatgpt_plan_model=None,
    clock=time.time,
):
    adapters = build_default_model_adapter_registry(
        chatgpt_plan_session_manager=chatgpt_plan_session
    )
    legacy = build_default_work_targets(
        configured_provider=provider,
        configured_model=model,
        adapter_registry=adapters,
        chatgpt_plan_enabled=chatgpt_plan_session is not None,
        chatgpt_plan_model=chatgpt_plan_model,
    )
    store = ModelRoutingStore(work_store)
    budget = PaidBudgetGovernor(store, config=config, clock=clock)
    prices, error = (
        _reviewed_prices(config.pricing_path, float(clock()))
        if config.enabled
        else ({}, None)
    )

    def credential_available(target):
        if target.provider_id == "chatgpt_plan":
            return (
                chatgpt_plan_session is not None and chatgpt_plan_session.is_connected()
            )
        try:
            if target.credential_ref is not None:
                return bool(resolve_target_api_key(target))
            return provider_api_key(target.provider_id) is not None
        except (RuntimeError, ValueError, KeyError, TypeError):
            return False

    router = ModelRouter(
        target_registry=legacy.registry,
        adapter_registry=adapters,
        strategy_registry=RoutingStrategyRegistry((EngineeringStageStrategy(),)),
        routing_store=store,
        credential_available=credential_available,
        clock=clock,
    )
    invoker = ModelInvoker(adapters, paid_budget=budget, clock=clock)
    runtime = RoutingRuntime(
        router,
        store,
        invoker,
        budget,
        legacy.primary_target_id,
        config,
        prices,
        clock,
        error,
    )
    invoker.pricing = runtime.pricing_for
    if config.enabled and provider == "gemini":
        model_name = resolve_ai_role_model(
            provider, "work_orchestration", configured_model=model
        )
        pair = runtime.targets_for("work", model_name)
        # Retain approved non-Gemini fallbacks, including configured plan priority.
        others = tuple(
            replace(t, registry_version=2)
            for t in legacy.registry.all()
            if t.provider_id != "gemini"
        )
        primary = (
            legacy.primary_target_id
            if chatgpt_plan_session is not None
            else pair[0].target_id
        )
        router = ModelRouter(
            target_registry=ModelTargetRegistry(adapters, (*pair, *others)),
            adapter_registry=adapters,
            strategy_registry=runtime.router.strategy_registry,
            routing_store=store,
            credential_available=credential_available,
            clock=clock,
            fallback_budget=2,
            historical_registries={legacy.registry.digest(): legacy.registry},
        )
        runtime.router = router
        runtime.primary_target_id = primary
    return runtime
