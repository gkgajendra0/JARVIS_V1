import json

from tests.gemini_fallback.helpers import budget_fixture

from jarvis.model_routing.gemini import GeminiFallbackConfig
from jarvis.model_routing.router import build_work_routing_request
from jarvis.work.brain import BrainAction, BrainRequest
from jarvis.work.models import WorkItem, WorkType


def test_shared_runtime_keeps_v1_disabled_and_optin_uses_v2(tmp_path, monkeypatch):
    from jarvis.model_routing.runtime import build_routing_runtime

    _, store, _, price = budget_fixture(tmp_path / "routing.db")
    monkeypatch.setenv("GOOGLE_API_KEY", "free-synthetic")
    monkeypatch.setenv("JARVIS_GEMINI_PAID_API_KEY", "paid-synthetic")
    disabled = build_routing_runtime(
        work_store=store.work_store,
        provider="gemini",
        model="gemini-budget-test",
        config=GeminiFallbackConfig(),
        clock=lambda: 100,
    )
    assert disabled.primary_target_id == "work.gemini.default"
    assert all(t.registry_version == 1 for t in disabled.router.target_registry.all())
    file = tmp_path / "prices.json"
    file.write_text(json.dumps(price.to_payload()), encoding="utf-8")
    enabled = build_routing_runtime(
        work_store=store.work_store,
        provider="gemini",
        model="gemini-budget-test",
        config=GeminiFallbackConfig(enabled=True, pricing_path=file),
        clock=lambda: 100,
    )
    work = WorkItem(
        request="fictional",
        work_type=WorkType.GENERIC,
        source_session_id="session",
        source_turn_id="turn",
    )
    store.work_store.create(work)
    request = BrainRequest(
        work=work,
        recent_steps=(),
        purpose="answer",
        allowed_actions=(
            BrainAction(
                name="record",
                description="fictional bounded action",
                parameter_schema={"type": "object"},
            ),
        ),
    )
    chosen = enabled.router.route(
        build_work_routing_request(request, primary_target_id=enabled.primary_target_id)
    )
    assert chosen.target.credential_ref == "GOOGLE_API_KEY"
    assert all(t.registry_version == 2 for t in enabled.router.target_registry.all())
    assert enabled.store.work_store is store.work_store
    assert enabled.invoker.paid_budget is enabled.paid_budget


def test_configured_chatgpt_plan_stays_primary_without_network_discovery(
    tmp_path, monkeypatch
):
    from jarvis.model_routing.runtime import build_routing_runtime

    _, store, _, _ = budget_fixture(tmp_path / "routing.db")
    monkeypatch.setenv("GOOGLE_API_KEY", "free-synthetic")
    monkeypatch.setenv("JARVIS_GEMINI_PAID_API_KEY", "paid-synthetic")

    class Connected:
        def is_connected(self):
            return True

    runtime = build_routing_runtime(
        work_store=store.work_store,
        provider="gemini",
        model="gemini-budget-test",
        config=GeminiFallbackConfig(enabled=True),
        chatgpt_plan_session=Connected(),
        chatgpt_plan_model="gpt-test",
        clock=lambda: 100,
    )
    work = WorkItem(
        request="fictional",
        work_type=WorkType.GENERIC,
        source_session_id="session",
        source_turn_id="turn",
    )
    store.work_store.create(work)
    request = BrainRequest(
        work=work,
        recent_steps=(),
        purpose="answer",
        allowed_actions=(
            BrainAction(
                name="record",
                description="fictional bounded action",
                parameter_schema={"type": "object"},
            ),
        ),
    )
    selected = runtime.router.route(
        build_work_routing_request(request, primary_target_id=runtime.primary_target_id)
    )
    assert selected.target.provider_id == "chatgpt_plan"
    assert len(selected.decision.ordered_target_ids) == 3
    assert selected.decision.fallback_budget == 2


