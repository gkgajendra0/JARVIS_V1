"""Strict PlanGraph proposal and validation for GICC."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field, field_validator

from jarvis.capabilities.models import CapabilityCatalog
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.hands.provider_adapters import StructuredOutputClient

from .models import (
    CapabilityGapV1,
    InformationNeedV1,
    MonitorPredicateV1,
    OwnerGoalV2,
    PlanGraphV1,
    PlanNodeType,
    PlanNodeV1,
)

_MAX_PLAN_NODES = 64
_MAX_PLAN_EDGES = 128
_MAX_PARAMETERS_JSON = 16_000
_EXECUTABLE_KEYS = {
    "code",
    "command",
    "executable",
    "powershell",
    "python",
    "script",
    "shell",
}


class PlanValidationError(RuntimeError):
    pass


class PlanNodeCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_type: PlanNodeType
    summary: str = Field(min_length=1, max_length=320)
    parameters: dict[str, object] = Field(default_factory=dict)
    capability_key: str | None = Field(default=None, max_length=180)
    operation: str | None = Field(default=None, max_length=120)
    information_need_id: str | None = Field(default=None, max_length=180)
    gap_id: str | None = Field(default=None, max_length=180)
    subgoal_id: str | None = Field(default=None, max_length=180)
    monitor_predicate_id: str | None = Field(default=None, max_length=180)
    postcondition_ref: str | None = Field(default=None, max_length=320)
    depends_on_indexes: list[int] = Field(default_factory=list, max_length=32)

    @field_validator(
        "capability_key",
        "operation",
        "information_need_id",
        "gap_id",
        "subgoal_id",
        "monitor_predicate_id",
        "postcondition_ref",
    )
    @classmethod
    def _optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("depends_on_indexes")
    @classmethod
    def _dependencies(cls, value: list[int]) -> list[int]:
        if any(isinstance(item, bool) or item < 0 for item in value):
            raise ValueError("depends_on_indexes must contain non-negative integers")
        return sorted(set(value))


class PlanProposalV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nodes: list[PlanNodeCandidate] = Field(
        min_length=1,
        max_length=_MAX_PLAN_NODES,
    )


@dataclass(frozen=True, slots=True)
class PlanValidationContext:
    catalog: CapabilityCatalog
    allowed_capability_operations: tuple[tuple[str, str], ...] = ()
    gaps: tuple[CapabilityGapV1, ...] = ()
    information_needs: tuple[InformationNeedV1, ...] = ()
    monitor_predicates: tuple[MonitorPredicateV1, ...] = ()
    subgoal_ids: tuple[str, ...] = ()
    allowed_postcondition_refs: tuple[str, ...] = ()


_SYSTEM_PROMPT = """
Build a bounded GICC PlanGraph candidate for an already interpreted owner goal.

