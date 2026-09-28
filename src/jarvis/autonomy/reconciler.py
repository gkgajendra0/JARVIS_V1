"""Bounded replay-safe autonomy reconciliation runtime for Phase 10A."""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass
from typing import Callable
from uuid import uuid4

from jarvis.autonomy.budgets import BudgetUsageV1
from jarvis.autonomy.dispatch import AutonomyDispatchResultV1, AutonomyDispatchService
from jarvis.autonomy.findings import FindingLifecycleManager
from jarvis.autonomy.models import (
    AutonomyBudgetPolicyV1,
    AutonomyFindingV1,
    AutonomyMode,
    CandidateDisposition,
    DesiredStateV1,
    FindingStatus,
    ObjectiveV1,
    ReconcileRunV1,
    ReconcileStatus,
    ReconcileTrigger,
    finding_id_for,
)
from jarvis.autonomy.portfolio import (
    PortfolioInputV1,
    PortfolioPrioritizer,
    PrioritizedCandidateV1,
    PriorityFactorsV1,
)
from jarvis.autonomy.resolution import (
    ActionResolutionResultV1,
    ActionResolutionService,
    UnknownActionResolverError,
)
from jarvis.autonomy.rules import (
    DesiredStateEvaluationStatus,
    DesiredStateEvaluationV1,
    DesiredStateEvaluator,
    DesiredStateStabilizer,
    StabilizationStateV1,
)
from jarvis.autonomy.store import AutonomyStore
from jarvis.autonomy.system_state import (
    SystemStateAggregator,
    SystemStateSnapshotV1,
    SystemStateTargetV1,
)
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.work.models import WorkPriority

LOGGER = logging.getLogger(__name__)

BudgetUsageProvider = Callable[
    [ObjectiveV1, DesiredStateV1, AutonomyFindingV1],
    BudgetUsageV1,
]
PriorityFactorProvider = Callable[
    [ObjectiveV1, DesiredStateV1, AutonomyFindingV1],
    PriorityFactorsV1,
]


def _epoch(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{field} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0:
        raise ValueError(f"{field} must be finite and non-negative")
    return normalized


def _text(value: object, field: str, *, max_length: int = 500) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    if len(normalized) > max_length:
        raise ValueError(f"{field} exceeds {max_length} characters")
    return normalized


@dataclass(frozen=True, slots=True)
class DesiredReconcileResultV1:
    desired_state_id: str
    desired_generation: int
    evaluation_status: DesiredStateEvaluationStatus
    finding_id: str | None
    finding_status: FindingStatus | None
    candidate_id: str | None
    candidate_disposition: CandidateDisposition | None
    dispatch_disposition: CandidateDisposition | None
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "desired_state_id",
            _text(self.desired_state_id, "desired_state_id", max_length=240),
        )
        if self.desired_generation <= 0:
            raise ValueError("desired_generation must be positive")
        if not isinstance(self.evaluation_status, DesiredStateEvaluationStatus):
            raise TypeError("evaluation_status must be DesiredStateEvaluationStatus")
        if self.finding_status is not None and not isinstance(
            self.finding_status, FindingStatus
        ):
            raise TypeError("finding_status must be FindingStatus")
        if self.candidate_disposition is not None and not isinstance(
            self.candidate_disposition,
            CandidateDisposition,
        ):
            raise TypeError("candidate_disposition must be CandidateDisposition")
        if self.dispatch_disposition is not None and not isinstance(
            self.dispatch_disposition,
            CandidateDisposition,
        ):
            raise TypeError("dispatch_disposition must be CandidateDisposition")
        reasons = tuple(
            sorted(
                {
                    str(value).strip().casefold()
                    for value in self.reason_codes
                    if str(value).strip()
                }
            )
        )
        if not reasons:
            raise ValueError("reason_codes must not be empty")
        object.__setattr__(self, "reason_codes", reasons)


