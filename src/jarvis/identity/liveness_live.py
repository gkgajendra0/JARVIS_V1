from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import cv2
import numpy as np
from livekit import rtc

from jarvis.authority import WindowsWtsSessionProvider
from jarvis.config import JarvisConfig
from jarvis.identity.calibration import _build_runtime, _draw_clickable_heads
from jarvis.identity.live_face_benchmark import _crop_head, _SelectionState
from jarvis.identity.liveness import (
    ActiveLivenessChallenge,
    LivenessAction,
    LivenessObservation,
    LivenessPhase,
)
from jarvis.identity.liveness_assets import ensure_face_landmarker_model
from jarvis.identity.liveness_mediapipe import MediaPipeFaceLandmarker
from jarvis.vision.models import TargetState
from jarvis.vision.observer import render_snapshot
from jarvis.voice.audio import (
    DEVICE_CHANNELS,
    DEVICE_SAMPLE_RATE,
    FRAME_SAMPLES,
    LocalAudioOutput,
    LocalAudioRuntime,
)
from jarvis.voice.scripted_speech import ScriptedSpeech, build_scripted_speech

_WINDOW_NAME = "JARVIS Active Liveness"
_ANALYSIS_INTERVAL_SECONDS = 0.08
_TARGET_LOST_TIMEOUT_SECONDS = 0.75
_HEAD_LOST_TIMEOUT_SECONDS = 1.00
_CHALLENGE_TTL_SECONDS = 45.0


@dataclass(slots=True)
class _DiagnosticStats:
    valid_observations: int = 0
    max_blink_pair: float = 0.0
    max_jaw_open: float = 0.0
    max_smile_pair: float = 0.0

    def update(self, values: dict[str, float]) -> None:
        canonical = {
            "".join(
                character for character in name.lower() if character.isalnum()
            ): score
            for name, score in values.items()
        }
        blink = min(
            canonical.get("eyeblinkleft", 0.0),
            canonical.get("eyeblinkright", 0.0),
        )
        smile = min(
            canonical.get("mouthsmileleft", 0.0),
            canonical.get("mouthsmileright", 0.0),
        )
        self.valid_observations += 1
        self.max_blink_pair = max(self.max_blink_pair, blink)
        self.max_jaw_open = max(self.max_jaw_open, canonical.get("jawopen", 0.0))
        self.max_smile_pair = max(self.max_smile_pair, smile)


class _VoicePrompter:
    """Output-only deterministic speech for the liveness diagnostic."""

    def __init__(self, config: JarvisConfig) -> None:
        self._config = config
        self._output: LocalAudioOutput | None = None
        self._speech: ScriptedSpeech | None = None
        self._disabled = False

    @property
    def enabled(self) -> bool:
        return (
            not self._disabled and self._output is not None and self._speech is not None
        )

    async def start(self) -> None:
        media_devices = rtc.MediaDevices(
            input_sample_rate=DEVICE_SAMPLE_RATE,
            output_sample_rate=DEVICE_SAMPLE_RATE,
            num_channels=DEVICE_CHANNELS,
            blocksize=FRAME_SAMPLES,
        )
        output_device = LocalAudioRuntime._resolve_device(
            media_devices.list_output_devices(),
            self._config.audio_output_device,
            kind="output",
        )
        self._output = LocalAudioOutput(output_device=output_device)
        self._output.start()
        self._speech = build_scripted_speech(self._config)

    async def speak(self, text: str) -> None:
        if self._disabled:
            return
        if self._output is None or self._speech is None:
            self._disabled = True
            return
        try:
            await self._speech.speak(self._output, text)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._disabled = True
            print(
                "Voice prompt failed; continuing with compact on-screen prompts only: "
                f"{type(exc).__name__}: {exc}"
            )

    async def aclose(self) -> None:
        if self._speech is not None:
            try:
                await self._speech.aclose()
            finally:
                self._speech = None
        if self._output is not None:
            await self._output.aclose()
            self._output = None


@dataclass(frozen=True, slots=True)
class _PromptState:
    action_index: int
    action: LivenessAction | None
    phase: LivenessPhase


