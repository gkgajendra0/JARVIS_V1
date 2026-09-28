"""Deterministic least-powerful action resolution for Phase 10A."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from jarvis.autonomy.models import (
    ActionCandidateV1,
    ActionKind,
    AutonomyFindingV1,
    AutonomyMode,
    CandidateDisposition,
    DesiredStateV1,
    FindingStatus,
    candidate_id_for,
)
from jarvis.autonomy.store import AutonomyStore
from jarvis.engineering_knowledge.canonical import JSONValue

_ACTION_POWER = {
    ActionKind.NO_ACTION: 0,
    ActionKind.EXISTING_CONTROLLER: 1,
    ActionKind.WORK_ITEM: 2,
    ActionKind.ENGINEERING_CHANGE: 3,
    ActionKind.OWNER_ATTENTION: 4,
}


@dataclass(frozen=True, slots=True)
class ActionResponseSpecV1:
    action_kind: ActionKind
    expected_effect: str
    reversibility_class: str
    resource_class: str
    cost_class: str
    risk_json: dict[str, JSONValue]
    dependencies: tuple[str, ...] = ()
    policy_reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.action_kind, ActionKind):
            raise TypeError("action_kind must be an ActionKind")
        for field_name in (
            "expected_effect",
            "reversibility_class",
            "resource_class",
            "cost_class",
        ):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"{field_name} must not be empty")
            object.__setattr__(self, field_name, value)
        if not isinstance(self.risk_json, dict):
            raise TypeError("risk_json must be a JSON object")
        object.__setattr__(
            self,
            "dependencies",
            tuple(dict.fromkeys(str(item).strip() for item in self.dependencies)),
        )
        object.__setattr__(
            self,
            "policy_reason_codes",
            tuple(
                dict.fromkeys(
                    str(item).strip().casefold()
                    for item in self.policy_reason_codes
                )
            ),
        )
        if any(not item for item in self.dependencies):
            raise ValueError("dependencies must not contain empty values")
        if any(not item for item in self.policy_reason_codes):
            raise ValueError("policy_reason_codes must not contain empty values")


@dataclass(frozen=True, slots=True)
class ActionResolutionResultV1:
    candidate: ActionCandidateV1 | None
    disposition: CandidateDisposition
    reason_codes: tuple[str, ...]
    resolver_key: str | None = None
    resolver_version: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, CandidateDisposition):
            raise TypeError("disposition must be a CandidateDisposition")
        normalized = tuple(
            sorted(
                {
                    str(item).strip().casefold()
                    for item in self.reason_codes
                    if str(item).strip()
                }
            )
        )
        if not normalized:
            raise ValueError("reason_codes must not be empty")
        object.__setattr__(self, "reason_codes", normalized)


class ActionResolver(Protocol):
    resolver_key: str
    resolver_version: int
    supported_rules: tuple[tuple[str, int], ...]
    supported_finding_kinds: tuple[str, ...]

    def resolve(
        self,
        desired: DesiredStateV1,
        finding: AutonomyFindingV1,
    ) -> ActionResponseSpecV1: ...


class DuplicateActionResolverError(RuntimeError):
    pass


class UnknownActionResolverError(RuntimeError):
    pass


class ActionResolverRegistry:
    """Exact resolver registry; unsupported mappings never fall back implicitly."""

    def __init__(self, resolvers: tuple[ActionResolver, ...] = ()) -> None:
        self._resolvers: dict[tuple[str, int], ActionResolver] = {}
        for resolver in resolvers:
            self.register(resolver)

    def register(self, resolver: ActionResolver) -> None:
        key = str(getattr(resolver, "resolver_key", "")).strip().casefold()
        version = getattr(resolver, "resolver_version", None)
        if (
            not key
            or isinstance(version, bool)
            or not isinstance(version, int)
            or version <= 0
        ):
            raise ValueError("resolver requires normalized key and positive version")
        identity = (key, version)
        if identity in self._resolvers:
            raise DuplicateActionResolverError(
                f"Action resolver already registered: {key}.v{version}"
            )
        self._resolvers[identity] = resolver

    def require(self, resolver_key: str, resolver_version: int) -> ActionResolver:
        key = str(resolver_key).strip().casefold()
        identity = (key, int(resolver_version))
        try:
            return self._resolvers[identity]
        except KeyError as exc:
            raise UnknownActionResolverError(
                f"unknown Action resolver: {key}.v{resolver_version}"
            ) from exc

    def all(self) -> tuple[ActionResolver, ...]:
        return tuple(self._resolvers[key] for key in sorted(self._resolvers))


class LeastPowerfulActionResolverV1:
    """Choose the least-powerful explicitly registered reliable response."""

    resolver_version = 1

    def __init__(
        self,
        *,
        resolver_key: str,
        supported_rules: tuple[tuple[str, int], ...],
        supported_finding_kinds: tuple[str, ...] = ("state_gap",),
        responses: tuple[ActionResponseSpecV1, ...],
    ) -> None:
        key = str(resolver_key).strip().casefold()
        if not key:
            raise ValueError("resolver_key must not be empty")
        if not supported_rules:
            raise ValueError("supported_rules must not be empty")
        if not supported_finding_kinds:
            raise ValueError("supported_finding_kinds must not be empty")
        if not responses:
            raise ValueError("responses must not be empty")
        self.resolver_key = key
        self.supported_rules = tuple(
            (str(rule_key).strip().casefold(), int(rule_version))
            for rule_key, rule_version in supported_rules
        )
        self.supported_finding_kinds = tuple(
            str(item).strip().casefold() for item in supported_finding_kinds
        )
        if any(not rule_key or version <= 0 for rule_key, version in self.supported_rules):
            raise ValueError("supported_rules contain invalid values")
        if any(not item for item in self.supported_finding_kinds):
            raise ValueError("supported_finding_kinds contain invalid values")
        self.responses = tuple(
            sorted(
                responses,
                key=lambda item: (
                    _ACTION_POWER[item.action_kind],
                    item.expected_effect,
                ),
            )
        )

    def resolve(
        self,
        desired: DesiredStateV1,
        finding: AutonomyFindingV1,
    ) -> ActionResponseSpecV1:
        if (desired.rule_key, desired.rule_version) not in self.supported_rules:
            raise ValueError("resolver does not support DesiredState rule/version")
        if finding.finding_kind not in self.supported_finding_kinds:
            raise ValueError("resolver does not support finding kind")
        return self.responses[0]


def build_default_action_resolver_registry() -> ActionResolverRegistry:
    return ActionResolverRegistry(
        (
            LeastPowerfulActionResolverV1(
                resolver_key="component_health",
                supported_rules=(("component_health", 1),),
                responses=(
                    ActionResponseSpecV1(
                        action_kind=ActionKind.WORK_ITEM,
                        expected_effect=(
                            "Collect bounded diagnostics for the unhealthy component."
                        ),
                        reversibility_class="fully_reversible",
                        resource_class="background",
                        cost_class="bounded",
                        risk_json={"risk": "low", "work_class": "diagnostics"},
                        policy_reason_codes=("bounded_diagnostics",),
                    ),
                    ActionResponseSpecV1(
                        action_kind=ActionKind.OWNER_ATTENTION,
                        expected_effect=(
                            "Request owner input if bounded diagnostics cannot proceed."
                        ),
                        reversibility_class="not_applicable",
                        resource_class="owner_attention",
                        cost_class="bounded",
                        risk_json={"risk": "low"},
                        policy_reason_codes=("owner_input_fallback",),
                    ),
                ),
            ),
            LeastPowerfulActionResolverV1(
                resolver_key="capability_effective_state",
                supported_rules=(("capability_effective_state", 1),),
                responses=(
                    ActionResponseSpecV1(
                        action_kind=ActionKind.EXISTING_CONTROLLER,
                        expected_effect=(
                            "Request the accepted deterministic capability controller "
                            "to reconcile effective state."
                        ),
                        reversibility_class="controller_defined",
                        resource_class="existing_controller",
                        cost_class="bounded",
                        risk_json={"risk": "bounded_by_existing_controller"},
                        policy_reason_codes=("existing_controller_preferred",),
                    ),
                    ActionResponseSpecV1(
                        action_kind=ActionKind.ENGINEERING_CHANGE,
                        expected_effect=(
                            "Open governed engineering only if the accepted controller "
                            "cannot reconcile the capability."
                        ),
                        reversibility_class="governed",
                        resource_class="engineering",
                        cost_class="bounded_by_governance",
                        risk_json={"risk": "governed"},
                        policy_reason_codes=("engineering_fallback",),
                    ),
                ),
            ),
            LeastPowerfulActionResolverV1(
                resolver_key="durable_work",
                supported_rules=(("durable_work", 1),),
                responses=(
                    ActionResponseSpecV1(
                        action_kind=ActionKind.NO_ACTION,
                        expected_effect=(
                            "Preserve the existing WorkItem as canonical execution "
                            "state without creating duplicate work."
                        ),
                        reversibility_class="not_applicable",
                        resource_class="none",
                        cost_class="none",
                        risk_json={"risk": "none"},
                        policy_reason_codes=("existing_work_remains_canonical",),
                    ),
                ),
            ),
        )
    )


class ActionResolutionService:
    """Persist immutable shadow candidates without dispatching downstream actions."""

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

    def resolve_and_record(
        self,
        desired: DesiredStateV1,
        finding: AutonomyFindingV1,
        *,
        resolver_key: str,
        resolver_version: int,
        mode: AutonomyMode = AutonomyMode.SHADOW,
    ) -> ActionResolutionResultV1:
        if finding.desired_state_id != desired.desired_state_id:
            return ActionResolutionResultV1(
                candidate=None,
                disposition=CandidateDisposition.BLOCKED_POLICY,
                reason_codes=("finding_desired_state_mismatch",),
            )
        if finding.desired_generation != desired.generation:
            return ActionResolutionResultV1(
                candidate=None,
                disposition=CandidateDisposition.OBSOLETE,
                reason_codes=("finding_generation_obsolete",),
            )
        if finding.status in {FindingStatus.RESOLVED, FindingStatus.SUPERSEDED}:
            return ActionResolutionResultV1(
                candidate=None,
                disposition=CandidateDisposition.OBSOLETE,
                reason_codes=("finding_not_actionable",),
            )
        if finding.status in {FindingStatus.STABILIZING, FindingStatus.SUPPRESSED}:
            return ActionResolutionResultV1(
                candidate=None,
                disposition=CandidateDisposition.INHIBITED,
                reason_codes=("finding_not_stably_actionable",),
            )
        if finding.status is not FindingStatus.ACTIVE:
            return ActionResolutionResultV1(
                candidate=None,
                disposition=CandidateDisposition.BLOCKED_POLICY,
                reason_codes=("unsupported_finding_status",),
            )
        if mode not in {AutonomyMode.OBSERVE, AutonomyMode.SHADOW}:
            return ActionResolutionResultV1(
                candidate=None,
                disposition=CandidateDisposition.BLOCKED_POLICY,
                reason_codes=("live_dispatch_not_implemented_in_phase10a4",),
            )
        try:
            resolver = self.registry.require(resolver_key, resolver_version)
            response = resolver.resolve(desired, finding)
        except (UnknownActionResolverError, TypeError, ValueError):
            return ActionResolutionResultV1(
                candidate=None,
                disposition=CandidateDisposition.BLOCKED_POLICY,
                reason_codes=("unsupported_action_mapping",),
                resolver_key=str(resolver_key).strip().casefold() or None,
                resolver_version=resolver_version,
            )

        candidate_id = candidate_id_for(
            finding,
            action_kind=response.action_kind,
            resolver_key=resolver.resolver_key,
            resolver_version=resolver.resolver_version,
        )
        candidate = ActionCandidateV1(
            candidate_id=candidate_id,
            finding_id=finding.finding_id,
            desired_state_id=desired.desired_state_id,
            desired_generation=desired.generation,
            action_kind=response.action_kind,
            resolver_key=resolver.resolver_key,
            resolver_version=resolver.resolver_version,
            expected_effect=response.expected_effect,
            target_namespace=finding.target_namespace,
            target_identity=finding.target_identity,
            snapshot_digest=finding.latest_snapshot_digest,
            reversibility_class=response.reversibility_class,
            resource_class=response.resource_class,
            cost_class=response.cost_class,
            risk_json=response.risk_json,
            dependencies=response.dependencies,
            mode=AutonomyMode.SHADOW,
            policy_reason_codes=tuple(
                dict.fromkeys(
                    (*response.policy_reason_codes, "phase10a4_shadow_only")
                )
            ),
            created_at_epoch=finding.last_seen_epoch,
        )
        persisted = self.store.create_action_candidate(candidate)
        return ActionResolutionResultV1(
            candidate=persisted,
            disposition=CandidateDisposition.SHADOW_ONLY,
            reason_codes=("candidate_recorded_shadow_only",),
            resolver_key=resolver.resolver_key,
            resolver_version=resolver.resolver_version,
        )