@dataclass(frozen=True, slots=True)
class ReconcileBatchResultV1:
    request_token: str
    trigger: ReconcileTrigger
    status: ReconcileStatus
    replayed: bool
    busy: bool
    run_id: str | None
    snapshot_id: str | None
    desired_generation_digest: str | None
    desired_results: tuple[DesiredReconcileResultV1, ...]
    started_at_epoch: float
    ended_at_epoch: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "request_token",
            _text(self.request_token, "request_token", max_length=500),
        )
        if not isinstance(self.trigger, ReconcileTrigger):
            raise TypeError("trigger must be ReconcileTrigger")
        if not isinstance(self.status, ReconcileStatus):
            raise TypeError("status must be ReconcileStatus")
        if not isinstance(self.replayed, bool) or not isinstance(self.busy, bool):
            raise TypeError("replayed and busy must be booleans")
        started = _epoch(self.started_at_epoch, "started_at_epoch")
        ended = _epoch(self.ended_at_epoch, "ended_at_epoch")
        if ended < started:
            raise ValueError("ended_at_epoch cannot precede started_at_epoch")
        object.__setattr__(self, "started_at_epoch", started)
        object.__setattr__(self, "ended_at_epoch", ended)


@dataclass(slots=True)
class _PendingCandidate:
    objective: ObjectiveV1
    desired: DesiredStateV1
    finding: AutonomyFindingV1
    resolution: ActionResolutionResultV1


def _default_priority_factors(
    objective: ObjectiveV1,
    desired: DesiredStateV1,
    finding: AutonomyFindingV1,
) -> PriorityFactorsV1:
    constraints = objective.constraint_json

    def explicit_bucket(key: str, *, maximum: int = 3) -> int:
        value = constraints.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            return 0
        if value < 0 or value > maximum:
            return 0
        return value

    provenance = {
        "owner_priority": "objective.priority",
        "obligation_criticality": (
            "objective.constraint_json.obligation_criticality"
            if "obligation_criticality" in constraints
            else "not_asserted"
        ),
        "deadline_urgency": (
            "objective.constraint_json.deadline_urgency"
            if "deadline_urgency" in constraints
            else "not_asserted"
        ),
        "impact_scope": (
            "objective.constraint_json.impact_scope"
            if "impact_scope" in constraints
            else "not_asserted"
        ),
        "dependency_unblocking": (
            "objective.constraint_json.dependency_unblocking"
            if "dependency_unblocking" in constraints
            else "not_asserted"
        ),
        "starvation_age": "not_asserted",
        "resource_feasibility": "not_measured",
    }
    return PriorityFactorsV1(
        owner_priority=objective.priority,
        obligation_criticality=explicit_bucket("obligation_criticality"),
        deadline_urgency=explicit_bucket("deadline_urgency"),
        impact_scope=explicit_bucket("impact_scope"),
        dependency_unblocking=explicit_bucket("dependency_unblocking"),
        starvation_age=0,
        resource_feasibility=0,
        provenance_json=provenance,
    )


def _stabilization_from_finding(
    desired: DesiredStateV1,
    finding: AutonomyFindingV1 | None,
) -> StabilizationStateV1 | None:
    if finding is None or finding.desired_generation != desired.generation:
        return None
    if finding.status in {FindingStatus.RESOLVED, FindingStatus.SUPERSEDED}:
        return None
    recovery = "recovery_stabilizing" in finding.reason_codes
    stable = (
        finding.status
        in {
            FindingStatus.ACTIVE,
            FindingStatus.SUPPRESSED,
        }
        or recovery
    )
    return StabilizationStateV1(
        desired_state_id=desired.desired_state_id,
        desired_generation=desired.generation,
        consecutive_violations=(0 if recovery else max(1, finding.violation_count)),
        first_violation_at_epoch=finding.first_seen_epoch,
        last_violation_at_epoch=finding.last_seen_epoch,
        recovery_started_at_epoch=(finding.last_seen_epoch if recovery else None),
        stable_violation=stable,
        last_raw_status=(
            DesiredStateEvaluationStatus.SATISFIED
            if recovery
            else DesiredStateEvaluationStatus.VIOLATED
        ),
    )


