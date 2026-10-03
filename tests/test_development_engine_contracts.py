from __future__ import annotations

import pytest

from jarvis.development_engine import (
    DevelopmentDisposition,
    DevelopmentResultV1,
    DevelopmentTicketV1,
    DevelopmentUsageV1,
)


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
        required_operations=("media_player.control", "media_player.play"),
        dependency_refs=("dependency:example==1.2.3",),
        research_evidence_refs=("evidence:research:1",),
        repository_context_refs=("repo:src/jarvis/capabilities/runtime.py",),
        writable_paths=(
            "src/jarvis/capabilities/tv_adapter.py",
            "tests/test_tv_adapter.py",
        ),
        acceptance_criteria=("targeted tests pass", "candidate diff is inspectable"),
        allowed_tools=("read_file", "write_file", "run_tests"),
        attempt=2,
    )


def test_ticket_is_canonical_and_order_independent() -> None:
    left = _ticket()
    right = DevelopmentTicketV1.create(
        request="Develop the approved capability.",
        work_id="work_demo",
        engineering_change_id="change_demo",
        goal_id="goal_demo",
        goal_digest="a" * 64,
        architecture_artifact_id="artifact_demo",
        architecture_digest="b" * 64,
        base_revision="c" * 40,
        workspace_id="workspace_demo",
        required_operations=("media_player.play", "media_player.control"),
        dependency_refs=("dependency:example==1.2.3",),
        research_evidence_refs=("evidence:research:1",),
        repository_context_refs=("repo:src/jarvis/capabilities/runtime.py",),
        writable_paths=(
            "tests\\test_tv_adapter.py",
            "src\\jarvis\\capabilities\\tv_adapter.py",
        ),
        acceptance_criteria=("candidate diff is inspectable", "targeted tests pass"),
        allowed_tools=("run_tests", "write_file", "read_file"),
        attempt=2,
    )

    assert left == right
    assert left.ticket_id == f"dev_ticket_{left.digest[:16]}"
    assert left.canonical_payload()["contract_version"] == 1


def test_ticket_writable_paths_are_canonical_and_repository_relative() -> None:
    ticket = _ticket()

    assert ticket.writable_paths == (
        "src/jarvis/capabilities/tv_adapter.py",
        "tests/test_tv_adapter.py",
    )
    assert ticket.canonical_payload()["writable_paths"] == list(ticket.writable_paths)

    with pytest.raises(ValueError, match="safe repository-relative path"):
        DevelopmentTicketV1.create(
            request="Develop the approved capability.",
            work_id="work_demo",
            engineering_change_id="change_demo",
            goal_id="goal_demo",
            goal_digest="a" * 64,
            architecture_artifact_id="artifact_demo",
            architecture_digest="b" * 64,
            base_revision="c" * 40,
            workspace_id="workspace_demo",
            required_operations=("operation.demo",),
            acceptance_criteria=("tests pass",),
            allowed_tools=("write_file",),
            writable_paths=("../escape.py",),
        )


def test_ticket_requires_bounded_tools_and_acceptance() -> None:
    with pytest.raises(ValueError, match="acceptance_criterion"):
        DevelopmentTicketV1.create(
            request="Develop the approved capability.",
            work_id="work_demo",
            engineering_change_id="change_demo",
            goal_id="goal_demo",
            goal_digest="a" * 64,
            architecture_artifact_id="artifact_demo",
            architecture_digest="b" * 64,
            base_revision="c" * 40,
            workspace_id="workspace_demo",
            required_operations=("operation.demo",),
            acceptance_criteria=(),
            allowed_tools=("read_file",),
        )

    with pytest.raises(ValueError, match="allowed_tool"):
        DevelopmentTicketV1.create(
            request="Develop the approved capability.",
            work_id="work_demo",
            engineering_change_id="change_demo",
            goal_id="goal_demo",
            goal_digest="a" * 64,
            architecture_artifact_id="artifact_demo",
            architecture_digest="b" * 64,
            base_revision="c" * 40,
            workspace_id="workspace_demo",
            required_operations=("operation.demo",),
            acceptance_criteria=("tests pass",),
            allowed_tools=(),
        )


