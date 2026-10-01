"""High-level GICC composition for canonical owner-turn intake."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from jarvis.conversation import ConversationRole, ConversationSession, ConversationTurn
from jarvis.capability_acquisition.runtime_context import AcquisitionContextProvider

from .capability_graph import CapabilityGapAnalysis, CapabilityGraphResolver
from .continuation import ContinuationCoordinator
from .information import InformationResolver
from .interpretation import GoalInterpretationResult, GoalInterpreter
from .models import (
    ContinuationBlockerType,
    GoalInterpretationCandidateV1,
    GoalKind,
    GoalState,
    InformationNeedCategory,
    InformationNeedV1,
    MonitorPredicateV1,
    OwnerGoalV2,
    PlanGraphV1,
    PlanNodeType,
    PlanNodeV1,
)
from .phase9 import Phase9GapAdmission, Phase9GoalBridge
from .planning import GoalPlanner, PlanValidationContext
from .requirements import RequirementDerivationResult, RequirementDeriver
from .store import GoalStore
from .telemetry import DEFAULT_GICC_TELEMETRY, GiccTelemetrySink
from .world import EntityResolutionState, EntityResolver

_WORLD_RESOURCE_TYPES = frozenset(
    {
        "camera",
        "computer",
        "display",
        "entrance",
        "generic_external_resource",
        "media_player",
        "room",
    }
)


class GoalIntakeDisposition(str, Enum):
    CONVERSATION_ONLY = "conversation_only"
    EXISTING_GOAL = "existing_goal"
    WAITING_INFORMATION = "waiting_information"
    WAITING_CAPABILITY = "waiting_capability"
    PLAN_READY = "plan_ready"


@dataclass(frozen=True, slots=True)
class GoalIntakeResult:
    disposition: GoalIntakeDisposition
    goal: OwnerGoalV2 | None
    interpretation: GoalInterpretationResult | None = None
    requirement_result: RequirementDerivationResult | None = None
    capability_analysis: CapabilityGapAnalysis | None = None
    information_needs: tuple[InformationNeedV1, ...] = ()
    information_interactions: tuple[dict[str, object], ...] = ()
    phase9_admissions: tuple[Phase9GapAdmission, ...] = ()
    plan: PlanGraphV1 | None = None


class CapabilityContextProvider(Protocol):
    def current(self): ...


def _entity_candidate(value: str) -> tuple[str | None, str]:
    raw = str(value).strip()
    if "::" not in raw:
        return None, raw
    proposed_type, mention = raw.split("::", 1)
    normalized_type = proposed_type.strip().casefold()
    return (
        None if normalized_type in {"", "unresolved"} else normalized_type,
        mention.strip(),
    )


def _task_specific_values(
    candidate: GoalInterpretationCandidateV1,
) -> tuple[str, ...]:
    values: list[str] = []
    for encoded in candidate.candidate_entities:
        proposed_type, mention = _entity_candidate(encoded)
        if mention and proposed_type not in _WORLD_RESOURCE_TYPES:
            values.append(mention)
    return tuple(values)


def _task_terms(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    terms: set[str] = set()
    for value in values:
        for token in re.findall(r"[A-Za-z0-9_]{3,}", str(value).casefold()):
            terms.add(token)
    return tuple(sorted(terms))


class GoalIntelligenceCoordinator:
    """Admit one accepted USER turn into the deterministic GICC pipeline."""

    def __init__(
        self,
        *,
        store: GoalStore,
        interpreter: GoalInterpreter,
        entity_resolver: EntityResolver,
        requirement_deriver: RequirementDeriver,
        capability_context: AcquisitionContextProvider,
        capability_graph_resolver: CapabilityGraphResolver,
        information_resolver: InformationResolver | None = None,
        phase9_bridge: Phase9GoalBridge | None = None,
        planner: GoalPlanner | None = None,
        continuation_coordinator: ContinuationCoordinator | None = None,
        telemetry: GiccTelemetrySink = DEFAULT_GICC_TELEMETRY,
    ) -> None:
        if not isinstance(store, GoalStore):
            raise TypeError("store must be GoalStore")
        if not isinstance(interpreter, GoalInterpreter):
            raise TypeError("interpreter must be GoalInterpreter")
        if not isinstance(entity_resolver, EntityResolver):
            raise TypeError("entity_resolver must be EntityResolver")
        if not isinstance(requirement_deriver, RequirementDeriver):
            raise TypeError("requirement_deriver must be RequirementDeriver")
        if not isinstance(capability_graph_resolver, CapabilityGraphResolver):
            raise TypeError("capability_graph_resolver must be CapabilityGraphResolver")
        if not callable(getattr(capability_context, "current", None)):
            raise TypeError("capability_context must provide current()")
        self._store = store
        self._interpreter = interpreter
        self._entities = entity_resolver
        self._requirements = requirement_deriver
        self._capability_context = capability_context
        self._capability_graph = capability_graph_resolver
        self._information = information_resolver or InformationResolver(store=store)
        self._phase9 = phase9_bridge
        self._planner = planner
        self._continuations = continuation_coordinator or ContinuationCoordinator(store)
        if not callable(getattr(telemetry, "emit", None)):
            raise TypeError("telemetry must provide emit()")
        self._telemetry = telemetry

    async def pursue(
        self,
        *,
        conversation: ConversationSession,
        turn: ConversationTurn,
    ) -> GoalIntakeResult:
        if turn.role is not ConversationRole.USER:
            raise ValueError("GICC intake requires a canonical USER turn")
        if turn not in conversation.turns:
            raise ValueError("GICC intake turn must belong to the conversation")

        existing = self._store.get_goal_by_source(
            source_session_id=conversation.session_id,
            source_turn_id=turn.turn_id,
        )
        if existing is not None:
            return GoalIntakeResult(
                disposition=GoalIntakeDisposition.EXISTING_GOAL,
                goal=existing,
            )

        interpretation = await self._interpreter.interpret(
            conversation=conversation,
            turn=turn,
            store=self._store,
        )
        if not interpretation.actionable:
            return GoalIntakeResult(
                disposition=GoalIntakeDisposition.CONVERSATION_ONLY,
                goal=None,
                interpretation=interpretation,
            )

        resolved_entity_ids: list[str] = []
        unresolved: list[tuple[str, str, tuple[str, ...]]] = []
        task_specific_values: list[str] = []
        for encoded in interpretation.candidate.candidate_entities:
            proposed_type, mention = _entity_candidate(encoded)
            if not mention:
                continue
            if proposed_type not in _WORLD_RESOURCE_TYPES:
                task_specific_values.append(mention)
                continue
            resolution = self._entities.resolve(
                mention,
                expected_entity_types=(proposed_type,),
                require_live_binding=False,
            )
            self._telemetry.emit(
                "gicc_entity_resolved",
                source_turn_id=turn.turn_id,
                entity_type=proposed_type,
                resolution_state=resolution.state.value,
                entity_id=resolution.entity_id,
                candidate_count=len(resolution.candidate_entity_ids),
            )
            if resolution.state is EntityResolutionState.RESOLVED:
                assert resolution.entity_id is not None
                resolved_entity_ids.append(resolution.entity_id)
                continue
            candidates = (
                resolution.candidate_entity_ids
                if resolution.state is EntityResolutionState.AMBIGUOUS
                else ()
            )
            unresolved.append((proposed_type, mention, candidates))

        initial_state = (
            GoalState.WAITING_INFORMATION if unresolved else GoalState.RESOLVING
        )
        goal = self._store.create_goal(
            OwnerGoalV2.create(
                source_session_id=conversation.session_id,
                source_turn_id=turn.turn_id,
                exact_owner_request=turn.text,
                goal_kind=interpretation.candidate.goal_kind,
                desired_outcome=interpretation.candidate.desired_outcome,
                completion_predicates=(
                    interpretation.candidate.candidate_completion_predicates
                ),
                referenced_entity_ids=tuple(sorted(set(resolved_entity_ids))),
                state=initial_state,
                interpretation_evidence=(
                    *interpretation.candidate.reasoning_evidence_refs,
                    f"interpretation:{interpretation.candidate.digest}",
                ),
            )
        )
        self._store.put_goal_interpretation_evidence(
            goal.goal_id,
            interpretation.candidate,
        )
        self._telemetry.emit(
            "gicc_goal_admitted",
            goal_id=goal.goal_id,
            goal_digest=goal.digest,
            goal_kind=goal.goal_kind.value,
            goal_state=goal.state.value,
            source_session_id=goal.source_session_id,
            source_turn_id=goal.source_turn_id,
        )

        if unresolved:
            needs: list[InformationNeedV1] = []
            interactions: list[dict[str, object]] = []
            for entity_type, mention, candidates in unresolved:
                ambiguous = bool(candidates)
                need = self._store.create_information_need(
                    InformationNeedV1.create(
                        goal_id=goal.goal_id,
                        category=(
                            InformationNeedCategory.AMBIGUOUS_REFERENCE
                            if ambiguous
                            else InformationNeedCategory.MISSING_VALUE
                        ),
                        subject=mention,
                        required_fact=(
                            f"canonical {entity_type} identity for {mention}"
                        ),
                        why_required=(
                            "The physical/resource target changes which governed "
                            "capability may act."
                        ),
                        candidate_values=candidates,
                        allowed_resolution_sources=(
                            "conversation_context",
                            "world_registry",
                            "bounded_local_discovery",
                            "owner_input",
                        ),
                        owner_question=(
                            f"Which {mention} do you mean?"
                            if ambiguous
                            else f"Which {mention} should I use?"
                        ),
                        answer_schema={"type": "entity_id"},
                    )
                )
                self._telemetry.emit(
                    "gicc_information_need_created",
                    goal_id=goal.goal_id,
                    information_need_id=need.information_need_id,
                    category=need.category.value,
                    state=need.state.value,
                    candidate_count=len(need.candidate_values),
                )
                resolution = self._information.resolve(
                    need,
                    owner_question=need.owner_question,
                )
                if resolution.state.value == "resolved":
                    self._telemetry.emit(
                        "gicc_information_need_resolved",
                        goal_id=goal.goal_id,
                        information_need_id=resolution.need.information_need_id,
                        state=resolution.need.state.value,
                    )
                needs.append(resolution.need)
                if resolution.interaction is not None:
                    interactions.append(resolution.interaction)
            return GoalIntakeResult(
                disposition=GoalIntakeDisposition.WAITING_INFORMATION,
                goal=goal,
                interpretation=interpretation,
                information_needs=tuple(needs),
                information_interactions=tuple(interactions),
            )

        return await self._advance_goal(
            goal=goal,
            candidate=interpretation.candidate,
            interpretation_result=interpretation,
        )

    async def continue_goal(self, goal_id: str) -> GoalIntakeResult:
        """Resume one exact durable goal after its current blocker is resolved."""

        goal = self._store.get_goal(str(goal_id).strip())
        if goal is None:
            raise ValueError(f"unknown GICC goal: {goal_id}")
        candidate = self._store.get_goal_interpretation_evidence(goal.goal_id)
        if candidate is None:
            raise ValueError(
                "GICC goal has no durable interpretation evidence and cannot resume"
            )

        if goal.state is GoalState.WAITING_INFORMATION:
            needs = self._store.list_information_needs(goal_id=goal.goal_id)
            unresolved = tuple(need for need in needs if need.state.value != "resolved")
            if unresolved:
                return GoalIntakeResult(
                    disposition=GoalIntakeDisposition.WAITING_INFORMATION,
                    goal=goal,
                    information_needs=unresolved,
                )
            entity_ids = tuple(
                need.resolution_ref
                for need in needs
                if need.resolution_ref is not None
                and self._store.get_entity(need.resolution_ref) is not None
            )
            goal = self._store.update_goal_referenced_entities(
                goal.goal_id,
                entity_ids,
                expected_revision=goal.goal_revision,
                state=GoalState.RESOLVING,
            )
            for need in needs:
                self._telemetry.emit(
                    "gicc_information_need_resolved",
                    goal_id=goal.goal_id,
                    information_need_id=need.information_need_id,
                    state=need.state.value,
                )
            return await self._advance_goal(
                goal=goal,
                candidate=candidate,
                interpretation_result=None,
            )

        return GoalIntakeResult(
            disposition=GoalIntakeDisposition.EXISTING_GOAL,
            goal=goal,
        )

    async def _advance_goal(
        self,
        *,
        goal: OwnerGoalV2,
        candidate: GoalInterpretationCandidateV1,
        interpretation_result: GoalInterpretationResult | None,
    ) -> GoalIntakeResult:
        requirement_result = await self._requirements.derive(
            goal=goal,
            interpretation=candidate,
            known_entity_ids=goal.referenced_entity_ids,
            task_specific_terms=_task_terms(_task_specific_values(candidate)),
        )
        graph = self._store.put_requirement_graph(requirement_result.graph)
        self._telemetry.emit(
            "gicc_requirement_graph_created",
            goal_id=goal.goal_id,
            graph_id=graph.graph_id,
            graph_digest=graph.digest,
            requirement_count=len(graph.requirements),
            edge_count=len(graph.edges),
        )
        goal = self._store.update_goal_state(
            goal.goal_id,
            GoalState.REQUIREMENTS_READY,
            expected_revision=goal.goal_revision,
        )
        analysis = self._capability_graph.analyze(
            graph,
            self._capability_context.current(),
            persist_gaps=True,
        )

        for gap in analysis.gaps:
            self._telemetry.emit(
                "gicc_capability_gap_created",
                goal_id=goal.goal_id,
                gap_id=gap.gap_id,
                gap_digest=gap.digest,
                capability_family=gap.reusable_capability_family,
                operation_count=len(gap.minimum_required_operations),
                target_entity_type=gap.target_entity_type,
                target_entity_id=gap.target_entity_id,
            )

        if analysis.gaps:
            goal = self._store.update_goal_state(
                goal.goal_id,
                GoalState.WAITING_CAPABILITY,
                expected_revision=goal.goal_revision,
            )
            admissions = (
                ()
                if self._phase9 is None
                else tuple(self._phase9.admit_gap(gap, goal) for gap in analysis.gaps)
            )
            for admission in admissions:
                admission_change = getattr(admission.admission, "change", None)
                self._telemetry.emit(
                    "gicc_phase9_linked",
                    goal_id=goal.goal_id,
                    gap_id=admission.request.gap_id,
                    request_id=getattr(admission.request, "request_id", None),
                    request_digest=getattr(admission.request, "digest", None),
                    acquisition_work_id=getattr(
                        admission.admission,
                        "acquisition_work_id",
                        None,
                    ),
                    change_id=(
                        None
                        if admission_change is None
                        else admission_change.change_id
                    ),
                )
            plan = self._build_acquisition_plan(goal, analysis)
            self._telemetry.emit(
                "gicc_plan_created",
                goal_id=goal.goal_id,
                plan_id=plan.plan_id,
                plan_digest=plan.digest,
                plan_revision=plan.plan_revision,
                node_count=len(plan.nodes),
                edge_count=len(plan.edges),
            )
            for node in plan.nodes:
                assert node.gap_id is not None
                admission = next(
                    (item for item in admissions if item.request.gap_id == node.gap_id),
                    None,
                )
                work_ids = (
                    ()
                    if admission is None
                    or admission.admission.acquisition_work_id is None
                    else (admission.admission.acquisition_work_id,)
                )
                self._continuations.block(
                    goal=goal,
                    plan=plan,
                    blocked_by_type=ContinuationBlockerType.CAPABILITY_ACQUISITION,
                    blocked_by_id=node.gap_id,
                    resume_node_id=node.node_id,
                    work_ids=work_ids,
                )
            return GoalIntakeResult(
                disposition=GoalIntakeDisposition.WAITING_CAPABILITY,
                goal=goal,
                interpretation=interpretation_result,
                requirement_result=requirement_result,
                capability_analysis=analysis,
                phase9_admissions=admissions,
                plan=plan,
            )

        if self._planner is None:
            return GoalIntakeResult(
                disposition=GoalIntakeDisposition.PLAN_READY,
                goal=goal,
                interpretation=interpretation_result,
                requirement_result=requirement_result,
                capability_analysis=analysis,
            )

        monitor_predicates = self._monitor_predicates(goal, graph)
        allowed_postconditions = set(goal.completion_predicates)
        for requirement in graph.requirements:
            allowed_postconditions.update(requirement.expected_postconditions)
            allowed_postconditions.update(requirement.observation_requirements)
        context = self._capability_context.current()
        plan = await self._planner.plan(
            goal=goal,
            context=PlanValidationContext(
                catalog=context.catalog,
                allowed_capability_operations=tuple(
                    sorted(
                        (match.capability_key, match.operation)
                        for match in analysis.matches
                    )
                ),
                monitor_predicates=monitor_predicates,
                allowed_postcondition_refs=tuple(sorted(allowed_postconditions)),
            ),
        )
        plan = self._store.put_plan(plan)
        self._telemetry.emit(
            "gicc_plan_created",
            goal_id=goal.goal_id,
            plan_id=plan.plan_id,
            plan_digest=plan.digest,
            plan_revision=plan.plan_revision,
            node_count=len(plan.nodes),
            edge_count=len(plan.edges),
        )
        goal = self._store.update_goal_state(
            goal.goal_id,
            (
                GoalState.MONITORING
                if goal.goal_kind is GoalKind.MONITORING
                else GoalState.PLANNED
            ),
            expected_revision=goal.goal_revision,
        )
        return GoalIntakeResult(
            disposition=GoalIntakeDisposition.PLAN_READY,
            goal=goal,
            interpretation=interpretation_result,
            requirement_result=requirement_result,
            capability_analysis=analysis,
            plan=plan,
        )

    def _build_acquisition_plan(
        self,
        goal: OwnerGoalV2,
        analysis: CapabilityGapAnalysis,
    ) -> PlanGraphV1:
        nodes = tuple(
            PlanNodeV1.create(
                plan_identity=f"{goal.goal_id}:{goal.goal_revision}:acquisition",
                ordinal=index,
                node_type=PlanNodeType.ACQUIRE_CAPABILITY,
                summary=(
                    f"Acquire reusable capability {gap.reusable_capability_family}."
                ),
                gap_id=gap.gap_id,
            )
            for index, gap in enumerate(analysis.gaps)
        )
        plan = PlanGraphV1.create(
            goal_id=goal.goal_id,
            goal_revision=goal.goal_revision,
            plan_revision=1,
            nodes=nodes,
            edges=(),
            root_node_ids=tuple(node.node_id for node in nodes),
            completion_node_ids=tuple(node.node_id for node in nodes),
        )
        return self._store.put_plan(plan)

    def _monitor_predicates(
        self,
        goal: OwnerGoalV2,
        graph,
    ) -> tuple[MonitorPredicateV1, ...]:
        if goal.goal_kind is not GoalKind.MONITORING:
            return ()
        observation_capabilities = tuple(
            sorted(
                {
                    requirement.semantic_capability
                    for requirement in graph.requirements
                    if requirement.observation_requirements
                    or "observe" in requirement.semantic_capability
                    or "perceive" in requirement.semantic_capability
                }
            )
        )
        predicate = self._store.put_monitor_predicate(
            MonitorPredicateV1.create(
                goal_id=goal.goal_id,
                source_entity_ids=goal.referenced_entity_ids,
                observation_capabilities=observation_capabilities,
                semantic_condition=goal.desired_outcome,
                candidate_trigger_strategy="event_first",
                stability_window=1.0,
                cooldown=60.0,
                timeout=None,
                completion_policy="complete_once",
                notification_policy="owner",
                verification_requirement="semantic_condition_verified",
            )
        )
        return (predicate,)
