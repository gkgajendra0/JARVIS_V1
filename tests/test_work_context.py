from __future__ import annotations

from jarvis.brain_routing.models import (
    BrainRouteKind,
    BrainRouteRecord,
    BrainRoutingMode,
)
from jarvis.brain_routing.work import build_work_global_route_facts
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.work.brain import BrainAction, BrainDecision, BrainRequest
from jarvis.work.context import (
    WorkContextAssembler,
    WorkContextMode,
    build_context_shadow_report,
)
from jarvis.work.context_evaluation import (
    compare_context_decisions,
    compare_recorded_context_decision,
)
from jarvis.work.models import WorkItem, WorkStep, WorkType
from jarvis.work.reasoner import _work_input_payload


def _work(work_type: WorkType = WorkType.DEVELOPMENT) -> WorkItem:
    return WorkItem(
        request="Implement bounded context selection safely",
        work_type=work_type,
        source_session_id="session-c6",
        source_turn_id="turn-c6",
    )


def _completed_step(
    work: WorkItem,
    kind: str,
    *,
    observation: dict | None = None,
    input_data: dict | None = None,
) -> WorkStep:
    return (
        WorkStep(
            work_id=work.work_id,
            kind=kind,
            summary=f"{kind} summary",
            input_data={} if input_data is None else input_data,
        )
        .start()
        .complete({} if observation is None else observation)
    )


def _action() -> BrainAction:
    return BrainAction(
        name="dev_status",
        description="Read bounded development status",
        parameter_schema={"type": "object", "additionalProperties": False},
    )


def test_development_context_keeps_stage_milestones_and_bounds_history() -> None:
    work = _work()
    steps = (
        _completed_step(work, "dev_prepare_workspace", observation={"prepared": True}),
        *tuple(
            _completed_step(
                work,
                "dev_read_file",
                observation={"path": f"src/file_{index}.py", "text": "x" * 200},
            )
            for index in range(8)
        ),
        *tuple(
            _completed_step(
                work,
                "dev_search",
                observation={"query": f"symbol-{index}", "matches": [str(index)]},
            )
            for index in range(6)
        ),
        _completed_step(work, "dev_write_file", observation={"written": True}),
        _completed_step(work, "dev_run_tests", observation={"passed": True}),
        _completed_step(work, "dev_diff", observation={"diff": "safe diff"}),
        _completed_step(
            work,
            "dev_commit",
            observation={"committed": True, "clean": True},
        ),
    )

    pack = WorkContextAssembler().build(work=work, steps=steps)
    kinds = [step.kind for step in pack.selected_steps]

    assert len(pack.selected_steps) <= 12
    assert pack.omitted_step_count > 0
    assert "dev_prepare_workspace" in kinds
    assert "dev_write_file" in kinds
    assert "dev_run_tests" in kinds
    assert "dev_diff" in kinds
    assert "dev_commit" in kinds
    assert pack.history_manifest_payload()["full_history_is_durable"] is True


def test_context_pack_compacts_large_payloads_with_recoverable_digest() -> None:
    work = _work()
    large_text = "0123456789" * 2000
    steps = (
        _completed_step(
            work,
            "dev_read_file",
            observation={"path": "src/large.py", "text": large_text},
        ),
    )
    assembler = WorkContextAssembler(max_string_chars=1200)

    pack = assembler.build(work=work, steps=steps)

    compacted = pack.selected_steps[0].observation["text"]
    assert isinstance(compacted, str)
    assert len(compacted) <= 1200
    assert "C6_CONTEXT_TRUNCATED" in compacted
    assert "sha256=" in compacted


def test_shadow_mode_keeps_legacy_payload_and_apply_uses_context_pack() -> None:
    work = _work()
    steps = tuple(
        _completed_step(
            work,
            "dev_read_file",
            observation={"path": f"src/{index}.py", "text": "x" * 1000},
        )
        for index in range(14)
    )
    legacy_steps = steps[-12:]
    pack = WorkContextAssembler(max_string_chars=1200).build(
        work=work,
        steps=steps,
    )
    shadow = BrainRequest(
        work=work,
        recent_steps=legacy_steps,
        purpose="choose the next bounded step",
        allowed_actions=(_action(),),
        context_pack=pack,
        context_mode=WorkContextMode.SHADOW,
    )
    apply_request = BrainRequest(
        work=work,
        recent_steps=legacy_steps,
        purpose="choose the next bounded step",
        allowed_actions=(_action(),),
        context_pack=pack,
        context_mode=WorkContextMode.APPLY,
    )
    off = BrainRequest(
        work=work,
        recent_steps=legacy_steps,
        purpose="choose the next bounded step",
        allowed_actions=(_action(),),
    )

    legacy_payload = _work_input_payload(off)
    shadow_payload = _work_input_payload(shadow)
    optimized_payload = _work_input_payload(apply_request)

    assert shadow_payload == legacy_payload
    assert optimized_payload != legacy_payload
    assert "history_manifest" in optimized_payload
    assert optimized_payload["history_manifest"]["omitted_step_count"] > 0

    report = build_context_shadow_report(
        legacy_payload=legacy_payload,
        optimized_payload=optimized_payload,
        pack=pack,
    )
    assert report.optimized_chars < report.legacy_chars
    assert report.optimized_estimated_tokens < report.legacy_estimated_tokens
    assert report.reduction_percent > 0


