"""Semantic realtime tool for returning JARVIS to local wake standby."""

from __future__ import annotations

from collections.abc import Callable

from livekit.agents import RunContext, function_tool

StandbyRequestHandler = Callable[[], bool]


class StandbyAgentTools:
    """Expose conversational standby without granting lifecycle ownership to the LLM."""

    def __init__(self, request_standby: StandbyRequestHandler) -> None:
        self._request_standby = request_standby

    @property
    def tools(self) -> list:
        return [self.enter_standby]

    @function_tool()
    async def enter_standby(self, context: RunContext) -> None:
        """Return JARVIS to wake-word standby when the conversation is clearly over.

        Use this only when the user clearly means they are finished talking to JARVIS
        for now and want JARVIS itself to stand by, go back to sleep, end the current
        JARVIS conversation, or wait for the next wake word while remaining running.

        Never use this for sleeping, restarting, shutting down, locking, or signing
        out of the Windows PC/computer. Those are computer power/session operations.
        Do not use this merely because the user says they are sleepy, discusses sleep,
        quotes a standby phrase, negates it, or otherwise mentions sleep ambiguously.
        """
        del context
        self._request_standby()