def _visual_prompt(action: LivenessAction | None, phase: LivenessPhase) -> str:
    if phase is LivenessPhase.WAIT_NEUTRAL:
        if action is LivenessAction.BLINK:
            return "Keep both eyes open"
        if action is LivenessAction.OPEN_MOUTH:
            return "Keep your mouth closed"
        return "Neutral expression"
    if phase is LivenessPhase.WAIT_ACTION:
        if action is LivenessAction.BLINK:
            return "BLINK NOW"
        if action is LivenessAction.OPEN_MOUTH:
            return "OPEN YOUR MOUTH NOW"
        return "SMILE NOW"
    if phase is LivenessPhase.WAIT_RELEASE:
        return "Return to neutral"
    if phase is LivenessPhase.PASSED:
        return "LIVENESS PASSED"
    return "LIVENESS FAILED"


def _spoken_prompt(action: LivenessAction | None, phase: LivenessPhase) -> str:
    if phase is LivenessPhase.WAIT_NEUTRAL:
        if action is LivenessAction.BLINK:
            return "Keep your eyes open and look at me, sir."
        if action is LivenessAction.OPEN_MOUTH:
            return "Keep your mouth closed and look at me, sir."
        return "Keep a neutral expression and look at me, sir."
    if phase is LivenessPhase.WAIT_ACTION:
        if action is LivenessAction.BLINK:
            return "Blink now, sir."
        if action is LivenessAction.OPEN_MOUTH:
            return "Open your mouth now, sir."
        return "Smile now, sir."
    if phase is LivenessPhase.WAIT_RELEASE:
        return "Thank you. Relax."
    if phase is LivenessPhase.PASSED:
        return "Liveness confirmed, sir."
    return "Liveness check failed, sir."


def _draw_overlay(
    preview: np.ndarray,
    *,
    challenge: ActiveLivenessChallenge | None,
    stats: _DiagnosticStats,
    selected_track_id: int | None,
) -> None:
    if challenge is None:
        lines = [
            "3B.7 VOICE-GUIDED LIVENESS | click GREEN HEAD once",
            "Press S when ready | C clear | Q abort",
        ]
    else:
        progress = challenge.progress
        total = len(challenge.challenge.actions)
        current = min(progress.action_index + 1, total)
        lines = [
            (
                f"TRACK {selected_track_id} | {current}/{total} | "
                f"{progress.phase.value.upper()}"
            ),
            _visual_prompt(progress.action, progress.phase),
            (
                f"blink {stats.max_blink_pair:.2f} | jaw {stats.max_jaw_open:.2f} | "
                f"smile {stats.max_smile_pair:.2f}"
            ),
        ]
    for index, line in enumerate(lines):
        cv2.putText(
            preview,
            line,
            (14, 26 + index * 24),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.54,
            (0, 255, 255),
            1,
            cv2.LINE_AA,
        )


