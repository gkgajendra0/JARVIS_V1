"""Voice tools for explicit, governed personal-memory operations."""

from __future__ import annotations

from livekit.agents import RunContext, function_tool
from livekit.agents.llm import ToolError

from jarvis.conversation import ConversationSession
from jarvis.memory.explicit import (
    ExplicitMemoryAction,
    ExplicitMemoryAuthorizationError,
    MemorySecretRejectedError,
    authorize_explicit_memory_action,
    build_owner_explicit_source,
    parse_memory_sensitivity,
    reject_prohibited_secret,
)
from jarvis.memory.service import (
    MemoryAlreadyExistsError,
    MemoryAmbiguousError,
    MemoryNotFoundError,
    MemoryService,
    MemoryServiceError,
)
from jarvis.memory.types import Sensitivity

_EXPECTED_MEMORY_ERRORS = (
    ExplicitMemoryAuthorizationError,
    MemorySecretRejectedError,
    MemoryAlreadyExistsError,
    MemoryAmbiguousError,
    MemoryNotFoundError,
    MemoryServiceError,
    TypeError,
    ValueError,
)


class MemoryAgentTools:
    """Expose only explicit MemoryService operations to the realtime agent."""

    def __init__(
        self,
        service: MemoryService,
        conversation: ConversationSession,
    ) -> None:
        if not isinstance(service, MemoryService):
            raise TypeError("service must be a MemoryService")
        if not isinstance(conversation, ConversationSession):
            raise TypeError("conversation must be a ConversationSession")
        self._service = service
        self._conversation = conversation

    @property
    def tools(self) -> list:
        return [
            self.remember_memory,
            self.correct_memory,
            self.forget_memory,
            self.inspect_memory,
        ]

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
        return {
            "ok": True,
            "operation": "forget",
            "predicate": forgotten_predicate,
        }

    async def inspect(self, *, predicate: str) -> dict[str, object]:
        authorize_explicit_memory_action(
            self._conversation,
            ExplicitMemoryAction.INSPECT,
        )
        result = await self._service.inspect_exact(predicate=predicate)
        record = result.record
        if record.sensitivity is Sensitivity.LOCAL_ONLY:
            return {
                "ok": False,
                "operation": "inspect",
                "predicate": result.predicate,
                "reason": (
                    "This memory is local_only and cannot be released to the "
                    "configured realtime provider."
                ),
            }
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
        """Remember one explicit personal text fact or preference durably.

        Use only when the user's latest utterance explicitly asks JARVIS to remember
        something. `predicate` is a short semantic key such as `home city` or
        `jimny tyre size`. `value` is the user's stated value. `sensitivity` may be
        `standard`, `private`, or `local_only`. Never use this tool for credentials,
        secrets, or inferred facts.
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
        wrong or asks JARVIS to correct/update it. Never guess the target predicate.
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
        remove, or delete that memory. Never guess an ambiguous target.
        """
        context.disallow_interruptions()
        return await self._call_tool(self.forget(predicate=predicate))

    @function_tool()
    async def inspect_memory(
        self,
        context: RunContext,
        predicate: str,
    ) -> dict[str, object]:
        """Inspect one exact current personal memory after an explicit memory query.

        This is exact lookup only; it is not fuzzy or semantic search. A local-only
        memory is never released across the realtime provider boundary.
        """
        del context
        return await self._call_tool(self.inspect(predicate=predicate))

    @staticmethod
    async def _call_tool(operation) -> dict[str, object]:
        try:
            return await operation
        except _EXPECTED_MEMORY_ERRORS as exc:
            raise ToolError(str(exc)) from exc
