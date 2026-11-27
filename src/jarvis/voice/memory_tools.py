"""Voice tools for explicit, governed personal-memory operations."""

from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from dataclasses import dataclass

from livekit.agents import RunContext, function_tool
from livekit.agents.llm import ToolError

from jarvis.conversation import (
    ConversationRole,
    ConversationSession,
    ConversationStatus,
    ConversationTurn,
)
from jarvis.memory.evidence_gate import MemoryEvidenceDisposition
from jarvis.memory.explicit import (
    ExplicitMemoryAction,
    ExplicitMemoryAuthorizationError,
    MemorySecretRejectedError,
    authorize_explicit_memory_action,
    build_owner_explicit_source,
    parse_memory_sensitivity,
    reject_negated_memory_change,
    reject_prohibited_secret,
)
from jarvis.memory.provider_verified_query import ProviderVerifiedMemoryQueryCoordinator
from jarvis.memory.retrieval import RetrievalEligibility
from jarvis.memory.service import (
    MemoryAlreadyExistsError,
    MemoryAmbiguousError,
    MemoryNotFoundError,
    MemoryService,
    MemoryServiceError,
    canonical_memory_predicate,
    normalize_memory_surface,
)
from jarvis.memory.types import Sensitivity

LOGGER = logging.getLogger(__name__)


class MemoryToolGroundingError(ValueError):
    pass


_EXPECTED_MEMORY_ERRORS = (
    ExplicitMemoryAuthorizationError,
    MemorySecretRejectedError,
    MemoryToolGroundingError,
    MemoryAlreadyExistsError,
    MemoryAmbiguousError,
    MemoryNotFoundError,
    MemoryServiceError,
    TypeError,
    ValueError,
    PermissionError,
)


def _semantic_text(value: str) -> str:
    normalized = normalize_memory_surface(value)
    characters = [
        character if unicodedata.category(character)[0] in {"L", "M", "N"} else " "
        for character in normalized
    ]
    return " ".join("".join(characters).split())


def _require_grounded_target(turn: ConversationTurn, predicate: str) -> None:
    target = _semantic_text(predicate.replace("_", " "))
    utterance = _semantic_text(turn.text)
    if not target or target not in utterance:
        raise MemoryToolGroundingError(
            "the exact memory predicate must be named in the latest user utterance; "
            "ask the user to state the memory target explicitly"
        )


def _require_grounded_value(turn: ConversationTurn, value: str) -> None:
    grounded_value = _semantic_text(value)
    utterance = _semantic_text(turn.text)
    if not grounded_value or grounded_value not in utterance:
        raise MemoryToolGroundingError(
            "the memory value must come directly from the latest user utterance; "
            "do not infer or invent a durable value"
        )


