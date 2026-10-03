from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.brain_routing.deterministic import (
    DeterministicResolution,
    DeterministicResolutionStatus,
    DeterministicResolverRegistry,
    InitialDevelopmentWorkspaceResolver,
    default_work_deterministic_resolvers,
)
from jarvis.brain_routing.models import (
    BrainRouteKind,
    BrainRoutingMode,
    GlobalBrainRouteFacts,
    project_global_facts_to_model_request,
)
from jarvis.brain_routing.store import BrainRouteStore
from jarvis.brain_routing.work import GlobalBrainRouterReasoner
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.model_routing.eligibility import EligibilityPolicy
from jarvis.model_routing.models import (
    BenchmarkStatus,
    EligibilitySnapshot,
    EvidenceSizeClass,
    LocalityRequirement,
    ModelLocality,
    ModelTarget,
    PrivacyClass,
    RoutingDecision,
    RoutingStrategyResult,
)
from jarvis.model_routing.registry import (
    ModelAdapterRegistry,
    ModelTargetRegistry,
    RoutingStrategyRegistry,
)
from jarvis.model_routing.router import ModelRouter, build_work_routing_request
from jarvis.model_routing.store import ModelRoutingStore
from jarvis.work.brain import BrainAction, BrainCoordinator, BrainDecision, BrainRequest
from jarvis.work.context import WorkContextAssembler, WorkContextMode
from jarvis.work.engine import WorkActionRegistry, WorkEngine
from jarvis.work.models import WorkItem, WorkStep, WorkType
from jarvis.work.store import SQLiteWorkStore


class CountingReasoner:
    def __init__(self, decision: BrainDecision | None = None) -> None:
        self.calls = 0
        self.decision = decision or BrainDecision(
            action="dev_list_files",
            summary="Model selected list files",
        )

    async def decide(self, request: BrainRequest) -> BrainDecision:
        del request
        self.calls += 1
        return self.decision


def _work(
    store: SQLiteWorkStore,
    *,
    work_type: WorkType = WorkType.DEVELOPMENT,
) -> WorkItem:
    item = WorkItem(
        request="Perform the next bounded step",
        work_type=work_type,
        source_session_id="session-c3",
        source_turn_id="turn-c3",
    )
    store.create(item)
    return item


def _request(
    work: WorkItem,
    *actions: str,
    recent_steps: tuple[WorkStep, ...] = (),
    context_mode: WorkContextMode = WorkContextMode.OFF,
    context_pack=None,
) -> BrainRequest:
    return BrainRequest(
        work=work,
        recent_steps=recent_steps,
        purpose="choose the next bounded step",
        allowed_actions=tuple(
            BrainAction(
                name=action,
                description=f"Execute {action}",
                parameter_schema={"type": "object", "additionalProperties": False},
            )
            for action in actions
        ),
        context_mode=context_mode,
        context_pack=context_pack,
    )


def _router(
    tmp_path: Path,
    *,
    work_type: WorkType = WorkType.DEVELOPMENT,
    model_decision: BrainDecision | None = None,
    mode: str = "apply",
    resolvers: DeterministicResolverRegistry | None = None,
):
    store = SQLiteWorkStore(tmp_path / "work.sqlite")
    work = _work(store, work_type=work_type)
    route_store = BrainRouteStore(store)
    model_store = ModelRoutingStore(store)
    model = CountingReasoner(model_decision)
    router = GlobalBrainRouterReasoner(
        model,
        work_store=store,
        route_store=route_store,
        model_routing_store=model_store,
        resolvers=resolvers or default_work_deterministic_resolvers(),
        mode=mode,
        clock=lambda: 100.0,
    )
    return store, work, route_store, model_store, model, router


