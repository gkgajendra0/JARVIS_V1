"""Voice tools for explicit, governed personal-memory operations."""

from __future__ import annotations

import logging
import unicodedata

from livekit.agents import RunContext, function_tool
from livekit.agents.llm import ToolError

from jarvis.conversation import ConversationRole, ConversationSession, ConversationTurn
from jarvis.memory.evidence_gate import MemoryEvidenceDisposition
from jarvis.memory.explicit import (
    ExplicitMemoryAction,
    ExplicitMemoryAuthorizationError,
    MemorySecretRejectedError,
    authorize_explicit_memory_action,
    build_owner_explicit_source,
    parse_memory_sensitivity,
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
        self._semantic_query_coordinator = semantic_query_coordinator

    @property
    def tools(self) -> list:
        tools = [
            self.remember_memory,
            self.correct_memory,
            self.forget_memory,
            self.inspect_memory,
        ]
        if self._semantic_query_coordinator is not None:
            tools.append(self.recall_memory)
        return tools

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
        _require_grounded_target(turn, predicate)
        _require_grounded_value(turn, value)
        resolved_sensitivity = parse_memory_sensitivity(sensitivity)
        reject_prohibited_secret(predicate=predicate, value=value)
        source = build_owner_explicit_source(
            conversation=self._conversation,
            turn=turn,
            sensitivity=resolved_sensitivity,
        )
        result = await self._service.remember_text(
            predicate=predicate,
            value=value,
            source=source,
            sensitivity=resolved_sensitivity,
        )
        LOGGER.info(
            "Explicit memory remember committed | predicate=%s | memory_id=%s | "
            "sensitivity=%s",
            result.predicate,
            result.record.assertion_id,
            result.record.sensitivity.value,
        )
        return {
            "ok": True,
            "operation": "remember",
            "predicate": result.predicate,
            "memory_id": result.record.assertion_id,
            "sensitivity": result.record.sensitivity.value,
        }

    async def correct(
        self,
        *,
        predicate: str,
        value: str,
    ) -> dict[str, object]:
        turn = authorize_explicit_memory_action(
            self._conversation,
            ExplicitMemoryAction.CORRECT,
        )
        _require_grounded_target(turn, predicate)
        _require_grounded_value(turn, value)
        reject_prohibited_secret(predicate=predicate, value=value)
        current = await self._service.inspect_exact(predicate=predicate)
        source = build_owner_explicit_source(
            conversation=self._conversation,
            turn=turn,
            sensitivity=current.record.sensitivity,
        )
        result = await self._service.correct_text(
            predicate=predicate,
            value=value,
            source=source,
        )
        LOGGER.info(
            "Explicit memory correction committed | predicate=%s | memory_id=%s | "
            "sensitivity=%s",
            result.predicate,
            result.record.assertion_id,
            result.record.sensitivity.value,
        )
        return {
            "ok": True,
            "operation": "correct",
            "predicate": result.predicate,
            "memory_id": result.record.assertion_id,
            "sensitivity": result.record.sensitivity.value,
        }

    async def forget(self, *, predicate: str) -> dict[str, object]:
        turn = authorize_explicit_memory_action(
            self._conversation,
            ExplicitMemoryAction.FORGET,
        )
        _require_grounded_target(turn, predicate)
        current = await self._service.inspect_exact(predicate=predicate)
        source = build_owner_explicit_source(
            conversation=self._conversation,
            turn=turn,
            sensitivity=current.record.sensitivity,
        )
        forgotten_predicate = await self._service.forget_exact(
            predicate=predicate,
            source=source,
        )
        LOGGER.info(
            "Explicit memory forget committed | predicate=%s",
            forgotten_predicate,
        )
        return {
            "ok": True,
            "operation": "forget",
            "predicate": forgotten_predicate,
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
            raise MemoryToolGroundingError(
                "semantic recall requires a latest accepted user utterance"
            )
        return turn

    async def semantic_recall(self) -> dict[str, object]:
        coordinator = self._semantic_query_coordinator
        if coordinator is None:
            raise MemoryToolGroundingError(
                "semantic memory recall is not enabled for this session"
            )
        turn = self._latest_user_turn()
        decision = await coordinator.resolve(
            turn.text,
            eligibility=RetrievalEligibility.cloud_context(),
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
        return await self._call_tool(
            self.remember(
                predicate=predicate,
                value=value,
                sensitivity=sensitivity,
            )
        )

    @function_tool()
    async def correct_memory(
        self,
        context: RunContext,
        predicate: str,
        value: str,
    ) -> dict[str, object]:
        """Correct one exact current personal memory after an explicit correction.

        Use only when the latest user utterance explicitly says the stored memory is
        wrong or asks JARVIS to correct/update it. The exact predicate and corrected
        value must both be directly present in that utterance. Never guess the target.
        """
        context.disallow_interruptions()
        return await self._call_tool(self.correct(predicate=predicate, value=value))

    @function_tool()
    async def forget_memory(
        self,
        context: RunContext,
        predicate: str,
    ) -> dict[str, object]:
        """Physically forget one exact current personal memory.

        Use only when the latest user utterance explicitly asks JARVIS to forget,
        remove, or delete that memory. The exact predicate must be directly named in
        that utterance. Never guess an ambiguous or implied target.
        """
        context.disallow_interruptions()
        return await self._call_tool(self.forget(predicate=predicate))

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