class MemoryAgentTools:
    """Expose only explicit MemoryService operations to the realtime agent."""

    def __init__(
        self,
        service: MemoryService,
        conversation: ConversationSession,
        *,
        semantic_query_coordinator: ProviderVerifiedMemoryQueryCoordinator
        | None = None,
        personal_context=None,
        split_owned_item_lists: bool = True,
        receipts=None,
    ) -> None:
        if not isinstance(service, MemoryService):
            raise TypeError("service must be a MemoryService")
        if not isinstance(conversation, ConversationSession):
            raise TypeError("conversation must be a ConversationSession")
        if semantic_query_coordinator is not None and not callable(
            getattr(semantic_query_coordinator, "resolve", None)
        ):
            raise TypeError(
                "semantic_query_coordinator must implement resolve when provided"
            )
        self._service = service
        self._conversation = conversation
        # False only for harnesses that reproduce runs recorded before lists
        # were split (their stored state must match the recording).
        self._split_owned_item_lists = split_owned_item_lists
        self._semantic_query_coordinator = semantic_query_coordinator
        self._personal_context = personal_context
        # Verified memory results per owner turn (jarvis.memory.memory_receipts):
        # explicit operations are recorded here, and memory_status reads them.
        self._receipts = receipts

    @property
    def tools(self) -> list:
        tools = [
            self.remember_memory,
            self.correct_memory,
            self.forget_memory,
        ]
        if self._personal_context is None:
            tools.append(self.inspect_memory)
        if (
            self._semantic_query_coordinator is not None
            and self._personal_context is None
        ):
            tools.append(self.recall_memory)
        if self._receipts is not None:
            tools.append(self.memory_status)
        return tools

    def _owner_turn_id(self):
        for turn in reversed(self._conversation.turns):
            if turn.role is ConversationRole.USER:
                return turn.turn_id
        return None

    def _record(self, result):
        """Record an explicit operation that returned ok for the latest owner
        turn (the turn it was asked in)."""
        if self._receipts is None or not isinstance(result, dict):
            return result
        turn_id = self._owner_turn_id()
        if not result.get("ok") or turn_id is None:
            return result
        operation = str(result.get("operation") or "")
        if operation not in {"remember", "correct", "forget"}:
            return result
        labels = tuple(result.get("saved") or ())
        if operation == "remember" and "saved" in result and not labels:
            operation, labels = (
                "already_saved",
                tuple(result.get("already_saved") or ()),
            )
        elif not labels and result.get("predicate"):
            labels = (str(result["predicate"]),)
        from jarvis.memory.memory_receipts import MemoryOperation, compose_say

        session = self._conversation.session_id
        self._receipts.explicit(session, turn_id, operation, labels)
        say = compose_say(
            [
                MemoryOperation("explicit", operation, label)
                for label in labels or (None,)
            ]
        )
        return {
            **result,
            "say": self._receipts.issue(session, say, turn_id),
            "say_rule": "Speak say exactly as given; add nothing about memory.",
        }

    async def remember(
        self,
        *,
        predicate: str,
        value: str,
        sensitivity: str = "standard",
    ) -> dict[str, object]:
        turn = authorize_explicit_memory_action(
            self._conversation,
            ExplicitMemoryAction.REMEMBER,
        )
        if self._personal_context is not None:
            self._personal_context.reserve_mutation("remember")
        _require_grounded_target(turn, predicate)
        _require_grounded_value(turn, value)
        resolved_sensitivity = parse_memory_sensitivity(sensitivity)
        reject_prohibited_secret(predicate=predicate, value=value)
        parsed = (
            _parse_item_list(predicate, value, turn.text)
            if self._split_owned_item_lists
            else _ItemList("not_a_list")
        )
        if parsed.status == "ambiguous":
            # Never save guessed items: ask the owner to name each one.
            LOGGER.info(
                "Memory change | operation=remember_items | status=clarification_required"
                " | reason=%s | turn_id=%s",
                parsed.reason,
                turn.turn_id,
            )
            return {
                "ok": False,
                "operation": "remember",
                "status": "clarification_required",
                "reason": parsed.reason,
                "saved": [],
                "message": (
                    "Nothing was saved. The items in this list are not clearly"
                    " separated. Ask the owner to name each item on its own, for"
                    " example 'a <first item> and a <second item>'."
                ),
            }
        if parsed.status == "items" and resolved_sensitivity.value == "standard":
            # One approval showing exactly what will be committed.
            return await self._remember_items(
                turn, predicate, parsed.kind, parsed.items
            )
        if self._personal_context is not None:
            await self._personal_context.authorize_mutation(
                "remember",
                canonical_memory_predicate(predicate),
                value,
                sensitivity=resolved_sensitivity.value,
            )
        source = build_owner_explicit_source(
            conversation=self._conversation,
            turn=turn,
            sensitivity=resolved_sensitivity,
        )
        try:
            result = await self._service.remember_text(
                predicate=predicate,
                value=value,
                source=source,
                sensitivity=resolved_sensitivity,
                **self._commit_guard(),
            )
        except (Exception, asyncio.CancelledError):
            if self._personal_context is not None:
                self._personal_context.mutation_failed()
            LOGGER.info(
                "Memory change | operation=remember | status=failed | turn_id=%s",
                turn.turn_id,
            )
            raise
        if self._personal_context is not None:
            self._personal_context.mutation_committed()
        LOGGER.info(
            "Memory change | operation=remember | status=committed | turn_id=%s",
            turn.turn_id,
        )
        return {
            "ok": True,
            "operation": "remember",
            "predicate": result.predicate,
            "memory_id": result.record.assertion_id,
            "sensitivity": result.record.sensitivity.value,
        }

    async def _remember_items(self, turn, predicate, kind, items):
        """One approval showing exactly the items that will be committed; one
        owned-item fact per item. Items already saved are left out before the
        review, and the write refuses if that changed after the review."""
        existing = await self._service.current_owned_item_labels()
        already = tuple(i for i in items if i.casefold() in existing)
        new_items = tuple(i for i in items if i.casefold() not in existing)
        if not new_items:
            return {
                "ok": True,
                "operation": "remember",
                "items": list(items),
                "saved": [],
                "already_saved": list(already),
                "memory_ids": [],
                "sensitivity": "standard",
            }
        shown = "; ".join(new_items)
        if self._personal_context is not None:
            await self._personal_context.authorize_mutation(
                "remember",
                canonical_memory_predicate(predicate),
                shown,
                sensitivity="standard",
            )
        source = build_owner_explicit_source(
            conversation=self._conversation,
            turn=turn,
            sensitivity=parse_memory_sensitivity("standard"),
        )
        try:
            records = await self._service.remember_owned_items(
                kind=kind, items=new_items, source=source, **self._commit_guard()
            )
        except (Exception, asyncio.CancelledError):
            if self._personal_context is not None:
                self._personal_context.mutation_failed()
            LOGGER.info(
                "Memory change | operation=remember_items | status=failed | turn_id=%s",
                turn.turn_id,
            )
            raise
        if self._personal_context is not None:
            self._personal_context.mutation_committed()
        LOGGER.info(
            "Memory change | operation=remember_items | status=committed | items=%d"
            " | saved=%d | turn_id=%s",
            len(items),
            len(records),
            turn.turn_id,
        )
        return {
            "ok": True,
            "operation": "remember",
            "items": list(items),
            "saved": [r.value["label"] for r in records],
            "already_saved": list(already),
            "memory_ids": [r.assertion_id for r in records],
            "sensitivity": "standard",
        }

    async def correct(
        self,
        *,
        predicate: str,
        value: str,
        catalog_id: str | None = None,
        facet_index: int | None = None,
    ) -> dict[str, object]:
        turn = self._change_turn(ExplicitMemoryAction.CORRECT)
        _require_grounded_value(turn, value)
        reject_prohibited_secret(predicate=predicate, value=value)
        current = await self._change_target(turn, predicate, catalog_id, facet_index)
        if current is None:
            return self._resolution_needed("correct", catalog_id is not None)
        predicate = current.predicate
        reject_prohibited_secret(predicate=predicate, value=value)
        if self._personal_context is not None:
            await self._personal_context.authorize_mutation(
                "correct",
                predicate,
                value,
                assertion_id=current.assertion_id,
                sensitivity=current.sensitivity.value,
            )
        source = build_owner_explicit_source(
            conversation=self._conversation,
            turn=turn,
            sensitivity=current.sensitivity,
        )
        try:
            result = await self._service.correct_text(
                predicate=predicate,
                value=value,
                source=source,
                **self._commit_guard(),
                **(
                    {"expected_assertion_id": current.assertion_id}
                    if self._personal_context is not None
                    else {}
                ),
            )
        except (Exception, asyncio.CancelledError):
            if self._personal_context is not None:
                self._personal_context.mutation_failed()
            LOGGER.info(
                "Memory change | operation=correct | status=failed | turn_id=%s",
                turn.turn_id,
            )
            raise
        if self._personal_context is not None:
            self._personal_context.mutation_committed()
        LOGGER.info(
            "Memory change | operation=correct | status=committed | turn_id=%s",
            turn.turn_id,
        )
        return {
            "ok": True,
            "operation": "correct",
            "predicate": result.predicate,
            "memory_id": result.record.assertion_id,
            "sensitivity": result.record.sensitivity.value,
        }

    async def forget(
        self,
        *,
        predicate: str,
        catalog_id: str | None = None,
        facet_index: int | None = None,
    ) -> dict[str, object]:
        turn = self._change_turn(ExplicitMemoryAction.FORGET)
        current = await self._change_target(turn, predicate, catalog_id, facet_index)
        if current is None:
            return self._resolution_needed("forget", catalog_id is not None)
        predicate = current.predicate
        if self._personal_context is not None:
            await self._personal_context.authorize_mutation(
                "forget",
                predicate,
                assertion_id=current.assertion_id,
                sensitivity=current.sensitivity.value,
            )
        source = build_owner_explicit_source(
            conversation=self._conversation,
            turn=turn,
            sensitivity=current.sensitivity,
        )
        try:
            forgotten_predicate = await self._service.forget_exact(
                predicate=predicate,
                source=source,
                **self._commit_guard(),
                **(
                    {"expected_assertion_id": current.assertion_id}
                    if self._personal_context is not None
                    else {}
                ),
            )
        except (Exception, asyncio.CancelledError):
            if self._personal_context is not None:
                self._personal_context.mutation_failed()
            LOGGER.info(
                "Memory change | operation=forget | status=failed | turn_id=%s",
                turn.turn_id,
            )
            raise
        if self._personal_context is not None:
            self._personal_context.mutation_committed()
        LOGGER.info(
            "Memory change | operation=forget | status=committed | turn_id=%s",
            turn.turn_id,
        )
        return {
            "ok": True,
            "operation": "forget",
            "predicate": forgotten_predicate,
        }

    def _change_turn(self, action):
        if self._personal_context is None:
            return authorize_explicit_memory_action(self._conversation, action)
        turn = self._latest_user_turn()
        reject_negated_memory_change(turn.text)
        self._personal_context.reserve_mutation(action.value)
        return turn

    async def _change_target(self, turn, predicate, catalog_id, facet_index):
        activity_epoch = self._conversation.user_activity_epoch
        try:
            if self._personal_context is not None and (
                catalog_id is not None or facet_index is not None
            ):
                return await self._personal_context.resolve_mutation_target(
                    catalog_id, facet_index
                )
            try:
                _require_grounded_target(turn, predicate)
                if self._personal_context is not None:
                    await self._personal_context.prepare_target_resolution()
                return (await self._service.inspect_exact(predicate=predicate)).record
            except (MemoryNotFoundError, MemoryToolGroundingError):
                if self._personal_context is None:
                    raise
                return None
        finally:
            if self._personal_context is not None and (
                self._conversation.status is not ConversationStatus.ACTIVE
                or self._latest_user_turn().turn_id != turn.turn_id
                or self._conversation.user_activity_epoch != activity_epoch
            ):
                raise ExplicitMemoryAuthorizationError(
                    "The memory request changed during target resolution"
                )

    def _resolution_needed(self, operation, invalid_selection):
        status = "invalid_selection" if invalid_selection else "resolution_required"
        LOGGER.info(
            "Memory change | operation=%s | status=%s | turn_id=%s",
            operation,
            status,
            self._latest_user_turn().turn_id,
        )
        return {
            "ok": False,
            "operation": operation,
            "status": status,
            "reason": "No canonical target selected. Use personal_context_catalog and select its actual facet index. "
            "If multiple targets are plausible, ask a natural clarification. "
            "Do not invent a key, claim absence, or fall back to remember_memory.",
        }

    def _commit_guard(self):
        return (
            {"commit_guard": self._personal_context.validate_mutation_commit}
            if self._personal_context is not None
            else {}
        )

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
            raise MemoryToolGroundingError(
                "semantic recall requires a latest accepted user utterance"
            )
        return turn

    async def semantic_recall(self) -> dict[str, object]:
        if self._personal_context is not None:
            raise MemoryToolGroundingError(
                "Use the consent-bound personal context tools"
            )
        coordinator = self._semantic_query_coordinator
        if coordinator is None:
            raise MemoryToolGroundingError(
                "semantic memory recall is not enabled for this session"
            )
        turn = self._latest_user_turn()
        activity_epoch = self._conversation.user_activity_epoch

        def validate_recall_source():
            if (
                self._conversation.status is not ConversationStatus.ACTIVE
                or self._latest_user_turn().turn_id != turn.turn_id
                or self._conversation.user_activity_epoch != activity_epoch
            ):
                raise ExplicitMemoryAuthorizationError(
                    "The original memory recall session or request changed"
                )

        decision = await coordinator.resolve(
            turn.text,
            eligibility=RetrievalEligibility.cloud_context(),
            before_dispatch=validate_recall_source,
        )
        if decision.disposition is MemoryEvidenceDisposition.ABSTAIN:
            LOGGER.info(
                "Semantic memory recall abstained | turn_id=%s | reason=%s",
                turn.turn_id,
                decision.reason_code,
            )
            return {
                "ok": False,
                "operation": "semantic_recall",
                "reason": "No safely releasable current memory matched this question.",
            }
        if decision.evidence is None:
            raise RuntimeError("semantic recall released without trusted evidence")
        record = decision.evidence.assertion
        LOGGER.info(
            "Semantic memory recall released | turn_id=%s | predicate=%s | "
            "sensitivity=%s | reason=%s",
            turn.turn_id,
            record.predicate,
            record.sensitivity.value,
            decision.reason_code,
        )
        return {
            "ok": True,
            "operation": "semantic_recall",
            "predicate": record.predicate,
            "value": record.value,
            "sensitivity": record.sensitivity.value,
            "freshness": record.freshness_class.value,
            "verification": record.verification_state.value,
        }

    async def inspect(self, *, predicate: str) -> dict[str, object]:
        if self._personal_context is not None:
            raise MemoryToolGroundingError(
                "Use the consent-bound personal context tools"
            )
        turn = authorize_explicit_memory_action(
            self._conversation,
            ExplicitMemoryAction.INSPECT,
        )
        _require_grounded_target(turn, predicate)
        result = await self._service.inspect_exact(predicate=predicate)
        record = result.record
        if record.sensitivity is Sensitivity.LOCAL_ONLY:
            LOGGER.info(
                "Explicit memory inspect blocked from provider release | predicate=%s | "
                "sensitivity=local_only",
                result.predicate,
            )
            return {
                "ok": False,
                "operation": "inspect",
                "predicate": result.predicate,
                "reason": (
                    "This memory is local_only and cannot be released to the "
                    "configured realtime provider."
                ),
            }
        LOGGER.info(
            "Explicit memory inspect hit | predicate=%s | sensitivity=%s | "
            "verification=%s",
            result.predicate,
            record.sensitivity.value,
            record.verification_state.value,
        )
        return {
            "ok": True,
            "operation": "inspect",
            "predicate": result.predicate,
            "value": record.value,
            "sensitivity": record.sensitivity.value,
            "freshness": record.freshness_class.value,
            "verification": record.verification_state.value,
        }

    @function_tool()
    async def remember_memory(
        self,
        context: RunContext,
        predicate: str,
        value: str,
        sensitivity: str = "standard",
    ) -> dict[str, object]:
        """Durably remember only an explicit user-commanded personal memory.

        STRICT invocation condition: the latest accepted USER utterance itself must
        explicitly command JARVIS to remember/store/save the information, for example
        "Remember that my home city is Sagar" or "Yaad rakhna ki meri city Sagar
        hai". Do NOT call this tool for declarative/implicit facts such as "My home
        city is Sagar", "I bought a Jimny", or "My candidate test animal is falcon",
        even if the fact seems stable, personal, important, or useful later. Those
        implicit facts belong to the separate Phase-4.4 candidate-extraction path.
        If explicit remember intent is absent or uncertain, do not call this tool.

        `predicate` must be a short target phrase directly named in the same latest
        utterance, such as `home city` or `jimny tyre size`. `value` must also come
        directly from that utterance. `sensitivity` may be `standard`, `private`, or
        `local_only`. Never use this tool for credentials, secrets, inferred facts,
        or implicit candidate promotion.
        """
        context.disallow_interruptions()
        return self._record(
            await self._call_tool(
                self.remember(
                    predicate=predicate,
                    value=value,
                    sensitivity=sensitivity,
                )
            )
        )

    @function_tool()
    async def correct_memory(
        self,
        context: RunContext,
        predicate: str,
        value: str,
        catalog_id: str | None = None,
        facet_index: int | None = None,
    ) -> dict[str, object]:
        """Correct one exact current personal memory after an explicit correction.

        Interpret the user's natural request to change an existing saved fact.
        In personal-context APPLY, resolve names using personal_context_catalog,
        then pass its catalog_id and zero-based facet_index. Copy the new value
        from catalog.request.text in its original script; do not translate it.
        The selected canonical target need not be said as an internal key by the user.
        Ambiguity requires clarification; negation/hypotheticals/third-party facts
        are not change commands. Concrete target/value require fresh owner approval.
        Without personal context, the legacy exact-command rules still apply.
        """
        context.disallow_interruptions()
        return self._record(
            await self._call_tool(
                self.correct(
                    predicate=predicate,
                    value=value,
                    catalog_id=catalog_id,
                    facet_index=facet_index,
                )
            )
        )

    @function_tool()
    async def forget_memory(
        self,
        context: RunContext,
        predicate: str,
        catalog_id: str | None = None,
        facet_index: int | None = None,
    ) -> dict[str, object]:
        """Physically forget one exact current personal memory.

        Use only for a clear natural request to delete an existing saved fact.
        In personal-context APPLY, select its actual catalog_id/facet_index from
        personal_context_catalog; never invent the stored key or guess an unclear
        referent. The exact deletion requires fresh owner approval. Without
        personal context, legacy exact-command rules still apply.
        """
        context.disallow_interruptions()
        return self._record(
            await self._call_tool(
                self.forget(
                    predicate=predicate, catalog_id=catalog_id, facet_index=facet_index
                )
            )
        )

    @function_tool()
    async def memory_status(self, context: RunContext) -> dict[str, object]:
        """What memory verifiably did for the owner's recent turns.

        Call this whenever the owner asks whether something was saved,
        noted, updated or forgotten, and speak its say sentence exactly as
        given. Never describe a memory change in your own words. It waits
        briefly for automatic learning of those turns to finish. It reads no
        other stored facts and changes nothing.
        """
        del context
        return await self.verified_memory_status()

    async def verified_memory_status(self, wait: float = 6.0) -> dict[str, object]:
        from jarvis.memory.memory_receipts import RECENT_TURNS

        owner_turns = [
            t
            for t in reversed(self._conversation.turns)
            if t.role is ConversationRole.USER
        ][:RECENT_TURNS]
        from jarvis.memory.memory_receipts import NOTHING_SAVED

        if self._receipts is None or not owner_turns:
            return {
                "say": NOTHING_SAVED,
                "turns": [],
                "rule": "Speak the say sentence exactly as given.",
            }
        session = self._conversation.session_id
        await self._receipts.wait_learning(
            session, tuple(t.turn_id for t in owner_turns), wait
        )
        view = self._receipts.view(session, [t.turn_id for t in owner_turns])
        self._receipts.issue(session, view["say"], owner_turns[0].turn_id)
        return view

    @function_tool()
    async def recall_memory(
        self,
        context: RunContext,
    ) -> dict[str, object]:
        """Recall one current personal fact for the latest USER question.

        Use this only when the latest accepted user utterance asks for a personal fact
        that may already exist in JARVIS durable memory. Do not provide a predicate or
        memory key: JARVIS reads the canonical latest USER utterance itself, performs
        structured semantic planning, exact canonical lookup, cloud-sensitivity
        filtering, and a second same-provider ALLOW/ABSTAIN verification. If the tool
        returns ok=false, do not guess or claim a remembered answer.
        """
        del context
        return await self._call_tool(self.semantic_recall())

    @function_tool()
    async def inspect_memory(
        self,
        context: RunContext,
        predicate: str,
    ) -> dict[str, object]:
        """Inspect one exact current personal memory after an explicit memory query.

        The exact predicate must be directly named in the latest user utterance. This
        is exact lookup only; it is not fuzzy or semantic search. A local-only memory
        is never released across the realtime provider boundary.
        """
        del context
        return await self._call_tool(self.inspect(predicate=predicate))

    @staticmethod
    async def _call_tool(operation) -> dict[str, object]:
        try:
            return await operation
        except _EXPECTED_MEMORY_ERRORS as exc:
            raise ToolError(str(exc)) from exc