Rules:
- use only capability keys and operations supplied in capability_catalog;
- ACTION performs a governed operation and must name a postcondition;
- consequential ACTION must lead to a VERIFY node;
- OBSERVE is read-only observation through an existing capability;
- VERIFY references an observable postcondition; never claim success from model text;
- ACQUIRE_CAPABILITY references only supplied gap IDs;
- CLARIFY references only supplied InformationNeed IDs;
- MONITOR references only supplied monitor predicate IDs;
- SUBGOAL references only supplied child goal IDs;
- WAIT has no executable payload;
- parameters are data for an existing capability, never shell/code/scripts/executables;
- keep the graph small and acyclic;
- do not grant Authority. Existing runtime authorization remains mandatory.
""".strip()


def _validate_parameters(parameters: dict[str, object]) -> None:
    try:
        encoded = json.dumps(
            parameters,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise PlanValidationError("plan parameters must be JSON serializable") from exc
    if len(encoded) > _MAX_PARAMETERS_JSON:
        raise PlanValidationError("plan parameters exceed bounded size")
    stack: list[object] = [parameters]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            for key, child in value.items():
                normalized = str(key).strip().casefold()
                if normalized in _EXECUTABLE_KEYS:
                    raise PlanValidationError(
                        f"plan parameters cannot contain executable field: {normalized}"
                    )
                stack.append(child)
        elif isinstance(value, list):
            stack.extend(value)


class PlanValidator:
    def validate(
        self,
        *,
        goal: OwnerGoalV2,
        proposal: PlanProposalV1,
        context: PlanValidationContext,
        plan_revision: int = 1,
        created_at: str | None = None,
    ) -> PlanGraphV1:
        if not isinstance(goal, OwnerGoalV2):
            raise TypeError("goal must be OwnerGoalV2")
        if not isinstance(proposal, PlanProposalV1):
            raise TypeError("proposal must be PlanProposalV1")
        if not isinstance(context, PlanValidationContext):
            raise TypeError("context must be PlanValidationContext")
        if len(proposal.nodes) > _MAX_PLAN_NODES:
            raise PlanValidationError("plan exceeds node limit")

        allowed_operations = {
            (str(key).strip(), str(operation).strip())
            for key, operation in context.allowed_capability_operations
            if str(key).strip() and str(operation).strip()
        }
        gaps = {item.gap_id for item in context.gaps}
        needs = {item.information_need_id for item in context.information_needs}
        monitors = {item.predicate_id for item in context.monitor_predicates}
        subgoals = set(context.subgoal_ids)
        postconditions = set(context.allowed_postcondition_refs)
        plan_identity = f"{goal.goal_id}:{goal.goal_revision}:{plan_revision}"
        nodes: list[PlanNodeV1] = []

        for index, candidate in enumerate(proposal.nodes):
            _validate_parameters(candidate.parameters)
            if candidate.node_type in {PlanNodeType.ACTION, PlanNodeType.OBSERVE}:
                if candidate.capability_key is None or candidate.operation is None:
                    raise PlanValidationError(
                        "ACTION/OBSERVE requires capability_key and operation"
                    )
                descriptor = context.catalog.by_key(candidate.capability_key)
                if (
                    descriptor is None
                    or not descriptor.execution_enabled
                    or candidate.operation not in descriptor.operations
                ):
                    raise PlanValidationError(
                        "ACTION/OBSERVE references unavailable capability operation"
                    )
                if (
                    candidate.capability_key,
                    candidate.operation,
                ) not in allowed_operations:
                    raise PlanValidationError(
                        "ACTION/OBSERVE is outside satisfied canonical requirements"
                    )
                if (
                    candidate.node_type is PlanNodeType.ACTION
                    and candidate.postcondition_ref is None
                ):
                    raise PlanValidationError("ACTION requires a postcondition_ref")
                if (
                    candidate.postcondition_ref is not None
                    and candidate.postcondition_ref not in postconditions
                ):
                    raise PlanValidationError(
                        "ACTION/OBSERVE references an unregistered postcondition"
                    )
                if candidate.node_type is PlanNodeType.OBSERVE:
                    semantic = descriptor.semantic_metadata()
                    declared = set(semantic.observation_operations)
                    looks_read_only = candidate.operation.casefold().startswith(
                        ("get_", "list_", "read_", "observe_", "current_", "status_")
                    )
                    if declared and candidate.operation.casefold() not in declared:
                        raise PlanValidationError(
                            "OBSERVE operation is not declared as observational"
                        )
                    if not declared and not looks_read_only:
                        raise PlanValidationError(
                            "legacy OBSERVE operation lacks read-only evidence"
                        )
            elif candidate.node_type is PlanNodeType.ACQUIRE_CAPABILITY:
                if candidate.gap_id not in gaps:
                    raise PlanValidationError(
                        "ACQUIRE_CAPABILITY references unknown canonical gap"
                    )
            elif candidate.node_type is PlanNodeType.CLARIFY:
                if candidate.information_need_id not in needs:
                    raise PlanValidationError(
                        "CLARIFY references unknown canonical InformationNeed"
                    )
            elif candidate.node_type is PlanNodeType.MONITOR:
                if candidate.monitor_predicate_id not in monitors:
                    raise PlanValidationError(
                        "MONITOR references unknown canonical predicate"
                    )
            elif candidate.node_type is PlanNodeType.SUBGOAL:
                if candidate.subgoal_id not in subgoals:
                    raise PlanValidationError(
                        "SUBGOAL references unknown canonical child goal"
                    )
            elif candidate.node_type is PlanNodeType.VERIFY:
                if candidate.postcondition_ref is None:
                    raise PlanValidationError("VERIFY requires postcondition_ref")
                if candidate.postcondition_ref not in postconditions:
                    raise PlanValidationError(
                        "VERIFY references an unregistered postcondition"
                    )

            if candidate.node_type not in {
                PlanNodeType.ACTION,
                PlanNodeType.OBSERVE,
            } and (
                candidate.capability_key is not None
                or candidate.operation is not None
                or candidate.parameters
            ):
                raise PlanValidationError(
                    "non ACTION/OBSERVE node cannot carry executable capability data"
                )
            if (
                candidate.node_type is not PlanNodeType.ACQUIRE_CAPABILITY
                and candidate.gap_id is not None
            ):
                raise PlanValidationError("gap_id is only valid for ACQUIRE_CAPABILITY")
            if (
                candidate.node_type is not PlanNodeType.CLARIFY
                and candidate.information_need_id is not None
            ):
                raise PlanValidationError(
                    "information_need_id is only valid for CLARIFY"
                )
            if (
                candidate.node_type is not PlanNodeType.MONITOR
                and candidate.monitor_predicate_id is not None
            ):
                raise PlanValidationError(
                    "monitor_predicate_id is only valid for MONITOR"
                )
            if (
                candidate.node_type is not PlanNodeType.SUBGOAL
                and candidate.subgoal_id is not None
            ):
                raise PlanValidationError("subgoal_id is only valid for SUBGOAL")

            nodes.append(
                PlanNodeV1.create(
                    plan_identity=plan_identity,
                    ordinal=index,
                    node_type=candidate.node_type,
                    summary=candidate.summary,
                    parameters=candidate.parameters,
                    capability_key=candidate.capability_key,
                    operation=candidate.operation,
                    information_need_id=candidate.information_need_id,
                    gap_id=candidate.gap_id,
                    subgoal_id=candidate.subgoal_id,
                    monitor_predicate_id=candidate.monitor_predicate_id,
                    postcondition_ref=candidate.postcondition_ref,
                )
            )

        edges: list[tuple[str, str]] = []
        for index, candidate in enumerate(proposal.nodes):
            for dependency in candidate.depends_on_indexes:
                if dependency >= len(nodes):
                    raise PlanValidationError(
                        "plan dependency references unknown node index"
                    )
                if dependency == index:
                    raise PlanValidationError("plan node cannot depend on itself")
                edges.append((nodes[dependency].node_id, nodes[index].node_id))
        if len(edges) > _MAX_PLAN_EDGES:
            raise PlanValidationError("plan exceeds edge limit")

        incoming = {node.node_id: 0 for node in nodes}
        outgoing: dict[str, set[str]] = {node.node_id: set() for node in nodes}
        for source, target in edges:
            incoming[target] += 1
            outgoing[source].add(target)

        verify_ids = {
            node.node_id for node in nodes if node.node_type is PlanNodeType.VERIFY
        }

        def has_verify_descendant(node_id: str) -> bool:
            pending = list(outgoing[node_id])
            seen: set[str] = set()
            while pending:
                current = pending.pop()
                if current in seen:
                    continue
                seen.add(current)
                if current in verify_ids:
                    return True
                pending.extend(outgoing[current])
            return False

        for node in nodes:
            if node.node_type is PlanNodeType.ACTION and not has_verify_descendant(
                node.node_id
            ):
                raise PlanValidationError(
                    "consequential ACTION must lead to a VERIFY node"
                )

        roots = tuple(
            sorted(node_id for node_id, count in incoming.items() if count == 0)
        )
        completions = tuple(
            sorted(node_id for node_id, children in outgoing.items() if not children)
        )
        return PlanGraphV1.create(
            goal_id=goal.goal_id,
            goal_revision=goal.goal_revision,
            plan_revision=plan_revision,
            nodes=tuple(nodes),
            edges=tuple(edges),
            root_node_ids=roots,
            completion_node_ids=completions,
            created_at=created_at,
        )


class GoalPlanner:
    def __init__(
        self,
        *,
        client: StructuredOutputClient,
        validator: PlanValidator | None = None,
    ) -> None:
        self._client = client
        self._validator = validator or PlanValidator()

    async def plan(
        self,
        *,
        goal: OwnerGoalV2,
        context: PlanValidationContext,
        prior_evidence: tuple[str, ...] | list[str] = (),
        plan_revision: int = 1,
    ) -> PlanGraphV1:
        allowed = {
            (str(key).strip(), str(operation).strip())
            for key, operation in context.allowed_capability_operations
            if str(key).strip() and str(operation).strip()
        }
        catalog_payload = [
            {
                "capability_key": item.key,
                "operations": [
                    operation
                    for operation in item.operations
                    if (item.key, operation) in allowed
                ],
            }
            for item in context.catalog.capabilities
            if item.execution_enabled and any(key == item.key for key, _ in allowed)
        ]
        input_payload = {
            "goal": {
                "goal_id": goal.goal_id,
                "goal_kind": goal.goal_kind.value,
                "desired_outcome": goal.desired_outcome,
                "completion_predicates": list(goal.completion_predicates),
                "referenced_entity_ids": list(goal.referenced_entity_ids),
            },
            "capability_catalog": catalog_payload,
            "gap_ids": [item.gap_id for item in context.gaps],
            "information_need_ids": [
                item.information_need_id for item in context.information_needs
            ],
            "monitor_predicate_ids": [
                item.predicate_id for item in context.monitor_predicates
            ],
            "subgoal_ids": list(context.subgoal_ids),
            "allowed_postcondition_refs": list(context.allowed_postcondition_refs),
            "prior_result_evidence": list(prior_evidence)[-20:],
        }
        telemetry = await self._client.parse_with_telemetry(
            system_prompt=_SYSTEM_PROMPT,
            input_payload=input_payload,
            response_model=PlanProposalV1,
        )
        parsed = telemetry.parsed
        if not isinstance(parsed, PlanProposalV1):
            raise PlanValidationError(
                "planner returned the wrong structured-output contract"
            )
        return self._validator.validate(
            goal=goal,
            proposal=parsed,
            context=context,
            plan_revision=plan_revision,
        )


@dataclass(slots=True)
class PlanProgressGuard:
    """Reject exact no-progress action repeats and bound replanning."""

    max_replans: int = 3
    _seen_fingerprints: set[str] = field(default_factory=set)
    _replan_count: int = 0

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_replans, bool)
            or not isinstance(self.max_replans, int)
            or self.max_replans < 0
        ):
            raise ValueError("max_replans must be a non-negative integer")

    @property
    def replan_count(self) -> int:
        return self._replan_count

    def action_fingerprint(
        self,
        node: PlanNodeV1,
        *,
        observed_state_digest: str,
    ) -> str:
        if node.node_type not in {PlanNodeType.ACTION, PlanNodeType.OBSERVE}:
            raise ValueError("fingerprint requires ACTION or OBSERVE node")
        state_digest = str(observed_state_digest).strip().casefold()
        if not state_digest:
            raise ValueError("observed_state_digest must not be empty")
        return canonical_digest(
            {
                "capability_key": node.capability_key,
                "operation": node.operation,
                "parameters": node.parameters,
                "observed_state_digest": state_digest,
            }
        )

    def admit_action(
        self,
        node: PlanNodeV1,
        *,
        observed_state_digest: str,
    ) -> str:
        fingerprint = self.action_fingerprint(
            node,
            observed_state_digest=observed_state_digest,
        )
        if fingerprint in self._seen_fingerprints:
            raise PlanValidationError(
                "exact action+parameter+state repetition would make no progress"
            )
        self._seen_fingerprints.add(fingerprint)
        return fingerprint

    def admit_replan(self) -> int:
        if self._replan_count >= self.max_replans:
            raise PlanValidationError("bounded replan budget exhausted")
        self._replan_count += 1
        return self._replan_count
