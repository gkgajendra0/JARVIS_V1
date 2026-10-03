from __future__ import annotations

from pathlib import Path

import pytest
from tools.research import c6_context_owner_acceptance as c6

from jarvis.brain_routing.models import BrainRouteKind, BrainRouteRecord, BrainRoutingMode
from jarvis.brain_routing.store import BrainRouteStore
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.model_routing.models import (
    ResponseContractResult,
    RoutingAttempt,
    RoutingAttemptKind,
)
from jarvis.work.models import WorkItem, WorkType
from jarvis.work.store import SQLiteWorkStore


class _AttemptStore:
    def __init__(self, *attempts: RoutingAttempt) -> None:
        self._attempts = attempts

    def list_attempts(self, decision_id: str) -> tuple[RoutingAttempt, ...]:
        assert decision_id == "decision-c6"
        return self._attempts


def _attempt(
    ordinal: int,
    *,
    provider: str = "chatgpt_plan",
    model: str = "reviewed-model",
    valid: bool = True,
) -> RoutingAttempt:
    return RoutingAttempt(
        attempt_id=f"attempt-{ordinal}",
        decision_id="decision-c6",
        work_id="work-c6",
        target_id="work.chatgpt_plan.default",
        attempt_ordinal=ordinal,
        started_at_epoch=float(ordinal),
        ended_at_epoch=float(ordinal) + 0.5,
        kind=RoutingAttemptKind.PRIMARY,
        provider_id=provider,
        model_id=model,
        response_contract_result=(
            ResponseContractResult.VALID if valid else ResponseContractResult.INVALID
        ),
    )


def test_historical_attempt_requires_one_exact_successful_model_result() -> None:
    accepted = _attempt(1)

    assert (
        c6._successful_historical_attempt(
            _AttemptStore(accepted),
            decision_id="decision-c6",
        )
        == accepted
    )
    repeated = c6._successful_historical_attempt(
        _AttemptStore(_attempt(1), _attempt(2)),
        decision_id="decision-c6",
    )
    assert repeated is not None
    assert repeated.model_id == "reviewed-model"

    assert (
        c6._successful_historical_attempt(
            _AttemptStore(_attempt(1), _attempt(2, model="different-model")),
            decision_id="decision-c6",
        )
        is None
    )
    assert (
        c6._successful_historical_attempt(
            _AttemptStore(_attempt(1, valid=False)),
            decision_id="decision-c6",
        )
        is None
    )


def test_replay_candidates_follow_global_model_routed_work_scope() -> None:
    work = WorkItem(
        request="Handle a generic model-routed task.",
        work_type=WorkType.GENERIC,
        source_session_id="session-c6",
        source_turn_id="turn-c6",
        work_id="work-c6",
    )
    route = BrainRouteRecord(
        route_request_id="route-c6",
        work_id=work.work_id,
        subsystem_key="work",
        task_kind=work.work_type.value,
        route_kind=BrainRouteKind.MODEL,
        mode=BrainRoutingMode.SHADOW,
        policy_version=1,
        policy_digest="a" * 64,
        reason_codes=("deterministic_abstained",),
        created_at_epoch=10.0,
        selected_action="generic_action",
        model_decision_id="decision-c6",
        model_target_id="work.chatgpt_plan.default",
        goal_complete=False,
        needs_owner=False,
        parameters_digest=canonical_digest({}),
        reasoner_contract_digest="b" * 64,
    )

    class _WorkStore:
        def list(self, *, limit: int):
            assert limit == 500
            return (work,)

        def list_steps(self, work_id: str):
            assert work_id == work.work_id
            return ()

    class _RouteStore:
        def list_for_work(self, work_id: str):
            assert work_id == work.work_id
            return (route,)

        def get_context_snapshot(self, route_request_id: str):
            assert route_request_id == route.route_request_id
            return {"reasoner_contract_digest": "b" * 64}

    candidates, stats = c6._replay_candidates(
        _WorkStore(),
        _RouteStore(),
        _AttemptStore(_attempt(1)),
        model="reviewed-model",
        limit=5,
    )

    assert len(candidates) == 1
    assert candidates[0][1].work_type is WorkType.GENERIC
    assert stats["model_routes_seen"] == 1
    assert stats["different_model_lineage"] == 0


@pytest.mark.asyncio
async def test_insufficient_replay_corpus_consumes_no_plan_quota(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SQLiteWorkStore(tmp_path / "work.sqlite3")
    route_store = BrainRouteStore(store)

    monkeypatch.setattr(
        c6,
        "_replay_candidates",
        lambda *args, **kwargs: (
            (),
            {
                "model_routes_seen": 0,
                "missing_decision_provenance": 0,
                "missing_context_snapshot": 0,
                "missing_exact_model_lineage": 0,
                "non_chatgpt_plan_lineage": 0,
                "different_model_lineage": 0,
            },
        ),
    )

    def _forbidden_plan():
        raise AssertionError("insufficient corpus must not initialize ChatGPT-plan")

    monkeypatch.setattr(c6, "ChatGPTPlanSessionManager", _forbidden_plan)

    result = await c6._run_decision_replay(
        store=store,
        route_store=route_store,
        model="reviewed-model",
        max_cases=3,
        min_equivalent_cases=3,
    )

    assert result["replayed_cases"] == 0
    assert result["c6_apply_decision_equivalence_proven"] is False
    assert result["provider_circuit_updated"] is False