def test_completed_result_requires_candidate_and_test_evidence() -> None:
    ticket = _ticket()

    with pytest.raises(ValueError, match="candidate_revision"):
        DevelopmentResultV1.create(
            ticket=ticket,
            disposition=DevelopmentDisposition.COMPLETED,
            engine_id="fake",
            engine_version="1",
            summary="done",
            test_evidence_refs=("test:1",),
        )

    with pytest.raises(ValueError, match="test evidence"):
        DevelopmentResultV1.create(
            ticket=ticket,
            disposition=DevelopmentDisposition.COMPLETED,
            engine_id="fake",
            engine_version="1",
            summary="done",
            candidate_revision="d" * 40,
        )


def test_architecture_revision_requires_reason_and_evidence() -> None:
    ticket = _ticket()

    with pytest.raises(ValueError, match="reason"):
        DevelopmentResultV1.create(
            ticket=ticket,
            disposition=DevelopmentDisposition.NEEDS_ARCHITECTURE_REVISION,
            engine_id="fake",
            engine_version="1",
            summary="blocked",
        )

    with pytest.raises(ValueError, match="evidence"):
        DevelopmentResultV1.create(
            ticket=ticket,
            disposition=DevelopmentDisposition.NEEDS_ARCHITECTURE_REVISION,
            engine_id="fake",
            engine_version="1",
            summary="blocked",
            reason="approved transport cannot satisfy the operation",
        )


def test_completed_result_carries_usage_without_workflow_authority() -> None:
    ticket = _ticket()
    usage = DevelopmentUsageV1(
        input_tokens=100,
        output_tokens=20,
        total_tokens=120,
    )
    result = DevelopmentResultV1.create(
        ticket=ticket,
        disposition=DevelopmentDisposition.COMPLETED,
        engine_id="codex_plan",
        engine_version="sdk-test",
        summary="implemented and tested",
        thread_id="thread_demo",
        candidate_revision="d" * 40,
        changed_files=("src/jarvis/demo.py",),
        test_evidence_refs=("test:pytest:pass",),
        evidence_refs=("evidence:diff:1",),
        usage=usage,
    )

    assert result.result_id == f"dev_result_{result.digest[:16]}"
    assert result.ticket_id == ticket.ticket_id
    assert result.ticket_digest == ticket.digest
    assert result.disposition is DevelopmentDisposition.COMPLETED
    assert result.usage == usage


def test_dependency_and_resource_dispositions_are_typed() -> None:
    ticket = _ticket()

    dependency = DevelopmentResultV1.create(
        ticket=ticket,
        disposition=DevelopmentDisposition.NEEDS_DEPENDENCY,
        engine_id="fake",
        engine_version="1",
        summary="dependency required",
        reason="implementation requires the approved client library",
        requested_dependencies=("example-client==1.2.3",),
    )
    assert dependency.requested_dependencies == ("example-client==1.2.3",)

    blocked = DevelopmentResultV1.create(
        ticket=ticket,
        disposition=DevelopmentDisposition.BLOCKED_RESOURCE,
        engine_id="fake",
        engine_version="1",
        summary="provider unavailable",
        reason="shared reasoning allowance is unavailable",
        blocker_code="subscription_usage_limit",
    )
    assert blocked.blocker_code == "subscription_usage_limit"


def test_usage_rejects_inconsistent_totals() -> None:
    with pytest.raises(ValueError, match="total_tokens"):
        DevelopmentUsageV1(
            input_tokens=10,
            output_tokens=5,
            total_tokens=14,
        )


def test_retry_cooldown_is_typed_and_resource_only() -> None:
    ticket = _ticket()
    blocked = DevelopmentResultV1.create(
        ticket=ticket,
        disposition=DevelopmentDisposition.BLOCKED_RESOURCE,
        engine_id="fake",
        engine_version="1",
        summary="capacity unavailable",
        reason="shared plan allowance is cooling down",
        blocker_code="provider_circuit_open",
        retry_after_seconds=1800.0,
    )
    assert blocked.retry_after_seconds == 1800.0

    with pytest.raises(ValueError, match="only valid for blocked-resource"):
        DevelopmentResultV1.create(
            ticket=ticket,
            disposition=DevelopmentDisposition.FAILED,
            engine_id="fake",
            engine_version="1",
            summary="failed",
            reason="non-resource failure",
            retry_after_seconds=10.0,
        )

    with pytest.raises(ValueError, match="must be positive"):
        DevelopmentResultV1.create(
            ticket=ticket,
            disposition=DevelopmentDisposition.BLOCKED_RESOURCE,
            engine_id="fake",
            engine_version="1",
            summary="capacity unavailable",
            reason="retry later",
            blocker_code="provider_circuit_open",
            retry_after_seconds=0.0,
        )
