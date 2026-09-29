"""C3 Work adapter around the existing Phase-4 routed model reasoner."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import replace

from jarvis.brain_routing.deterministic import (
    DeterministicResolution,
    DeterministicResolutionStatus,
    DeterministicResolverRegistry,
)
from jarvis.brain_routing.models import (
    BrainRouteKind,
    BrainRouteRecord,
    BrainRoutingMode,
    GlobalBrainRouteFacts,
)
from jarvis.brain_routing.store import BrainRouteStore
from jarvis.model_routing.models import (
    EvidenceSizeClass,
    LocalityRequirement,
    PrivacyClass,
)
from jarvis.model_routing.router import reasoning_cycle_key
from jarvis.model_routing.store import ModelRoutingStore
from jarvis.model_routing.strategy import derive_work_step_signals
from jarvis.work.brain import BrainDecision, BrainReasoner, BrainRequest
from jarvis.work.context import WorkContextMode
from jarvis.work.models import WorkStep
from jarvis.work.store import SQLiteWorkStore


def _use_context_pack(request: BrainRequest) -> bool:
    return (
        request.context_mode is WorkContextMode.APPLY
        and request.context_pack is not None
    )


def _estimated_context_tokens(request: BrainRequest) -> int:
    pack = request.context_pack
    use_pack = _use_context_pack(request)
    steps = (
        pack.recent_steps_payload()
        if use_pack and pack is not None
        else [
            {
                "kind": step.kind,
                "summary": step.summary,
                "input": step.input_data,
                "observation": step.observation,
                "error": step.error,
            }
            for step in request.recent_steps
        ]
    )
    evidence = (
        list(pack.evidence) if use_pack and pack is not None else list(request.evidence)
    )
    payload = {
        "request": request.work.request,
        "purpose": request.purpose,
        "actions": [
            {
                "name": action.name,
                "description": action.description,
                "parameter_schema": action.parameter_schema,
            }
            for action in request.allowed_actions
        ],
        "steps": steps,
        "evidence": evidence,
    }
    if use_pack and pack is not None:
        payload["history_manifest"] = pack.history_manifest_payload()
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    )
    return max(1, (len(encoded) + 3) // 4)


def _evidence_size_class(request: BrainRequest) -> EvidenceSizeClass:
    pack = request.context_pack
    evidence_count = (
        len(pack.evidence)
        if _use_context_pack(request) and pack is not None
        else len(request.evidence)
    )
    if evidence_count >= 6:
        return EvidenceSizeClass.HETEROGENEOUS
    estimated = _estimated_context_tokens(request)
    if estimated >= 16_000:
        return EvidenceSizeClass.LARGE
    if estimated >= 4_000:
        return EvidenceSizeClass.MEDIUM
    return EvidenceSizeClass.SMALL


def build_work_global_route_facts(
    request: BrainRequest,
    *,
    all_steps: tuple[WorkStep, ...],
    deterministic_candidate_count: int = 0,
) -> GlobalBrainRouteFacts:
    """Project canonical Work state into subsystem-neutral routing facts."""

    if not isinstance(request, BrainRequest):
        raise TypeError("request must be a BrainRequest")
    if any(not isinstance(step, WorkStep) for step in all_steps):
        raise TypeError("all_steps must contain WorkStep values")
    signals = derive_work_step_signals(all_steps[-12:])
    return GlobalBrainRouteFacts(
        route_request_id=reasoning_cycle_key(request),
        scope_id=request.work.work_id,
        subsystem_key="work",
        task_kind=request.work.work_type.value,
        required_capabilities=(
            "engineering_reasoning",
            "structured_output",
        ),
        privacy_class=PrivacyClass.STANDARD,
        locality_requirement=LocalityRequirement.ANY,
        estimated_context_tokens=_estimated_context_tokens(request),
        evidence_size_class=_evidence_size_class(request),
        latency_preference="balanced",
        cost_preference="balanced",
        output_contract="brain_decision.v1",
        quality_class="balanced",
        knowledge_state=(
            "evidence_present"
            if (
                (
                    request.context_pack is not None
                    and _use_context_pack(request)
                    and request.context_pack.evidence
                )
                or request.evidence
            )
            else "no_evidence"
        ),
        recent_progress_signals=signals.progress_signals,
        recent_failure_signals=signals.failure_signals,
        affinity_key=f"work:{request.work.work_id}",
        deterministic_candidate_count=deterministic_candidate_count,
    )


def _decision_matches(
    proposal: BrainDecision,
    actual: BrainDecision,
) -> bool:
    return (
        proposal.action == actual.action
        and proposal.parameters == actual.parameters
        and proposal.goal_complete == actual.goal_complete
        and proposal.needs_owner == actual.needs_owner
    )


def _validate_deterministic_decision(
    request: BrainRequest,
    resolution: DeterministicResolution,
) -> BrainDecision:
    decision = resolution.decision
    if not resolution.matched or decision is None:
        raise ValueError("deterministic resolution did not produce a decision")
    allowed = {action.name for action in request.allowed_actions}
    if decision.action is None or decision.action not in allowed:
        raise ValueError("deterministic resolver selected an unapproved action")
    if decision.goal_complete or decision.needs_owner:
        raise ValueError("C3 deterministic resolvers may only select approved actions")
    return decision


class GlobalBrainRouterReasoner:
    """Choose deterministic vs model reasoning without executing any action."""

    def __init__(
        self,
        model_reasoner: BrainReasoner,
        *,
        work_store: SQLiteWorkStore,
        route_store: BrainRouteStore,
        model_routing_store: ModelRoutingStore,
        resolvers: DeterministicResolverRegistry,
        mode: str | BrainRoutingMode = BrainRoutingMode.SHADOW,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._model_reasoner = model_reasoner
        self._work_store = work_store
        self._route_store = route_store
        self._model_routing_store = model_routing_store
        self._resolvers = resolvers
        self._mode = BrainRoutingMode.parse(mode)
        self._clock = clock

    @property
    def mode(self) -> BrainRoutingMode:
        return self._mode

    @property
    def policy_digest(self) -> str:
        return self._resolvers.digest()

    def _facts_and_resolution(
        self,
        request: BrainRequest,
        all_steps: tuple[WorkStep, ...],
    ) -> tuple[GlobalBrainRouteFacts, DeterministicResolution]:
        base = build_work_global_route_facts(request, all_steps=all_steps)
        if self._mode is BrainRoutingMode.OFF:
            return base, DeterministicResolution(
                status=DeterministicResolutionStatus.ABSTAIN,
                resolver_id="global_router_off",
                resolver_version=self._resolvers.policy_version,
                reason_codes=("global_router_off",),
            )
        count = self._resolvers.candidate_count(
            facts=base,
            request=request,
            all_steps=all_steps,
        )
        facts = replace(base, deterministic_candidate_count=count)
        resolution = self._resolvers.resolve(
            facts=facts,
            request=request,
            all_steps=all_steps,
        )
        return facts, resolution

    def _model_lineage(
        self,
        route_request_id: str,
    ) -> tuple[str | None, str | None]:
        persisted = self._model_routing_store.find_decision_by_request(route_request_id)
        if persisted is None:
            return None, None
        return (
            persisted.decision.decision_id,
            persisted.decision.selected_target_id,
        )

    def _record(
        self,
        *,
        facts: GlobalBrainRouteFacts,
        route_kind: BrainRouteKind,
        reason_codes: tuple[str, ...],
        selected_action: str | None,
        resolution: DeterministicResolution | None = None,
        shadow_match: bool | None = None,
        model_decision_id: str | None = None,
        model_target_id: str | None = None,
        outcome_code: str = "selected",
    ) -> BrainRouteRecord:
        return self._route_store.record(
            BrainRouteRecord(
                route_request_id=facts.route_request_id,
                work_id=facts.scope_id,
                subsystem_key=facts.subsystem_key,
                task_kind=facts.task_kind,
                route_kind=route_kind,
                mode=self._mode,
                policy_version=self._resolvers.policy_version,
                policy_digest=self._resolvers.digest(),
                reason_codes=reason_codes,
                created_at_epoch=float(self._clock()),
                selected_action=selected_action,
                resolver_id=(None if resolution is None else resolution.resolver_id),
                resolver_version=(
                    None if resolution is None else resolution.resolver_version
                ),
                shadow_proposed_action=(
                    None
                    if resolution is None or resolution.decision is None
                    else resolution.decision.action
                ),
                shadow_match=shadow_match,
                model_decision_id=model_decision_id,
                model_target_id=model_target_id,
                outcome_code=outcome_code,
            )
        )

    async def decide(self, request: BrainRequest) -> BrainDecision:
        all_steps = self._work_store.list_steps(request.work.work_id)
        facts, resolution = self._facts_and_resolution(request, all_steps)
        existing = self._route_store.get(facts.route_request_id)
        preexisting_model_decision = self._model_routing_store.find_decision_by_request(
            facts.route_request_id
        )

        if existing is not None and existing.route_kind is BrainRouteKind.DETERMINISTIC:
            if preexisting_model_decision is not None:
                raise RuntimeError(
                    "global deterministic provenance conflicts with a persisted model route"
                )
            current = self._resolvers.resolve(
                facts=facts,
                request=request,
                all_steps=all_steps,
            )
            decision = _validate_deterministic_decision(request, current)
            if decision.action != existing.selected_action:
                raise RuntimeError(
                    "deterministic route replay disagrees with durable provenance"
                )
            return decision

        preserve_model_route = (
            existing is not None and existing.route_kind is BrainRouteKind.MODEL
        ) or (existing is None and preexisting_model_decision is not None)
        if (
            not preserve_model_route
            and self._mode is BrainRoutingMode.APPLY
            and resolution.matched
        ):
            decision = _validate_deterministic_decision(request, resolution)
            self._record(
                facts=facts,
                route_kind=BrainRouteKind.DETERMINISTIC,
                reason_codes=resolution.reason_codes,
                selected_action=decision.action,
                resolution=resolution,
                outcome_code="model_bypassed",
            )
            return decision

        try:
            actual = await self._model_reasoner.decide(request)
        except Exception:
            model_decision_id, model_target_id = self._model_lineage(
                facts.route_request_id
            )
            if existing is None:
                self._record(
                    facts=facts,
                    route_kind=BrainRouteKind.MODEL,
                    reason_codes=(
                        ("global_router_off",)
                        if self._mode is BrainRoutingMode.OFF
                        else ("deterministic_abstained",)
                    ),
                    selected_action=None,
                    resolution=(resolution if resolution.matched else None),
                    model_decision_id=model_decision_id,
                    model_target_id=model_target_id,
                    outcome_code="model_error",
                )
            raise

        model_decision_id, model_target_id = self._model_lineage(facts.route_request_id)
        if existing is None:
            shadow_match = (
                _decision_matches(resolution.decision, actual)
                if (
                    self._mode is BrainRoutingMode.SHADOW
                    and resolution.matched
                    and resolution.decision is not None
                )
                else None
            )
            reason_codes = (
                ("global_router_off",)
                if self._mode is BrainRoutingMode.OFF
                else (
                    ("shadow_deterministic_match",)
                    if shadow_match is True
                    else (
                        ("shadow_deterministic_mismatch",)
                        if shadow_match is False
                        else ("deterministic_abstained",)
                    )
                )
            )
            self._record(
                facts=facts,
                route_kind=BrainRouteKind.MODEL,
                reason_codes=reason_codes,
                selected_action=actual.action,
                resolution=(resolution if resolution.matched else None),
                shadow_match=shadow_match,
                model_decision_id=model_decision_id,
                model_target_id=model_target_id,
            )
        return actual