def test_reviewed_catalog_pins_independent_model_prices_without_probes(
    tmp_path, monkeypatch
):
    from dataclasses import replace

    from jarvis.model_routing.runtime import build_routing_runtime

    _, store, _, price = budget_fixture(tmp_path / "routing.db")
    other = replace(
        price,
        model_id="gemini-other",
        profile=replace(price.profile, profile_id="other-price"),
    )
    file = tmp_path / "catalog.json"
    file.write_text(
        json.dumps(
            {"schema_version": 1, "prices": [price.to_payload(), other.to_payload()]}
        ),
        encoding="utf-8",
    )
    runtime = build_routing_runtime(
        work_store=store.work_store,
        provider="gemini",
        model="gemini-budget-test",
        config=GeminiFallbackConfig(enabled=True, pricing_path=file),
        clock=lambda: 100,
    )
    target = next(
        t
        for t in runtime.router.target_registry.all()
        if t.credential_ref == "JARVIS_GEMINI_PAID_API_KEY"
    )
    assert runtime.pricing_for(target).model_id == "gemini-budget-test"
    from jarvis.model_routing.gemini import build_gemini_role_targets

    another = build_gemini_role_targets(
        role="memory.extraction",
        model="gemini-other",
        adapter_id="gemini",
        config=GeminiFallbackConfig(enabled=True),
    )[1]
    assert runtime.pricing_for(another).profile.profile_id == "other-price"


def test_work_target_pins_price_fx_across_runtime_restart(tmp_path, monkeypatch):
    from dataclasses import replace
    from decimal import Decimal

    from jarvis.model_routing.runtime import build_routing_runtime

    _, store, _, price = budget_fixture(tmp_path / "routing.db")
    file = tmp_path / "price.json"
    file.write_text(json.dumps(price.to_payload()), encoding="utf-8")
    config = GeminiFallbackConfig(enabled=True, pricing_path=file)
    first = build_routing_runtime(
        work_store=store.work_store,
        provider="gemini",
        model="gemini-budget-test",
        config=config,
        clock=lambda: 100,
    )
    old = next(
        t
        for t in first.router.target_registry.all()
        if t.credential_ref == "JARVIS_GEMINI_PAID_API_KEY"
    )
    file.write_text(
        json.dumps(
            replace(price, inr_per_usd=Decimal(110), fx_version="new-fx").to_payload()
        ),
        encoding="utf-8",
    )
    second = build_routing_runtime(
        work_store=store.work_store,
        provider="gemini",
        model="gemini-budget-test",
        config=config,
        clock=lambda: 100,
    )
    assert second.pricing_for(old).inr_per_usd == Decimal(100)
    new = next(
        t
        for t in second.router.target_registry.all()
        if t.credential_ref == "JARVIS_GEMINI_PAID_API_KEY"
    )
    assert old.pricing_ref != new.pricing_ref
    assert second.pricing_for(new).inr_per_usd == Decimal(110)


def test_global_deterministic_work_bypasses_enabled_free_paid_path(
    tmp_path, monkeypatch
):
    import asyncio

    from jarvis.brain_routing.deterministic import default_work_deterministic_resolvers
    from jarvis.brain_routing.store import BrainRouteStore
    from jarvis.brain_routing.work import GlobalBrainRouterReasoner
    from jarvis.model_routing.runtime import build_routing_runtime
    from jarvis.work.reasoner import RoutedWorkReasoner

    _, store, _, _ = budget_fixture(tmp_path / "routing.db")
    runtime = build_routing_runtime(
        work_store=store.work_store,
        provider="gemini",
        model="gemini-budget-test",
        config=GeminiFallbackConfig(enabled=True),
        clock=lambda: 100,
    )
    work = WorkItem(
        request="fictional development",
        work_type=WorkType.DEVELOPMENT,
        source_session_id="session",
        source_turn_id="turn",
    )
    store.work_store.create(work)
    model = RoutedWorkReasoner(
        router=runtime.router,
        invoker=runtime.invoker,
        primary_target_id=runtime.primary_target_id,
    )
    global_reasoner = GlobalBrainRouterReasoner(
        model,
        work_store=store.work_store,
        route_store=BrainRouteStore(store.work_store),
        model_routing_store=runtime.store,
        resolvers=default_work_deterministic_resolvers(),
        mode="apply",
    )
    request = BrainRequest(
        work=work,
        recent_steps=(),
        purpose="prepare",
        allowed_actions=(
            BrainAction(
                name="dev_prepare_workspace",
                description="prepare",
                parameter_schema={"type": "object"},
            ),
        ),
    )
    result = asyncio.run(global_reasoner.decide(request))
    assert result.action == "dev_prepare_workspace"
    assert runtime.store.list_attempts_for_work(work.work_id) == ()
    assert runtime.paid_budget.status().spent_inr_minor == 0