@pytest.mark.asyncio
async def test_apply_mode_bypasses_model_for_initial_workspace(
    tmp_path: Path,
) -> None:
    _store, work, route_store, model_store, model, router = _router(tmp_path)

    decision = await router.decide(_request(work, "dev_prepare_workspace"))

    assert decision.action == "dev_prepare_workspace"
    assert decision.parameters == {}
    assert model.calls == 0
    assert model_store.list_attempts_for_work(work.work_id) == ()
    summary = route_store.summary_for_work(work.work_id)
    assert summary == {
        "route_count": 1,
        "deterministic_routes": 1,
        "model_routes": 0,
        "model_calls_avoided": 1,
        "shadow_matches": 0,
        "shadow_mismatches": 0,
    }
    record = route_store.list_for_work(work.work_id)[0]
    assert record.route_kind is BrainRouteKind.DETERMINISTIC
    assert record.resolver_id == "work.development.initial_workspace"
    assert record.outcome_code == "model_bypassed"


class _PrepareWorkspaceExecutor:
    descriptor = BrainAction(
        name="dev_prepare_workspace",
        description="Prepare the isolated workspace",
        parameter_schema={"type": "object", "additionalProperties": False},
    )
    work_types = frozenset({WorkType.DEVELOPMENT})

    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, *, work: WorkItem, parameters: dict) -> dict:
        del work
        assert parameters == {}
        self.calls += 1
        return {"prepared": True, "verified": True}


@pytest.mark.asyncio
async def test_work_engine_apply_cycle_executes_deterministically_without_model(
    tmp_path: Path,
) -> None:
    store, work, route_store, _, model, router = _router(tmp_path)
    executor = _PrepareWorkspaceExecutor()
    engine = WorkEngine(
        store=store,
        brain=BrainCoordinator(router),
        actions=WorkActionRegistry((executor,)),
    )

    result = await engine.advance(work.work_id)

    assert result.progressed is True
    assert executor.calls == 1
    assert model.calls == 0
    steps = store.list_steps(work.work_id)
    assert len(steps) == 1
    assert steps[0].kind == "dev_prepare_workspace"
    assert steps[0].observation["prepared"] is True
    assert route_store.summary_for_work(work.work_id)["model_calls_avoided"] == 1


@pytest.mark.asyncio
async def test_shadow_mode_preserves_model_behavior_and_records_match(
    tmp_path: Path,
) -> None:
    model_decision = BrainDecision(
        action="dev_prepare_workspace",
        summary="Model agrees",
    )
    store, work, route_store, _, model, router = _router(
        tmp_path,
        mode="shadow",
        model_decision=model_decision,
    )
    context_pack = WorkContextAssembler().build(work=work, steps=())

    decision = await router.decide(
        _request(
            work,
            "dev_prepare_workspace",
            context_mode=WorkContextMode.SHADOW,
            context_pack=context_pack,
        )
    )

    assert decision == model_decision
    assert model.calls == 1
    record = route_store.list_for_work(work.work_id)[0]
    assert record.route_kind is BrainRouteKind.MODEL
    assert record.shadow_proposed_action == "dev_prepare_workspace"
    assert record.shadow_match is True
    assert record.reason_codes == ("shadow_deterministic_match",)
    assert record.goal_complete is False
    assert record.needs_owner is False
    assert record.owner_question is None
    assert record.parameters_digest == canonical_digest({})

    snapshot = route_store.get_context_snapshot(record.route_request_id)
    assert snapshot is not None
    assert snapshot["schema"] == "c6_work_reasoning_snapshot.v1"
    assert snapshot["work_version"] == work.version
    assert snapshot["work_state"] == work.state.value
    assert snapshot["history_step_count"] == 0
    assert snapshot["recent_step_ids"] == []
    assert snapshot["context_version"] == context_pack.version
    assert snapshot["history_step_ids_digest"] == canonical_digest([])
    assert snapshot["allowed_actions"][0]["name"] == "dev_prepare_workspace"
    assert store.list_steps(work.work_id) == ()


@pytest.mark.asyncio
async def test_shadow_mode_records_mismatch_without_overriding_model(
    tmp_path: Path,
) -> None:
    model_decision = BrainDecision(
        action="dev_list_files",
        summary="Model chose inspection",
    )
    _, work, route_store, _, model, router = _router(
        tmp_path,
        mode="shadow",
        model_decision=model_decision,
    )

    decision = await router.decide(
        _request(work, "dev_prepare_workspace", "dev_list_files")
    )

    assert decision.action == "dev_list_files"
    assert model.calls == 1
    record = route_store.list_for_work(work.work_id)[0]
    assert record.shadow_match is False
    assert record.reason_codes == ("shadow_deterministic_mismatch",)


