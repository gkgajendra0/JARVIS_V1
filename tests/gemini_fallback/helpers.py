from jarvis.model_routing.gemini import GeminiFallbackConfig, build_gemini_role_targets
from jarvis.model_routing.models import (
    EvidenceSizeClass,
    LocalityRequirement,
    PrivacyClass,
    RoutingStrategyResult,
)
from jarvis.model_routing.registry import (
    ModelAdapterRegistry,
    ModelTargetRegistry,
    RoutingStrategyRegistry,
)
from jarvis.model_routing.router import ModelRouter
from jarvis.model_routing.store import ModelRoutingStore
from jarvis.work.store import SQLiteWorkStore


class Adapter:
    adapter_id = "gemini"

    async def invoke_structured(self, **kwargs):
        raise AssertionError("No provider invocation expected in routing tests")


class Strategy:
    strategy_key = "test_slots"
    strategy_version = 1
    strategy_digest = "d" * 64

    def rank(self, *, request, eligible_targets, history):
        return RoutingStrategyResult(
            ordered_target_ids=tuple(t.target_id for t in eligible_targets),
            reason_codes=("test_slots",),
            selected_role="efficient",
        )


def make_router(tmp_path, *, model="gemini-test", historical_registries=None):
    adapters = ModelAdapterRegistry((Adapter(),))
    targets = build_gemini_role_targets(
        role="work",
        model=model,
        adapter_id="gemini",
        config=GeminiFallbackConfig(enabled=True),
    )
    registry = ModelTargetRegistry(adapters, targets)
    store = ModelRoutingStore(SQLiteWorkStore(tmp_path / "routing.db"))
    kwargs = (
        {}
        if historical_registries is None
        else {"historical_registries": historical_registries}
    )
    router = ModelRouter(
        target_registry=registry,
        adapter_registry=adapters,
        strategy_registry=RoutingStrategyRegistry((Strategy(),)),
        routing_store=store,
        credential_available=lambda t: True,
        clock=lambda: 100,
        **kwargs,
    )
    return router, store


def scoped_request(**changes):
    from jarvis.model_routing.models import ScopedRoutingRequest

    values = {
        "routing_request_id": "scope-request-1",
        "scope_kind": "memory",
        "scope_id": "source-1",
        "task_kind": "memory",
        "strategy_key": "test_slots",
        "strategy_version": 1,
        "required_capabilities": ("structured_output",),
        "privacy_class": PrivacyClass.STANDARD,
        "locality_requirement": LocalityRequirement.ANY,
        "estimated_context_tokens": 100,
        "evidence_size_class": EvidenceSizeClass.SMALL,
        "recent_progress_signals": (),
        "recent_failure_signals": (),
        "latency_preference": "balanced",
        "cost_preference": "low",
    }
    values.update(changes)
    return ScopedRoutingRequest(**values)


def budget_fixture(path, *, ceiling=35000):
    from decimal import Decimal

    from jarvis.model_routing.budget import PaidBudgetGovernor
    from jarvis.model_routing.models import CostProfile
    from jarvis.model_routing.pricing import PricingSnapshot

    config = GeminiFallbackConfig(enabled=True, ceiling_inr_minor=ceiling)
    store = ModelRoutingStore(SQLiteWorkStore(path))
    profile = CostProfile(
        profile_id="synthetic-test-price",
        version=1,
        effective_from_epoch=0,
        effective_to_epoch=1000,
        input_usd_per_million_tokens=200,
        output_usd_per_million_tokens=200,
    )
    pricing = PricingSnapshot(
        profile=profile,
        model_id="gemini-budget-test",
        service_key="structured",
        source="synthetic:test-only",
        inr_per_usd=Decimal(100),
        fx_source="synthetic:test-only",
        fx_version="test-fx-v1",
        fx_effective_from_epoch=0,
        fx_effective_to_epoch=1000,
    )
    target = build_gemini_role_targets(
        role="memory.extraction",
        model="gemini-budget-test",
        adapter_id="gemini",
        config=config,
        cost_profile=profile,
    )[1]
    return (
        PaidBudgetGovernor(store, config=config, clock=lambda: 100),
        store,
        target,
        pricing,
    )


def exposure(input_tokens=5000, output_tokens=5000, *, scope_id="source-budget"):
    from jarvis.model_routing.pricing import PaidExposure

    return PaidExposure(
        usage_bounds={"input_tokens": input_tokens, "output_tokens": output_tokens},
        scope_kind="memory",
        scope_id=scope_id,
    )
