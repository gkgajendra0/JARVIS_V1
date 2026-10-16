"""Shadow-only task-brief compiler tests; no provider/memory database access."""

from __future__ import annotations

from dataclasses import replace

import pytest

from jarvis.memory.decision_shadow import (
    ContextShadowEvidence,
    ContextUtilitySignal,
)
from jarvis.memory.task_context_shadow import (
    ShadowMemoryCandidate,
    ShadowTaskNeed,
    TaskNeedKind,
    compile_shadow_plan,
)
from jarvis.memory.types import (
    AssertionState,
    AuthorityClass,
    MemorySourceClass,
    Sensitivity,
)


def _candidate(
    identity: str,
    *,
    rank: int = 1,
    scope: str = "interview_style",
) -> ShadowMemoryCandidate:
    return ShadowMemoryCandidate(
        opaque_assertion_id=identity,
        evidence=ContextShadowEvidence(
            authority=AuthorityClass.OWNER_DIRECT,
            source=MemorySourceClass.OWNER_DIRECT,
            sensitivity=Sensitivity.STANDARD,
            state=AssertionState.ACTIVE,
            canonical_source_ref="canonical:owner-utterance",
            memory_scope=scope,
            current_task_scope=scope,
            task_grounded_in_current_turn=True,
            conflicts_with_current_turn=False,
            utility_signal=ContextUtilitySignal.HELPFUL,
        ),
        need_kind=TaskNeedKind.PRESENTATION_STYLE,
        provenance_verified=True,
        fact_support_verified=True,
        utility_rank=rank,
    )


def _task() -> ShadowTaskNeed:
    return ShadowTaskNeed(
        scope="interview_style",
        kind=TaskNeedKind.PRESENTATION_STYLE,
        grounded_in_current_user_turn=True,
    )


def test_compiler_selects_minimal_ranked_opaque_ids_and_no_values() -> None:
    plan = compile_shadow_plan(
        task=_task(),
        candidates=(
            _candidate("fact-c", rank=3),
            _candidate("fact-b", rank=1),
            _candidate("fact-a", rank=1),
        ),
    )
    assert plan.candidate_ids == ("fact-a", "fact-b")
    assert plan.examined_count == 3
    assert plan.rejected_count == 1
    assert plan.mode == "shadow_only_not_authorized"
    assert not hasattr(plan, "context_packet")
    assert not hasattr(plan, "memory_values")


@pytest.mark.parametrize(
    "candidate",
    [
        replace(_candidate("a"), provenance_verified=False),
        replace(_candidate("a"), fact_support_verified=False),
        replace(_candidate("a"), need_kind=TaskNeedKind.EXACT_OWNER_FACT),
        replace(_candidate("a"), evidence=replace(
            _candidate("a").evidence,
            sensitivity=Sensitivity.LOCAL_ONLY,
        )),
        replace(_candidate("a"), evidence=replace(
            _candidate("a").evidence,
            state=AssertionState.RETRACTED,
        )),
        replace(_candidate("a"), evidence=replace(
            _candidate("a").evidence,
            conflicts_with_current_turn=True,
        )),
        replace(_candidate("a"), evidence=replace(
            _candidate("a").evidence,
            utility_signal=ContextUtilitySignal.STEERING_RISK,
        )),
        _candidate("a", scope="unrelated_device"),
    ],
)
def test_compiler_fails_closed(candidate: ShadowMemoryCandidate) -> None:
    assert compile_shadow_plan(task=_task(), candidates=(candidate,)).candidate_ids == ()


def test_ungrounded_task_or_unclassified_intent_abstains() -> None:
    c = _candidate("a")
    t = replace(_task(), grounded_in_current_user_turn=False)
    assert compile_shadow_plan(task=t, candidates=(c,)).candidate_ids == ()
    t = replace(_task(), kind=TaskNeedKind.UNCLASSIFIED)
    assert compile_shadow_plan(task=t, candidates=(c,)).candidate_ids == ()


def test_duplicate_identity_and_invalid_budget_are_rejected() -> None:
    c = _candidate("a")
    with pytest.raises(ValueError, match="duplicate"):
        compile_shadow_plan(task=_task(), candidates=(c, c))
    with pytest.raises(ValueError, match="max_selected"):
        compile_shadow_plan(task=_task(), candidates=(c,), max_selected=0)


def test_compiler_does_not_derive_task_scope_from_memory_itself() -> None:
    """Wrong current task scope is rejected even if the memory is persuasive."""

    task = replace(_task(), scope="neutral_report")
    assert compile_shadow_plan(
        task=task, candidates=(_candidate("same-memory"),)
    ).candidate_ids == ()
