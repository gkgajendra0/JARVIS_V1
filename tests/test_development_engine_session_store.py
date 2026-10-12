from __future__ import annotations

from jarvis.development_engine import (
    DevelopmentDisposition,
    DevelopmentResultV1,
    DevelopmentSessionState,
    DevelopmentSessionStore,
    DevelopmentTicketV1,
    DevelopmentUsageV1,
    build_development_reasoning_fingerprint,
)
from jarvis.work.models import WorkItem, WorkType
from jarvis.work.store import SQLiteWorkStore


def _ticket() -> DevelopmentTicketV1:
    return DevelopmentTicketV1.create(
        request="Develop the approved capability.",
        work_id="work_demo",
        engineering_change_id="change_demo",
        goal_id="goal_demo",
        goal_digest="a" * 64,
        architecture_artifact_id="artifact_demo",
        architecture_digest="b" * 64,
        base_revision="c" * 40,
        workspace_id="workspace_demo",
        required_operations=("operation.beta", "operation.alpha"),
        research_evidence_refs=("research:2", "research:1"),
        acceptance_criteria=("tests pass",),
        allowed_tools=("run_tests", "read_file"),
    )


def _store(tmp_path) -> SQLiteWorkStore:
    store = SQLiteWorkStore(tmp_path / "work.sqlite3")
    store.create(
        WorkItem(
            request="develop capability",
            work_type=WorkType.DEVELOPMENT,
            source_session_id="session",
            source_turn_id="turn",
            work_id="work_demo",
        )
    )
    return store


def test_reasoning_fingerprint_is_order_independent() -> None:
    ticket = _ticket()

    left = build_development_reasoning_fingerprint(
        ticket,
        evidence_refs=("evidence:b", "evidence:a"),
        failure_refs=("failure:2", "failure:1"),
    )
    right = build_development_reasoning_fingerprint(
        ticket,
        evidence_refs=("evidence:a", "evidence:b"),
        failure_refs=("failure:1", "failure:2"),
    )

    assert left == right
    assert len(left) == 64


def test_session_persists_thread_and_exact_result(tmp_path) -> None:
    ticket = _ticket()
    store = _store(tmp_path)
    sessions = DevelopmentSessionStore(store)
    fingerprint = build_development_reasoning_fingerprint(ticket)

    started = sessions.begin(
        ticket=ticket,
        engine_id="codex_plan",
        engine_version="0.160.0",
        reasoning_fingerprint=fingerprint,
    )
    assert started.state is DevelopmentSessionState.ACTIVE
    assert started.thread_id is None

    bound = sessions.bind_thread(
        ticket_digest=ticket.digest,
        thread_id="thr_demo",
    )
    assert bound.thread_id == "thr_demo"

    result = DevelopmentResultV1.create(
        ticket=ticket,
        disposition=DevelopmentDisposition.COMPLETED,
        engine_id="codex_plan",
        engine_version="0.160.0",
        summary="implemented and tested",
        thread_id="thr_demo",
        candidate_revision="d" * 40,
        changed_files=("src/jarvis/demo.py",),
        test_evidence_refs=("test:pytest:pass",),
        usage=DevelopmentUsageV1(
            input_tokens=120,
            output_tokens=30,
            total_tokens=150,
        ),
    )
    recorded = sessions.record_result(
        ticket=ticket,
        result=result,
        reasoning_fingerprint=fingerprint,
    )

    assert recorded.state is DevelopmentSessionState.COMPLETED
    assert recorded.last_result_digest == result.digest
    assert (
        sessions.load_result(
            ticket=ticket,
            result_digest=result.digest,
        )
        == result
    )
    assert (
        sessions.reusable_result(
            ticket=ticket,
            reasoning_fingerprint=fingerprint,
            engine_id="codex_plan",
            engine_version="0.160.0",
        )
        == result
    )