class AutonomyReconciler:
    """One bounded deterministic whole-JARVIS reconciliation service."""

    def __init__(
        self,
        *,
        store: AutonomyStore,
        aggregator: SystemStateAggregator,
        evaluator: DesiredStateEvaluator,
        stabilizer: DesiredStateStabilizer,
        findings: FindingLifecycleManager,
        resolution: ActionResolutionService,
        portfolio: PortfolioPrioritizer,
        dispatch: AutonomyDispatchService,
        budget_policy: AutonomyBudgetPolicyV1 | None = None,
        budget_usage_provider: BudgetUsageProvider | None = None,
        priority_factor_provider: PriorityFactorProvider | None = None,
        max_desired_states: int = 100,
        max_facts: int = 500,
        clock=time.time,
    ) -> None:
        if not isinstance(store, AutonomyStore):
            raise TypeError("store must be AutonomyStore")
        if not isinstance(aggregator, SystemStateAggregator):
            raise TypeError("aggregator must be SystemStateAggregator")
        if not isinstance(evaluator, DesiredStateEvaluator):
            raise TypeError("evaluator must be DesiredStateEvaluator")
        if not isinstance(stabilizer, DesiredStateStabilizer):
            raise TypeError("stabilizer must be DesiredStateStabilizer")
        if not isinstance(findings, FindingLifecycleManager):
            raise TypeError("findings must be FindingLifecycleManager")
        if not isinstance(resolution, ActionResolutionService):
            raise TypeError("resolution must be ActionResolutionService")
        if not isinstance(portfolio, PortfolioPrioritizer):
            raise TypeError("portfolio must be PortfolioPrioritizer")
        if not isinstance(dispatch, AutonomyDispatchService):
            raise TypeError("dispatch must be AutonomyDispatchService")
        if max_desired_states <= 0 or max_desired_states > 1000:
            raise ValueError("max_desired_states must be between 1 and 1000")
        if max_facts <= 0 or max_facts > 5000:
            raise ValueError("max_facts must be between 1 and 5000")
        self.store = store
        self.aggregator = aggregator
        self.evaluator = evaluator
        self.stabilizer = stabilizer
        self.findings = findings
        self.resolution = resolution
        self.portfolio = portfolio
        self.dispatch = dispatch
        self.budget_policy = budget_policy
        self.budget_usage_provider = budget_usage_provider
        self.priority_factor_provider = (
            priority_factor_provider or _default_priority_factors
        )
        self.max_desired_states = max_desired_states
        self.max_facts = max_facts
        self.clock = clock
        self._lock = threading.Lock()
        self._stabilization: dict[str, StabilizationStateV1] = {}

    @property
    def mode(self) -> AutonomyMode:
        return self.dispatch.config.mode

    def reconcile(
        self,
        request_token: str,
        *,
        trigger: ReconcileTrigger,
    ) -> ReconcileBatchResultV1:
        token = _text(request_token, "request_token", max_length=500)
        if not isinstance(trigger, ReconcileTrigger):
            raise TypeError("trigger must be ReconcileTrigger")
        now = _epoch(self.clock(), "clock")
        if self.mode is AutonomyMode.OFF:
            return ReconcileBatchResultV1(
                request_token=token,
                trigger=trigger,
                status=ReconcileStatus.REPLAY_NOOP,
                replayed=False,
                busy=False,
                run_id=None,
                snapshot_id=None,
                desired_generation_digest=None,
                desired_results=(),
                started_at_epoch=now,
                ended_at_epoch=now,
            )
        if not self._lock.acquire(blocking=False):
            return ReconcileBatchResultV1(
                request_token=token,
                trigger=trigger,
                status=ReconcileStatus.REPLAY_NOOP,
                replayed=False,
                busy=True,
                run_id=None,
                snapshot_id=None,
                desired_generation_digest=None,
                desired_results=(),
                started_at_epoch=now,
                ended_at_epoch=now,
            )
        try:
            return self._reconcile_locked(token, trigger=trigger)
        finally:
            self._lock.release()

    def _reconcile_locked(
        self,
        token: str,
        *,
        trigger: ReconcileTrigger,
    ) -> ReconcileBatchResultV1:
        started = _epoch(self.clock(), "clock")
        try:
            existing = self.store.require_reconcile_run_by_token(token)
        except KeyError:
            existing = None
        if (
            existing is not None
            and existing.status is ReconcileStatus.COMPLETED
            and existing.handled_token == token
        ):
            ended = _epoch(self.clock(), "clock")
            return ReconcileBatchResultV1(
                request_token=token,
                trigger=existing.trigger,
                status=ReconcileStatus.REPLAY_NOOP,
                replayed=True,
                busy=False,
                run_id=existing.reconcile_run_id,
                snapshot_id=None,
                desired_generation_digest=existing.desired_generation_digest,
                desired_results=(),
                started_at_epoch=started,
                ended_at_epoch=ended,
            )

        objectives = self.store.list_objectives(
            statuses=("active",),
            limit=self.max_desired_states,
        )
        objective_by_id = {item.objective_id: item for item in objectives}
        desired = tuple(
            item
            for item in self.store.list_desired_states(
                statuses=("active",),
                limit=self.max_desired_states + 1,
            )
            if item.objective_id in objective_by_id
        )
        if len(desired) > self.max_desired_states:
            raise RuntimeError("active DesiredState batch exceeds configured bound")

        desired_digest = canonical_digest(
            [
                {
                    "desired_state_id": item.desired_state_id,
                    "objective_id": item.objective_id,
                    "generation": item.generation,
                    "rule_key": item.rule_key,
                    "rule_version": item.rule_version,
                }
                for item in desired
            ]
        )
        run_id = (
            existing.reconcile_run_id
            if existing is not None
            else f"reconcile_{canonical_digest({'request_token': token})[:24]}"
        )
        run_started = existing.started_at_epoch if existing is not None else started
        if existing is None:
            self.store.create_reconcile_run(
                ReconcileRunV1(
                    reconcile_run_id=run_id,
                    request_token=token,
                    trigger=trigger,
                    started_at_epoch=run_started,
                    desired_generation_digest=desired_digest,
                    status=ReconcileStatus.STARTED,
                )
            )
        elif (
            existing.trigger is not trigger
            or existing.desired_generation_digest != desired_digest
        ):
            raise RuntimeError(
                "reconcile token replay does not match original trigger/generation set"
            )

        snapshot: SystemStateSnapshotV1 | None = None
        desired_results: tuple[DesiredReconcileResultV1, ...] = ()
        try:
            if desired:
                namespaces = tuple(
                    sorted(
                        {
                            namespace
                            for item in desired
                            for namespace in item.required_source_namespaces
                        }
                    )
                )
                targets = tuple(
                    sorted(
                        {
                            SystemStateTargetV1(
                                target_namespace=item.target_namespace,
                                target_identity=item.target_identity,
                            )
                            for item in desired
                        },
                        key=lambda item: (
                            item.target_namespace,
                            item.target_identity,
                        ),
                    )
                )
                snapshot = self.aggregator.snapshot(
                    requested_namespaces=namespaces,
                    targets=targets,
                    max_facts=self.max_facts,
                )
                self.store.record_system_snapshot(snapshot)
                desired_results = self._evaluate_and_dispatch(
                    desired,
                    objective_by_id=objective_by_id,
                    snapshot=snapshot,
                )

            ended = _epoch(self.clock(), "clock")
            completed = ReconcileRunV1(
                reconcile_run_id=run_id,
                request_token=token,
                trigger=trigger,
                started_at_epoch=run_started,
                ended_at_epoch=ended,
                desired_generation_digest=desired_digest,
                snapshot_digest=(
                    None if snapshot is None else snapshot.snapshot_digest
                ),
                status=ReconcileStatus.COMPLETED,
                handled_token=token,
            )
            self.store.finalize_reconcile_run(completed)
            return ReconcileBatchResultV1(
                request_token=token,
                trigger=trigger,
                status=ReconcileStatus.COMPLETED,
                replayed=False,
                busy=False,
                run_id=run_id,
                snapshot_id=None if snapshot is None else snapshot.snapshot_id,
                desired_generation_digest=desired_digest,
                desired_results=desired_results,
                started_at_epoch=run_started,
                ended_at_epoch=ended,
            )
        except Exception:
            ended = _epoch(self.clock(), "clock")
            failed = ReconcileRunV1(
                reconcile_run_id=run_id,
                request_token=token,
                trigger=trigger,
                started_at_epoch=run_started,
                ended_at_epoch=ended,
                desired_generation_digest=desired_digest,
                snapshot_digest=(
                    None if snapshot is None else snapshot.snapshot_digest
                ),
                status=ReconcileStatus.FAILED,
                handled_token=None,
            )
            self.store.finalize_reconcile_run(failed)
            raise

    def _evaluate_and_dispatch(
        self,
        desired_states: tuple[DesiredStateV1, ...],
        *,
        objective_by_id: dict[str, ObjectiveV1],
        snapshot: SystemStateSnapshotV1,
    ) -> tuple[DesiredReconcileResultV1, ...]:
        interim: dict[str, DesiredReconcileResultV1] = {}
        pending: list[_PendingCandidate] = []

        for desired in desired_states:
            objective = objective_by_id[desired.objective_id]
            raw = self.evaluator.evaluate_raw(desired, snapshot)
            finding_id = finding_id_for(desired, finding_kind="state_gap")
            try:
                current = self.store.require_finding(finding_id)
            except KeyError:
                current = None
            previous = self._stabilization.get(desired.desired_state_id)
            if previous is None:
                previous = _stabilization_from_finding(desired, current)
            stabilized = self.stabilizer.apply(
                desired,
                raw,
                previous=previous,
            )
            self._stabilization[desired.desired_state_id] = stabilized.state
            lifecycle = self.findings.apply(
                desired,
                stabilized.evaluation,
            )
            finding = lifecycle.finding
            resolution: ActionResolutionResultV1 | None = None
            if finding is not None and stabilized.evaluation.status is not (
                DesiredStateEvaluationStatus.UNKNOWN
            ):
                resolver = self._resolver_for(desired, finding)
                if resolver is not None:
                    resolution = self.resolution.resolve_and_record(
                        desired,
                        finding,
                        resolver_key=resolver[0],
                        resolver_version=resolver[1],
                    )

            if (
                finding is not None
                and finding.status is FindingStatus.ACTIVE
                and resolution is not None
                and resolution.candidate is not None
            ):
                pending.append(
                    _PendingCandidate(
                        objective=objective,
                        desired=desired,
                        finding=finding,
                        resolution=resolution,
                    )
                )

            interim[desired.desired_state_id] = DesiredReconcileResultV1(
                desired_state_id=desired.desired_state_id,
                desired_generation=desired.generation,
                evaluation_status=stabilized.evaluation.status,
                finding_id=None if finding is None else finding.finding_id,
                finding_status=None if finding is None else finding.status,
                candidate_id=(
                    None
                    if resolution is None or resolution.candidate is None
                    else resolution.candidate.candidate_id
                ),
                candidate_disposition=(
                    None if resolution is None else resolution.disposition
                ),
                dispatch_disposition=None,
                reason_codes=tuple(
                    dict.fromkeys(
                        (
                            *stabilized.evaluation.reason_codes,
                            lifecycle.reason_code,
                            *(() if resolution is None else resolution.reason_codes),
                        )
                    )
                ),
            )

        prioritized = self._prioritize(tuple(pending))
        priority_by_candidate = {item.candidate_id: item for item in prioritized}
        for item in pending:
            candidate = item.resolution.candidate
            assert candidate is not None
            current_result = interim[item.desired.desired_state_id]
            dispatch_result = self._dispatch_candidate(
                item,
                priority=priority_by_candidate[candidate.candidate_id],
            )
            interim[item.desired.desired_state_id] = DesiredReconcileResultV1(
                desired_state_id=current_result.desired_state_id,
                desired_generation=current_result.desired_generation,
                evaluation_status=current_result.evaluation_status,
                finding_id=current_result.finding_id,
                finding_status=current_result.finding_status,
                candidate_id=current_result.candidate_id,
                candidate_disposition=current_result.candidate_disposition,
                dispatch_disposition=dispatch_result.disposition,
                reason_codes=tuple(
                    dict.fromkeys(
                        (*current_result.reason_codes, *dispatch_result.reason_codes)
                    )
                ),
            )

        return tuple(interim[key] for key in sorted(interim))

    def _resolver_for(
        self,
        desired: DesiredStateV1,
        finding: AutonomyFindingV1,
    ) -> tuple[str, int] | None:
        matches = tuple(
            resolver
            for resolver in self.resolution.registry.all()
            if (desired.rule_key, desired.rule_version) in resolver.supported_rules
            and finding.finding_kind in resolver.supported_finding_kinds
        )
        if len(matches) != 1:
            return None
        resolver = matches[0]
        try:
            self.resolution.registry.require(
                resolver.resolver_key,
                resolver.resolver_version,
            )
        except UnknownActionResolverError:
            return None
        return resolver.resolver_key, resolver.resolver_version

    def _prioritize(
        self,
        pending: tuple[_PendingCandidate, ...],
    ) -> tuple[PrioritizedCandidateV1, ...]:
        inputs = tuple(
            PortfolioInputV1(
                candidate=item.resolution.candidate,
                objective=item.objective,
                factors=self.priority_factor_provider(
                    item.objective,
                    item.desired,
                    item.finding,
                ),
            )
            for item in pending
            if item.resolution.candidate is not None
        )
        return self.portfolio.prioritize(inputs)

    def _dispatch_candidate(
        self,
        item: _PendingCandidate,
        *,
        priority: PrioritizedCandidateV1,
    ) -> AutonomyDispatchResultV1:
        candidate = item.resolution.candidate
        assert candidate is not None
        now = _epoch(self.clock(), "clock")
        if self._cooldown_active(item, now_epoch=now):
            return AutonomyDispatchResultV1(
                candidate_id=candidate.candidate_id,
                mode=self.mode,
                disposition=CandidateDisposition.DEFERRED_COOLDOWN,
                reason_codes=("dispatch_cooldown_active",),
            )
        if self.mode is AutonomyMode.ASSISTED and self.budget_usage_provider is None:
            return AutonomyDispatchResultV1(
                candidate_id=candidate.candidate_id,
                mode=self.mode,
                disposition=CandidateDisposition.BLOCKED_POLICY,
                reason_codes=("budget_usage_provider_unavailable",),
            )
        usage = (
            BudgetUsageV1(
                active_autonomous_work_items=0,
                new_autonomous_work_items_in_window=0,
                active_candidates_for_objective=0,
                repeated_dispatches_for_finding_window=0,
                owner_attention_notifications_in_window=0,
            )
            if self.mode is not AutonomyMode.ASSISTED
            else self.budget_usage_provider(
                item.objective,
                item.desired,
                item.finding,
            )
        )
        return self.dispatch.dispatch(
            candidate.candidate_id,
            budget_policy=self.budget_policy,
            budget_usage=usage,
            priority=priority,
            now_epoch=now,
            renotify_interval_seconds=(
                item.desired.stabilization_policy.renotify_interval_seconds
            ),
        )

    def _cooldown_active(
        self,
        item: _PendingCandidate,
        *,
        now_epoch: float,
    ) -> bool:
        cooldown = item.desired.stabilization_policy.cooldown_after_dispatch_seconds
        if cooldown <= 0:
            return False
        for candidate in self.store.list_action_candidates_for_finding(
            item.finding.finding_id
        ):
            link = self.store.get_dispatch_link(candidate.candidate_id)
            if link is not None and now_epoch < link.created_at_epoch + cooldown:
                return True
        return False


