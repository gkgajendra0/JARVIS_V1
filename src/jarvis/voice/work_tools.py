"""Voice-facing control surface for persistent background JARVIS work."""

from __future__ import annotations

from livekit.agents import RunContext, function_tool

from jarvis.conversation import ConversationRole, ConversationSession, ConversationTurn
from jarvis.work.estimates import estimate_work, owner_work_status_summary
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
        "progress_summary": estimate.progress_summary,
        "remaining_summary": estimate.remaining_summary,
        "blocked_reason": estimate.blocked_reason,
        "eta_low_seconds": estimate.eta_low_seconds,
        "eta_high_seconds": estimate.eta_high_seconds,
        "eta_confidence": estimate.eta_confidence,
        "eta_reason": estimate.eta_reason,
        "estimate_updated_at": estimate.estimate_updated_at,
        "owner_status_summary": owner_work_status_summary(
            item,
            estimate,
            completion_notification_expected=completion_notification_expected,
        ),
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
        range/confidence rather than inventing an exact completion time. For progress or
        status questions, owner_status_summary is the canonical owner-facing wording: keep
        its blocker, remaining-work description, ETA confidence, and completion-notification
        promise rather than weakening them into generic language.
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

        Treat progress_percent as approximate unless the task is terminal. For a progress
        or status answer, use owner_status_summary as canonical owner-facing content. Do not
        replace a specific blocked_reason with generic "resources", omit the remaining work,
        drop ETA confidence, or invent a different completion time.
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