@pytest.mark.asyncio
async def test_model_route_persists_owner_wait_decision_fingerprint(
    tmp_path: Path,
) -> None:
    model_decision = BrainDecision(
        action=None,
        summary="Protected pairing input is required.",
        needs_owner=True,
        owner_question="Enter the pairing PIN.",
    )
    _, work, route_store, _, model, router = _router(
        tmp_path,
        mode="shadow",
        model_decision=model_decision,
    )

    decision = await router.decide(_request(work, "dev_prepare_workspace"))

    assert decision == model_decision
    assert model.calls == 1
    record = route_store.list_for_work(work.work_id)[0]
    assert record.route_kind is BrainRouteKind.MODEL
    assert record.selected_action is None
    assert record.goal_complete is False
    assert record.needs_owner is True
    assert record.owner_question == "Enter the pairing PIN."
    assert record.parameters_digest == canonical_digest({})


@pytest.mark.asyncio
async def test_off_mode_is_clean_rollback_to_model_reasoner(tmp_path: Path) -> None:
    _, work, route_store, _, model, router = _router(
        tmp_path,
        mode="off",
    )

    decision = await router.decide(
        _request(work, "dev_prepare_workspace", "dev_list_files")
    )

    assert decision.action == "dev_list_files"
    assert model.calls == 1
    record = route_store.list_for_work(work.work_id)[0]
    assert record.mode is BrainRoutingMode.OFF
    assert record.route_kind is BrainRouteKind.MODEL
    assert record.reason_codes == ("global_router_off",)


@pytest.mark.asyncio
async def test_preexisting_phase4_route_pins_retry_to_model_path(
    tmp_path: Path,
) -> None:
    _, work, route_store, model_store, model, router = _router(tmp_path)
    request = _request(work, "dev_prepare_workspace", "dev_list_files")
    model_request = build_work_routing_request(
        request,
        primary_target_id="legacy-model",
    )
    eligibility = EligibilitySnapshot(
        snapshot_id="eligibility-preexisting",
        routing_request_id=model_request.routing_request_id,
        considered_target_ids=("legacy-model",),
        eligible_target_ids=("legacy-model",),
        exclusions=(),
        target_health_versions={},
        credential_availability={"legacy-model": True},
        required_capabilities=model_request.required_capabilities,
        privacy_class=model_request.privacy_class,
        locality_requirement=model_request.locality_requirement,
        policy_version=1,
        policy_digest="a" * 64,
    )
    model_store.record_decision(
        request=model_request,
        eligibility=eligibility,
        decision=RoutingDecision(
            decision_id="decision-preexisting",
            routing_request_id=model_request.routing_request_id,
            strategy_key=model_request.strategy_key,
            strategy_version=model_request.strategy_version,
            strategy_digest="b" * 64,
            ordered_target_ids=("legacy-model",),
            selected_target_id="legacy-model",
            reason_codes=("preexisting_model_route",),
            selected_role="efficient",
            fallback_budget=0,
            created_at_epoch=99.0,
        ),
        registry_digest="c" * 64,
    )

    decision = await router.decide(request)

    assert decision.action == "dev_list_files"
    assert model.calls == 1
    record = route_store.list_for_work(work.work_id)[0]
    assert record.route_kind is BrainRouteKind.MODEL
    assert record.model_decision_id == "decision-preexisting"
    assert record.model_target_id == "legacy-model"


class _ExplodingResolver:
    resolver_id = "test.exploding"
    resolver_version = 1

    def resolve(self, *, facts, request, all_steps):
        del facts, request, all_steps
        raise AssertionError("resolver must not run while global router is off")