class PeriodicAutonomyReconciler:
    """Replaceable trigger wrapper; canonical correctness remains in AutonomyReconciler."""

    def __init__(
        self,
        reconciler: AutonomyReconciler,
        *,
        interval_seconds: float = 300.0,
        instance_token: str | None = None,
        clock=time.time,
    ) -> None:
        if not isinstance(reconciler, AutonomyReconciler):
            raise TypeError("reconciler must be AutonomyReconciler")
        if (
            isinstance(interval_seconds, bool)
            or not isinstance(interval_seconds, int | float)
            or not math.isfinite(float(interval_seconds))
            or interval_seconds <= 0
        ):
            raise ValueError("interval_seconds must be finite and positive")
        self.reconciler = reconciler
        self.interval_seconds = float(interval_seconds)
        self.instance_token = _text(
            instance_token or uuid4().hex,
            "instance_token",
            max_length=200,
        )
        self.clock = clock
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="jarvis-autonomy-reconciler",
            daemon=True,
        )
        self._thread.start()

    def stop(self, *, timeout_seconds: float = 5.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=max(0.0, float(timeout_seconds)))
            if thread.is_alive():
                raise RuntimeError("autonomy reconciler did not stop cleanly")
        self._thread = None

    def state_change_hint(self, token: str) -> ReconcileBatchResultV1:
        return self.reconciler.reconcile(
            f"state-change:{_text(token, 'token', max_length=300)}",
            trigger=ReconcileTrigger.STATE_CHANGE_HINT,
        )

    def manual_test(self, token: str) -> ReconcileBatchResultV1:
        return self.reconciler.reconcile(
            f"manual-test:{_text(token, 'token', max_length=300)}",
            trigger=ReconcileTrigger.MANUAL_TEST,
        )

    def _run(self) -> None:
        try:
            self.reconciler.reconcile(
                f"startup:{self.instance_token}",
                trigger=ReconcileTrigger.STARTUP,
            )
        except Exception:
            LOGGER.exception("startup autonomy reconciliation failed")
        while not self._stop.wait(self.interval_seconds):
            bucket = int(_epoch(self.clock(), "clock") // self.interval_seconds)
            try:
                self.reconciler.reconcile(
                    f"periodic:{self.instance_token}:{bucket}",
                    trigger=ReconcileTrigger.PERIODIC,
                )
            except Exception:
                LOGGER.exception("periodic autonomy reconciliation failed")
