"""Voice-facing control surface for persistent background JARVIS work."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from livekit.agents import RunContext, function_tool

from jarvis.capability_acquisition.models import OwnerCapabilityGoalV1
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

    def __init__(
        self,
        runtime: WorkRuntime,
        conversation: ConversationSession,
        *,
        bound_owner_input_work_id: str | None = None,
        on_bound_owner_input_submitted: Callable[[WorkItem], None] | None = None,
    ) -> None:
        if not isinstance(runtime, WorkRuntime):
            raise TypeError("runtime must be a WorkRuntime")
        if not isinstance(conversation, ConversationSession):
            raise TypeError("conversation must be a ConversationSession")
        normalized_bound_work_id = str(bound_owner_input_work_id or "").strip() or None
        self._runtime = runtime
        self._conversation = conversation
        self._bound_owner_input_work_id = normalized_bound_work_id
        self._on_bound_owner_input_submitted = on_bound_owner_input_submitted

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
            self.retry_failed_background_work,
            self.set_background_work_update_interval,
            self.start_capability_acquisition,
            self.activate_acquired_capability,
            self.disable_acquired_capability,
            self.start_engineering_change,
            self.propose_change_architecture,
            self.revise_change_architecture,
            self.prepare_change_acceptance,
            self.prepare_change_promotion,
            self.execute_change_promotion,
            self.decide_change_gate,
            self.get_engineering_change_status,
        ]

    @function_tool()
    async def retry_failed_background_work(
        self,
        context: RunContext,
        work_id: str = "",
    ) -> dict[str, object]:
        """Retry failed durable work without creating a new semantic task.

        Use when the latest accepted USER turn clearly refers back to failed work with
        language such as "try that again", "retry it", or "continue from the failure".
        If a prior canonical status lookup established one owner-focused WorkItem,
        that focus survives wake-session boundaries and is authoritative for deictic
        requests such as "retry that" or "same task". In that case omit work_id; a
        conflicting model-supplied ID fails closed. If no focus exists and exactly one
        failed WorkItem exists, work_id may be omitted. JARVIS preserves the original
        canonical request, EngineeringChange linkage, steps and evidence, while recording
        the latest USER retry instruction as new durable evidence.
        """
        del context
        turn = self._latest_user_turn()
        requested_work_id = str(work_id or "").strip()
        focused_work_id = self._runtime.owner_work_focus_id
        if (
            focused_work_id is not None
            and requested_work_id
            and requested_work_id != focused_work_id
        ):
            return {
                "ok": False,
                "status": "work_reference_target_mismatch",
                "work_id": requested_work_id,
                "focused_work_id": focused_work_id,
                "reason": (
                    "the requested retry target conflicts with the canonical task "
                    "most recently surfaced to the owner"
                ),
            }
        target_work_id = focused_work_id or requested_work_id or None
        try:
            item = self._runtime.retry_failed_work(
                target_work_id,
                owner_request=turn.text,
                source_session_id=self._conversation.session_id,
                source_turn_id=turn.turn_id,
            )
        except WorkStoreError:
            return {"ok": False, "status": "unknown_work_id", "work_id": work_id}
        except ValueError as exc:
            return {
                "ok": False,
                "status": "retry_target_unresolved",
                "reason": str(exc),
            }
        self._runtime.set_owner_work_focus(item.work_id)
        return {
            "ok": True,
            "status": "retrying",
            **_public_work(item, self._runtime),
            "canonical_user_turn_id": turn.turn_id,
            "truth_note": (
                "retry continues the same canonical work and preserved evidence; "
                "it does not create a new background goal"
            ),
        }

    @function_tool()
    async def set_background_work_update_interval(
        self,
        context: RunContext,
        interval_minutes: int,
        work_id: str = "",
    ) -> dict[str, object]:
        """Configure periodic owner-visible progress updates for active work.

        interval_minutes must be 1..1440. Use 0 to disable scheduled updates. If
        exactly one WorkItem is active, work_id may be omitted. Critical owner-input,
        blocker, failure and completion notifications remain independent of this timer.
        """
        del context
        try:
            item = self._runtime.configure_status_updates(
                work_id or None,
                interval_minutes=interval_minutes,
            )
        except WorkStoreError:
            return {"ok": False, "status": "unknown_work_id", "work_id": work_id}
        except ValueError as exc:
            return {
                "ok": False,
                "status": "update_target_unresolved",
                "reason": str(exc),
            }
        return {
            "ok": True,
            "status": "disabled" if interval_minutes == 0 else "scheduled",
            "work_id": item.work_id,
            "interval_minutes": interval_minutes,
            "state": item.state.value,
        }

    @function_tool()
    async def start_capability_acquisition(
        self,
        context: RunContext,
        requested_capability: str,
        required_operations: list[str],
        target_hints: list[str] | None = None,
    ) -> dict[str, object]:
        """Start governed Phase-9 acquisition from the latest accepted USER request.

        Use when the owner explicitly asks JARVIS to obtain a capability, or when
        the owner's requested external-device/service outcome requires a capability
        that is not currently available. The owner's exact latest request remains the
        canonical goal; outcome-driven acquisition only starts governed engineering
        work and grants no later Architecture, Authority, promotion, activation, or
        external-effect permission.

        requested_capability, required_operations and target_hints are structured
        interpretation fields, not Authority. target_hints must preserve explicit
        target/device/service/transport qualifiers and may carry a target uniquely
        grounded by the immediately preceding accepted conversation. Do not invent a
        target from model assumptions or collapse an external target into a
        superficially similar local operation. JARVIS binds the acquisition to its
        trusted current Git revision.
        """
        del context
        coordinator = self._runtime.capability_acquisition
        if coordinator is None:
            return {"ok": False, "status": "capability_acquisition_unavailable"}

        turn = self._latest_user_turn()
        goal = OwnerCapabilityGoalV1.create(
            request=turn.text,
            requested_capability=requested_capability,
            required_operations=required_operations,
            target_hints=target_hints or (),
            source_session_id=self._conversation.session_id,
            source_turn_id=turn.turn_id,
        )
        admission = coordinator.admit(
            goal,
            source_revision=self._runtime.current_source_revision(),
        )
        selected = admission.initial_resolution.selected_candidate
        result: dict[str, object] = {
            "ok": True,
            "status": admission.disposition.value,
            "goal_id": goal.goal_id,
            "goal_digest": goal.digest,
            "canonical_user_turn_id": turn.turn_id,
            "requested_capability": goal.requested_capability,
            "required_operations": list(goal.required_operations),
            "selected_candidate_id": (
                None if selected is None else selected.candidate_id
            ),
            "selected_strategy": (
                None if selected is None else selected.strategy.value
            ),
        }
        if admission.change is not None:
            result.update(
                {
                    "change_id": admission.change.change_id,
                    "change_state": admission.change.state.value,
                    "acquisition_work_id": admission.acquisition_work_id,
                    "truth_note": (
                        "accepted means durable Phase-9 acquisition work started; "
                        "it does not mean the capability is built or enabled"
                    ),
                }
            )
        elif admission.disposition.value == "existing_lifecycle":
            result["truth_note"] = (
                "an existing compatible package can be reused, but lifecycle "
                "Authority is still required before it becomes enabled"
            )
        else:
            result["truth_note"] = (
                "the requested capability is already effectively available; "
                "no engineering work was started"
            )
        return result

    @function_tool()
    async def activate_acquired_capability(
        self,
        context: RunContext,
        change_id: str,
    ) -> dict[str, object]:
        """Activate the exact admitted Phase-9 package from an explicit owner turn.

        Use only when the latest accepted USER turn explicitly asks to activate,
        enable or start using the acquired capability. Phase-8 lifecycle Authority
        independently authorizes and consumes the state-changing permit.
        """
        del context
        lifecycle = self._runtime.capability_lifecycle
        if lifecycle is None:
            return {"ok": False, "status": "capability_lifecycle_unavailable"}
        turn = self._latest_user_turn()
        result = await asyncio.to_thread(
            lifecycle.activate,
            change_id,
            authority_session_id=self._conversation.session_id,
            source_turn_id=turn.turn_id,
        )
        self._runtime.refresh_capability_catalog()
        acceptance = self._runtime.capability_external_acceptance
        acceptance_work = (
            None
            if acceptance is None
            else await asyncio.to_thread(
                acceptance.start,
                change_id,
                activation_artifact_id=result.artifact.artifact_id,
                authority_session_id=self._conversation.session_id,
                source_turn_id=turn.turn_id,
            )
        )
        return {
            "ok": True,
            "status": "enabled",
            "change_id": change_id,
            "capability_id": result.capability_id,
            "package_id": result.package_id,
            "package_version": result.package_version,
            "package_digest": result.package_digest,
            "lifecycle_artifact_id": result.artifact.artifact_id,
            "lifecycle_artifact_digest": result.artifact.digest,
            "external_acceptance_work_id": (
                None if acceptance_work is None else acceptance_work.work_id
            ),
            "external_acceptance_state": (
                None if acceptance_work is None else acceptance_work.state.value
            ),
            "canonical_user_turn_id": turn.turn_id,
        }

    @function_tool()
    async def disable_acquired_capability(
        self,
        context: RunContext,
        change_id: str,
    ) -> dict[str, object]:
        """Disable the exact admitted Phase-9 package from an explicit owner turn.

        Use for owner-requested disable/rollback safety. The operation reuses the
        Phase-8 lifecycle Authority path and cannot bypass package provenance,
        compatibility or durable registry generation checks.
        """
        del context
        lifecycle = self._runtime.capability_lifecycle
        if lifecycle is None:
            return {"ok": False, "status": "capability_lifecycle_unavailable"}
        turn = self._latest_user_turn()
        result = await asyncio.to_thread(
            lifecycle.disable,
            change_id,
            authority_session_id=self._conversation.session_id,
            source_turn_id=turn.turn_id,
        )
        self._runtime.refresh_capability_catalog()
        return {
            "ok": True,
            "status": "disabled",
            "change_id": change_id,
            "capability_id": result.capability_id,
            "package_id": result.package_id,
            "package_version": result.package_version,
            "package_digest": result.package_digest,
            "lifecycle_artifact_id": result.artifact.artifact_id,
            "lifecycle_artifact_digest": result.artifact.digest,
            "canonical_user_turn_id": turn.turn_id,
        }

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
        """Publish the exact verified candidate and prepare Phase-7 PR/CI evidence.

        Use after owner acceptance when the change is READY_FOR_PROMOTION. The
        latest canonical USER turn authorizes only the short-lived GitHub credential
        lease needed to publish/read the exact candidate. This tool never merges.
        If CI is still running, report that truthfully and retry this same operation
        later; PR/ref reconciliation is idempotent.
        """
        del context
        runtime = self._runtime.promotion_runtime
        if runtime is None:
            return {
                "ok": False,
                "status": "promotion_runtime_unavailable",
                "change_id": change_id,
            }
        review = await asyncio.to_thread(
            runtime.prepare_review,
            change_id,
            session=self._conversation,
        )
        return {
            "ok": True,
            "change_id": change_id,
            "attempt_id": review.attempt.attempt_id,
            "gate_id": review.gate.gate_id,
            "artifact_digest": review.artifact.digest,
            "evidence_digest": review.evidence.digest,
            "pr_number": review.evidence.pr_number,
            "candidate_head_sha": review.evidence.candidate_head_sha,
            "status": "awaiting_explicit_owner_promotion_decision",
        }

    @function_tool()
    async def execute_change_promotion(
        self,
        context: RunContext,
        gate_id: str,
    ) -> dict[str, object]:
        """Authorize and merge the exact current Phase-7 promotion gate.

        Use only after the latest canonical USER turn explicitly says
        "approve <gate_id>" or otherwise satisfies the existing exact Phase-7
        promotion decision grammar. GitHub credentials receive a fresh one-use
        SecretBroker lease and the merge still consumes one-shot Authority.
        """
        del context
        runtime = self._runtime.promotion_runtime
        if runtime is None:
            return {"ok": False, "status": "promotion_runtime_unavailable"}
        result = await asyncio.to_thread(
            runtime.authorize_and_merge,
            gate_id,
            session=self._conversation,
        )
        return {
            "ok": True,
            "status": "merged",
            "change_id": result.evidence.change_id,
            "gate_id": gate_id,
            "promotion_attempt_id": result.evidence.attempt_id,
            "evidence_digest": result.evidence.digest,
            "merge_sha": result.merge.merge_sha,
            "reconciled_after_external_merge": (
                result.merge.reconciled_after_external_merge
            ),
            "truth_note": (
                "merge is complete; the production supervisor owns exact-release "
                "deployment, observation and rollback"
            ),
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
        stages: list[dict[str, object]] = []
        for stage in coordinator.store.list_stages(change_id):
            item = coordinator.store.work.require(stage.work_id)
            estimate = estimate_work(coordinator.store.work, item)
            stages.append(
                {
                    "stage": stage.stage_key,
                    "attempt": stage.attempt,
                    "work_id": stage.work_id,
                    "work_state": item.state.value,
                    "progress_percent": estimate.progress_percent,
                    "progress_is_approximate": estimate.progress_is_approximate,
                    "eta_low_seconds": estimate.eta_low_seconds,
                    "eta_high_seconds": estimate.eta_high_seconds,
                    "eta_confidence": estimate.eta_confidence,
                }
            )
        return {
            "ok": True,
            "change_id": change_id,
            "state": change.state.value,
            "version": change.version,
            "progress_percent": None,
            "progress_is_approximate": True,
            "eta_low_seconds": None,
            "eta_high_seconds": None,
            "eta_confidence": "unknown",
            "eta_basis": [
                (
                    "EngineeringChange spans multiple WorkItems and owner gates; "
                    "no validated aggregate duration model is available."
                )
            ],
            "stages": stages,
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
        and development for repository implementation/testing. This generic background-work
        tool is not a fallback for a missing external-device/service capability: when the
        latest owner outcome requires unavailable control, use `start_capability_acquisition`
        instead of creating research work or asking the owner to perform the missing operation.
        The canonical request text comes from JARVIS's latest accepted USER turn; never invent
        or paraphrase a hidden task prompt.

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
        them. If no work is active, surface the most recent terminal WorkItem so a just-failed
        or just-completed background task is not incorrectly described as if no task existed.
        """
        del context
        items = self._runtime.orchestrator.list_active(limit=50)
        payload: dict[str, object] = {
            "ok": True,
            "status": "listed",
            "work": [_public_work(item, self._runtime) for item in items],
        }
        if len(items) == 1:
            self._runtime.set_owner_work_focus(items[0].work_id)
        elif items:
            self._runtime.set_owner_work_focus(None)
        else:
            recent = self._runtime.store.list_recent(limit=1)
            if recent and recent[0].state.terminal:
                self._runtime.set_owner_work_focus(recent[0].work_id)
                payload["recent_terminal_work"] = _public_work(
                    recent[0],
                    self._runtime,
                )
                payload["truth_note"] = (
                    "no work is currently active; report the recent terminal work "
                    "instead of saying no background task existed"
                )
            else:
                self._runtime.set_owner_work_focus(None)
        return payload

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
        items = self._runtime.store.list_recent(limit=50)
        if len(items) == 1:
            self._runtime.set_owner_work_focus(items[0].work_id)
        else:
            self._runtime.set_owner_work_focus(None)
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
        self._runtime.set_owner_work_focus(item.work_id)
        return {"ok": True, "status": "found", **_public_work(item, self._runtime)}

    @function_tool()
    async def cancel_background_work(
        self,
        context: RunContext,
        work_id: str = "",
    ) -> dict[str, object]:
        """Cancel one JARVIS WorkItem without affecting independent work.

        In an ordinary voice session, pass the exact work_id resolved from canonical
        Work state. In a proactive owner-input interaction, work_id may be omitted
        because the tool is already bound to one exact WAITING_FOR_OWNER WorkItem.
        A bound interaction cannot cancel a different WorkItem.
        """
        del context
        requested_work_id = str(work_id or "").strip()
        bound_work_id = self._bound_owner_input_work_id
        if (
            bound_work_id is not None
            and requested_work_id
            and requested_work_id != bound_work_id
        ):
            return {
                "ok": False,
                "status": "owner_input_target_mismatch",
                "work_id": requested_work_id,
                "bound_work_id": bound_work_id,
            }
        target_work_id = requested_work_id or bound_work_id
        if target_work_id is None:
            return {
                "ok": False,
                "status": "cancel_target_unresolved",
                "reason": "cancel requires an exact work_id outside bound owner input",
            }
        try:
            item = self._runtime.orchestrator.cancel(target_work_id)
        except WorkStoreError:
            return {
                "ok": False,
                "status": "unknown_work_id",
                "work_id": target_work_id,
            }
        if (
            bound_work_id is not None
            and self._on_bound_owner_input_submitted is not None
        ):
            # The callback closes the bounded proactive interaction. Cancellation
            # resolves the pending owner-attention dependency just as definitively
            # as supplying an answer, without submitting fake owner input to DBOS.
            self._on_bound_owner_input_submitted(item)
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

        Normal conversation may omit work_id only when JARVIS can resolve a unique
        WAITING_FOR_OWNER WorkItem. A proactive owner-input voice interaction can bind
        this tool to one exact WorkItem; in that mode an omitted work_id resolves to the
        bound item and any attempt to target a different item fails closed. The actual
        response is always grounded from the canonical USER turn, never from
        model-generated hidden text.
        """
        del context
        turn = self._latest_user_turn()
        requested_work_id = str(work_id or "").strip()
        bound_work_id = self._bound_owner_input_work_id
        if (
            bound_work_id is not None
            and requested_work_id
            and requested_work_id != bound_work_id
        ):
            return {
                "ok": False,
                "status": "owner_input_target_mismatch",
                "work_id": requested_work_id,
                "bound_work_id": bound_work_id,
            }
        target_work_id = requested_work_id or bound_work_id
        try:
            waiting = self._runtime.submit_owner_input(target_work_id, turn.text)
        except WorkStoreError:
            return {
                "ok": False,
                "status": "unknown_work_id",
                "work_id": target_work_id or "",
            }
        except ValueError as exc:
            return {
                "ok": False,
                "status": "owner_input_target_unresolved",
                "reason": str(exc),
            }
        if (
            bound_work_id is not None
            and self._on_bound_owner_input_submitted is not None
        ):
            self._on_bound_owner_input_submitted(waiting)
        return {
            "ok": True,
            "status": "owner_input_submitted",
            **_public_work(waiting, self._runtime),
            "canonical_user_turn_id": turn.turn_id,
        }