_HARD_SEPARATORS = re.compile(r"\s*[,;]\s*")
# "and"/"aur" separates items only when the next word starts a new item.
_ITEM_BOUNDARY = re.compile(
    r"\s+(?:and|aur)\s+(?=(?:a|an|the|my|one|another|ek)\s)", re.IGNORECASE
)
_INNER_CONJUNCTION = re.compile(r"\b(?:and|aur)\b|&", re.IGNORECASE)
_LEADING_CONJUNCTION = re.compile(r"^(?:and|aur)\s+", re.IGNORECASE)
_LEADING_ARTICLE = re.compile(r"^(?:a|an|the|my|one|another|ek)\s+", re.IGNORECASE)
# Wording shared with another item ("a red one", "HP ones") cannot stand alone.
_SHARED_WORDING = re.compile(r"(?:^|\s)(?:one|ones|wala|wali|wale)$", re.IGNORECASE)
_PLURAL_ITEM_PREDICATES = frozenset({"vehicles", "devices"})


@dataclass(frozen=True)
class _ItemList:
    status: str  # "items" | "single" | "ambiguous" | "not_a_list"
    items: tuple[str, ...] = ()
    kind: str = ""
    reason: str = ""


def _parse_item_list(predicate, value, turn_text):
    """Split a newly supplied possessions list only at unambiguous item
    boundaries. Conjunctions inside a name or description are kept ("a black
    and white Vespa"); when the boundaries cannot be told apart ("a Thar and
    Ather", "Dell and HP laptops"), nothing is guessed."""
    from jarvis.memory.learning_values import has_identifier
    from jarvis.personal_learning_scope import LEGACY_FACETS

    canonical = canonical_memory_predicate(predicate)
    facet = LEGACY_FACETS.get(canonical, "")
    if not facet.startswith("owned_item."):
        return _ItemList("not_a_list")
    kind = facet.split(".", 1)[1]
    plural = canonical in _PLURAL_ITEM_PREDICATES
    items = []
    inner = False
    all_marked = True  # every item introduced by a/an/the/my/one/ek...
    for segment in _HARD_SEPARATORS.split(value.strip().strip(".")):
        segment = _LEADING_CONJUNCTION.sub("", segment.strip())
        for part in _ITEM_BOUNDARY.split(segment):
            part = part.strip()
            item = _LEADING_ARTICLE.sub("", part).strip(" .")
            if not item:
                continue
            all_marked = all_marked and item != part.strip(" .")
            inner = inner or _INNER_CONJUNCTION.search(item) is not None
            items.append(item)
    items = list(dict.fromkeys(items))
    # With every item explicitly introduced, an unmarked "and" belongs to a
    # name ("a Bang and Olufsen speaker and an iPad Air"); otherwise it could
    # be either, so nothing is guessed.
    unclear = inner and not all_marked
    if len(items) < 2:
        # A plural memory ("vehicles") holding one phrase with an unmarked
        # "and" could be one named item or two ("a Pulsar and Chetak").
        if plural and inner:
            return _ItemList("ambiguous", reason="one_or_several_items")
        return _ItemList("single")
    if unclear:
        return _ItemList("ambiguous", reason="item_boundaries_unclear")
    if any(_SHARED_WORDING.search(item) for item in items):
        return _ItemList("ambiguous", reason="shared_wording")
    if len(items) > 8:
        return _ItemList("ambiguous", reason="too_many_items")
    lowered = turn_text.casefold()
    if any(len(item) > 120 or item.casefold() not in lowered for item in items):
        return _ItemList("ambiguous", reason="items_not_in_request")
    if any(has_identifier(item) for item in items):
        return _ItemList("ambiguous", reason="identifier_not_allowed")
    return _ItemList("items", tuple(items), kind)