@pytest.mark.asyncio
async def test_off_mode_does_not_execute_deterministic_resolvers(
    tmp_path: Path,
) -> None:
    registry = DeterministicResolverRegistry((_ExplodingResolver(),))
    _, work, _, _, model, router = _router(
        tmp_path,
        mode="off",
        resolvers=registry,
    )

    decision = await router.decide(_request(work, "dev_list_files"))

    assert decision.action == "dev_list_files"
    assert model.calls == 1


@pytest.mark.asyncio
async def test_deterministic_route_replays_without_duplicate_provenance(
    tmp_path: Path,
) -> None:
    _, work, route_store, _, model, router = _router(tmp_path)
    request = _request(work, "dev_prepare_workspace")

    first = await router.decide(request)
    second = await router.decide(request)

    assert first.action == second.action == "dev_prepare_workspace"
    assert model.calls == 0
    assert len(route_store.list_for_work(work.work_id)) == 1


class _AlwaysMatchResolver:
    def __init__(self, resolver_id: str, action: str) -> None:
        self.resolver_id = resolver_id
        self.resolver_version = 1
        self._action = action

    def resolve(self, *, facts, request, all_steps):
        del facts, request, all_steps
        return DeterministicResolution(
            status=DeterministicResolutionStatus.MATCH,
            resolver_id=self.resolver_id,
            resolver_version=1,
            reason_codes=("test_match",),
            decision=BrainDecision(action=self._action, summary="Test decision"),
        )


@pytest.mark.asyncio
async def test_ambiguous_deterministic_matches_fall_back_to_model(
    tmp_path: Path,
) -> None:
    registry = DeterministicResolverRegistry(
        (
            _AlwaysMatchResolver("test.one", "dev_prepare_workspace"),
            _AlwaysMatchResolver("test.two", "dev_list_files"),
        )
    )
    _, work, route_store, _, model, router = _router(
        tmp_path,
        resolvers=registry,
    )

    decision = await router.decide(
        _request(work, "dev_prepare_workspace", "dev_list_files")
    )

    assert decision.action == "dev_list_files"
    assert model.calls == 1
    record = route_store.list_for_work(work.work_id)[0]
    assert record.route_kind is BrainRouteKind.MODEL
    assert record.reason_codes == ("deterministic_abstained",)


@pytest.mark.asyncio
async def test_unapproved_deterministic_action_is_rejected(
    tmp_path: Path,
) -> None:
    registry = DeterministicResolverRegistry(
        (_AlwaysMatchResolver("test.bad", "forbidden_action"),)
    )
    _, work, route_store, _, model, router = _router(
        tmp_path,
        resolvers=registry,
    )

    with pytest.raises(ValueError, match="unapproved action"):
        await router.decide(_request(work, "dev_prepare_workspace"))

    assert model.calls == 0
    assert route_store.list_for_work(work.work_id) == ()


@pytest.mark.asyncio
async def test_initial_diagnostic_incident_is_deterministic(tmp_path: Path) -> None:
    _, work, _, _, model, router = _router(
        tmp_path,
        work_type=WorkType.DIAGNOSTICS,
    )

    decision = await router.decide(_request(work, "diag_get_incident"))

    assert decision.action == "diag_get_incident"
    assert model.calls == 0


@pytest.mark.asyncio
async def test_verified_post_test_diff_is_deterministic(tmp_path: Path) -> None:
    store, work, _, _, model, router = _router(tmp_path)
    write = WorkStep(
        work_id=work.work_id,
        kind="dev_write_file",
        summary="Write source",
    )
    store.add_step(write)
    write = write.start().complete({"path": "src/example.py"})
    store.save_step(write)
    tests = WorkStep(
        work_id=work.work_id,
        kind="dev_run_tests",
        summary="Run tests",
    )
    store.add_step(tests)
    tests = tests.start().complete({"passed": True})
    store.save_step(tests)

    decision = await router.decide(
        _request(
            work,
            "dev_diff",
            recent_steps=(write, tests),
        )
    )

    assert decision.action == "dev_diff"
    assert model.calls == 0


