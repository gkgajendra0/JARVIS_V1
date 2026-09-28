"""Deterministic action resolution and pre-dispatch intent evidence for Phase 10A.4."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from jarvis.engineering_knowledge.canonical import JSONValue

from .models import (
    ActionCandidateV1,
    ActionKind,
    AutonomyFindingV1,
    AutonomyMode,
    CandidateDisposition,
    CandidateDispositionRecordV1,
    DesiredStateV1,
    DispatchIntentV1,
    FindingStatus,
    candidate_decision_id_for,
    candidate_id_for,
    dispatch_intent_id_for,
)
from .store import AutonomyStore


@dataclass(frozen=True, slots=True)
class ActionResolutionSpecV1:
    action_kind: ActionKind
    expected_effect: str
    reversibility_class: str
    resource_class: str
    cost_class: str
    risk_json: dict[str, JSONValue]
    dependencies: tuple[str, ...] = ()
    policy_reason_codes: tuple[str, ...] = ()
    dispatch_role: str = "primary"

    def __post_init__(self) -> None:
        if not isinstance(self.action_kind, ActionKind):
            raise TypeError("action_kind must be an ActionKind")
        if not str(self.expected_effect).strip():
            raise ValueError("expected_effect must not be empty")
        for field_name in (
            "reversibility_class",
            "resource_class",
            "cost_class",
            "dispatch_role",
        ):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} must not be empty")
        if not isinstance(self.risk_json, dict):
            raise TypeError("risk_json must be a dictionary")
        if len(set(self.dependencies)) != len(self.dependencies):
            raise ValueError("dependencies must be unique")
        if len(set(self.policy_reason_codes)) != len(self.policy_reason_codes):
            raise ValueError("policy_reason_codes must be unique")


class ActionResolver(Protocol):
    rule_key: str
    rule_version: int
    finding_kind: str
    resolver_key: str
    resolver_version: int

    def resolve(
        self,
        desired: DesiredStateV1,
        finding: AutonomyFindingV1,
    ) -> ActionResolutionSpecV1: ...


class DuplicateActionResolverError(RuntimeError):
    pass


class UnknownActionResolverError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class StaticActionResolverV1:
    rule_key: str
    rule_version: int
    finding_kind: str
    resolver_key: str
    resolver_version: int
    spec: ActionResolutionSpecV1

    def __post_init__(self) -> None:
        for field_name in (
            "rule_key",
            "finding_kind",
            "resolver_key",
        ):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} must not be empty")
        for field_name in ("rule_version", "resolver_version"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{field_name} must be a positive integer")
        if not isinstance(self.spec, ActionResolutionSpecV1):
            raise TypeError("spec must be an ActionResolutionSpecV1")

    def resolve(
        self,
        desired: DesiredStateV1,
        finding: AutonomyFindingV1,
    ) -> ActionResolutionSpecV1:
        if desired.rule_key != self.rule_key or desired.rule_version != self.rule_version:
            raise ValueError("resolver DesiredState contract mismatch")
        if finding.finding_kind != self.finding_kind:
            raise ValueError("resolver finding-kind mismatch")
        return self.spec


class ActionResolverRegistry:
    """Exact rule/version/finding registry; ambiguous mappings are rejected."""

    def __init__(self, resolvers: tuple[ActionResolver, ...] = ()) -> None:
        self._resolvers: dict[tuple[str, int, str], ActionResolver] = {}
        for resolver in resolvers:
            self.register(resolver)

    @staticmethod
    def _identity(resolver: ActionResolver) -> tuple[str, int, str]:
        rule_key = str(getattr(resolver, "rule_key", "")).strip().casefold()
        finding_kind = str(getattr(resolver, "finding_kind", "")).strip().casefold()
        rule_version = getattr(resolver, "rule_version", None)
        resolver_key = str(getattr(resolver, "resolver_key", "")).strip().casefold()
        resolver_version = getattr(resolver, "resolver_version", None)
        if not rule_key or not finding_kind or not resolver_key:
            raise ValueError("resolver keys must not be empty")
        for value, field in (
            (rule_version, "rule_version"),
            (resolver_version, "resolver_version"),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{field} must be a positive integer")
        if not callable(getattr(resolver, "resolve", None)):
            raise TypeError("resolver must provide resolve(desired, finding)")
        return rule_key, rule_version, finding_kind

    def register(self, resolver: ActionResolver) -> None:
        identity = self._identity(resolver)
        if identity in self._resolvers:
            raise DuplicateActionResolverError(
                "ActionResolver already registered for "
                f"{identity[0]}.v{identity[1]}:{identity[2]}"
            )
        self._resolvers[identity] = resolver

    def require(
        self,
        *,
        rule_key: str,
        rule_version: int,
        finding_kind: str,
    ) -> ActionResolver:
        identity = (
            str(rule_key).strip().casefold(),
            int(rule_version),
            str(finding_kind).strip().casefold(),
        )
        try:
            return self._resolvers[identity]
        except KeyError as exc:
            raise UnknownActionResolverError(
                "no ActionResolver registered for "
                f"{identity[0]}.v{identity[1]}:{identity[2]}"
            ) from exc

    def all(self) -> tuple[ActionResolver, ...]:
        return tuple(self._resolvers[key] for key in sorted(self._resolvers))


def _existing_controller_spec(
    *,
    controller_key: str,
    expected_effect: str,
) -> ActionResolutionSpecV1:
    return ActionResolutionSpecV1(
        action_kind=ActionKind.EXISTING_CONTROLLER,
        expected_effect=expected_effect,
        reversibility_class="controller_owned",
        resource_class="existing_controller",
        cost_class="bounded",
        risk_json={
            "controller_key": controller_key,
            "new_agentic_execution": False,
        },
        dependencies=(f"controller:{controller_key}",),
        policy_reason_codes=("prefer_existing_controller",),
        dispatch_role="controller_request",
    )


def build_default_action_resolver_registry() -> ActionResolverRegistry:
    return ActionResolverRegistry(
        (
            StaticActionResolverV1(
                rule_key="component_health",
                rule_version=1,
                finding_kind="state_gap",
                resolver_key="component_health_existing_controller",
                resolver_version=1,
                spec=_existing_controller_spec(
                    controller_key="self_repair",
                    expected_effect=(
                        "Delegate health diagnosis/repair handling to the existing "
                        "governed self-repair controller."
                    ),
                ),
            ),
            StaticActionResolverV1(
                rule_key="capability_effective_state",
                rule_version=1,
                finding_kind="state_gap",
                resolver_key="capability_registry_existing_controller",
                resolver_version=1,
                spec=_existing_controller_spec(
                    controller_key="capability_registry_reconciler",
                    expected_effect=(
                        "Delegate capability convergence to the existing deterministic "
                        "capability-registry reconciler."
                    ),
                ),
            ),
            StaticActionResolverV1(
                rule_key="durable_work",
                rule_version=1,
                finding_kind="state_gap",
                resolver_key="work_orchestrator_existing_controller",
                resolver_version=1,
                spec=_existing_controller_spec(
                    controller_key="work_orchestrator",
                    expected_effect=(
                        "Keep durable work lifecycle handling under the existing "
                        "WorkOrchestrator rather than creating duplicate work."
                    ),
                ),
            ),
        )
    )


@dataclass(frozen=True, slots=True)
class ActionResolutionResultV1:
    candidate: ActionCandidateV1
    decision: CandidateDispositionRecordV1
    dispatch_intent: DispatchIntentV1 | None
    reused_candidate: bool
    resolver_supported: bool


class ActionResolutionService:
    """Create replay-safe proposal evidence without performing downstream dispatch."""

    def __init__(
        self,
        store: AutonomyStore,
        registry: ActionResolverRegistry,
    ) -> None:
        if not isinstance(store, AutonomyStore):
            raise TypeError("store must be an AutonomyStore")
        if not isinstance(registry, ActionResolverRegistry):
            raise TypeError("registry must be an ActionResolverRegistry")
        self.store = store
        self.registry = registry

    @staticmethod
    def _fail_closed_spec(reason_code: str) -> ActionResolutionSpecV1:
        return ActionResolutionSpecV1(
            action_kind=ActionKind.NO_ACTION,
            expected_effect="Do not perform autonomous downstream work.",
            reversibility_class="none",
            resource_class="none",
            cost_class="none",
            risk_json={"state_change": False},
            policy_reason_codes=(reason_code,),
            dispatch_role="none",
        )

    def resolve(
        self,
        desired: DesiredStateV1,
        finding: AutonomyFindingV1,
        *,
        mode: AutonomyMode,
    ) -> ActionResolutionResultV1:
        if not isinstance(desired, DesiredStateV1):
            raise TypeError("desired must be a DesiredStateV1")
        if not isinstance(finding, AutonomyFindingV1):
            raise TypeError("finding must be an AutonomyFindingV1")
        if not isinstance(mode, AutonomyMode):
            raise TypeError("mode must be an AutonomyMode")

        supported = True
        if (
            finding.status is not FindingStatus.ACTIVE
            or finding.desired_state_id != desired.desired_state_id
            or finding.desired_generation != desired.generation
            or finding.rule_key != desired.rule_key
            or finding.rule_version != desired.rule_version
        ):
            resolver = None
            spec = self._fail_closed_spec("finding_not_actionable")
            resolver_key = "fail_closed_no_action"
            resolver_version = 1
            supported = False
        else:
            try:
                resolver = self.registry.require(
                    rule_key=finding.rule_key,
                    rule_version=finding.rule_version,
                    finding_kind=finding.finding_kind,
                )
                spec = resolver.resolve(desired, finding)
                resolver_key = resolver.resolver_key
                resolver_version = resolver.resolver_version
            except UnknownActionResolverError:
                resolver = None
                spec = self._fail_closed_spec("unsupported_action_mapping")
                resolver_key = "fail_closed_no_action"
                resolver_version = 1
                supported = False

        candidate_id = candidate_id_for(
            finding,
            action_kind=spec.action_kind,
            resolver_key=resolver_key,
            resolver_version=resolver_version,
        )
        reused = False
        try:
            candidate = self.store.require_action_candidate(candidate_id)
            reused = True
        except KeyError:
            candidate = ActionCandidateV1(
                candidate_id=candidate_id,
                finding_id=finding.finding_id,
                desired_state_id=finding.desired_state_id,
                desired_generation=finding.desired_generation,
                action_kind=spec.action_kind,
                resolver_key=resolver_key,
                resolver_version=resolver_version,
                expected_effect=spec.expected_effect,
                target_namespace=finding.target_namespace,
                target_identity=finding.target_identity,
                snapshot_digest=finding.latest_snapshot_digest,
                reversibility_class=spec.reversibility_class,
                resource_class=spec.resource_class,
                cost_class=spec.cost_class,
                risk_json=spec.risk_json,
                dependencies=spec.dependencies,
                mode=mode,
                policy_reason_codes=spec.policy_reason_codes,
                created_at_epoch=finding.last_seen_epoch,
            )
            candidate = self.store.create_action_candidate(candidate)

        if spec.action_kind is ActionKind.NO_ACTION:
            disposition = CandidateDisposition.BLOCKED_POLICY
            decision_reasons = (
                *spec.policy_reason_codes,
                "no_downstream_action",
            )
        elif mode in {
            AutonomyMode.OFF,
            AutonomyMode.OBSERVE,
            AutonomyMode.SHADOW,
        }:
            disposition = CandidateDisposition.SHADOW_ONLY
            decision_reasons = (
                *spec.policy_reason_codes,
                "mode_has_no_live_dispatch",
            )
        else:
            disposition = CandidateDisposition.BLOCKED_POLICY
            decision_reasons = (
                *spec.policy_reason_codes,
                "admission_deferred_until_phase10a5",
            )

        decision = CandidateDispositionRecordV1(
            decision_id=candidate_decision_id_for(
                candidate,
                disposition=disposition,
                source_identity="action_resolution:phase10a4",
                reason_codes=decision_reasons,
            ),
            candidate_id=candidate.candidate_id,
            disposition=disposition,
            reason_codes=decision_reasons,
            source_identity="action_resolution:phase10a4",
            created_at_epoch=candidate.created_at_epoch,
        )
        decision = self.store.record_candidate_decision(decision)

        intent = None
        if spec.action_kind is not ActionKind.NO_ACTION:
            intent = DispatchIntentV1(
                intent_id=dispatch_intent_id_for(
                    candidate,
                    dispatch_role=spec.dispatch_role,
                ),
                candidate_id=candidate.candidate_id,
                action_kind=candidate.action_kind,
                dispatch_role=spec.dispatch_role,
                source_identity=f"autonomy_candidate:{candidate.candidate_id}",
                target_namespace=candidate.target_namespace,
                target_identity=candidate.target_identity,
                intent_json={
                    "resolver_key": candidate.resolver_key,
                    "resolver_version": candidate.resolver_version,
                    "expected_effect": candidate.expected_effect,
                    "proposal_only": True,
                    "live_dispatch_performed": False,
                },
                created_at_epoch=candidate.created_at_epoch,
            )
            intent = self.store.record_dispatch_intent(intent)

        return ActionResolutionResultV1(
            candidate=candidate,
            decision=decision,
            dispatch_intent=intent,
            reused_candidate=reused,
            resolver_supported=supported,
        )
