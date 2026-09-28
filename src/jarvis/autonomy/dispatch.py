"""Governed SHADOW/ASSISTED dispatch bridges for Phase 10A."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

from jarvis.autonomy.attention import (
    AttentionDeliveryAttemptV1,
    OwnerAttentionDeliveryAdapter,
    OwnerAttentionManager,
)
from jarvis.autonomy.budgets import (
    AutonomyBudgetEvaluator,
    BudgetUsageV1,
)
from jarvis.autonomy.models import (
    ActionCandidateV1,
    ActionKind,
    AutonomyBudgetPolicyV1,
    AutonomyDispatchLinkV1,
    AutonomyMode,
    CandidateDisposition,
    DesiredStateStatus,
    FindingStatus,
    ObjectiveStatus,
    ObjectiveV1,
    deterministic_id,
)
from jarvis.autonomy.portfolio import PrioritizedCandidateV1
from jarvis.autonomy.store import AutonomyStore
from jarvis.capability_registry.reconciliation import (
    CapabilityLifecycleReconciler,
    ReconciliationTrigger,
)
from jarvis.engineering_change.coordinator import ChangeCoordinator
from jarvis.engineering_change.models import EngineeringChange
from jarvis.engineering_knowledge.canonical import JSONValue
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.work.models import DeliveryPolicy, WorkPriority, WorkType
from jarvis.work.orchestrator import WorkOrchestrator, WorkSubmission
from jarvis.work.store import SQLiteWorkStore

_ASSISTED_WORK_TYPES = frozenset(
    {
        WorkType.MONITORING,
        WorkType.RESEARCH,
        WorkType.DIAGNOSTICS,
    }
)


def _text(value: object, field: str, *, max_length: int = 2000) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    if len(normalized) > max_length:
        raise ValueError(f"{field} exceeds {max_length} characters")
    if any(ord(character) < 32 for character in normalized):
        raise ValueError(f"{field} contains control characters")
    return normalized


def _token(value: object, field: str, *, max_length: int = 200) -> str:
    return _text(value, field, max_length=max_length).casefold()


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be an integer")
    if value <= 0:
        raise ValueError(f"{field} must be positive")
    return value


def _epoch(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{field} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0:
        raise ValueError(f"{field} must be finite and non-negative")
    return normalized


def _json_object(value: object, field: str) -> dict[str, JSONValue]:
    if not isinstance(value, dict):
        raise TypeError(f"{field} must be a JSON object")
    canonical_digest(value)
    return dict(value)


def _candidate_source_identity(
    candidate: ActionCandidateV1,
) -> tuple[str, str, str]:
    session_id = f"autonomy:{candidate.resolver_key}:v{candidate.resolver_version}"
    turn_id = f"dispatch:{candidate.candidate_id}"
    return session_id, turn_id, f"{session_id}/{turn_id}"


def _candidate_request(candidate: ActionCandidateV1) -> str:
    return (
        f"Autonomy candidate {candidate.candidate_id}. "
        f"Expected effect: {candidate.expected_effect} "
        f"Target: {candidate.target_namespace}:{candidate.target_identity}. "
        f"Finding: {candidate.finding_id}. "
        f"Evidence snapshot: {candidate.snapshot_digest}."
    )


@dataclass(frozen=True, slots=True)
class AutonomyDispatchConfigV1:
    """Runtime mode boundary. Production construction defaults to SHADOW."""

    mode: AutonomyMode = AutonomyMode.SHADOW

    def __post_init__(self) -> None:
        if not isinstance(self.mode, AutonomyMode):
            raise TypeError("mode must be AutonomyMode")
        if self.mode is AutonomyMode.ACTIVE_BOUNDED:
            raise ValueError(
                "ACTIVE_BOUNDED requires later explicit owner-approved policy"
            )


@dataclass(frozen=True, slots=True)
class DispatchBridgeRegistrationV1:
    """Exact resolver/action -> accepted downstream bridge contract."""

    resolver_key: str
    resolver_version: int
    action_kind: ActionKind
    work_type: WorkType | None = None
    process_key: str | None = None
    process_version: int | None = None
    controller_key: str | None = None
    controller_version: int | None = None
    controller_contract_digest: str | None = None
    attention_group_key: str | None = None
    attention_reason_codes: tuple[str, ...] = ()
    attention_question: str | None = None
    attention_option_metadata_json: dict[str, JSONValue] | None = None
    attention_consequence_of_waiting: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "resolver_key",
            _token(self.resolver_key, "resolver_key"),
        )
        object.__setattr__(
            self,
            "resolver_version",
            _positive_int(self.resolver_version, "resolver_version"),
        )
        if not isinstance(self.action_kind, ActionKind):
            raise TypeError("action_kind must be an ActionKind")
        if self.action_kind is ActionKind.NO_ACTION:
            raise ValueError("NO_ACTION cannot register a dispatch bridge")

        if self.action_kind is ActionKind.WORK_ITEM:
            if self.work_type not in _ASSISTED_WORK_TYPES:
                raise ValueError(
                    "autonomous WorkItem bridge must use MONITORING/RESEARCH/DIAGNOSTICS"
                )
            self._reject_non_work_fields()
        elif self.action_kind is ActionKind.ENGINEERING_CHANGE:
            process_key = _token(
                self.process_key,
                "process_key",
                max_length=240,
            )
            process_version = _positive_int(
                self.process_version,
                "process_version",
            )
            object.__setattr__(self, "process_key", process_key)
            object.__setattr__(self, "process_version", process_version)
            self._reject_fields(
                "work_type",
                "controller_key",
                "controller_version",
                "controller_contract_digest",
                "attention_group_key",
                "attention_question",
                "attention_option_metadata_json",
                "attention_consequence_of_waiting",
            )
            if self.attention_reason_codes:
                raise ValueError(
                    "engineering-change bridge cannot carry attention reason codes"
                )
        elif self.action_kind is ActionKind.EXISTING_CONTROLLER:
            controller_key = _token(
                self.controller_key,
                "controller_key",
                max_length=240,
            )
            controller_version = _positive_int(
                self.controller_version,
                "controller_version",
            )
            object.__setattr__(self, "controller_key", controller_key)
            object.__setattr__(self, "controller_version", controller_version)
            digest = _text(
                self.controller_contract_digest,
                "controller_contract_digest",
                max_length=64,
            ).casefold()
            if len(digest) != 64 or any(
                char not in "0123456789abcdef" for char in digest
            ):
                raise ValueError("controller_contract_digest must be SHA-256")
            object.__setattr__(self, "controller_contract_digest", digest)
            self._reject_fields(
                "work_type",
                "process_key",
                "process_version",
                "attention_group_key",
                "attention_question",
                "attention_option_metadata_json",
                "attention_consequence_of_waiting",
            )
            if self.attention_reason_codes:
                raise ValueError(
                    "controller bridge cannot carry attention reason codes"
                )
        elif self.action_kind is ActionKind.OWNER_ATTENTION:
            object.__setattr__(
                self,
                "attention_group_key",
                _token(
                    self.attention_group_key,
                    "attention_group_key",
                    max_length=500,
                ),
            )
            reasons = tuple(
                dict.fromkeys(
                    _token(value, "attention_reason_code", max_length=240)
                    for value in self.attention_reason_codes
                )
            )
            if not reasons:
                raise ValueError("attention bridge requires reason codes")
            object.__setattr__(self, "attention_reason_codes", reasons)
            object.__setattr__(
                self,
                "attention_question",
                _text(self.attention_question, "attention_question"),
            )
            object.__setattr__(
                self,
                "attention_option_metadata_json",
                _json_object(
                    self.attention_option_metadata_json,
                    "attention_option_metadata_json",
                ),
            )
            object.__setattr__(
                self,
                "attention_consequence_of_waiting",
                _text(
                    self.attention_consequence_of_waiting,
                    "attention_consequence_of_waiting",
                ),
            )
            self._reject_fields(
                "work_type",
                "process_key",
                "process_version",
                "controller_key",
                "controller_version",
                "controller_contract_digest",
            )
        else:  # pragma: no cover - enum exhaustiveness guard
            raise ValueError("unsupported action kind")

    def _reject_non_work_fields(self) -> None:
        self._reject_fields(
            "process_key",
            "process_version",
            "controller_key",
            "controller_version",
            "controller_contract_digest",
            "attention_group_key",
            "attention_question",
            "attention_option_metadata_json",
            "attention_consequence_of_waiting",
        )
        if self.attention_reason_codes:
            raise ValueError("work bridge cannot carry attention reason codes")

    def _reject_fields(self, *field_names: str) -> None:
        present = [
            field_name
            for field_name in field_names
            if getattr(self, field_name) is not None
        ]
        if present:
            raise ValueError(
                f"dispatch bridge has fields invalid for {self.action_kind.value}: "
                f"{present}"
            )

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "resolver_key": self.resolver_key,
            "resolver_version": self.resolver_version,
            "action_kind": self.action_kind.value,
            "work_type": None if self.work_type is None else self.work_type.value,
            "process_key": self.process_key,
            "process_version": self.process_version,
            "controller_key": self.controller_key,
            "controller_version": self.controller_version,
            "controller_contract_digest": self.controller_contract_digest,
            "attention_group_key": self.attention_group_key,
            "attention_reason_codes": list(self.attention_reason_codes),
            "attention_question": self.attention_question,
            "attention_option_metadata_json": self.attention_option_metadata_json,
            "attention_consequence_of_waiting": (self.attention_consequence_of_waiting),
        }

    @property
    def digest(self) -> str:
        return canonical_digest(self.to_payload())


class DuplicateDispatchBridgeError(RuntimeError):
    pass


class DispatchBridgeRegistry:
    """Exact candidate resolver/action registry. No generic invocation fallback exists."""

    def __init__(
        self,
        registrations: tuple[DispatchBridgeRegistrationV1, ...] = (),
    ) -> None:
        self._registrations: dict[
            tuple[str, int, ActionKind],
            DispatchBridgeRegistrationV1,
        ] = {}
        for registration in registrations:
            self.register(registration)

    def register(self, registration: DispatchBridgeRegistrationV1) -> None:
        if not isinstance(registration, DispatchBridgeRegistrationV1):
            raise TypeError("registration must be DispatchBridgeRegistrationV1")
        identity = (
            registration.resolver_key,
            registration.resolver_version,
            registration.action_kind,
        )
        if identity in self._registrations:
            raise DuplicateDispatchBridgeError(
                "dispatch bridge already registered for "
                f"{registration.resolver_key}.v{registration.resolver_version}/"
                f"{registration.action_kind.value}"
            )
        self._registrations[identity] = registration

    def get(
        self,
        candidate: ActionCandidateV1,
    ) -> DispatchBridgeRegistrationV1 | None:
        return self._registrations.get(
            (
                candidate.resolver_key,
                candidate.resolver_version,
                candidate.action_kind,
            )
        )

    def all(self) -> tuple[DispatchBridgeRegistrationV1, ...]:
        return tuple(
            self._registrations[key]
            for key in sorted(
                self._registrations,
                key=lambda item: (item[0], item[1], item[2].value),
            )
        )


@dataclass(frozen=True, slots=True)
class ControllerDispatchReceiptV1:
    downstream_id: str
    downstream_version: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "downstream_id",
            _text(self.downstream_id, "downstream_id", max_length=500),
        )
        if self.downstream_version is not None:
            object.__setattr__(
                self,
                "downstream_version",
                _text(
                    self.downstream_version,
                    "downstream_version",
                    max_length=500,
                ),
            )


class ExistingController(Protocol):
    controller_key: str
    controller_version: int
    contract_digest: str
    replay_safe: bool

    def invoke(
        self,
        candidate: ActionCandidateV1,
        *,
        source_identity: str,
    ) -> ControllerDispatchReceiptV1: ...


class DuplicateExistingControllerError(RuntimeError):
    pass


class ExistingControllerRegistry:
    """Only explicitly registered replay-safe deterministic controllers are callable."""

    def __init__(self, controllers: tuple[ExistingController, ...] = ()) -> None:
        self._controllers: dict[tuple[str, int], ExistingController] = {}
        for controller in controllers:
            self.register(controller)

    def register(self, controller: ExistingController) -> None:
        key = _token(
            getattr(controller, "controller_key", ""),
            "controller_key",
        )
        version = _positive_int(
            getattr(controller, "controller_version", None),
            "controller_version",
        )
        digest = _text(
            getattr(controller, "contract_digest", ""),
            "contract_digest",
            max_length=64,
        ).casefold()
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("controller contract_digest must be SHA-256")
        if getattr(controller, "replay_safe", False) is not True:
            raise ValueError(
                "existing controller must explicitly declare replay safety"
            )
        if not callable(getattr(controller, "invoke", None)):
            raise TypeError("existing controller must provide invoke")
        identity = (key, version)
        if identity in self._controllers:
            raise DuplicateExistingControllerError(
                f"existing controller already registered: {key}.v{version}"
            )
        self._controllers[identity] = controller

    def get(self, key: str, version: int) -> ExistingController | None:
        return self._controllers.get(
            (
                _token(key, "controller_key"),
                _positive_int(version, "controller_version"),
            )
        )


class CapabilityReconciliationControllerV1:
    """Typed adapter to the accepted Phase-8 deterministic reconciler."""

    controller_key = "capability_registry.reconcile"
    controller_version = 1
    replay_safe = True
    contract_digest = canonical_digest(
        {
            "controller_key": controller_key,
            "controller_version": controller_version,
            "implementation": "CapabilityLifecycleReconciler.reconcile",
            "trigger": ReconciliationTrigger.LIFECYCLE.value,
        }
    )

    def __init__(self, reconciler: CapabilityLifecycleReconciler) -> None:
        if not isinstance(reconciler, CapabilityLifecycleReconciler):
            raise TypeError("reconciler must be CapabilityLifecycleReconciler")
        self.reconciler = reconciler

    def invoke(
        self,
        candidate: ActionCandidateV1,
        *,
        source_identity: str,
    ) -> ControllerDispatchReceiptV1:
        del source_identity
        if candidate.target_namespace != "capability":
            raise ValueError(
                "capability reconciler requires a capability target namespace"
            )
        snapshot = self.reconciler.reconcile(ReconciliationTrigger.LIFECYCLE)
        state = snapshot.state(candidate.target_identity)
        if state is None:
            raise ValueError("capability reconciler did not produce target state")
        return ControllerDispatchReceiptV1(
            downstream_id=state.capability_id,
            downstream_version=snapshot.digest,
        )


def capability_reconciliation_registration(
    controller: CapabilityReconciliationControllerV1,
) -> DispatchBridgeRegistrationV1:
    if not isinstance(controller, CapabilityReconciliationControllerV1):
        raise TypeError("controller must be CapabilityReconciliationControllerV1")
    return DispatchBridgeRegistrationV1(
        resolver_key="capability_effective_state",
        resolver_version=1,
        action_kind=ActionKind.EXISTING_CONTROLLER,
        controller_key=controller.controller_key,
        controller_version=controller.controller_version,
        controller_contract_digest=controller.contract_digest,
    )


class WorkOrchestratorDispatchBridge:
    """Replay-safe direct bounded-work bridge over the canonical WorkOrchestrator."""

    def __init__(
        self,
        *,
        orchestrator: WorkOrchestrator,
        store: SQLiteWorkStore,
        supported_work_types: frozenset[WorkType],
        standalone_diagnostics_admission=None,
    ) -> None:
        if not isinstance(orchestrator, WorkOrchestrator):
            raise TypeError("orchestrator must be a WorkOrchestrator")
        if not isinstance(store, SQLiteWorkStore):
            raise TypeError("store must be a SQLiteWorkStore")
        if any(not isinstance(item, WorkType) for item in supported_work_types):
            raise TypeError("supported_work_types must contain WorkType values")
        self.orchestrator = orchestrator
        self.store = store
        self.supported_work_types = frozenset(supported_work_types)
        self.standalone_diagnostics_admission = standalone_diagnostics_admission

    def dispatch(
        self,
        candidate: ActionCandidateV1,
        registration: DispatchBridgeRegistrationV1,
        *,
        priority: WorkPriority,
    ) -> WorkSubmission:
        work_type = registration.work_type
        if work_type is None:
            raise ValueError("work dispatch registration has no work_type")
        if work_type not in self.supported_work_types:
            raise ValueError("registered autonomous work type is not runtime-supported")
        if work_type is WorkType.DIAGNOSTICS:
            admitted = (
                False
                if self.standalone_diagnostics_admission is None
                else bool(self.standalone_diagnostics_admission(candidate))
            )
            if not admitted:
                raise ValueError(
                    "standalone diagnostics lacks canonical diagnostic context"
                )
        session_id, turn_id, _ = _candidate_source_identity(candidate)
        request = _candidate_request(candidate)
        existing = self.store.find_by_source_turn(
            source_session_id=session_id,
            source_turn_id=turn_id,
            work_type=work_type,
        )
        if existing is not None and (
            existing.request != request
            or existing.priority is not priority
            or existing.delivery_policy is not DeliveryPolicy.SILENT
            or existing.dependencies != candidate.dependencies
        ):
            raise ValueError(
                "candidate source identity already owns different WorkItem semantics"
            )
        submission = self.orchestrator.start(
            request=request,
            work_type=work_type,
            source_session_id=session_id,
            source_turn_id=turn_id,
            priority=priority,
            delivery_policy=DeliveryPolicy.SILENT,
            dependencies=candidate.dependencies,
        )
        if submission.work.work_type is not work_type:
            raise RuntimeError("WorkOrchestrator returned mismatched work type")
        return submission


class ChangeCoordinatorDispatchBridge:
    """Replay-safe governed EngineeringChange bridge preserving all owner gates."""

    def __init__(self, coordinator: ChangeCoordinator) -> None:
        if not isinstance(coordinator, ChangeCoordinator):
            raise TypeError("coordinator must be a ChangeCoordinator")
        self.coordinator = coordinator

    def dispatch(
        self,
        candidate: ActionCandidateV1,
        registration: DispatchBridgeRegistrationV1,
    ) -> EngineeringChange:
        if registration.process_key is None or registration.process_version is None:
            raise ValueError("engineering-change registration is incomplete")
        session_id, turn_id, _ = _candidate_source_identity(candidate)
        request = _candidate_request(candidate)
        existing = self.coordinator.store.find_by_source(
            session_id,
            turn_id,
            registration.process_key,
        )
        if existing is not None and (
            existing.request != request
            or existing.process_version != registration.process_version
        ):
            raise ValueError(
                "candidate source identity already owns different change semantics"
            )
        return self.coordinator.start(
            request,
            session_id,
            turn_id,
            process_key=registration.process_key,
            process_version=registration.process_version,
        )


@dataclass(frozen=True, slots=True)
class AutonomyDispatchResultV1:
    candidate_id: str
    mode: AutonomyMode
    disposition: CandidateDisposition
    reason_codes: tuple[str, ...]
    link: AutonomyDispatchLinkV1 | None = None
    replayed: bool = False
    attention_delivery: AttentionDeliveryAttemptV1 | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "candidate_id",
            _text(self.candidate_id, "candidate_id", max_length=240),
        )
        if not isinstance(self.mode, AutonomyMode):
            raise TypeError("mode must be AutonomyMode")
        if not isinstance(self.disposition, CandidateDisposition):
            raise TypeError("disposition must be CandidateDisposition")
        reasons = tuple(
            sorted(
                {
                    _token(value, "reason_code", max_length=240)
                    for value in self.reason_codes
                }
            )
        )
        if not reasons:
            raise ValueError("reason_codes must not be empty")
        object.__setattr__(self, "reason_codes", reasons)
        if self.link is not None and not isinstance(
            self.link,
            AutonomyDispatchLinkV1,
        ):
            raise TypeError("link must be AutonomyDispatchLinkV1")
        if not isinstance(self.replayed, bool):
            raise TypeError("replayed must be boolean")


class AutonomyDispatchService:
    """Current-mode policy and exact bridges. It is not a workflow engine."""

    def __init__(
        self,
        *,
        store: AutonomyStore,
        registrations: DispatchBridgeRegistry,
        config: AutonomyDispatchConfigV1 | None = None,
        budget_evaluator: AutonomyBudgetEvaluator | None = None,
        work_bridge: WorkOrchestratorDispatchBridge | None = None,
        change_bridge: ChangeCoordinatorDispatchBridge | None = None,
        controllers: ExistingControllerRegistry | None = None,
        attention_manager: OwnerAttentionManager | None = None,
        attention_delivery: OwnerAttentionDeliveryAdapter | None = None,
    ) -> None:
        if not isinstance(store, AutonomyStore):
            raise TypeError("store must be an AutonomyStore")
        if not isinstance(registrations, DispatchBridgeRegistry):
            raise TypeError("registrations must be a DispatchBridgeRegistry")
        self.store = store
        self.registrations = registrations
        self.config = config or AutonomyDispatchConfigV1()
        if not isinstance(self.config, AutonomyDispatchConfigV1):
            raise TypeError("config must be AutonomyDispatchConfigV1")
        self.budget_evaluator = budget_evaluator or AutonomyBudgetEvaluator()
        self.work_bridge = work_bridge
        self.change_bridge = change_bridge
        self.controllers = controllers or ExistingControllerRegistry()
        self.attention_manager = attention_manager
        self.attention_delivery = attention_delivery

    def dispatch(
        self,
        candidate_id: str,
        *,
        budget_policy: AutonomyBudgetPolicyV1 | None,
        budget_usage: BudgetUsageV1,
        priority: PrioritizedCandidateV1 | None,
        now_epoch: float,
        renotify_interval_seconds: float = 3600.0,
    ) -> AutonomyDispatchResultV1:
        mode = self.config.mode
        if not isinstance(budget_usage, BudgetUsageV1):
            raise TypeError("budget_usage must be BudgetUsageV1")
        now = _epoch(now_epoch, "now_epoch")
        candidate = self.store.require_action_candidate(candidate_id)
        finding = self.store.require_finding(candidate.finding_id)
        desired = self.store.require_desired_state(candidate.desired_state_id)
        objective = self.store.require_objective(desired.objective_id)

        identity_problem = self._identity_problem(
            candidate,
            finding=finding,
            desired_generation=desired.generation,
            desired_status=desired.status,
            objective=objective,
            priority=priority,
        )
        if identity_problem is not None:
            return AutonomyDispatchResultV1(
                candidate_id=candidate.candidate_id,
                mode=mode,
                disposition=CandidateDisposition.OBSOLETE,
                reason_codes=(identity_problem,),
            )

        registration = self.registrations.get(candidate)

        if mode is AutonomyMode.ASSISTED and registration is not None:
            existing = self.store.get_dispatch_link(candidate.candidate_id)
            if existing is not None:
                if existing.bridge_contract_digest != registration.digest:
                    return AutonomyDispatchResultV1(
                        candidate_id=candidate.candidate_id,
                        mode=mode,
                        disposition=CandidateDisposition.BLOCKED_POLICY,
                        reason_codes=(
                            "dispatch_bridge_semantics_changed_without_version",
                        ),
                        link=existing,
                    )
                return AutonomyDispatchResultV1(
                    candidate_id=candidate.candidate_id,
                    mode=mode,
                    disposition=CandidateDisposition.ADMITTED,
                    reason_codes=("downstream_dispatch_replay_reused",),
                    link=existing,
                    replayed=True,
                )

        assessment = self.budget_evaluator.evaluate(
            candidate,
            mode=mode,
            policy=budget_policy,
            usage=budget_usage,
        )
        if assessment.disposition is not CandidateDisposition.ADMITTED:
            return AutonomyDispatchResultV1(
                candidate_id=candidate.candidate_id,
                mode=mode,
                disposition=assessment.disposition,
                reason_codes=assessment.reason_codes,
            )

        if registration is None:
            return AutonomyDispatchResultV1(
                candidate_id=candidate.candidate_id,
                mode=mode,
                disposition=CandidateDisposition.BLOCKED_POLICY,
                reason_codes=("dispatch_bridge_not_registered",),
            )

        if mode is not AutonomyMode.ASSISTED:
            return AutonomyDispatchResultV1(
                candidate_id=candidate.candidate_id,
                mode=mode,
                disposition=CandidateDisposition.BLOCKED_POLICY,
                reason_codes=("only_assisted_dispatch_is_implemented",),
            )

        if candidate.action_kind is ActionKind.WORK_ITEM:
            if priority is None:
                return self._blocked(candidate, mode, "portfolio_priority_required")
            return self._dispatch_work(
                candidate,
                registration,
                priority=priority.work_priority,
                now_epoch=now,
            )
        if candidate.action_kind is ActionKind.ENGINEERING_CHANGE:
            if priority is None:
                return self._blocked(candidate, mode, "portfolio_priority_required")
            return self._dispatch_change(candidate, registration, now_epoch=now)
        if candidate.action_kind is ActionKind.EXISTING_CONTROLLER:
            return self._dispatch_controller(candidate, registration, now_epoch=now)
        if candidate.action_kind is ActionKind.OWNER_ATTENTION:
            return self._dispatch_attention(
                candidate,
                registration,
                objective=objective,
                now_epoch=now,
                renotify_interval_seconds=renotify_interval_seconds,
            )
        return self._blocked(candidate, mode, "action_kind_not_dispatchable")

    @staticmethod
    def _identity_problem(
        candidate: ActionCandidateV1,
        *,
        finding,
        desired_generation: int,
        desired_status: DesiredStateStatus,
        objective: ObjectiveV1,
        priority: PrioritizedCandidateV1 | None,
    ) -> str | None:
        if objective.status is not ObjectiveStatus.ACTIVE:
            return "objective_not_active"
        if desired_status is not DesiredStateStatus.ACTIVE:
            return "desired_state_not_active"
        if finding.status is not FindingStatus.ACTIVE:
            return "finding_not_active"
        if (
            finding.finding_id != candidate.finding_id
            or finding.desired_state_id != candidate.desired_state_id
            or finding.desired_generation != candidate.desired_generation
            or desired_generation != candidate.desired_generation
        ):
            return "candidate_generation_or_finding_obsolete"
        if priority is not None and (
            priority.candidate_id != candidate.candidate_id
            or priority.objective_id != objective.objective_id
            or priority.work_priority is not objective.priority
        ):
            return "portfolio_priority_identity_mismatch"
        return None

    @staticmethod
    def _blocked(
        candidate: ActionCandidateV1,
        mode: AutonomyMode,
        reason: str,
    ) -> AutonomyDispatchResultV1:
        return AutonomyDispatchResultV1(
            candidate_id=candidate.candidate_id,
            mode=mode,
            disposition=CandidateDisposition.BLOCKED_POLICY,
            reason_codes=(reason,),
        )

    def _dispatch_work(
        self,
        candidate: ActionCandidateV1,
        registration: DispatchBridgeRegistrationV1,
        *,
        priority: WorkPriority,
        now_epoch: float,
    ) -> AutonomyDispatchResultV1:
        if self.work_bridge is None:
            return self._blocked(
                candidate, AutonomyMode.ASSISTED, "work_bridge_unavailable"
            )
        try:
            submission = self.work_bridge.dispatch(
                candidate,
                registration,
                priority=priority,
            )
        except (RuntimeError, TypeError, ValueError):
            return self._blocked(
                candidate, AutonomyMode.ASSISTED, "work_bridge_rejected"
            )
        _, _, source_identity = _candidate_source_identity(candidate)
        return self._record_link(
            candidate,
            registration,
            downstream_kind="work_item",
            downstream_id=submission.work.work_id,
            downstream_version=str(submission.work.version),
            source_identity=source_identity,
            now_epoch=now_epoch,
            reason_codes=("assisted_work_dispatched",),
        )

    def _dispatch_change(
        self,
        candidate: ActionCandidateV1,
        registration: DispatchBridgeRegistrationV1,
        *,
        now_epoch: float,
    ) -> AutonomyDispatchResultV1:
        if self.change_bridge is None:
            return self._blocked(
                candidate,
                AutonomyMode.ASSISTED,
                "change_bridge_unavailable",
            )
        try:
            change = self.change_bridge.dispatch(candidate, registration)
        except (RuntimeError, TypeError, ValueError):
            return self._blocked(
                candidate,
                AutonomyMode.ASSISTED,
                "change_bridge_rejected",
            )
        _, _, source_identity = _candidate_source_identity(candidate)
        return self._record_link(
            candidate,
            registration,
            downstream_kind="engineering_change",
            downstream_id=change.change_id,
            downstream_version=str(change.version),
            source_identity=source_identity,
            now_epoch=now_epoch,
            reason_codes=("assisted_governed_change_opened",),
        )

    def _dispatch_controller(
        self,
        candidate: ActionCandidateV1,
        registration: DispatchBridgeRegistrationV1,
        *,
        now_epoch: float,
    ) -> AutonomyDispatchResultV1:
        if (
            registration.controller_key is None
            or registration.controller_version is None
            or registration.controller_contract_digest is None
        ):
            return self._blocked(
                candidate,
                AutonomyMode.ASSISTED,
                "controller_registration_incomplete",
            )
        controller = self.controllers.get(
            registration.controller_key,
            registration.controller_version,
        )
        if controller is None:
            return self._blocked(
                candidate,
                AutonomyMode.ASSISTED,
                "registered_controller_unavailable",
            )
        if controller.contract_digest != registration.controller_contract_digest:
            return self._blocked(
                candidate,
                AutonomyMode.ASSISTED,
                "registered_controller_contract_mismatch",
            )
        _, _, source_identity = _candidate_source_identity(candidate)
        try:
            receipt = controller.invoke(
                candidate,
                source_identity=source_identity,
            )
        except Exception:  # noqa: BLE001 - controller failure is a blocked dispatch
            return self._blocked(
                candidate,
                AutonomyMode.ASSISTED,
                "registered_controller_failed",
            )
        return self._record_link(
            candidate,
            registration,
            downstream_kind="existing_controller",
            downstream_id=receipt.downstream_id,
            downstream_version=receipt.downstream_version,
            source_identity=source_identity,
            now_epoch=now_epoch,
            reason_codes=("assisted_registered_controller_invoked",),
        )

    def _dispatch_attention(
        self,
        candidate: ActionCandidateV1,
        registration: DispatchBridgeRegistrationV1,
        *,
        objective: ObjectiveV1,
        now_epoch: float,
        renotify_interval_seconds: float,
    ) -> AutonomyDispatchResultV1:
        if self.attention_manager is None or self.attention_delivery is None:
            return self._blocked(
                candidate,
                AutonomyMode.ASSISTED,
                "owner_attention_bridge_unavailable",
            )
        assert registration.attention_group_key is not None
        assert registration.attention_question is not None
        assert registration.attention_option_metadata_json is not None
        assert registration.attention_consequence_of_waiting is not None
        admission = self.attention_manager.open_or_update(
            objective_id=objective.objective_id,
            finding_id=candidate.finding_id,
            candidate_id=candidate.candidate_id,
            group_key=registration.attention_group_key,
            priority=objective.priority,
            reason_codes=registration.attention_reason_codes,
            question=registration.attention_question,
            option_metadata_json=registration.attention_option_metadata_json,
            consequence_of_waiting=registration.attention_consequence_of_waiting,
            now_epoch=now_epoch,
        )
        attempt = self.attention_delivery.attempt(
            admission.item,
            now_epoch=now_epoch,
            renotify_interval_seconds=renotify_interval_seconds,
        )
        _, _, source_identity = _candidate_source_identity(candidate)
        result = self._record_link(
            candidate,
            registration,
            downstream_kind="owner_attention",
            downstream_id=attempt.attention.attention_id,
            downstream_version=str(attempt.attention.version),
            source_identity=source_identity,
            now_epoch=now_epoch,
            reason_codes=("assisted_owner_attention_persisted",),
        )
        return AutonomyDispatchResultV1(
            candidate_id=result.candidate_id,
            mode=result.mode,
            disposition=result.disposition,
            reason_codes=result.reason_codes,
            link=result.link,
            replayed=result.replayed,
            attention_delivery=attempt,
        )

    def _record_link(
        self,
        candidate: ActionCandidateV1,
        registration: DispatchBridgeRegistrationV1,
        *,
        downstream_kind: str,
        downstream_id: str,
        downstream_version: str | None,
        source_identity: str,
        now_epoch: float,
        reason_codes: tuple[str, ...],
    ) -> AutonomyDispatchResultV1:
        link = AutonomyDispatchLinkV1(
            dispatch_link_id=deterministic_id(
                "dispatch_link",
                {
                    "candidate_id": candidate.candidate_id,
                    "dispatch_role": "dispatch",
                },
            ),
            candidate_id=candidate.candidate_id,
            dispatch_role="dispatch",
            downstream_kind=downstream_kind,
            downstream_id=downstream_id,
            downstream_version=downstream_version,
            source_identity=source_identity,
            mode=AutonomyMode.ASSISTED,
            disposition=CandidateDisposition.ADMITTED,
            bridge_contract_digest=registration.digest,
            reason_codes=reason_codes,
            created_at_epoch=now_epoch,
        )
        persisted = self.store.record_dispatch_link(link)
        return AutonomyDispatchResultV1(
            candidate_id=candidate.candidate_id,
            mode=AutonomyMode.ASSISTED,
            disposition=CandidateDisposition.ADMITTED,
            reason_codes=reason_codes,
            link=persisted,
        )
