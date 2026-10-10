"""Voice-facing GICC APPLY tools grounded to canonical USER turns."""

from __future__ import annotations

import logging
from typing import Protocol

from livekit.agents import RunContext, function_tool

from jarvis.conversation import ConversationRole, ConversationSession, ConversationTurn
from jarvis.goal_intelligence.composition import (
    GoalIntakeDisposition,
    GoalIntakeResult,
    GoalIntelligenceCoordinator,
)
from jarvis.goal_intelligence.information import (
    BoundInformationInteraction,
    can_rediscover_information,
)
from jarvis.goal_intelligence.models import GoalState, PlanState
from jarvis.goal_intelligence.status import OwnerObjectiveStatusResolver
from jarvis.goal_intelligence.store import GoalStore, GoalStoreConflict
from jarvis.goal_intelligence.telemetry import (
    DEFAULT_GICC_TELEMETRY,
    GiccTelemetrySink,
)

LOGGER = logging.getLogger(__name__)


class GiccToolGroundingError(ValueError):
    pass


class GiccExecutionRuntime(Protocol):
    async def pursue(
        self,
        *,
        conversation: ConversationSession,
        turn: ConversationTurn,
    ) -> GoalIntakeResult: ...

    async def continue_goal(self, goal_id: str) -> GoalIntakeResult: ...