def test_changed_reasoning_fingerprint_invalidates_reuse(tmp_path) -> None:
    ticket = _ticket()
    store = _store(tmp_path)
    sessions = DevelopmentSessionStore(store)
    first = build_development_reasoning_fingerprint(
        ticket,
        evidence_refs=("evidence:first",),
    )
    sessions.begin(
        ticket=ticket,
        engine_id="codex_plan",
        engine_version="0.160.0",
        reasoning_fingerprint=first,
    )
    result = DevelopmentResultV1.create(
        ticket=ticket,
        disposition=DevelopmentDisposition.NEEDS_RESEARCH,
        engine_id="codex_plan",
        engine_version="0.160.0",
        summary="more evidence required",
        reason="the current protocol evidence is insufficient",
        evidence_refs=("evidence:first",),
    )
    sessions.record_result(
        ticket=ticket,
        result=result,
        reasoning_fingerprint=first,
    )
    sessions.bind_thread(
        ticket_digest=ticket.digest,
        thread_id="thr_same_engine",
    )
    assert (
        sessions.reusable_result(
            ticket=ticket,
            reasoning_fingerprint=first,
            engine_id="codex_plan",
            engine_version="0.160.0",
        )
        == result
    )

    second = build_development_reasoning_fingerprint(
        ticket,
        evidence_refs=("evidence:first", "evidence:new"),
    )
    reopened = sessions.begin(
        ticket=ticket,
        engine_id="codex_plan",
        engine_version="0.160.0",
        reasoning_fingerprint=second,
    )

    assert reopened.state is DevelopmentSessionState.ACTIVE
    assert reopened.thread_id == "thr_same_engine"
    assert reopened.last_result_digest is None
    assert (
        sessions.reusable_result(
            ticket=ticket,
            reasoning_fingerprint=second,
            engine_id="codex_plan",
            engine_version="0.160.0",
        )
        is None
    )


def test_engine_generation_change_invalidates_result_and_thread(tmp_path) -> None:
    ticket = _ticket()
    store = _store(tmp_path)
    sessions = DevelopmentSessionStore(store)
    fingerprint = build_development_reasoning_fingerprint(ticket)
    sessions.begin(
        ticket=ticket,
        engine_id="codex_plan",
        engine_version="0.160.0",
        reasoning_fingerprint=fingerprint,
    )
    sessions.bind_thread(
        ticket_digest=ticket.digest,
        thread_id="thr_codex_generation",
    )
    result = DevelopmentResultV1.create(
        ticket=ticket,
        disposition=DevelopmentDisposition.NEEDS_RESEARCH,
        engine_id="codex_plan",
        engine_version="0.160.0",
        summary="Current engine needs more evidence.",
        reason="The current evidence is insufficient.",
    )
    sessions.record_result(
        ticket=ticket,
        result=result,
        reasoning_fingerprint=fingerprint,
    )

    assert (
        sessions.reusable_result(
            ticket=ticket,
            reasoning_fingerprint=fingerprint,
            engine_id="replacement_engine",
            engine_version="2",
        )
        is None
    )

    reopened = sessions.begin(
        ticket=ticket,
        engine_id="replacement_engine",
        engine_version="2",
        reasoning_fingerprint=fingerprint,
    )

    assert reopened.state is DevelopmentSessionState.ACTIVE
    assert reopened.engine_id == "replacement_engine"
    assert reopened.engine_version == "2"
    assert reopened.thread_id is None
    assert reopened.last_result_digest is None


def test_resource_blocker_is_never_reused(tmp_path) -> None:
    ticket = _ticket()
    store = _store(tmp_path)
    sessions = DevelopmentSessionStore(store)
    fingerprint = build_development_reasoning_fingerprint(ticket)
    sessions.begin(
        ticket=ticket,
        engine_id="codex_plan",
        engine_version="0.160.0",
        reasoning_fingerprint=fingerprint,
    )
    result = DevelopmentResultV1.create(
        ticket=ticket,
        disposition=DevelopmentDisposition.BLOCKED_RESOURCE,
        engine_id="codex_plan",
        engine_version="0.160.0",
        summary="shared allowance unavailable",
        reason="provider capacity is currently unavailable",
        blocker_code="subscription_usage_limit",
    )
    sessions.record_result(
        ticket=ticket,
        result=result,
        reasoning_fingerprint=fingerprint,
    )

    assert (
        sessions.reusable_result(
            ticket=ticket,
            reasoning_fingerprint=fingerprint,
            engine_id="codex_plan",
            engine_version="0.160.0",
        )
        is None
    )
