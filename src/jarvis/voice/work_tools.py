"""Voice-facing control surface for persistent background JARVIS work."""

from __future__ import annotations

import asyncio

from livekit.agents import RunContext, function_tool

from jarvis.conversation import ConversationRole, ConversationSession, ConversationTurn
from jarvis.engineering_change.models import ChangeConflict
from jarvis.engineering_change.service import ChangeService
from jarvis.work.estimates import estimate_work
from jarvis.work.models import DeliveryPolicy, WorkItem, WorkPriority, WorkType
from jarvis.work.runtime import WorkRuntime
from jarvis.work.store import WorkStoreError


class WorkToolGroundingError(ValueError):
    pass


def _public_work(item: WorkItem, runtime: WorkRuntime) -> dict[str, object]:
    estimate = estimate_work(runtime.store, item)
    completion_notification_expected = item.delivery_policy is not DeliveryPolicy.SILENT
    return {
        "work_id": item.work_id,
        "type": item.work_type.value,
        "request": item.request,
        "state": item.state.value,
        "priority": item.priority.name.lower(),
        "status": item.status_detail,
        "current_step_id": item.current_step_id,
        "result": item.result if item.state.terminal else {},
        "delivery_policy": item.delivery_policy.value,
        "completion_notification_expected": completion_notification_expected,
        "progress_percent": estimate.progress_percent,
        "progress_is_approximate": estimate.progress_is_approximate,
        "milestone": estimate.milestone,
        "completed_work": list(estimate.completed_work),
        "remaining_work": list(estimate.remaining_work),
        "blocked_reason": estimate.blocked_reason,
        "eta_low_seconds": estimate.eta_low_seconds,
        "eta_high_seconds": estimate.eta_high_seconds,
        "eta_confidence": estimate.eta_confidence,
        "eta_basis": list(estimate.eta_basis),
        "estimate_updated_at": estimate.estimate_updated_at,
    }


