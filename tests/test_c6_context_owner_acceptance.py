from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.brain_routing.store import BrainRouteStore
from jarvis.model_routing.models import (
    ResponseContractResult,
    RoutingAttempt,
    RoutingAttemptKind,
)
from jarvis.work.store import SQLiteWorkStore
from tools.research import c6_context_owner_acceptance as c6


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
