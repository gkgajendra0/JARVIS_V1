from __future__ import annotations

import pytest

from jarvis.authority import EvidenceModality, EvidenceVerdict
from jarvis.identity.liveness import (
    ActiveLivenessChallenge,
    LivenessAction,
    LivenessObservation,
    LivenessPhase,
)


def _observation(
    *,
    at: float,
    values: dict[str, float],
    session_id: str = "wts:3",
    track_id: int = 7,
) -> LivenessObservation:
    return LivenessObservation(
        session_id=session_id,
        visual_track_id=track_id,
        observed_at_monotonic=at,
        blendshapes=values,
    )


def _feed_twice(
    challenge: ActiveLivenessChallenge,
    *,
    start: float,
    values: dict[str, float],
) -> None:
    challenge.observe(_observation(at=start, values=values))
    challenge.observe(_observation(at=start + 0.01, values=values))


def test_randomized_challenge_can_pass_all_supported_actions() -> None:
    challenge = ActiveLivenessChallenge.create(
        session_id="wts:3",
        visual_track_id=7,
        now_monotonic=100.0,
        ttl_seconds=20.0,
        actions=(
            LivenessAction.BLINK,
            LivenessAction.OPEN_MOUTH,
            LivenessAction.SMILE,
        ),
    )

    _feed_twice(
        challenge,
        start=100.1,
        values={"eyeBlinkLeft": 0.05, "eyeBlinkRight": 0.05},
    )
    _feed_twice(
        challenge,
        start=100.2,
        values={"eyeBlinkLeft": 0.85, "eyeBlinkRight": 0.88},
    )
    _feed_twice(
        challenge,
        start=100.3,
        values={"eyeBlinkLeft": 0.04, "eyeBlinkRight": 0.03},
    )

    _feed_twice(challenge, start=100.4, values={"jawOpen": 0.05})
    _feed_twice(challenge, start=100.5, values={"jawOpen": 0.78})
    _feed_twice(challenge, start=100.6, values={"jawOpen": 0.08})

    _feed_twice(
        challenge,
        start=100.7,
        values={"mouthSmileLeft": 0.08, "mouthSmileRight": 0.10},
    )
    _feed_twice(
        challenge,
        start=100.8,
        values={"mouthSmileLeft": 0.72, "mouthSmileRight": 0.75},
    )
    _feed_twice(
        challenge,
        start=100.9,
        values={"mouthSmileLeft": 0.10, "mouthSmileRight": 0.12},
    )

    progress = challenge.progress
    assert progress.phase is LivenessPhase.PASSED
    assert progress.completed_actions == (
        LivenessAction.BLINK,
        LivenessAction.OPEN_MOUTH,
        LivenessAction.SMILE,
    )

    evidence = challenge.to_identity_evidence(evidence_ttl_seconds=8.0)
    assert evidence.modality is EvidenceModality.FACE_LIVENESS
    assert evidence.verdict is EvidenceVerdict.PASSED
    assert evidence.visual_track_id == 7
    assert evidence.expires_at_monotonic - evidence.observed_at_monotonic == 8.0


def test_static_action_without_neutral_transition_does_not_pass() -> None:
    challenge = ActiveLivenessChallenge.create(
        session_id="wts:3",
        visual_track_id=7,
        now_monotonic=10.0,
        ttl_seconds=5.0,
        actions=(LivenessAction.SMILE,),
    )

    for offset in range(10):
        challenge.observe(
            _observation(
                at=10.0 + offset * 0.1,
                values={"mouthSmileLeft": 0.9, "mouthSmileRight": 0.9},
            )
        )

    assert challenge.progress.phase is LivenessPhase.WAIT_NEUTRAL


def test_visual_track_switch_fails_closed() -> None:
    challenge = ActiveLivenessChallenge.create(
        session_id="wts:3",
        visual_track_id=7,
        now_monotonic=10.0,
        actions=(LivenessAction.BLINK,),
    )

    progress = challenge.observe(
        _observation(
            at=10.1,
            track_id=8,
            values={"eyeBlinkLeft": 0.05, "eyeBlinkRight": 0.05},
        )
    )

    assert progress.phase is LivenessPhase.FAILED
    assert progress.reason_codes == ("visual_track_mismatch",)


def test_session_switch_fails_closed() -> None:
    challenge = ActiveLivenessChallenge.create(
        session_id="wts:3",
        visual_track_id=7,
        now_monotonic=10.0,
        actions=(LivenessAction.BLINK,),
    )

    progress = challenge.observe(
        _observation(
            at=10.1,
            session_id="wts:4",
            values={"eyeBlinkLeft": 0.05, "eyeBlinkRight": 0.05},
        )
    )

    assert progress.phase is LivenessPhase.FAILED
    assert progress.reason_codes == ("session_mismatch",)


def test_expired_challenge_fails_closed_and_cannot_create_evidence() -> None:
    challenge = ActiveLivenessChallenge.create(
        session_id="wts:3",
        visual_track_id=7,
        now_monotonic=10.0,
        ttl_seconds=1.0,
        actions=(LivenessAction.BLINK,),
    )

    progress = challenge.check_timeout(11.01)

    assert progress.phase is LivenessPhase.FAILED
    assert progress.reason_codes == ("challenge_expired",)
    with pytest.raises(RuntimeError):
        challenge.to_identity_evidence()