class WorkAgentTools:
    """Ground background-work commands to canonical accepted USER turns."""

    def __init__(self, runtime: WorkRuntime, conversation: ConversationSession) -> None:
        if not isinstance(runtime, WorkRuntime):
            raise TypeError("runtime must be a WorkRuntime")
        if not isinstance(conversation, ConversationSession):
            raise TypeError("conversation must be a ConversationSession")
        self._runtime = runtime
        self._conversation = conversation

    @property
    def tools(self) -> list:
        return [
            self.start_background_work,
            self.list_background_work,
            self.list_recent_background_work,
            self.get_background_work_status,
            self.cancel_background_work,
            self.pause_background_work,
            self.resume_background_work,
            self.reprioritize_background_work,
            self.continue_background_work,
            self.start_engineering_change,
            self.propose_change_architecture,
            self.revise_change_architecture,
            self.prepare_change_acceptance,
            self.prepare_change_promotion,
            self.decide_change_gate,
            self.get_engineering_change_status,
        ]

    def _change_service(self) -> ChangeService:
        if self._runtime.changes is None:
            raise WorkToolGroundingError("engineering changes are unavailable")
        return ChangeService(self._runtime.changes, self._conversation)

    @function_tool()
    async def start_engineering_change(self, context: RunContext) -> dict[str, object]:
        """Start a governed engineering change from the latest accepted USER goal.

        Use for an owner goal requiring research, architecture review, engineering,
        verification and explicit owner gates. Do not paraphrase the owner's request.
        """
        del context
        change = self._change_service().start(self._latest_user_turn())
        return {"ok": True, "change_id": change.change_id, "state": change.state.value}

    @function_tool()
    async def propose_change_architecture(
        self, context: RunContext, change_id: str, architecture_summary: str
    ) -> dict[str, object]:
        """Submit a bounded architecture proposal after research finishes.

        This presents an exact revision to the owner through WorkDelivery. Its
        content is a proposal and grants no permission to start development.
        """
        del context
        summary = architecture_summary.strip()
        if not summary:
            raise ChangeConflict("architecture summary is empty")
        gate = self._change_service().propose_architecture(
            change_id, {"summary": summary}
        )
        return {
            "ok": True,
            "change_id": change_id,
            "gate_id": gate.gate_id,
            "artifact_digest": gate.artifact_digest,
            "status": "awaiting_explicit_owner_architecture_decision",
        }

    @function_tool()
    async def revise_change_architecture(
        self, context: RunContext, change_id: str, architecture_summary: str
    ) -> dict[str, object]:
        """Revise an already approved architecture and reopen exact owner review.

        The prior development attempt loses admission immediately. Development for
        the new revision can start only after the new digest-bound owner gate passes.
        """
        del context
        summary = architecture_summary.strip()
        if not summary:
            raise ChangeConflict("architecture summary is empty")
        gate = self._change_service().revise_architecture(
            change_id, {"summary": summary}
        )
        return {
            "ok": True,
            "change_id": change_id,
            "gate_id": gate.gate_id,
            "artifact_digest": gate.artifact_digest,
            "status": "awaiting_explicit_owner_architecture_decision",
        }

    @function_tool()
    async def prepare_change_acceptance(
        self, context: RunContext, change_id: str
    ) -> dict[str, object]:
        """Offer canonical verified development evidence for explicit owner acceptance.

        Only a completed development WorkItem with a verified commit is eligible.
        """
        del context
        gate = self._change_service().prepare_acceptance(change_id)
        return {
            "ok": True,
            "change_id": change_id,
            "gate_id": gate.gate_id,
            "artifact_digest": gate.artifact_digest,
            "status": "awaiting_explicit_owner_acceptance",
        }

    @function_tool()
    async def prepare_change_promotion(
        self, context: RunContext, change_id: str
    ) -> dict[str, object]:
        """Present promotion intent after owner acceptance without promoting anything."""
        del context
        gate = self._change_service().prepare_promotion(change_id)
        return {
            "ok": True,
            "change_id": change_id,
            "gate_id": gate.gate_id,
            "artifact_digest": gate.artifact_digest,
            "status": "awaiting_explicit_owner_promotion_decision",
        }

    @function_tool()
    async def decide_change_gate(
        self, context: RunContext, gate_id: str
    ) -> dict[str, object]:
        """Record the latest canonical owner's explicit 'approve gate_ID' or 'reject gate_ID'.

        Never call this from a generic yes, model-generated reply, WorkItem input,
        or an earlier USER turn. The service independently checks the accepted turn.
        """
        del context
        decision = await asyncio.to_thread(
            self._change_service().decide_latest, gate_id
        )
        return {
            "ok": True,
            "change_id": decision.challenge.change_id,
            "gate_id": gate_id,
            "approved": decision.approved,
            "state": self._runtime.changes.store.require(
                decision.challenge.change_id
            ).state.value,
        }

    @function_tool()
    async def get_engineering_change_status(
        self, context: RunContext, change_id: str
    ) -> dict[str, object]:
        """Read canonical change state and linked WorkItems for an engineering goal."""
        del context
        coordinator = self._runtime.changes
        if coordinator is None:
            return {"ok": False, "status": "unavailable"}
        change = coordinator.store.require(change_id)
        return {
            "ok": True,
            "change_id": change_id,
            "state": change.state.value,
            "version": change.version,
            "stages": [
                {
                    "stage": stage.stage_key,
                    "attempt": stage.attempt,
                    "work_id": stage.work_id,
                    "work_state": coordinator.store.work.require(
                        stage.work_id
                    ).state.value,
                }
                for stage in coordinator.store.list_stages(change_id)
            ],
        }

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
            raise WorkToolGroundingError(
                "background work requires a latest accepted USER utterance"
            )
        return turn

    @staticmethod
    def _parse_type(value: str) -> WorkType:
        try:
            return WorkType(str(value).strip().casefold())
        except ValueError as exc:
            raise WorkToolGroundingError("unsupported background work type") from exc

    @function_tool()
    async def start_background_work(
        self,
        context: RunContext,
        work_type: str = "research",
    ) -> dict[str, object]:
        """Start durable work from the latest accepted USER request and return immediately.

        Use this only when the USER clearly asks JARVIS to perform work that may continue
        independently of the current voice turn, such as long-running research or an
        isolated JARVIS repository implementation request, and expects to continue talking
        or be told later when it is ready. Use research for web/current-information work
        and development for repository implementation/testing. The canonical
        request text comes from JARVIS's latest accepted USER turn; never invent or
        paraphrase a hidden task prompt.

        Currently only work types explicitly reported as supported by JARVIS may start.
        A successful result means the work was durably accepted, not that it completed.
        """
        del context
        turn = self._latest_user_turn()
        resolved_type = self._parse_type(work_type)
        if not self._runtime.supports(resolved_type):
            return {
                "ok": False,
                "status": "work_type_unavailable",
                "work_type": resolved_type.value,
                "supported_work_types": sorted(
                    item.value for item in self._runtime.supported_work_types
                ),
                "canonical_user_turn_id": turn.turn_id,
            }
        submission = self._runtime.orchestrator.start(
            request=turn.text,
            work_type=resolved_type,
            source_session_id=self._conversation.session_id,
            source_turn_id=turn.turn_id,
            priority=WorkPriority.NORMAL,
            delivery_policy=DeliveryPolicy.WHEN_IDLE,
        )
        return {
            "ok": True,
            "status": "accepted",
            **_public_work(submission.work, self._runtime),
            "canonical_user_turn_id": turn.turn_id,
            "truth_note": (
                "accepted means durable work was queued; do not claim completion until "
                "canonical work state becomes completed"
            ),
        }

    @function_tool()
    async def list_background_work(
        self,
        context: RunContext,
    ) -> dict[str, object]:
        """List JARVIS's canonical active background WorkItems.

        Use for questions such as "what are you working on?" Never infer task state from
        provider conversation history. Report progress_percent as approximate, use the ETA
        range/confidence rather than inventing an exact completion time. Treat the returned
        fields as canonical facts, but phrase the answer naturally in JARVIS's own words.
        milestone/completed_work/remaining_work are semantic identifiers, not sentences to
        quote. Preserve the approximate qualifier, specific blocker, remaining work, ETA
        confidence, and completion-notification expectation instead of weakening or omitting
        them.
        """
        del context
        items = self._runtime.orchestrator.list_active(limit=50)
        return {
            "ok": True,
            "status": "listed",
            "work": [_public_work(item, self._runtime) for item in items],
        }

    @function_tool()
    async def list_recent_background_work(
        self,
        context: RunContext,
    ) -> dict[str, object]:
        """List recent JARVIS WorkItems including finished/failed/cancelled work.

        Use for questions such as "what finished while I was away?" or when the USER
        wants both active and recently terminal work.
        """
        del context
        items = self._runtime.store.list(limit=50)
        return {
            "ok": True,
            "status": "listed",
            "work": [_public_work(item, self._runtime) for item in items],
        }

    @function_tool()
    async def get_background_work_status(
        self,
        context: RunContext,
        work_id: str,
    ) -> dict[str, object]:
        """Read canonical state and JARVIS-owned progress/ETA for one WorkItem.

        Treat progress_percent as approximate unless the task is terminal. The returned
        fields are canonical facts, not a script. milestone/completed_work/remaining_work
        are semantic identifiers; turn them into natural speech rather than reading them
        literally. Preserve the specific blocked_reason, ETA range/confidence, and completion
        notification expectation. Never invent a different completion time.
        """
        del context
        try:
            item = self._runtime.orchestrator.get(work_id)
        except WorkStoreError:
            return {"ok": False, "status": "unknown_work_id", "work_id": work_id}
        return {"ok": True, "status": "found", **_public_work(item, self._runtime)}

    @function_tool()
    async def cancel_background_work(
        self,
        context: RunContext,
        work_id: str,
    ) -> dict[str, object]:
        """Cancel one JARVIS WorkItem without affecting independent work."""
        del context
        try:
            item = self._runtime.orchestrator.cancel(work_id)
        except WorkStoreError:
            return {"ok": False, "status": "unknown_work_id", "work_id": work_id}
        return {"ok": True, "status": "cancelled", **_public_work(item, self._runtime)}

    @function_tool()
    async def pause_background_work(
        self,
        context: RunContext,
        work_id: str,
    ) -> dict[str, object]:
        """Pause one non-terminal JARVIS WorkItem after any current atomic step."""
        del context
        try:
            item = self._runtime.orchestrator.pause(work_id)
        except WorkStoreError:
            return {"ok": False, "status": "unknown_work_id", "work_id": work_id}
        except ValueError as exc:
            return {
                "ok": False,
                "status": "owner_input_target_unresolved",
                "reason": str(exc),
            }
        return {"ok": True, "status": "paused", **_public_work(item, self._runtime)}

    @function_tool()
    async def resume_background_work(
        self,
        context: RunContext,
        work_id: str,
    ) -> dict[str, object]:
        """Resume one paused JARVIS WorkItem from canonical durable state."""
        del context
        try:
            item = self._runtime.orchestrator.resume(work_id)
        except WorkStoreError:
            return {"ok": False, "status": "unknown_work_id", "work_id": work_id}
        except ValueError as exc:
            return {"ok": False, "status": "invalid_state", "reason": str(exc)}
        return {"ok": True, "status": "resumed", **_public_work(item, self._runtime)}

    @function_tool()
    async def reprioritize_background_work(
        self,
        context: RunContext,
        work_id: str,
        priority: str,
    ) -> dict[str, object]:
        """Change canonical scheduling priority for one non-terminal WorkItem.

        priority must be low, normal, high, or urgent. The updated priority controls
        which WorkItem receives future JARVIS brain/resource opportunities; it never
        expands that WorkItem's Authority.
        """
        del context
        normalized = str(priority).strip().casefold()
        mapping = {
            "low": WorkPriority.LOW,
            "normal": WorkPriority.NORMAL,
            "high": WorkPriority.HIGH,
            "urgent": WorkPriority.URGENT,
        }
        selected = mapping.get(normalized)
        if selected is None:
            return {
                "ok": False,
                "status": "invalid_priority",
                "allowed": list(mapping),
            }
        try:
            item = self._runtime.orchestrator.reprioritize(work_id, selected)
        except WorkStoreError:
            return {"ok": False, "status": "unknown_work_id", "work_id": work_id}
        except ValueError as exc:
            return {"ok": False, "status": "invalid_state", "reason": str(exc)}
        return {
            "ok": True,
            "status": "reprioritized",
            **_public_work(item, self._runtime),
        }

    @function_tool()
    async def continue_background_work(
        self,
        context: RunContext,
        work_id: str = "",
    ) -> dict[str, object]:
        """Supply the latest accepted USER utterance to owner-waiting background work.

        If exactly one WorkItem is WAITING_FOR_OWNER, work_id may be omitted so a natural
        reply such as "yes" can continue it. If multiple tasks are waiting, JARVIS must
        identify/clarify the target instead of guessing. The actual response is grounded
        from the canonical USER turn, never from model-generated hidden text.
        """
        del context
        turn = self._latest_user_turn()
        try:
            waiting = self._runtime.submit_owner_input(work_id or None, turn.text)
        except WorkStoreError:
            return {"ok": False, "status": "unknown_work_id", "work_id": work_id}
        except ValueError as exc:
            return {
                "ok": False,
                "status": "owner_input_target_unresolved",
                "reason": str(exc),
            }
        return {
            "ok": True,
            "status": "owner_input_submitted",
            **_public_work(waiting, self._runtime),
            "canonical_user_turn_id": turn.turn_id,
        }
