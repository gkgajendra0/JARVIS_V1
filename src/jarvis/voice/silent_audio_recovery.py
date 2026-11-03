"""Recover assistant turns whose realtime transcript exists but PCM is silent."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from jarvis.config import JarvisConfig
from jarvis.conversation import ConversationRole, ConversationTurn
from jarvis.voice.media_devices_audio import (
    MediaDevicesAudioOutput,
    PlaybackQualitySnapshot,
)
from jarvis.voice.scripted_speech import ScriptedSpeech, build_scripted_speech

LOGGER = logging.getLogger(__name__)

_SILENT_RMS_DBFS = -55.0
_SILENT_PEAK_ABS = 512
_QUALITY_WAIT_SECONDS = 10.0
_QUALITY_POLL_SECONDS = 0.02
# An assistant turn is committed after its playout; if no playback segment has
# started by then (plus this grace), Gemini produced no PCM at all.
_NO_AUDIO_GRACE_SECONDS = 1.5


def needs_scripted_recovery(quality: PlaybackQualitySnapshot) -> bool:
    """Return True only for objectively near-silent completed assistant audio."""

    return (
        not quality.interrupted
        and quality.rms_dbfs <= _SILENT_RMS_DBFS
        and quality.peak_abs <= _SILENT_PEAK_ABS
    )


class SilentRealtimeAudioRecovery:
    """Replay assistant text through deterministic TTS when realtime PCM is silent."""

    def __init__(
        self,
        config: JarvisConfig,
        *,
        output_getter: Callable[[], MediaDevicesAudioOutput | None],
        speech_factory: Callable[
            [JarvisConfig], ScriptedSpeech
        ] = build_scripted_speech,
    ) -> None:
        self._config = config
        self._output_getter = output_getter
        self._speech_factory = speech_factory
        output = output_getter()
        initial = output.last_completed_quality if output is not None else None
        self._last_consumed_sequence = initial.sequence if initial is not None else 0
        self._last_started_seen = (
            getattr(output, "started_segment_sequence", 0) if output is not None else 0
        )
        # Opt-in recovery for turns with NO playback (transcript only). Bound by
        # project voice memory, whose response gate must approve the replay.
        self._allow_unplayed = None
        self._replayed = None
        self._fallback = None
        self._tasks: set[asyncio.Task[None]] = set()
        self._lock = asyncio.Lock()
        self._closed = False

    def bind_unplayed_turn_policy(self, *, allow, replayed=None, fallback=None) -> None:
        """Replay an assistant turn that produced no audio at all, once.

        ``allow(turn)`` is the response gate: a turn it withheld is never
        replayed. ``replayed(turn)`` runs after an audible replay (e.g. to save
        it). ``fallback(text)`` speaks another way when scripted TTS fails.
        """
        self._allow_unplayed = allow
        self._replayed = replayed
        self._fallback = fallback

    def observe_turn(self, turn: ConversationTurn) -> None:
        if self._closed or turn.role is not ConversationRole.ASSISTANT:
            return
        task = asyncio.create_task(
            self._recover_turn(turn),
            name=f"jarvis-silent-audio-recovery-{turn.turn_id[:8]}",
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def close(self) -> None:
        self._closed = True
        for task in tuple(self._tasks):
            task.cancel()

    async def _wait_for_next_quality(self) -> PlaybackQualitySnapshot | None:
        deadline = asyncio.get_running_loop().time() + _QUALITY_WAIT_SECONDS
        while not self._closed:
            output = self._output_getter()
            quality = output.last_completed_quality if output is not None else None
            if quality is not None and quality.sequence > self._last_consumed_sequence:
                return quality
            if asyncio.get_running_loop().time() >= deadline:
                return None
            await asyncio.sleep(_QUALITY_POLL_SECONDS)
        return None

    async def _segment_started(self) -> bool | None:
        """True if a playback segment started since the previous turn, False if
        none did within the grace period, None if the output cannot tell."""
        deadline = asyncio.get_running_loop().time() + _NO_AUDIO_GRACE_SECONDS
        while not self._closed:
            output = self._output_getter()
            started = getattr(output, "started_segment_sequence", None)
            if not isinstance(started, int):
                return None
            if started > self._last_started_seen:
                self._last_started_seen = started
                return True
            if asyncio.get_running_loop().time() >= deadline:
                return False
            await asyncio.sleep(_QUALITY_POLL_SECONDS)
        return None

    async def _replay_unplayed(self, turn: ConversationTurn) -> None:
        text = turn.text.strip()
        output = self._output_getter()
        if not text or output is None:
            return
        try:
            allowed = self._allow_unplayed(turn) is True
        except Exception:  # an unknown gate state never speaks
            LOGGER.exception("Unplayed-turn gate check failed")
            allowed = False
        if not allowed:
            LOGGER.info(
                "Assistant turn %s produced no audio and the response gate "
                "withheld it; not replayed",
                turn.turn_id,
            )
            return
        LOGGER.warning(
            "Realtime assistant turn produced no audio | turn_id=%s | "
            "replay=scripted_tts",
            turn.turn_id,
        )
        spoken = False
        speech = None
        try:
            speech = self._speech_factory(self._config)
            await speech.speak(output, text)
            spoken = True
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception(
                "Scripted TTS replay failed for unplayed assistant turn %s",
                turn.turn_id,
            )
        finally:
            if speech is not None:
                await speech.aclose()
        if not spoken and self._fallback is not None:
            self._fallback(text)
        started = getattr(self._output_getter(), "started_segment_sequence", None)
        if isinstance(started, int):
            self._last_started_seen = max(self._last_started_seen, started)
        recovered = output.last_completed_quality
        if recovered is not None:
            self._last_consumed_sequence = max(
                self._last_consumed_sequence, recovered.sequence
            )
        if self._replayed is not None:
            self._replayed(turn)

    async def _recover_turn(self, turn: ConversationTurn) -> None:
        async with self._lock:
            if (
                self._allow_unplayed is not None
                and not turn.interrupted
                and await self._segment_started() is False
            ):
                await self._replay_unplayed(turn)
                return
            quality = await self._wait_for_next_quality()
            if quality is None:
                LOGGER.warning(
                    "Silent-audio recovery could not correlate assistant turn %s "
                    "with completed playback quality",
                    turn.turn_id,
                )
                return

            self._last_consumed_sequence = quality.sequence
            if turn.interrupted or not needs_scripted_recovery(quality):
                return

            output = self._output_getter()
            text = turn.text.strip()
            if output is None or not text:
                return

            LOGGER.warning(
                "Near-silent realtime assistant audio detected | turn_id=%s | "
                "segment=%s | rms_dbfs=%.1f | peak=%s | replay=scripted_tts",
                turn.turn_id,
                quality.sequence,
                quality.rms_dbfs,
                quality.peak_abs,
            )

            speech = self._speech_factory(self._config)
            try:
                await speech.speak(output, text)
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception(
                    "Scripted TTS recovery failed for near-silent assistant turn %s",
                    turn.turn_id,
                )
            finally:
                await speech.aclose()

            recovered = output.last_completed_quality
            if (
                recovered is not None
                and recovered.sequence > self._last_consumed_sequence
            ):
                self._last_consumed_sequence = recovered.sequence