class GiccAgentTools:
    """Expose only high-level goal pursuit and exact clarification continuation."""

    def __init__(
        self,
        coordinator: GoalIntelligenceCoordinator,
        conversation: ConversationSession,
        store: GoalStore,
        *,
        execution_runtime: GiccExecutionRuntime | None = None,
        objective_status: OwnerObjectiveStatusResolver | None = None,
        telemetry: GiccTelemetrySink = DEFAULT_GICC_TELEMETRY,
    ) -> None:
        if not isinstance(coordinator, GoalIntelligenceCoordinator):
            raise TypeError("coordinator must be GoalIntelligenceCoordinator")
        if not isinstance(conversation, ConversationSession):
            raise TypeError("conversation must be ConversationSession")
        if not isinstance(store, GoalStore):
            raise TypeError("store must be GoalStore")
        if not callable(getattr(telemetry, "emit", None)):
            raise TypeError("telemetry must provide emit()")
        if execution_runtime is not None and (
            not callable(getattr(execution_runtime, "pursue", None))
            or not callable(getattr(execution_runtime, "continue_goal", None))
        ):
            raise TypeError(
                "execution_runtime must provide pursue() and continue_goal()"
            )
        self._coordinator = coordinator
        self._execution_runtime = execution_runtime
        self._objective_status = objective_status
        self._conversation = conversation
        self._store = store
        self._telemetry = telemetry

    @property
    def action_tools(self) -> list:
        """Goal-changing tools that may be suppressed at protected decision boundaries."""

        return [
            self.pursue_owner_goal,
            self.resolve_goal_information,
        ]

    @property
    def read_tools(self) -> list:
        """Read-only owner-objective awareness tools; safe during approval gates."""

        if self._objective_status is None:
            return []
        return [
            self.list_owner_objectives,
            self.get_owner_objective_status,
        ]

    @property
    def tools(self) -> list:
        return [*self.action_tools, *self.read_tools]

    @function_tool()
    async def list_owner_objectives(
        self,
        context: RunContext,
    ) -> dict[str, object]:
        """List canonical active owner objectives across their full lifecycle.

        Use for questions about an overall task, goal, capability request, or whether
        something is still in progress. Child WorkItem completion is not overall
        completion; verified_completion is the only completion authority.
        """

        del context
        resolver = self._objective_status
        if resolver is None:
            return {"ok": False, "status": "objective_status_unavailable"}
        objectives = resolver.list_active(limit=50)
        return {
            "ok": True,
            "status": "listed",
            "objectives": [item.public_payload() for item in objectives],
            "truth_note": (
                "These are owner-level objectives joined across GICC, Work, "
                "EngineeringChange, activation, and external acceptance. Never infer "
                "overall completion from a child WorkItem alone."
            ),
        }

    @function_tool()
    async def get_owner_objective_status(
        self,
        context: RunContext,
        goal_id: str,
    ) -> dict[str, object]:
        """Read one canonical owner objective across its complete persisted lineage."""

        del context
        resolver = self._objective_status
        if resolver is None:
            return {"ok": False, "status": "objective_status_unavailable"}
        try:
            objective = resolver.resolve(goal_id)
        except ValueError:
            return {"ok": False, "status": "unknown_goal_id", "goal_id": goal_id}
        return {"ok": True, "status": "found", **objective.public_payload()}

    def _latest_user_turn(self) -> ConversationTurn:
        turn = next(
            (
                candidate
                for candidate in reversed(self._conversation.turns)
                if candidate.role is ConversationRole.USER
            ),
            None,
        )
        if turn is None:
            raise GiccToolGroundingError(
                "GICC requires a latest accepted USER utterance"
            )
        return turn

    def _internal_failure(
        self,
        *,
        turn: ConversationTurn,
        stage: str,
        error: Exception,
    ) -> dict[str, object]:
        LOGGER.exception(
            "GICC voice tool failed internally before verified target completion | "
            "stage=%s turn_id=%s",
            stage,
            turn.turn_id,
            exc_info=error,
        )
        self._telemetry.emit(
            "gicc_goal_processing_error",
            source_turn_id=turn.turn_id,
            stage=stage,
            error_type=type(error).__name__,
        )
        return {
            "ok": False,
            "status": "internal_goal_processing_error",
            "canonical_user_turn_id": turn.turn_id,
            "retryable": True,
            "truth_note": (
                "Goal processing failed internally before any target device or "
                "service action was verified. Do not claim a device connectivity "
                "failure, execution, or completion."
            ),
        }

    def _public_result(self, result: GoalIntakeResult) -> dict[str, object]:
        goal = result.goal
        payload: dict[str, object] = {
            "ok": True,
            "status": result.disposition.value,
            "goal_id": None if goal is None else goal.goal_id,
            "goal_state": None if goal is None else goal.state.value,
        }

        if goal is not None and goal.state is GoalState.COMPLETED:
            payload["status"] = "completed"
            payload["plan_id"] = None if result.plan is None else result.plan.plan_id
            payload["verified_completion"] = True
            payload["truth_note"] = (
                "The durable goal and plan reached verified completion. "
                "You may acknowledge that the requested outcome completed."
            )
            return payload

        if goal is not None and goal.state is GoalState.FAILED:
            payload["status"] = "failed"
            payload["plan_id"] = None if result.plan is None else result.plan.plan_id
            payload["verified_completion"] = False
            payload["truth_note"] = (
                "Durable goal execution failed before verified completion. "
                "Do not claim the requested outcome completed."
            )
            return payload

        if result.plan is not None and result.plan.state is PlanState.WAITING:
            results = self._store.list_plan_node_results(
                plan_id=result.plan.plan_id,
                limit=1000,
            )
            pending = next(
                (
                    item
                    for item in reversed(results)
                    if isinstance(item.get("payload"), dict)
                    and isinstance(item["payload"].get("interaction"), dict)
                    and item["payload"]["interaction"].get("kind")
                    == "external_owner_input"
                ),
                None,
            )
            if pending is not None:
                interaction = dict(pending["payload"]["interaction"])
                payload["status"] = "waiting_owner_input"
                payload["plan_id"] = result.plan.plan_id
                payload["owner_input"] = {
                    "interaction_ref": pending.get("result_id"),
                    "input_kind": interaction.get("input_kind"),
                    "prompt": interaction.get("prompt"),
                    "parameter": interaction.get("parameter"),
                    "sensitive": interaction.get("sensitive") is True,
                }
                if interaction.get("sensitive") is True:
                    payload["truth_note"] = (
                        "The exact capability is waiting for sensitive owner input. "
                        "Do not ask the owner to send the PIN through a generic GICC "
                        "tool argument or claim completion; use the dedicated secure "
                        "owner-input/acceptance path."
                    )
                else:
                    payload["truth_note"] = (
                        "The exact capability is waiting for bound owner input. "
                        "Do not claim completion until that interaction is resolved "
                        "and postconditions verify."
                    )
                return payload

        if result.disposition is GoalIntakeDisposition.CONVERSATION_ONLY:
            payload["handled"] = False
            payload["truth_note"] = (
                "GICC found no actionable owner goal; respond conversationally."
            )
            return payload

        if result.disposition is GoalIntakeDisposition.WAITING_INFORMATION:
            interactions = {
                str(item["information_need_id"]): item
                for item in result.information_interactions
            }
            questions: list[dict[str, object]] = []
            for need in result.information_needs:
                interaction = interactions.get(need.information_need_id)
                options: list[dict[str, object]] = []
                for value in need.candidate_values:
                    entity = self._store.get_entity(value)
                    options.append(
                        {
                            "value": value,
                            "label": (
                                value if entity is None else entity.canonical_name
                            ),
                            "entity_type": (
                                None if entity is None else entity.entity_type
                            ),
                        }
                    )
                questions.append(
                    {
                        "information_need_id": need.information_need_id,
                        "interaction_id": (
                            None
                            if interaction is None
                            else interaction["interaction_id"]
                        ),
                        "question": need.owner_question,
                        "options": options,
                        "answer_type": need.answer_schema.get("type"),
                    }
                )
            payload["questions"] = questions
            payload["truth_note"] = (
                "Ask only the returned question. The owner's next answer must be "
                "submitted through resolve_goal_information with the exact "
                "interaction ID and selected candidate value."
            )
            # A passive OS scope check can prepare a consent summary. This is
            # explicitly NOT a registered approval, permit, or active scan.
            # An unverified AEP sighting must never be offered as a canonical
            # candidate value for resolve_goal_information.
            runtime = self._execution_runtime
            if (
                runtime is not None
                and goal.source_session_id == self._conversation.session_id
            ):
                prepare = getattr(runtime, "prepare_network_discovery_consent", None)
                if callable(prepare):
                    try:
                        proposal = prepare(
                            goal_id=goal.goal_id,
                            session_id=goal.source_session_id,
                        )
                    except Exception:
                        LOGGER.warning(
                            "GICC could not prepare passive network consent scope",
                            exc_info=True,
                        )
                    else:
                        valid_proposal = (
                            proposal is not None
                            and proposal.has_valid_fingerprint()
                            and not proposal.is_expired()
                            and proposal.session_id == goal.source_session_id
                            and proposal.capability == "network_discovery"
                            and proposal.operation == "enumerate_aep"
                        )
                        if valid_proposal:
                            target = proposal.target()
                            bound_need = self._store.get_information_need(
                                str(target.get("gicc_need_id") or "")
                            )
                            valid_proposal = (
                                target.get("gicc_goal_id") == goal.goal_id
                                and bound_need is not None
                                and bound_need.goal_id == goal.goal_id
                                and can_rediscover_information(bound_need)
                            )
                        if valid_proposal:
                            payload["network_discovery"] = {
                                "state": "proposal_only_not_authorized",
                                "summary": proposal.material_summary,
                                "protocol": target.get("protocol"),
                                "result_address_filters": target.get(
                                    "address_result_filters"
                                ),
                                "all_local_interfaces": target.get(
                                    "all_local_interfaces"
                                ),
                                "information_need_id": target.get("gicc_need_id"),
                                "owner_approval_required": True,
                                "scan_started": False,
                            }
                            payload["truth_note"] = (
                                "An eligible bounded device discovery scope was "
                                "prepared without active scanning. The owner must "
                                "consent using the canonical AuthorityService "
                                "approval path before any scan runs. This tool has "
                                "not registered an approval request or executed "
                                "network discovery; generic spoken agreement is "
                                "not execution authority. Do not ask the owner to "
                                "find the TV IP manually, invent devices, or "
                                "treat unverified network observations as identity."
                            )
                suggestions = getattr(
                    runtime, "pending_network_device_suggestions", None
                )
                if callable(suggestions):
                    try:
                        hints = suggestions(
                            goal_id=goal.goal_id,
                            session_id=goal.source_session_id,
                        )
                    except Exception:
                        LOGGER.warning(
                            "GICC could not read unverified device hints",
                            exc_info=True,
                        )
                    else:
                        if hints:
                            payload["unverified_device_hints"] = [
                                {
                                    "display_hint": hint.display_hint,
                                    "address": hint.address,
                                    "protocol_observed": hint.protocol,
                                    "neighbor_correlated": hint.neighbor_correlated,
                                    "verified_identity": False,
                                    "control_access_verified": False,
                                }
                                for hint in hints
                            ]
            return payload

        if result.disposition is GoalIntakeDisposition.WAITING_CAPABILITY:
            payload["capability_gaps"] = [
                {
                    "gap_id": gap.gap_id,
                    "family": gap.reusable_capability_family,
                    "operations": list(gap.minimum_required_operations),
                    "target_entity_type": gap.target_entity_type,
                    "target_entity_id": gap.target_entity_id,
                }
                for gap in (
                    ()
                    if result.capability_analysis is None
                    else result.capability_analysis.gaps
                )
            ]
            payload["acquisition_work_ids"] = [
                admission.admission.acquisition_work_id
                for admission in result.phase9_admissions
                if admission.admission.acquisition_work_id is not None
            ]
            payload["truth_note"] = (
                "Governed acquisition may have started. This does not mean the "
                "capability is built, activated, verified, or authorized for use."
            )
            return payload

        if result.disposition is GoalIntakeDisposition.PLAN_READY:
            payload["plan_id"] = None if result.plan is None else result.plan.plan_id
            payload["plan_node_types"] = (
                []
                if result.plan is None
                else [node.node_type.value for node in result.plan.nodes]
            )
            payload["truth_note"] = (
                "The goal has a validated plan. Do not claim completion until "
                "governed execution and postcondition verification succeed."
            )
            return payload

        payload["truth_note"] = "This exact durable goal already exists."
        return payload

    @function_tool()
    async def pursue_owner_goal(
        self,
        context: RunContext,
    ) -> dict[str, object]:
        """Submit the latest accepted USER outcome to GICC.

        Use in GICC APPLY mode for external-device/service outcomes, monitoring or
        conditional goals, and multi-step owner outcomes where target/resource or
        reusable-capability resolution may be needed. Ordinary local actions that
        are already directly supported by current Hands can continue using Hands.
        """

        del context
        turn = self._latest_user_turn()
        try:
            runtime = self._execution_runtime
            result = (
                await self._coordinator.pursue(
                    conversation=self._conversation,
                    turn=turn,
                )
                if runtime is None
                else await runtime.pursue(
                    conversation=self._conversation,
                    turn=turn,
                )
            )
        except Exception as exc:  # noqa: BLE001 - voice boundary must stay truthful
            return self._internal_failure(
                turn=turn,
                stage="pursue_owner_goal",
                error=exc,
            )
        payload = self._public_result(result)
        payload["canonical_user_turn_id"] = turn.turn_id
        return payload

    @function_tool()
    async def resolve_goal_information(
        self,
        context: RunContext,
        interaction_id: str,
        selected_candidate_value: str,
    ) -> dict[str, object]:
        """Resolve one exact GICC clarification from the owner's latest answer.

        Only use the interaction_id and candidate value returned by a prior
        pursue_owner_goal call. Never bind ambient speech to an unrelated need.
        """

        del context
        turn = self._latest_user_turn()
        interaction_key = str(interaction_id).strip()
        selected = str(selected_candidate_value).strip()
        interaction = self._store.get_information_interaction(interaction_key)
        if interaction is None:
            return {
                "ok": False,
                "status": "unknown_information_interaction",
                "interaction_id": interaction_key,
            }
        if interaction["state"] != "active":
            return {
                "ok": False,
                "status": "information_interaction_not_active",
                "interaction_id": interaction_key,
            }
        allowed = tuple(
            str(item) for item in interaction.get("allowed_candidate_values", ())
        )
        if selected not in allowed:
            return {
                "ok": False,
                "status": "candidate_value_not_allowed",
                "interaction_id": interaction_key,
                "allowed_candidate_values": list(allowed),
            }
        goal_id = str(interaction["goal_id"])
        need_id = str(interaction["information_need_id"])
        try:
            resolved = BoundInformationInteraction(
                store=self._store,
                interaction_id=interaction_key,
                goal_id=goal_id,
                information_need_id=need_id,
            ).submit(
                turn,
                resolution_ref=selected,
            )
        except GoalStoreConflict as exc:
            return {
                "ok": False,
                "status": "information_interaction_conflict",
                "interaction_id": interaction_key,
                "reason": str(exc),
            }

        self._telemetry.emit(
            "gicc_information_need_resolved",
            goal_id=goal_id,
            information_need_id=resolved.information_need_id,
            state=resolved.state.value,
            source_turn_id=turn.turn_id,
        )
        try:
            runtime = self._execution_runtime
            continued = (
                await self._coordinator.continue_goal(goal_id)
                if runtime is None
                else await runtime.continue_goal(goal_id)
            )
        except Exception as exc:  # noqa: BLE001 - voice boundary must stay truthful
            return self._internal_failure(
                turn=turn,
                stage="continue_goal",
                error=exc,
            )
        payload = self._public_result(continued)
        payload.update(
            {
                "canonical_user_turn_id": turn.turn_id,
                "resolved_information_need_id": resolved.information_need_id,
                "interaction_id": interaction_key,
            }
        )
        return payload