def test_default_resolver_registry_is_versioned_and_deterministic() -> None:
    registry = default_work_deterministic_resolvers()

    assert registry.policy_version == 1
    assert len(registry.digest()) == 64
    assert registry.digest() == default_work_deterministic_resolvers().digest()


def test_individual_resolvers_abstain_after_action_was_attempted() -> None:
    work = WorkItem(
        request="Continue work",
        work_type=WorkType.DEVELOPMENT,
        source_session_id="session",
        source_turn_id="turn",
    )
    attempted = WorkStep(
        work_id=work.work_id,
        kind="dev_prepare_workspace",
        summary="Already attempted",
    )
    request = _request(work, "dev_prepare_workspace")
    facts = GlobalBrainRouteFacts(
        route_request_id="route",
        scope_id=work.work_id,
        subsystem_key="work",
        task_kind="development",
        required_capabilities=("engineering_reasoning",),
        privacy_class=PrivacyClass.STANDARD,
        locality_requirement=LocalityRequirement.ANY,
        estimated_context_tokens=1,
        evidence_size_class=EvidenceSizeClass.SMALL,
        latency_preference="balanced",
        cost_preference="balanced",
        output_contract="brain_decision.v1",
        quality_class="balanced",
        knowledge_state="no_evidence",
    )

    result = InitialDevelopmentWorkspaceResolver().resolve(
        facts=facts,
        request=request,
        all_steps=(attempted,),
    )

    assert result.matched is False


class _NoopAdapter:
    adapter_id = "local_memory"


class _MemoryStrategy:
    strategy_key = "memory_global"
    strategy_version = 1
    strategy_digest = "a" * 64

    def rank(self, *, request, eligible_targets, history=None):
        del request, history
        return RoutingStrategyResult(
            ordered_target_ids=tuple(target.target_id for target in eligible_targets),
            reason_codes=("memory_test_route",),
            selected_role="efficient",
        )


def test_non_engineering_global_facts_project_into_same_model_router(
    tmp_path: Path,
) -> None:
    store = SQLiteWorkStore(tmp_path / "memory.sqlite")
    work = _work(store, work_type=WorkType.GENERIC)
    adapters = ModelAdapterRegistry((_NoopAdapter(),))
    target = ModelTarget(
        target_id="memory.local.accepted",
        adapter_id="local_memory",
        provider_id="local",
        model_id="memory-local-test",
        locality=ModelLocality.LOCAL,
        capabilities=("memory_query_interpretation", "structured_output"),
        roles=("efficient",),
        max_context_tokens=8_000,
        supports_structured_output=True,
        supports_tools=False,
        supports_streaming=False,
        latency_class="fast",
        benchmark_status=BenchmarkStatus.ACCEPTED,
        registry_version=1,
    )
    targets = ModelTargetRegistry(adapters, (target,))
    model_router = ModelRouter(
        target_registry=targets,
        adapter_registry=adapters,
        strategy_registry=RoutingStrategyRegistry((_MemoryStrategy(),)),
        routing_store=ModelRoutingStore(store),
        eligibility_policy=EligibilityPolicy(),
        credential_available=lambda _target: True,
        clock=lambda: 123.0,
    )
    facts = GlobalBrainRouteFacts(
        route_request_id="memory-route-1",
        scope_id=work.work_id,
        subsystem_key="memory",
        task_kind="query_interpretation",
        required_capabilities=(
            "memory_query_interpretation",
            "structured_output",
        ),
        privacy_class=PrivacyClass.LOCAL_ONLY,
        locality_requirement=LocalityRequirement.LOCAL_ONLY,
        estimated_context_tokens=500,
        evidence_size_class=EvidenceSizeClass.SMALL,
        latency_preference="fast",
        cost_preference="lowest",
        output_contract="memory_query.v1",
        quality_class="routine",
        knowledge_state="verified_local_memory",
    )
    request = project_global_facts_to_model_request(
        facts,
        strategy_key="memory_global",
        strategy_version=1,
        stage_key="memory_query",
    )

    selection = model_router.route(request)

    assert selection.target.target_id == "memory.local.accepted"
    assert selection.target.locality is ModelLocality.LOCAL
