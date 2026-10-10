"""Voice-facing GICC APPLY tools grounded to canonical USER turns."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from collections.abc import Callable
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
from jarvis.goal_intelligence.world import canonical_world_entity_type

LOGGER = logging.getLogger(__name__)


def _device_choice_digest(hints: tuple[object, ...]) -> str:
    """Bind the voice options to one exact live, ordered candidate set."""
    refs = tuple(str(getattr(hint, "evidence_ref", "")) for hint in hints)
    return hashlib.sha256("\n".join(refs).encode("utf-8")).hexdigest()


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
        # UI-offered option snapshots are session-local only; after restart,
        # ask JARVIS to show the fresh options again instead of trusting a
        # model-supplied digest as proof an owner actually saw them.
        self._offered_device_options: dict[tuple[str, str], tuple[str, str]] = {}
        # An accepted "approve discovery" utterance requires a *previously
        # offered* scope for this exact goal in the same live conversation.
        self._offered_network_discovery: dict[str, tuple[tuple[object, ...], str]] = {}

    @property
    def action_tools(self) -> list:
        """Goal-changing tools that may be suppressed at protected decision boundaries."""

        return [
            self.pursue_owner_goal,
            self.resolve_goal_information,
            self.authorize_bounded_network_discovery,
            self.confirm_discovered_device_identity,
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
                            # A runtime suggestion is untrusted until the exact
                            # canonical current InformationNeed records both
                            # this evidence ref and its authorized AEP scope.
                            eligible_by_need = {
                                need.information_need_id: tuple(
                                    hint
                                    for hint in hints
                                    if getattr(hint, "evidence_ref", None)
                                    in need.evidence_refs
                                    and (
                                        "windows_aep_authorized_scope_consumed:"
                                        + str(getattr(hint, "protocol", ""))
                                    )
                                    in need.evidence_refs
                                )
                                for need in result.information_needs
                                if need.goal_id == goal.goal_id
                            }
                            eligible_refs = {
                                hint.evidence_ref
                                for entries in eligible_by_need.values()
                                for hint in entries
                            }
                            eligible = tuple(
                                hint
                                for hint in hints
                                if getattr(hint, "evidence_ref", None) in eligible_refs
                            )
                            if eligible:
                                payload["unverified_device_hints"] = [
                                    {
                                        "display_hint": hint.display_hint,
                                        "address": hint.address,
                                        "protocol_observed": hint.protocol,
                                        "neighbor_correlated": hint.neighbor_correlated,
                                        "verified_identity": False,
                                        "control_access_verified": False,
                                    }
                                    for hint in eligible
                                ]
                            choice_sets = []
                            for need in result.information_needs:
                                candidates = eligible_by_need.get(
                                    need.information_need_id, ()
                                )
                                if not candidates:
                                    continue
                                choice_sets.append(
                                    {
                                        "information_need_id": need.information_need_id,
                                        "digest": _device_choice_digest(candidates),
                                        "options": [
                                            {
                                                "option": index,
                                                "display_hint": hint.display_hint,
                                                "evidence_ref": hint.evidence_ref,
                                                "verified_identity": False,
                                            }
                                            for index, hint in enumerate(
                                                candidates, start=1
                                            )
                                        ],
                                    }
                                )
                            if choice_sets:
                                payload["device_choice_sets"] = choice_sets

            # The original identity question remains durable, but it is a
            # fallback, not the next owner action when governed discovery is
            # available. Otherwise LiveKit sees "Which TV?" alongside a valid
            # scoped discovery proposal and can repeatedly request a model/IP
            # instead of advancing the existing InformationNeed.
            options = payload.get("device_choice_sets")
            scopes = payload.get("network_discovery")
            bound_need_ids: set[str] = set()
            if isinstance(options, list) and options:
                bound_need_ids.update(
                    str(item["information_need_id"]) for item in options
                )
                payload["next_action"] = "confirm_discovered_device_identity"
                payload["truth_note"] = (
                    "A governed observation produced unverified devices. Show "
                    "the exact option set and request explicit owner confirmation "
                    "of their identity. No control, pairing, or access is yet "
                    "authorized. Do not ask for a model or network address."
                )
            elif isinstance(scopes, dict):
                bound_need_ids.add(str(scopes["information_need_id"]))
                payload["next_action"] = "request_scoped_discovery_approval"
                payload["truth_note"] = (
                    "A bounded discovery scope is available. Present its exact "
                    "scope and ask for explicit owner authorization before any "
                    "active scan; Windows Hello and the AuthorityService are "
                    "still required. Defer the generic device identity question "
                    "until governed discovery genuinely cannot resolve it. "
                    "Never ask the owner to identify an IP, model or protocol "
                    "as a substitute for discovery."
                )
            if bound_need_ids:
                deferred = [
                    question
                    for question in questions
                    if str(question["information_need_id"]) in bound_need_ids
                ]
                payload["questions"] = [
                    question
                    for question in questions
                    if str(question["information_need_id"]) not in bound_need_ids
                ]
                if deferred:
                    payload["deferred_information_questions"] = deferred
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
        if result.goal is not None:
            self._offered_network_discovery.pop(result.goal.goal_id, None)
        scope = payload.get("network_discovery")
        if isinstance(scope, dict) and result.goal is not None:
            self._offered_network_discovery[result.goal.goal_id] = (
                (
                    scope["information_need_id"],
                    scope["protocol"],
                    scope["summary"],
                    tuple(scope.get("result_address_filters") or ()),
                    scope["all_local_interfaces"],
                ),
                turn.turn_id,
            )
        # Offering candidate options is separate from the later NEW owner
        # choice; no option token can be invented by a model invocation.
        for key in tuple(self._offered_device_options):
            if result.goal is not None and key[0] == result.goal.goal_id:
                self._offered_device_options.pop(key, None)
        for options in payload.get("device_choice_sets", ()):
            self._offered_device_options[
                (payload["goal_id"], options["information_need_id"])
            ] = (options["digest"], turn.turn_id)
        payload["canonical_user_turn_id"] = turn.turn_id
        return payload

    @function_tool()
    async def authorize_bounded_network_discovery(
        self,
        context: RunContext,
        goal_id: str,
    ) -> dict[str, object]:
        """Ask for one exact, owner-confirmed local-device discovery.

        This action is ONLY for a fresh accepted USER turn explicitly approving
        network discovery (for example, "approve the network discovery").
        Never infer permission from the original goal, generic "yes", or an
        older approval. Windows Hello and canonical AuthorityService must
        independently approve the full current scope before any scan begins.
        Unverified sightings are NOT paired or accepted as physical identity.
        """
        del context
        turn = self._latest_user_turn()
        # Deliberately recognize an affirmative, *whole utterance*, not
        # keywords embedded in a refusal, quote, question or conditional.
        # Windows Hello is still required independently after this check.
        spoken = turn.text.casefold().strip()
        explicit_scope_consent = re.fullmatch(
            r"(?:jarvis[,\s:]+)?(?:yes[,\s]+)?(?:i\s+)?"
            r"(?:explicitly\s+)?(?:approve|authorize|allow|permit)\s+"
            r"(?:the\s+|this\s+)?"
            r"(?:(?:bounded|local|one[- ]time)\s+)*"
            r"network\s+(?:device\s+)?(?:discovery|scan|scanning)"
            r"(?:\s+now)?[.!]?",
            spoken,
        )
        if explicit_scope_consent is None:
            return {
                "ok": False,
                "status": "explicit_discovery_permission_not_given",
                "truth_note": (
                    "The owner's latest accepted turn did not explicitly approve "
                    "network discovery. Do not initiate a scan or treat generic "
                    "acknowledgment as permission."
                ),
            }
        goal = self._store.get_goal(str(goal_id).strip())
        if (
            goal is None
            or goal.state is not GoalState.WAITING_INFORMATION
            or goal.source_session_id != self._conversation.session_id
        ):
            return {
                "ok": False,
                "status": "discovery_goal_not_current_or_not_waiting",
            }
        runtime = self._execution_runtime
        execute = (
            None
            if runtime is None
            else getattr(runtime, "authorize_and_discover_network", None)
        )
        if not callable(execute):
            return {"ok": False, "status": "governed_discovery_unavailable"}
        offered = self._offered_network_discovery.get(goal.goal_id)
        if offered is None or offered[1] == turn.turn_id:
            return {
                "ok": False,
                "status": "discovery_scope_not_previously_offered",
            }
        prepare = getattr(runtime, "prepare_network_discovery_consent", None)
        if not callable(prepare):
            return {"ok": False, "status": "governed_discovery_scope_unavailable"}
        try:
            current_proposal = prepare(
                goal_id=goal.goal_id,
                session_id=goal.source_session_id,
            )
            if (
                current_proposal is None
                or not current_proposal.has_valid_fingerprint()
                or current_proposal.is_expired()
                or current_proposal.session_id != goal.source_session_id
                or current_proposal.capability != "network_discovery"
                or current_proposal.operation != "enumerate_aep"
            ):
                return {
                    "ok": False,
                    "status": "discovery_scope_changed_reoffer_required",
                }
            current_target = current_proposal.target()
            current_material = (
                current_target.get("gicc_need_id"),
                current_target.get("protocol"),
                current_proposal.material_summary,
                tuple(current_target.get("address_result_filters") or ()),
                current_target.get("all_local_interfaces"),
            )
            if (
                current_target.get("gicc_goal_id") != goal.goal_id
                or current_material != offered[0]
            ):
                return {
                    "ok": False,
                    "status": "discovery_scope_changed_reoffer_required",
                }
        except Exception:
            LOGGER.warning("GICC could not revalidate owner scan scope", exc_info=True)
            return {"ok": False, "status": "discovery_scope_changed_reoffer_required"}
        # Scope confirmation is a one-time voice decision, not a reusable
        # credential. Even cancellation requires another explicit fresh offer.
        self._offered_network_discovery.pop(goal.goal_id, None)
        try:
            # Windows Hello may block. Never run it on the audio event loop.
            result = await asyncio.to_thread(
                execute,
                goal_id=goal.goal_id,
                session_id=goal.source_session_id,
                owner_turn_id=turn.turn_id,
                expected_scope_material=offered[0],
            )
        except Exception:
            LOGGER.warning(
                "GICC owner discovery authorization or execution denied",
                exc_info=True,
            )
            return {
                "ok": False,
                "status": "discovery_not_authorized_or_unavailable",
                "truth_note": (
                    "No verified device control or successful discovery is "
                    "established. Never claim that authorization was granted."
                ),
            }
        if result is None:
            return {
                "ok": False,
                "status": "discovery_scope_changed_or_unavailable",
                "truth_note": "No device scan or control is verified.",
            }
        payload: dict[str, object] = {
            "ok": True,
            "status": "authorized_discovery_observation_recorded",
            "goal_id": goal.goal_id,
            "information_need_id": result.need.information_need_id,
            "information_need_state": result.need.state.value,
            "verified_device_control": False,
            "truth_note": (
                "The governed observation returned. Unverified device "
                "advertisements do not prove identity, pairing, access or "
                "TV control. Await corroborated registry confirmation before "
                "restarting the same original goal."
            ),
        }
        hints = getattr(runtime, "pending_network_device_suggestions", None)
        if callable(hints):
            candidates = hints(
                goal_id=goal.goal_id,
                session_id=goal.source_session_id,
            )
            eligible = tuple(
                item
                for item in candidates
                if getattr(item, "evidence_ref", None) in result.need.evidence_refs
                and (
                    "windows_aep_authorized_scope_consumed:"
                    + str(getattr(item, "protocol", ""))
                )
                in result.need.evidence_refs
            )
            payload["unverified_device_hints"] = [
                {
                    "display_hint": item.display_hint,
                    "address": item.address,
                    "protocol_observed": item.protocol,
                    "verified_identity": False,
                }
                for item in eligible
            ]
            if eligible:
                offer_digest = _device_choice_digest(eligible)
                self._offered_device_options[
                    (goal.goal_id, result.need.information_need_id)
                ] = (offer_digest, turn.turn_id)
                payload["device_choice_set"] = {
                    "information_need_id": result.need.information_need_id,
                    "digest": offer_digest,
                    "options": [
                        {
                            "option": index,
                            "display_hint": item.display_hint,
                            "evidence_ref": item.evidence_ref,
                            "verified_identity": False,
                        }
                        for index, item in enumerate(eligible, start=1)
                    ],
                }
        # If this strictly one-time observation produced no fresh device
        # suggestion, provide the NEXT bounded scope to the owner instead of
        # looping the exhausted protocol or asking for a manual IP. This is
        # read-only disclosure, NEVER an automatic second scan/approval.
        if not payload.get("unverified_device_hints"):
            prepare = getattr(runtime, "prepare_network_discovery_consent", None)
            if callable(prepare):
                try:
                    proposal = prepare(
                        goal_id=goal.goal_id,
                        session_id=goal.source_session_id,
                    )
                except Exception:
                    LOGGER.warning(
                        "GICC could not prepare follow-up discovery scope",
                        exc_info=True,
                    )
                else:
                    if (
                        proposal is not None
                        and proposal.has_valid_fingerprint()
                        and not proposal.is_expired()
                        and proposal.session_id == goal.source_session_id
                        and proposal.capability == "network_discovery"
                        and proposal.operation == "enumerate_aep"
                    ):
                        next_target = proposal.target()
                        if (
                            next_target.get("gicc_goal_id") == goal.goal_id
                            and next_target.get("gicc_need_id")
                            == result.need.information_need_id
                        ):
                            self._offered_network_discovery[goal.goal_id] = (
                                (
                                    result.need.information_need_id,
                                    next_target.get("protocol"),
                                    proposal.material_summary,
                                    tuple(
                                        next_target.get("address_result_filters") or ()
                                    ),
                                    next_target.get("all_local_interfaces"),
                                ),
                                turn.turn_id,
                            )
                            payload["next_network_discovery"] = {
                                "state": "proposal_only_not_authorized",
                                "summary": proposal.material_summary,
                                "protocol": next_target.get("protocol"),
                                "information_need_id": result.need.information_need_id,
                                "result_address_filters": next_target.get(
                                    "address_result_filters"
                                ),
                                "all_local_interfaces": next_target.get(
                                    "all_local_interfaces"
                                ),
                                "owner_approval_required": True,
                                "scan_started": False,
                            }
        return payload

    @function_tool()
    async def confirm_discovered_device_identity(
        self,
        context: RunContext,
        goal_id: str,
        information_need_id: str,
        selected_evidence_ref: str = "",
        displayed_choice_set_digest: str = "",
    ) -> dict[str, object]:
        """Confirm one recent discovered TV/camera as owner inventory.

        Use ONLY after a fresh distinct USER turn explicitly confirming the
        one displayed device is theirs. Mere "yes" cannot identify a device.
        No scanner, new approval, pairing, endpoint binding or control action
        is authorized. Multiple/conflicting/expired hints fail closed.
        """
        del context
        turn = self._latest_user_turn()
        consent = re.fullmatch(
            r"(?:i\s+)?confirm\s+(?:that\s+)?(?:the|this)\s+"
            r"(?:discovered|detected)\s+(?P<kind>tv|television|camera)\s+"
            r"(?:option\s+(?P<option>[1-8])\s+)?"
            r"(?:is\s+mine|belongs\s+to\s+me|is\s+my\s+"
            r"(?P<kind_suffix>tv|television|camera))[.!]?",
            turn.text.casefold().strip(),
        )
        if consent is None:
            return {
                "ok": False,
                "status": "explicit_device_identity_confirmation_not_given",
            }
        goal = self._store.get_goal(str(goal_id).strip())
        if (
            goal is None
            or goal.state is not GoalState.WAITING_INFORMATION
            or goal.source_session_id != self._conversation.session_id
        ):
            return {"ok": False, "status": "device_confirmation_goal_not_current"}
        need = self._store.get_information_need(str(information_need_id).strip())
        expected_kind = (
            None
            if need is None or need.goal_id != goal.goal_id
            else canonical_world_entity_type(need.answer_schema.get("entity_type"))
        )
        spoken_kind = canonical_world_entity_type(consent.group("kind"))
        tail_kind = consent.group("kind_suffix")
        if (
            expected_kind not in {"media_player", "camera"}
            or spoken_kind != expected_kind
            or (
                tail_kind is not None
                and canonical_world_entity_type(tail_kind) != expected_kind
            )
        ):
            return {
                "ok": False,
                "status": "owner_device_confirmation_type_mismatch",
            }
        runtime = self._execution_runtime
        confirm = (
            None
            if runtime is None
            else getattr(runtime, "confirm_owner_discovered_device", None)
        )
        if not callable(confirm):
            return {"ok": False, "status": "owner_device_confirmation_unavailable"}
        selected: dict[str, object] = {}
        option = consent.group("option")
        if option is not None:
            hints_method = getattr(runtime, "pending_network_device_suggestions", None)
            if not callable(hints_method):
                return {"ok": False, "status": "owner_device_choice_is_not_current"}
            try:
                hints = hints_method(
                    goal_id=goal.goal_id,
                    session_id=goal.source_session_id,
                )
            except Exception:
                LOGGER.warning(
                    "GICC could not verify owner device options", exc_info=True
                )
                return {"ok": False, "status": "owner_device_choice_is_not_current"}
            candidates = tuple(
                hint
                for hint in hints
                if getattr(hint, "evidence_ref", None) in need.evidence_refs
                and (
                    "windows_aep_authorized_scope_consumed:"
                    + str(getattr(hint, "protocol", ""))
                )
                in need.evidence_refs
            )
            option_index = int(option) - 1
            offered = self._offered_device_options.get(
                (goal.goal_id, need.information_need_id)
            )
            if (
                option_index >= len(candidates)
                or len(candidates) < 2
                or offered is None
                or offered[0] != displayed_choice_set_digest
                or offered[1] == turn.turn_id
                or displayed_choice_set_digest != _device_choice_digest(candidates)
                or selected_evidence_ref != candidates[option_index].evidence_ref
            ):
                return {"ok": False, "status": "owner_device_choice_is_not_current"}
            selected["selected_evidence_ref"] = selected_evidence_ref
        elif selected_evidence_ref or displayed_choice_set_digest:
            # A model may not select a device that the owner did not name.
            return {"ok": False, "status": "explicit_device_option_not_given"}
        else:
            # A single device also has to be visibly offered *before* the
            # owner speaks. An agent must not turn a generic "this TV is mine"
            # into confirmation of an unseen network advertisement.
            offered = self._offered_device_options.get(
                (goal.goal_id, need.information_need_id)
            )
            hints_method = getattr(runtime, "pending_network_device_suggestions", None)
            if not callable(hints_method) or offered is None:
                return {"ok": False, "status": "owner_device_not_previously_offered"}
            try:
                hints = hints_method(
                    goal_id=goal.goal_id,
                    session_id=goal.source_session_id,
                )
            except Exception:
                LOGGER.warning(
                    "GICC could not revalidate displayed device", exc_info=True
                )
                return {"ok": False, "status": "owner_device_choice_is_not_current"}
            candidates = tuple(
                hint
                for hint in hints
                if getattr(hint, "evidence_ref", None) in need.evidence_refs
                and (
                    "windows_aep_authorized_scope_consumed:"
                    + str(getattr(hint, "protocol", ""))
                )
                in need.evidence_refs
            )
            if (
                len(candidates) != 1
                or offered[0] != _device_choice_digest(candidates)
                or offered[1] == turn.turn_id
            ):
                return {"ok": False, "status": "owner_device_choice_is_not_current"}
        try:
            entity = confirm(
                goal_id=goal.goal_id,
                information_need_id=str(information_need_id).strip(),
                session_id=goal.source_session_id,
                owner_turn_id=turn.turn_id,
                **selected,
            )
        except Exception:
            LOGGER.warning(
                "Canonical device identity confirmation failed", exc_info=True
            )
            return {"ok": False, "status": "device_identity_confirmation_failed"}
        if entity is None:
            return {
                "ok": False,
                "status": "no_unique_recent_confirmable_device",
                "truth_note": (
                    "No single fresh device hint could be independently owner "
                    "confirmed. Do not register an identity, guess an IP or "
                    "claim connectivity."
                ),
            }
        self._offered_device_options.pop(
            (goal.goal_id, str(information_need_id).strip()), None
        )
        try:
            continued = await runtime.continue_goal(
                goal.goal_id, retry_information=True
            )
        except Exception as exc:  # noqa: BLE001 - voice boundary must remain truthful
            return self._internal_failure(
                turn=turn, stage="resume_owner_confirmed_device_goal", error=exc
            )
        payload = self._public_result(continued)
        payload.update(
            {
                "confirmed_entity_id": entity.entity_id,
                "owner_inventory_only": True,
                "network_access_verified": False,
                "device_control_verified": False,
                "canonical_user_turn_id": turn.turn_id,
            }
        )
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


def build_session_scoped_gicc_tools(
    coordinator: GoalIntelligenceCoordinator,
    store: GoalStore,
    *,
    execution_runtime: GiccExecutionRuntime | None = None,
    objective_status: OwnerObjectiveStatusResolver | None = None,
    telemetry: GiccTelemetrySink = DEFAULT_GICC_TELEMETRY,
) -> Callable[[ConversationSession], GiccAgentTools]:
    """Reuse consent/choice offers across tool-list refreshes of one conversation.

    Production may enumerate action/read tools on every speech turn. Creating
    a new GiccAgentTools each time would lose the prior scoped consent offer
    and the exact displayed device-choice set. A different conversation gets
    a clean instance and cannot inherit the previous owner's offers.
    """
    current_session: ConversationSession | None = None
    current_tools: GiccAgentTools | None = None

    def get(conversation: ConversationSession) -> GiccAgentTools:
        nonlocal current_session, current_tools
        if current_session is conversation and current_tools is not None:
            return current_tools
        current_tools = GiccAgentTools(
            coordinator,
            conversation,
            store,
            execution_runtime=execution_runtime,
            objective_status=objective_status,
            telemetry=telemetry,
        )
        current_session = conversation
        return current_tools

    return get
