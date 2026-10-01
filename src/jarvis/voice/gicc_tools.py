"""Voice-facing GICC APPLY tools grounded to canonical USER turns."""

from __future__ import annotations

import logging

from livekit.agents import RunContext, function_tool

from jarvis.conversation import ConversationRole, ConversationSession, ConversationTurn
from jarvis.goal_intelligence.composition import (
    GoalIntakeDisposition,
    GoalIntakeResult,
    GoalIntelligenceCoordinator,
)
from jarvis.goal_intelligence.information import BoundInformationInteraction
from jarvis.goal_intelligence.store import GoalStore, GoalStoreConflict
from jarvis.goal_intelligence.telemetry import (
    DEFAULT_GICC_TELEMETRY,
    GiccTelemetrySink,
)

LOGGER = logging.getLogger(__name__)


class GiccToolGroundingError(ValueError):
    pass


class GiccAgentTools:
    """Expose only high-level goal pursuit and exact clarification continuation."""

    def __init__(
        self,
        coordinator: GoalIntelligenceCoordinator,
        conversation: ConversationSession,
        store: GoalStore,
        *,
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
        self._coordinator = coordinator
        self._conversation = conversation
        self._store = store
        self._telemetry = telemetry

    @property
    def tools(self) -> list:
        return [
            self.pursue_owner_goal,
            self.resolve_goal_information,
        ]

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
            result = await self._coordinator.pursue(
                conversation=self._conversation,
                turn=turn,
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
            continued = await self._coordinator.continue_goal(goal_id)
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
