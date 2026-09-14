"""Voice-session resilience observer for terminal realtime-provider failures."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from livekit.agents import ErrorEvent
from livekit.agents.voice import io

from jarvis.provider_resilience import (
    ProviderFailureKind,
    ProviderResilienceState,
    classify_provider_failure,
)
from jarvis.voice.local_status_speech import LocalStatusSpeech

LOGGER = logging.getLogger(__name__)

_JARVIS_TERMINAL_FAILURE_KINDS = frozenset(
    {
        ProviderFailureKind.QUOTA_EXHAUSTED,
        ProviderFailureKind.AUTHENTICATION_FAILED,
        ProviderFailureKind.PERMISSION_DENIED,
        ProviderFailureKind.MODEL_UNAVAILABLE,
        ProviderFailureKind.REQUEST_REJECTED,
    }
)


class ProviderResilienceSessionObserver:
    """Diagnose terminal realtime failures, announce locally, then close cleanly.

    LiveKit documents realtime-model errors as safe to mark recoverable from an
    ``error`` handler. JARVIS treats that flag as transport guidance rather than
    canonical policy: billing/credential/request failures remain terminal even when
    the SDK marks the wrapper recoverable. JARVIS keeps a session alive only long
    enough to play its zero-cloud status message, then explicitly closes it.
    """

    def __init__(
        self,
        session: Any,
        *,
        provider: str,
        state: ProviderResilienceState,
        status_speech: LocalStatusSpeech | None,
        output_getter: Callable[[], io.AudioOutput | None],
        health_observer: Callable[[ProviderResilienceState], None] | None = None,
    ) -> None:
        self._session = session
        self._provider = provider
        self._state = state
        self._status_speech = status_speech
        self._output_getter = output_getter
        self._health_observer = health_observer
        self._terminal_task: asyncio.Task[None] | None = None
        session.on("error", self._on_error)
        session.on("agent_state_changed", self._on_agent_state_changed)

    @property
    def terminal_task(self) -> asyncio.Task[None] | None:
        return self._terminal_task

    def _notify_health(self) -> None:
        if self._health_observer is None:
            return
        try:
            self._health_observer(self._state)
        except Exception:  # noqa: BLE001,S110 - diagnostics must not break resilience
            pass

    def _on_agent_state_changed(self, event: Any) -> None:
        if getattr(event, "new_state", None) not in {
            "listening",
            "thinking",
            "speaking",
        }:
            return
        if self._state.mark_recovered():
            self._notify_health()
            LOGGER.info(
                "Cloud provider recovered | provider=%s | health=healthy",
                self._provider,
            )

    def _on_error(self, event: ErrorEvent) -> None:
        error = event.error
        if getattr(error, "type", None) != "realtime_model_error":
            return

        failure = classify_provider_failure(error, provider=self._provider)
        if self._terminal_task is not None and not self._terminal_task.done():
            return

        sdk_recoverable = bool(getattr(error, "recoverable", False))
        jarvis_terminal = failure.kind in _JARVIS_TERMINAL_FAILURE_KINDS
        if sdk_recoverable and not jarvis_terminal:
            LOGGER.warning(
                "Recoverable realtime provider error | provider=%s | kind=%s | "
                "status_code=%s | retryable=%s",
                self._provider,
                failure.kind.value,
                failure.status_code,
                failure.retryable,
            )
            return

        self._state.mark_failure(failure)
        self._notify_health()
        LOGGER.error(
            "Terminal realtime provider error | provider=%s | kind=%s | "
            "status_code=%s | retryable=%s | sdk_recoverable=%s | health=degraded",
            self._provider,
            failure.kind.value,
            failure.status_code,
            failure.retryable,
            sdk_recoverable,
        )

        # LiveKit's error contract allows realtime-model failures to be marked
        # recoverable. We use that only as a short transport bridge while local
        # deterministic status speech plays; JARVIS policy still owns whether the
        # failure is terminal and closes the session immediately after the message.
        error.recoverable = True
        self._terminal_task = asyncio.create_task(
            self._announce_and_close(failure.spoken_message),
            name=f"jarvis-provider-failure-{failure.kind.value}",
        )

    async def _announce_and_close(self, message: str) -> None:
        try:
            output = self._output_getter()
            if output is None:
                LOGGER.error(
                    "Local provider-failure announcement skipped because audio output "
                    "is unavailable"
                )
            elif self._status_speech is None:
                LOGGER.error(
                    "Local provider-failure announcement unavailable on this platform"
                )
            else:
                try:
                    await self._status_speech.speak(output, message)
                    LOGGER.info("Local provider-failure status announcement completed")
                except asyncio.CancelledError:
                    raise
                except Exception:
                    LOGGER.exception(
                        "Local provider-failure status announcement failed; closing "
                        "the session safely"
                    )
        finally:
            try:
                await self._session.aclose()
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception(
                    "Provider-failed session did not close cleanly after local status"
                )
