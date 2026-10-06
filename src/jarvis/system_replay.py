"""Locked S1 cross-system replay corpus for the Global Supervisor rollout.

S1 is intentionally observational: it records the system scenarios that must remain
replayable before supervisor semantics change. Cases marked KNOWN_GAP capture a
currently understood architectural defect; later S-phases must turn those cases into
enforced regressions rather than hiding the historical failure.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from jarvis.engineering_substrate.canonical import canonical_digest


class SystemReplayStatus(str, Enum):
    COVERED = "covered"
    KNOWN_GAP = "known_gap"
    LIVE_ACCEPTANCE_PENDING = "live_acceptance_pending"


@dataclass(frozen=True, slots=True)
class SystemReplayCaseV1:
    case_id: str
    requirement: str
    evidence_tests: tuple[str, ...]
    status: SystemReplayStatus = SystemReplayStatus.COVERED
    owning_phase: str = "S1"

    def __post_init__(self) -> None:
        if not self.case_id.strip():
            raise ValueError("case_id must not be empty")
        if not self.requirement.strip():
            raise ValueError("requirement must not be empty")
        if not self.evidence_tests or any(
            not str(item).strip() for item in self.evidence_tests
        ):
            raise ValueError("evidence_tests must not be empty")
        if not self.owning_phase.strip():
            raise ValueError("owning_phase must not be empty")

    def to_payload(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "requirement": self.requirement,
            "evidence_tests": list(self.evidence_tests),
            "status": self.status.value,
            "owning_phase": self.owning_phase,
        }


GLOBAL_SUPERVISOR_S1_REPLAY_CORPUS_V1: tuple[SystemReplayCaseV1, ...] = (
    SystemReplayCaseV1(
        "01-research-provider-overload",
        "Temporary research-provider pressure waits or retries without consuming the governing objective as a terminal failure.",
        (
            "tests/test_work_orchestration.py::test_provider_pressure_uses_durable_backoff_without_failure_budget",
            "tests/test_work_delivery_retry.py::test_provider_retry_hint_prefers_structured_retry_info_through_wrapper",
        ),
    ),
    SystemReplayCaseV1(
        "02-development-provider-overload",
        "DevelopmentEngine provider overload parks development instead of converting transient capacity pressure into terminal engineering failure.",
        (
            "tests/test_development_engine_codex.py::test_codex_app_server_overload_parks_development",
            "tests/test_development_engine_work_control.py::test_executor_resource_blocker_parks_without_reasoning_failure",
        ),
    ),
    SystemReplayCaseV1(
        "03-malformed-model-structured-output",
        "Malformed model output is repaired or rejected under the typed contract rather than silently becoming canonical system state.",
        (
            "tests/test_development_engine_codex.py::test_codex_engine_repairs_one_malformed_directive_in_same_thread",
        ),
    ),
    SystemReplayCaseV1(
        "04-codex-contract-repair",
        "A recoverable Codex contract violation is repaired within the bounded DevelopmentEngine session without duplicating the governing work.",
        (
            "tests/test_development_engine_codex.py::test_codex_engine_repairs_one_malformed_directive_in_same_thread",
            "tests/test_development_engine_codex.py::test_codex_engine_reconstructs_when_saved_thread_is_stale",
        ),
    ),
    SystemReplayCaseV1(
        "05-temporary-resource-wait",
        "Temporary resource pressure is represented as waiting state and resumes without burning the normal reasoning failure budget.",
        (
            "tests/test_work_orchestration.py::test_resource_leases_bound_execution_and_surface_waiting_state",
            "tests/test_work_dbos.py::test_waiting_states_do_not_consume_reasoning_budget",
        ),
    ),
    SystemReplayCaseV1(
        "06-failed-research-replaced-by-success",
        "A failed architecture-source attempt remains historical while a fresh replacement attempt can become the current source of evidence.",
        (
            "tests/test_engineering_change_coordinator.py::test_revision_research_compatibility_recovery_starts_fresh_attempt",
            "tests/test_capability_acquisition_workflow.py::test_phase9_research_revision_binds_architecture_to_exact_second_attempt",
        ),
    ),
    SystemReplayCaseV1(
        "07-superseded-work-cannot-poison-current-work",
        "Superseded failed research must not remain an active dependency of a development attempt bound to newer authoritative evidence.",
        (
            "tests/test_development_engine_phase9.py::test_research_evidence_excludes_superseded_source_attempt",
            "tests/test_work_orchestration.py::test_failed_dependency_fails_only_dependent_work",
            "tests/test_engineering_change_coordinator.py::test_revision_research_compatibility_recovery_starts_fresh_attempt",
            "tests/test_goal_objective_workspace.py::test_superseded_failed_work_is_not_an_objective_blocker",
        ),
        status=SystemReplayStatus.COVERED,
        owning_phase="S3-S4",
    ),
    SystemReplayCaseV1(
        "08-target-incompatible-candidate",
        "A candidate incompatible with the canonical target, such as a Samsung-specific SDK for a Hisense/VIDAA target, must be non-selectable before architecture or development.",
        (
            "tests/test_capability_acquisition_resolver.py::test_target_specific_goal_does_not_reuse_unscoped_operation_match",
            "tests/test_capability_acquisition_resolver.py::test_target_specific_goal_reuses_only_explicitly_scoped_capability",
        ),
        status=SystemReplayStatus.COVERED,
        owning_phase="S6",
    ),
    SystemReplayCaseV1(
        "09-pypi-url-package-identity",
        "A PyPI project URL supplied as SDK identity is normalized to the canonical package identity before downstream selection and verification.",
        (
            "tests/test_capability_acquisition_workflow.py::test_record_sdk_candidate_normalizes_pypi_project_url",
        ),
    ),
    SystemReplayCaseV1(
        "10-architecture-revision",
        "Development can request governed architecture revision and the lifecycle returns to architecture-source research without creating a new owner goal.",
        (
            "tests/test_engineering_change_coordinator.py::test_development_can_reopen_governed_architecture_research",
            "tests/test_capability_acquisition_verification.py::test_development_engine_revision_reopens_phase9_research_end_to_end",
        ),
    ),
    SystemReplayCaseV1(
        "11-new-architecture-new-approval",
        "A revised architecture invalidates the previous build approval and requires a fresh owner-bound architecture gate before new development.",
        (
            "tests/test_engineering_change_service.py::test_revise_approved_architecture_reopens_gate_and_creates_fresh_build_attempt",
            "tests/test_engineering_change_coordinator.py::test_dev_stage_cannot_be_created_before_approval_or_after_revision_change",
        ),
    ),
    SystemReplayCaseV1(
        "12-restart-during-active-research",
        "Restart reconciliation reuses the existing research stage/work binding instead of creating duplicate research work.",
        (
            "tests/test_engineering_change_coordinator.py::test_restart_reconciles_submission_without_duplicate_stage",
            "tests/test_work_dbos.py::test_dbos_recovers_waiting_work_after_runtime_restart",
        ),
    ),
    SystemReplayCaseV1(
        "13-restart-during-development",
        "Restart during development reconstructs durable execution and reuses canonical progress rather than starting a second engineering attempt.",
        (
            "tests/test_development_engine_codex.py::test_codex_engine_reconstructs_completion_from_canonical_progress",
            "tests/test_work_orchestration.py::test_orchestrator_reconciles_active_execution_idempotently",
        ),
    ),
    SystemReplayCaseV1(
        "14-restart-after-owner-approval",
        "Restart after an owner gate decision preserves the exact approved architecture binding and does not manufacture another approval or build identity.",
        (
            "tests/test_engineering_change_service.py::test_restart_resends_same_architecture_gate_and_delivery",
            "tests/test_engineering_change_coordinator.py::test_startup_reconciles_terminal_research_and_unsubmitted_stage",
        ),
    ),
    SystemReplayCaseV1(
        "15-duplicate-dbos-replay",
        "Duplicate DBOS control/execution replay is idempotent and does not duplicate durable work side effects.",
        (
            "tests/test_work_dbos.py::test_dbos_control_messages_use_idempotency_keys",
            "tests/test_work_orchestration.py::test_orchestrator_reconciles_active_execution_idempotently",
            "tests/test_work_orchestration.py::test_apply_owner_input_is_idempotent_after_canonical_save",
            "tests/test_work_orchestration.py::test_interrupted_running_step_recovers_waiting_for_owner",
        ),
    ),
    SystemReplayCaseV1(
        "16-developer-requests-more-research",
        "Development can emit a bounded need for additional evidence and return the same governing change to research rather than failing the owner objective.",
        (
            "tests/test_engineering_change_coordinator.py::test_development_can_reopen_governed_architecture_research",
            "tests/test_development_engine_phase9.py::test_phase9_completion_guard_allows_typed_revision_without_fake_commit",
        ),
    ),
    SystemReplayCaseV1(
        "17-research-answer-resumes-development",
        "Fresh research can produce a newly bound architecture and, after the required approval, development resumes on that authoritative generation.",
        (
            "tests/test_capability_acquisition_workflow.py::test_phase9_research_revision_binds_architecture_to_exact_second_attempt",
            "tests/test_engineering_change_service.py::test_revise_approved_architecture_reopens_gate_and_creates_fresh_build_attempt",
        ),
    ),
    SystemReplayCaseV1(
        "18-verification-rejects-implementation",
        "Verification may reject stale or invalid implementation evidence without treating the rejection itself as permission to bypass architecture, gates or lineage.",
        (
            "tests/test_capability_acquisition_verification.py::test_stale_architecture_blocks_acceptance_gate",
            "tests/test_gicc_apply_runtime_execution.py::test_failed_verification_replans_once_and_completes",
        ),
    ),
    SystemReplayCaseV1(
        "19-owner-input-required",
        "A specialist can request owner input as an explicit waiting boundary without converting that request into an execution failure.",
        (
            "tests/test_work_orchestration.py::test_executor_can_request_owner_input_without_becoming_failure",
            "tests/test_engineering_change_service.py::test_only_explicit_canonical_owner_turn_can_decide_current_gate",
        ),
    ),
    SystemReplayCaseV1(
        "20-tv-goal-full-lifecycle",
        "The original TV owner goal must survive capability acquisition, architecture revision, development, verification, activation and external acceptance, then resume the same continuation.",
        (
            "tests/test_gicc_phase9_bridge.py::test_phase9_bridge_persists_exact_cross_lifecycle_lineage",
            "tests/test_gicc_apply_runtime_execution.py::test_external_acceptance_fences_capability_continuation",
            "tests/test_goal_continuation.py::test_continuation_restores_exact_blocker_after_restart",
            "tests/test_capability_acquisition_verification.py::test_development_engine_revision_reopens_phase9_research_end_to_end",
            "tests/test_goal_objective_workspace.py::test_failed_gap_linked_change_remains_governing_and_retryable",
            "tests/test_goal_objective_workspace.py::test_supervisor_assisted_retry_uses_attached_canonical_retry",
            "tests/test_capability_acquisition_system_hardening.py::test_invariant_checker_detects_completed_retryable_work",
            "tests/test_goal_objective_workspace.py::test_objective_workspace_projects_phase9_external_acceptance_work",
            "tests/test_phase9h_external_completion.py::test_external_acceptance_decline_waits_for_same_owner_authorization",
            "tests/test_phase9h_external_completion.py::test_external_acceptance_authority_must_match_activation_artifact",
            "tests/test_capability_acquisition_owner_flow_hardening.py::test_owner_turn_discovers_target_and_enters_exact_phase9_lineage",
            "tests/test_capability_acquisition_completion_hardening.py::test_exact_completion_lineage_fences_and_resumes_original_goal",
        ),
        status=SystemReplayStatus.LIVE_ACCEPTANCE_PENDING,
        owning_phase="S13",
    ),
)


def global_supervisor_s1_replay_corpus_digest() -> str:
    return canonical_digest(
        [item.to_payload() for item in GLOBAL_SUPERVISOR_S1_REPLAY_CORPUS_V1]
    )


def validate_global_supervisor_s1_replay_corpus() -> None:
    if len(GLOBAL_SUPERVISOR_S1_REPLAY_CORPUS_V1) != 20:
        raise ValueError("Global Supervisor S1 replay corpus must contain 20 cases")
    identities = tuple(item.case_id for item in GLOBAL_SUPERVISOR_S1_REPLAY_CORPUS_V1)
    if len(set(identities)) != len(identities):
        raise ValueError("Global Supervisor S1 replay case IDs must be unique")


def global_supervisor_s1_pytest_node_ids() -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            evidence
            for case in GLOBAL_SUPERVISOR_S1_REPLAY_CORPUS_V1
            for evidence in case.evidence_tests
            if evidence.startswith("tests/") and "::" in evidence
        )
    )


def global_supervisor_s1_known_gap_ids() -> tuple[str, ...]:
    return tuple(
        case.case_id
        for case in GLOBAL_SUPERVISOR_S1_REPLAY_CORPUS_V1
        if case.status is SystemReplayStatus.KNOWN_GAP
    )
