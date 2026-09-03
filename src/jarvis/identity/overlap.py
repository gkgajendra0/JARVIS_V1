from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from itertools import pairwise

import numpy as np


class OverlapState(str, Enum):
    SINGLE_SPEAKER = "single_speaker"
    OVERLAP_DETECTED = "overlap_detected"
    SPEAKER_CHANGE = "speaker_change"
    AMBIGUOUS = "ambiguous"
    INSUFFICIENT = "insufficient"


@dataclass(frozen=True, slots=True)
class OverlapEvidence:
    state: OverlapState
    frame_count: int
    speech_frames: int
    overlap_frames: int
    longest_overlap_run: int
    stable_speaker_runs: tuple[tuple[int, int], ...]
    active_speaker_peak: int
    overlap_fraction: float
    threshold: float
    reason_codes: tuple[str, ...] = ()


def _longest_true_run(values: np.ndarray) -> int:
    longest = 0
    current = 0
    for value in values.tolist():
        if bool(value):
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _stable_single_speaker_runs(
    active: np.ndarray,
    *,
    minimum_frames: int,
) -> tuple[tuple[int, int], ...]:
    """Return stable contiguous (speaker_index, frame_count) single-speaker runs."""

    runs: list[tuple[int, int]] = []
    current_speaker: int | None = None
    current_length = 0

    def flush() -> None:
        nonlocal current_speaker, current_length
        if current_speaker is not None and current_length >= minimum_frames:
            runs.append((current_speaker, current_length))
        current_speaker = None
        current_length = 0

    for row in active:
        indices = np.flatnonzero(row)
        if len(indices) != 1:
            flush()
            continue
        speaker = int(indices[0])
        if current_speaker == speaker:
            current_length += 1
        else:
            flush()
            current_speaker = speaker
            current_length = 1
    flush()
    return tuple(runs)


def interpret_sortformer_probabilities(
    probabilities: np.ndarray,
    *,
    threshold: float = 0.5,
    minimum_speech_frames: int = 3,
    minimum_overlap_frames: int = 2,
    minimum_change_run_frames: int = 3,
) -> OverlapEvidence:
    """Convert frame-level speaker activity probabilities into bounded evidence.

    Thresholds here are diagnostic benchmark parameters, not deployment authority
    thresholds. Production values must be frozen only after real JARVIS-machine
    distributions are accepted.
    """

    probs = np.asarray(probabilities, dtype=np.float32)
    if probs.ndim != 2 or probs.shape[1] < 2:
        raise ValueError("probabilities must have shape [frames, speakers>=2]")
    if probs.shape[0] == 0:
        return OverlapEvidence(
            state=OverlapState.INSUFFICIENT,
            frame_count=0,
            speech_frames=0,
            overlap_frames=0,
            longest_overlap_run=0,
            stable_speaker_runs=(),
            active_speaker_peak=0,
            overlap_fraction=0.0,
            threshold=threshold,
            reason_codes=("no_diarization_frames",),
        )
    if not np.isfinite(probs).all():
        raise ValueError("probabilities contain non-finite values")
    if not 0.0 < threshold < 1.0:
        raise ValueError("threshold must be between 0 and 1")
    if minimum_speech_frames < 1:
        raise ValueError("minimum_speech_frames must be positive")
    if minimum_overlap_frames < 1:
        raise ValueError("minimum_overlap_frames must be positive")
    if minimum_change_run_frames < 1:
        raise ValueError("minimum_change_run_frames must be positive")

    active = probs >= threshold
    active_counts = active.sum(axis=1)
    speech_mask = active_counts >= 1
    overlap_mask = active_counts >= 2
    speech_frames = int(speech_mask.sum())
    overlap_frames = int(overlap_mask.sum())
    longest_overlap_run = _longest_true_run(overlap_mask)
    stable_runs = _stable_single_speaker_runs(
        active,
        minimum_frames=minimum_change_run_frames,
    )
    active_peak = int(active_counts.max(initial=0))
    overlap_fraction = (
        float(overlap_frames / speech_frames) if speech_frames > 0 else 0.0
    )

    if speech_frames < minimum_speech_frames:
        state = OverlapState.INSUFFICIENT
        reasons = ("insufficient_speech_activity",)
    elif longest_overlap_run >= minimum_overlap_frames:
        state = OverlapState.OVERLAP_DETECTED
        reasons = ("concurrent_speaker_activity",)
    else:
        speaker_sequence = tuple(speaker for speaker, _ in stable_runs)
        changed = any(
            previous != current for previous, current in pairwise(speaker_sequence)
        )
        if changed:
            state = OverlapState.SPEAKER_CHANGE
            reasons = ("stable_speaker_change",)
        elif stable_runs:
            state = OverlapState.SINGLE_SPEAKER
            reasons = ()
        else:
            state = OverlapState.AMBIGUOUS
            reasons = ("activity_without_stable_single_speaker_run",)

    return OverlapEvidence(
        state=state,
        frame_count=int(probs.shape[0]),
        speech_frames=speech_frames,
        overlap_frames=overlap_frames,
        longest_overlap_run=longest_overlap_run,
        stable_speaker_runs=stable_runs,
        active_speaker_peak=active_peak,
        overlap_fraction=overlap_fraction,
        threshold=threshold,
        reason_codes=reasons,
    )