def test_context_decision_equivalence_requires_all_safety_fields_to_match() -> None:
    legacy = BrainDecision(
        action="dev_status",
        summary="Inspect status",
        parameters={},
    )
    same = BrainDecision(
        action="dev_status",
        summary="Different wording is allowed",
        parameters={},
    )
    changed = BrainDecision(
        action=None,
        summary="Need owner",
        needs_owner=True,
        owner_question="Approve?",
    )

    assert compare_context_decisions(legacy, same).equivalent is True
    result = compare_context_decisions(legacy, changed)
    assert result.equivalent is False
    assert result.action_equal is False
    assert result.needs_owner_equal is False


def test_global_route_facts_use_context_pack_only_in_apply() -> None:
    work = _work()
    steps = tuple(
        _completed_step(
            work,
            "dev_read_file",
            observation={"path": f"src/{index}.py", "text": "x" * 5000},
        )
        for index in range(14)
    )
    legacy_steps = steps[-12:]
    pack = WorkContextAssembler(max_string_chars=1200).build(
        work=work,
        steps=steps,
    )
    shadow = BrainRequest(
        work=work,
        recent_steps=legacy_steps,
        purpose="choose the next bounded step",
        allowed_actions=(_action(),),
        context_pack=pack,
        context_mode=WorkContextMode.SHADOW,
    )
    apply_request = BrainRequest(
        work=work,
        recent_steps=legacy_steps,
        purpose="choose the next bounded step",
        allowed_actions=(_action(),),
        context_pack=pack,
        context_mode=WorkContextMode.APPLY,
    )

    shadow_facts = build_work_global_route_facts(shadow, all_steps=steps)
    apply_facts = build_work_global_route_facts(apply_request, all_steps=steps)

    assert apply_facts.route_request_id == shadow_facts.route_request_id
    assert apply_facts.estimated_context_tokens < shadow_facts.estimated_context_tokens


def _recorded_decision(
    decision: BrainDecision,
    *,
    include_c6_provenance: bool = True,
) -> BrainRouteRecord:
    return BrainRouteRecord(
        route_request_id="route-c6-recorded",
        work_id="work-c6-recorded",
        subsystem_key="work",
        task_kind="development",
        route_kind=BrainRouteKind.MODEL,
        mode=BrainRoutingMode.SHADOW,
        policy_version=1,
        policy_digest="a" * 64,
        reason_codes=("deterministic_abstained",),
        created_at_epoch=1.0,
        selected_action=decision.action,
        goal_complete=(decision.goal_complete if include_c6_provenance else None),
        needs_owner=(decision.needs_owner if include_c6_provenance else None),
        owner_question=(decision.owner_question if include_c6_provenance else None),
        parameters_digest=(
            canonical_digest(decision.parameters) if include_c6_provenance else None
        ),
    )


def test_recorded_context_equivalence_uses_full_safety_fingerprint() -> None:
    legacy = BrainDecision(
        action="dev_status",
        summary="Inspect status",
        parameters={"scope": "candidate"},
    )
    same = BrainDecision(
        action="dev_status",
        summary="Different wording is allowed",
        parameters={"scope": "candidate"},
    )
    changed = BrainDecision(
        action="dev_status",
        summary="Different parameters are material",
        parameters={"scope": "workspace"},
    )

    equivalent = compare_recorded_context_decision(
        _recorded_decision(legacy),
        same,
    )
    assert equivalent is not None and equivalent.equivalent is True

    mismatch = compare_recorded_context_decision(
        _recorded_decision(legacy),
        changed,
    )
    assert mismatch is not None
    assert mismatch.equivalent is False
    assert mismatch.parameters_equal is False


def test_recorded_context_equivalence_rejects_legacy_incomplete_provenance() -> None:
    decision = BrainDecision(
        action="dev_status",
        summary="Inspect status",
    )

    assert (
        compare_recorded_context_decision(
            _recorded_decision(decision, include_c6_provenance=False),
            decision,
        )
        is None
    )