async def run_live_liveness() -> int:
    session_provider = WindowsWtsSessionProvider()
    session = session_provider.current_session()
    if not session.active_unlocked:
        print("Active liveness requires an active, unlocked Windows session.")
        return 2

    config = JarvisConfig.from_environment()
    model_path = ensure_face_landmarker_model()
    print("JARVIS Step 3B.7 active liveness")
    print("---------------------------------")
    print(f"Windows session: {session.session_id}")
    print(f"Pinned Face Landmarker: {model_path}")
    print("Camera/PTZ is READ-ONLY for this diagnostic; PTZ is never armed or moved.")
    print(
        "Voice prompts use the configured JARVIS scripted-speech provider and speaker."
    )
    print("Click one GREEN associated head once, then press S when ready.")
    print(
        "Only the current challenge step is shown; the full sequence stays undisclosed."
    )
    print("No frame, landmark, blendshape vector, or liveness sample is persisted.")

    runtime, framing_policy = _build_runtime()
    selection = _SelectionState()
    voice = _VoicePrompter(config)
    challenge: ActiveLivenessChallenge | None = None
    stats = _DiagnosticStats()
    started_at: float | None = None
    last_analysis_at: float | None = None
    last_visible_target_at: float | None = None
    last_associated_head_at: float | None = None
    final_phase: LivenessPhase | None = None
    final_reasons: tuple[str, ...] = ()
    announced_state: _PromptState | None = None

    try:
        try:
            await voice.start()
        except Exception as exc:
            print(
                "Voice prompt setup failed; continuing with compact on-screen prompts only: "
                f"{type(exc).__name__}: {exc}"
            )

        cv2.namedWindow(_WINDOW_NAME)
        cv2.setMouseCallback(_WINDOW_NAME, selection.on_mouse)

        try:
            with MediaPipeFaceLandmarker(model_path) as landmarker:
                runtime.start()
                while True:
                    snapshot = runtime.process_once(timeout_seconds=1.0)
                    if snapshot is None:
                        if challenge is not None:
                            progress = challenge.check_timeout(time.monotonic())
                            if progress.terminal:
                                final_phase = progress.phase
                                final_reasons = progress.reason_codes
                                break
                        continue
                    frame = runtime.latest_frame
                    if frame is None:
                        continue

                    clickable_head_regions = []
                    heads = list(snapshot.heads)
                    for track in snapshot.tracks:
                        if not runtime.head_lock_eligible(track.track_id):
                            continue
                        candidate = TargetState(track_id=track.track_id, track=track)
                        associated = framing_policy.associated_head(candidate, heads)
                        if associated is not None:
                            clickable_head_regions.append(
                                (track.track_id, associated.bounds)
                            )

                    selection.update(
                        snapshot.tracks,
                        head_regions=clickable_head_regions,
                        width=frame.width,
                        height=frame.height,
                    )
                    if selection.clicked_track_id is not None:
                        requested_track = selection.clicked_track_id
                        selection.clicked_track_id = None
                        if challenge is not None:
                            print(
                                "Challenge is active; target changes are not allowed."
                            )
                        else:
                            try:
                                runtime.lock(requested_track)
                                print(
                                    f"Locked track {requested_track}; press S when ready."
                                )
                                await voice.speak(
                                    "Target locked. Press S when you are ready, sir."
                                )
                            except ValueError as exc:
                                print(exc)

                    target = runtime.target
                    now = frame.captured_at
                    if target is not None and target.visible:
                        last_visible_target_at = now
                    associated_head = framing_policy.associated_head(target, heads)
                    if (
                        associated_head is not None
                        and target is not None
                        and target.visible
                    ):
                        last_associated_head_at = now

                    if challenge is not None:
                        progress = challenge.progress
                        prompt_state = _PromptState(
                            action_index=progress.action_index,
                            action=progress.action,
                            phase=progress.phase,
                        )
                        if prompt_state != announced_state and not progress.terminal:
                            announced_state = prompt_state
                            await voice.speak(
                                _spoken_prompt(progress.action, progress.phase)
                            )

                        current_session = session_provider.current_session()
                        if (
                            current_session.session_id != session.session_id
                            or not current_session.active_unlocked
                        ):
                            progress = challenge.fail("windows_session_changed")
                            final_phase = progress.phase
                            final_reasons = progress.reason_codes
                            break
                        if (
                            target is None
                            or target.track_id != challenge.challenge.visual_track_id
                        ):
                            progress = challenge.fail("visual_track_changed")
                            final_phase = progress.phase
                            final_reasons = progress.reason_codes
                            break
                        if (
                            last_visible_target_at is None
                            or now - last_visible_target_at
                            > _TARGET_LOST_TIMEOUT_SECONDS
                        ):
                            progress = challenge.fail("target_lost")
                            final_phase = progress.phase
                            final_reasons = progress.reason_codes
                            break
                        if (
                            last_associated_head_at is None
                            or now - last_associated_head_at
                            > _HEAD_LOST_TIMEOUT_SECONDS
                        ):
                            progress = challenge.fail("associated_head_lost")
                            final_phase = progress.phase
                            final_reasons = progress.reason_codes
                            break

                        should_analyze = (
                            associated_head is not None
                            and target.visible
                            and (
                                last_analysis_at is None
                                or now - last_analysis_at >= _ANALYSIS_INTERVAL_SECONDS
                            )
                        )
                        if should_analyze:
                            last_analysis_at = now
                            crop = _crop_head(
                                frame.image,
                                associated_head.bounds,
                                margin_fraction=0.35,
                            )
                            observed = landmarker.observe(
                                crop.image,
                                observed_at_monotonic=now,
                            )
                            if observed is not None:
                                stats.update(observed.blendshapes)
                                progress = challenge.observe(
                                    LivenessObservation(
                                        session_id=session.session_id,
                                        visual_track_id=target.track_id,
                                        observed_at_monotonic=(
                                            observed.observed_at_monotonic
                                        ),
                                        blendshapes=observed.blendshapes,
                                    )
                                )
                                if progress.terminal:
                                    final_phase = progress.phase
                                    final_reasons = progress.reason_codes
                                    break
                        progress = challenge.check_timeout(now)
                        if progress.terminal:
                            final_phase = progress.phase
                            final_reasons = progress.reason_codes
                            break

                    preview = render_snapshot(frame.image, snapshot)
                    _draw_clickable_heads(preview, clickable_head_regions)
                    _draw_overlay(
                        preview,
                        challenge=challenge,
                        stats=stats,
                        selected_track_id=(
                            target.track_id if target is not None else None
                        ),
                    )
                    cv2.imshow(_WINDOW_NAME, preview)

                    key = cv2.waitKey(1) & 0xFF
                    if key in (ord("q"), ord("Q"), 27):
                        print("STEP_3B7_ACTIVE_LIVENESS = ABORTED")
                        return 2
                    if key in (ord("c"), ord("C")) and challenge is None:
                        runtime.clear_target()
                        print("Selected target cleared.")
                    if key in (ord("s"), ord("S")) and challenge is None:
                        target = runtime.target
                        if target is None or not target.visible:
                            print(
                                "Lock one visible GREEN associated head before starting."
                            )
                            continue
                        if framing_policy.associated_head(target, heads) is None:
                            print(
                                "Selected track does not currently have an associated head."
                            )
                            continue
                        challenge = ActiveLivenessChallenge.create(
                            session_id=session.session_id,
                            visual_track_id=target.track_id,
                            now_monotonic=now,
                            ttl_seconds=_CHALLENGE_TTL_SECONDS,
                        )
                        stats = _DiagnosticStats()
                        started_at = now
                        last_analysis_at = None
                        last_visible_target_at = now
                        last_associated_head_at = now
                        announced_state = None
                        print(
                            f"Challenge started on track {target.track_id}; "
                            "follow JARVIS voice prompts."
                        )
        finally:
            runtime.close()
            cv2.destroyAllWindows()

        print()
        print("ACTIVE LIVENESS SUMMARY")
        if challenge is None or final_phase is None:
            print("STEP_3B7_ACTIVE_LIVENESS = ABORTED")
            return 2
        elapsed = 0.0 if started_at is None else max(0.0, time.monotonic() - started_at)
        print(f"challenge_id = {challenge.challenge.challenge_id}")
        print(f"visual_track_id = {challenge.challenge.visual_track_id}")
        print(
            "sequence = "
            + " -> ".join(
                action.value.upper() for action in challenge.challenge.actions
            )
        )
        print(
            f"completed_actions = "
            f"{[action.value for action in challenge.progress.completed_actions]}"
        )
        print(f"valid_landmarker_observations = {stats.valid_observations}")
        print(f"max_blink_pair = {stats.max_blink_pair:.3f}")
        print(f"max_jaw_open = {stats.max_jaw_open:.3f}")
        print(f"max_smile_pair = {stats.max_smile_pair:.3f}")
        print(f"elapsed_seconds = {elapsed:.2f}")
        print(f"reason_codes = {final_reasons}")
        print(f"voice_guidance_enabled = {voice.enabled}")
        print("frames_saved = False")
        print("landmarks_saved = False")
        print("blendshape_vectors_saved = False")
        print("face_evidence_grants_T2 = False")

        if final_phase is LivenessPhase.PASSED:
            evidence = challenge.to_identity_evidence()
            print(f"liveness_evidence_verdict = {evidence.verdict.value}")
            print(
                "liveness_evidence_ttl_seconds = "
                f"{evidence.expires_at_monotonic - evidence.observed_at_monotonic:.1f}"
            )
            await voice.speak("Liveness confirmed, sir.")
            print("STEP_3B7_ACTIVE_LIVENESS = PASS")
            return 0

        await voice.speak("Liveness check failed, sir.")
        print("STEP_3B7_ACTIVE_LIVENESS = FAIL")
        return 3
    finally:
        await voice.aclose()


def main() -> None:
    raise SystemExit(asyncio.run(run_live_liveness()))


if __name__ == "__main__":
    main()
