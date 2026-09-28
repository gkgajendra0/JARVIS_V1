"""Locked Phase-10A replay corpus manifest."""

from __future__ import annotations

from dataclasses import dataclass

from jarvis.engineering_substrate.canonical import canonical_digest


@dataclass(frozen=True, slots=True)
class Phase10AReplayCaseV1:
    case_id: str
    requirement: str
    evidence_tests: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.case_id.strip():
            raise ValueError("case_id must not be empty")
        if not self.requirement.strip():
            raise ValueError("requirement must not be empty")
        if not self.evidence_tests or any(
            not str(item).strip() for item in self.evidence_tests
        ):
            raise ValueError("evidence_tests must not be empty")

    def to_payload(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "requirement": self.requirement,
            "evidence_tests": list(self.evidence_tests),
        }


PHASE10A_REPLAY_CORPUS_V1: tuple[Phase10AReplayCaseV1, ...] = (
    Phase10AReplayCaseV1(
        "01-quiet-healthy",
        "All DesiredStates satisfied produces no finding, work or owner attention.",
        (
            "tests/test_autonomy_reconciler.py::test_reconciler_quiet_violation_replay_and_recovery",
        ),
    ),
    Phase10AReplayCaseV1(
        "02-missing-source",
        "Missing required canonical source evaluates UNKNOWN and dispatches nothing.",
        (
            "tests/test_autonomy_rules.py::test_required_source_incomplete_is_unknown_not_violation",
        ),
    ),
    Phase10AReplayCaseV1(
        "03-stale-evidence",
        "Stale required evidence evaluates UNKNOWN and dispatches nothing.",
        (
            "tests/test_autonomy_rules.py::test_required_source_incomplete_is_unknown_not_violation",
        ),
    ),
    Phase10AReplayCaseV1(
        "04-transient-violation",
        "One transient violation remains STABILIZING.",
        (
            "tests/test_autonomy_reconciler.py::test_reconciler_quiet_violation_replay_and_recovery",
        ),
    ),
    Phase10AReplayCaseV1(
        "05-sustained-violation",
        "Sustained violation creates one ACTIVE finding.",
        (
            "tests/test_autonomy_reconciler.py::test_reconciler_quiet_violation_replay_and_recovery",
        ),
    ),
    Phase10AReplayCaseV1(
        "06-snapshot-replay",
        "Replaying one handled request does not duplicate finding or candidate state.",
        (
            "tests/test_autonomy_reconciler.py::test_reconciler_quiet_violation_replay_and_recovery",
        ),
    ),
    Phase10AReplayCaseV1(
        "07-restart-replay",
        "Restart reconstruction reuses the same candidate and downstream identity.",
        (
            "tests/test_autonomy_reconciler.py::test_restart_reconstructs_stabilization_without_duplicate_candidate",
        ),
    ),
    Phase10AReplayCaseV1(
        "08-stable-recovery",
        "Stable canonical recovery resolves the finding.",
        (
            "tests/test_autonomy_reconciler.py::test_reconciler_quiet_violation_replay_and_recovery",
        ),
    ),
    Phase10AReplayCaseV1(
        "09-deterministic-controller",
        "Registered deterministic controller is preferred over new agentic work.",
        (
            "tests/test_autonomy_findings_resolution.py::test_existing_controller_wins_over_new_agentic_work",
        ),
    ),
    Phase10AReplayCaseV1(
        "10-diagnostics-path",
        "Unknown repair path creates only one bounded diagnostics/research proposal.",
        (
            "tests/test_autonomy_dispatch.py::test_assisted_work_dispatch_is_exactly_once_and_preserves_dependencies",
        ),
    ),
    Phase10AReplayCaseV1(
        "11-governed-change",
        "Novel engineering work creates one governed EngineeringChange.",
        (
            "tests/test_autonomy_dispatch.py::test_assisted_engineering_change_uses_governed_change_lifecycle",
        ),
    ),
    Phase10AReplayCaseV1(
        "12-shadow-zero-dispatch",
        "SHADOW persists evidence/candidates and performs zero downstream dispatch.",
        (
            "tests/test_autonomy_dispatch.py::test_shadow_dispatch_has_zero_downstream_side_effects",
        ),
    ),
    Phase10AReplayCaseV1(
        "13-assisted-one-work",
        "ASSISTED bounded work creates exactly one canonical WorkItem.",
        (
            "tests/test_autonomy_dispatch.py::test_assisted_work_dispatch_is_exactly_once_and_preserves_dependencies",
        ),
    ),
    Phase10AReplayCaseV1(
        "14-authority-preserved",
        "Downstream executor actions remain under existing Authority.",
        (
            "tests/test_autonomy_dispatch.py::test_assisted_engineering_change_uses_governed_change_lifecycle",
        ),
    ),
    Phase10AReplayCaseV1(
        "15-attention-dedupe",
        "Repeated equivalent owner attention deduplicates.",
        (
            "tests/test_autonomy_budgets_portfolio_attention.py::test_repeated_same_attention_is_deduplicated",
        ),
    ),
    Phase10AReplayCaseV1(
        "16-attention-inhibition",
        "Root owner attention inhibits derivative notification spam.",
        (
            "tests/test_autonomy_budgets_portfolio_attention.py::test_root_attention_inhibits_derivative_spam",
        ),
    ),
    Phase10AReplayCaseV1(
        "17-attention-renotify",
        "Owner-attention re-notify interval prevents notification spam.",
        (
            "tests/test_autonomy_budgets_portfolio_attention.py::test_renotify_interval_is_respected",
        ),
    ),
    Phase10AReplayCaseV1(
        "18-budget-exhausted",
        "Exhausted budget defers the candidate and creates no work.",
        (
            "tests/test_autonomy_budgets_portfolio_attention.py::test_budget_exhaustion_creates_no_work",
        ),
    ),
    Phase10AReplayCaseV1(
        "19-cooldown",
        "Active dispatch cooldown prevents redispatch.",
        (
            "tests/test_autonomy_rules.py::test_numeric_tolerance_and_dispatch_cooldown_are_bounded_helpers",
        ),
    ),
    Phase10AReplayCaseV1(
        "20-portfolio-order",
        "Two active objectives receive deterministic portfolio ordering.",
        (
            "tests/test_autonomy_budgets_portfolio_attention.py::test_portfolio_ordering_is_deterministic_and_owner_priority_is_preserved",
        ),
    ),
    Phase10AReplayCaseV1(
        "21-owner-priority",
        "Owner Objective priority is preserved and interactive work is not demoted.",
        (
            "tests/test_autonomy_budgets_portfolio_attention.py::test_portfolio_ordering_is_deterministic_and_owner_priority_is_preserved",
        ),
    ),
    Phase10AReplayCaseV1(
        "22-dependency-tiebreak",
        "Dependency-unblocking tie break remains deterministic and auditable.",
        (
            "tests/test_autonomy_budgets_portfolio_attention.py::test_portfolio_ordering_is_deterministic_and_owner_priority_is_preserved",
        ),
    ),
    Phase10AReplayCaseV1(
        "23-malformed-evidence",
        "Malformed evidence fails closed instead of becoming a valid violation.",
        (
            "tests/test_autonomy_system_state.py::test_malformed_canonical_timestamp_is_explicitly_incomplete",
        ),
    ),
    Phase10AReplayCaseV1(
        "24-unknown-rule-version",
        "Unknown DesiredState rule version fails closed.",
        (
            "tests/test_autonomy_rules.py::test_rule_registry_is_exact_versioned_and_duplicate_safe",
        ),
    ),
    Phase10AReplayCaseV1(
        "25-generation-binding",
        "Stale evaluation cannot satisfy a newer DesiredState generation.",
        (
            "tests/test_autonomy_rules.py::test_stale_generation_cannot_satisfy_new_desired_state",
        ),
    ),
    Phase10AReplayCaseV1(
        "26-reconcile-token",
        "Handled reconcile token is a replay no-op.",
        (
            "tests/test_autonomy_reconciler.py::test_reconciler_quiet_violation_replay_and_recovery",
        ),
    ),
    Phase10AReplayCaseV1(
        "27-outcome-link",
        "Downstream terminal outcome is referenced without copying execution truth.",
        (
            "tests/test_autonomy_store.py::test_autonomy_store_uses_workstore_only_and_round_trips_contracts",
        ),
    ),
    Phase10AReplayCaseV1(
        "28-change-owner-gate",
        "Autonomous EngineeringChange still reaches existing owner architecture gate.",
        (
            "tests/test_autonomy_dispatch.py::test_assisted_engineering_change_uses_governed_change_lifecycle",
        ),
    ),
    Phase10AReplayCaseV1(
        "29-no-self-approval",
        "Autonomy mode/budget never self-grants Authority or owner approval.",
        (
            "tests/test_autonomy_dispatch.py::test_production_autonomy_mode_defaults_to_shadow",
        ),
    ),
    Phase10AReplayCaseV1(
        "30-protected-state",
        "Owner acceptance leaves protected main and production state unchanged.",
        ("src/jarvis/autonomy/phase10a_acceptance.py",),
    ),
)


def phase10a_replay_corpus_digest() -> str:
    return canonical_digest([item.to_payload() for item in PHASE10A_REPLAY_CORPUS_V1])


def validate_phase10a_replay_corpus() -> None:
    if len(PHASE10A_REPLAY_CORPUS_V1) != 30:
        raise ValueError("Phase-10A replay corpus must contain exactly 30 locked cases")
    identities = tuple(item.case_id for item in PHASE10A_REPLAY_CORPUS_V1)
    if len(set(identities)) != len(identities):
        raise ValueError("Phase-10A replay case IDs must be unique")


def phase10a_pytest_node_ids() -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            evidence
            for case in PHASE10A_REPLAY_CORPUS_V1
            for evidence in case.evidence_tests
            if evidence.startswith("tests/") and "::" in evidence
        )
    )
