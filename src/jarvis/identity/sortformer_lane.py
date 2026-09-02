from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class LanePhase:
    name: str
    start_seconds: float
    end_seconds: float

    def __post_init__(self) -> None:
        if self.start_seconds < 0.0 or self.end_seconds <= self.start_seconds:
            raise ValueError("lane phase must have a positive time range")


@dataclass(frozen=True, slots=True)
class LanePhaseStats:
    dominant_lane: int
    mean_probabilities: tuple[float, ...]
    active_fractions: tuple[float, ...]
    frame_count: int


@dataclass(frozen=True, slots=True)
class OwnerLaneAnalysis:
    owner_lane: int
    phone_lane: int
    owner_lane_reacquired: bool
    phone_lane_stable: bool
    owner_phone_lanes_distinct: bool
    overlap_concurrent_fraction: float
    owner_first_onset_available_ms: float | None
    owner_reacquire_available_ms: float | None
    owner_first_offset_available_ms: float | None
    owner_overlap_offset_available_ms: float | None
    phase_stats: Mapping[str, LanePhaseStats]

    @property
    def functional_pass(self) -> bool:
        return (
            self.owner_phone_lanes_distinct
            and self.owner_lane_reacquired
            and self.phone_lane_stable
            and self.overlap_concurrent_fraction > 0.0
        )


def _phase_frame_mask(
    frame_count: int,
    *,
    seconds_per_frame: float,
    phase: LanePhase,
) -> np.ndarray:
    centers = (np.arange(frame_count, dtype=np.float64) + 0.5) * seconds_per_frame
    return (centers >= phase.start_seconds) & (centers < phase.end_seconds)


def summarize_phase(
    probabilities: np.ndarray,
    *,
    seconds_per_frame: float,
    phase: LanePhase,
    threshold: float,
) -> LanePhaseStats:
    matrix = np.asarray(probabilities, dtype=np.float32)
    if matrix.ndim != 2 or matrix.shape[0] == 0 or matrix.shape[1] < 2:
        raise ValueError("probabilities must be non-empty [frames, speakers]")
    if seconds_per_frame <= 0.0:
        raise ValueError("seconds_per_frame must be positive")
    if not 0.0 < threshold < 1.0:
        raise ValueError("threshold must be in (0,1)")

    mask = _phase_frame_mask(
        matrix.shape[0],
        seconds_per_frame=seconds_per_frame,
        phase=phase,
    )
    selected = matrix[mask]
    if selected.shape[0] == 0:
        raise ValueError(f"phase {phase.name} contains no labeled frames")
    means = np.mean(selected, axis=0)
    active = np.mean(selected >= threshold, axis=0)
    order = np.lexsort((means, active))
    dominant = int(order[-1])
    return LanePhaseStats(
        dominant_lane=dominant,
        mean_probabilities=tuple(float(item) for item in means),
        active_fractions=tuple(float(item) for item in active),
        frame_count=int(selected.shape[0]),
    )


def _first_active_availability_ms(
    probabilities: np.ndarray,
    availability_seconds: np.ndarray,
    *,
    lane: int,
    seconds_per_frame: float,
    phase: LanePhase,
    threshold: float,
) -> float | None:
    mask = _phase_frame_mask(
        probabilities.shape[0],
        seconds_per_frame=seconds_per_frame,
        phase=phase,
    )
    indexes = np.flatnonzero(mask & (probabilities[:, lane] >= threshold))
    if indexes.size == 0:
        return None
    available = float(availability_seconds[int(indexes[0])])
    if not np.isfinite(available):
        return None
    return max(0.0, (available - phase.start_seconds) * 1000.0)


def _inactive_availability_ms(
    probabilities: np.ndarray,
    availability_seconds: np.ndarray,
    *,
    lane: int,
    seconds_per_frame: float,
    boundary_seconds: float,
    threshold: float,
    consecutive_frames: int,
) -> float | None:
    if consecutive_frames <= 0:
        raise ValueError("consecutive_frames must be positive")
    frame_centers = (
        np.arange(probabilities.shape[0], dtype=np.float64) + 0.5
    ) * seconds_per_frame
    eligible = np.flatnonzero(frame_centers >= boundary_seconds)
    if eligible.size < consecutive_frames:
        return None
    below = probabilities[:, lane] < threshold
    for end_position in range(consecutive_frames - 1, eligible.size):
        window = eligible[end_position - consecutive_frames + 1 : end_position + 1]
        if bool(np.all(below[window])):
            available = float(np.max(availability_seconds[window]))
            if np.isfinite(available):
                return max(0.0, (available - boundary_seconds) * 1000.0)
    return None


def analyze_owner_lane_sequence(
    probabilities: np.ndarray,
    availability_seconds: np.ndarray,
    *,
    seconds_per_frame: float,
    phases: Mapping[str, LanePhase],
    threshold: float = 0.5,
    inactive_consecutive_frames: int = 3,
) -> OwnerLaneAnalysis:
    required = (
        "A1_OWNER_ONLY",
        "B1_PHONE_ONLY",
        "G_OWNER_PLUS_PHONE",
        "B2_PHONE_ONLY",
        "A2_OWNER_ONLY",
    )
    missing = [name for name in required if name not in phases]
    if missing:
        raise ValueError("missing required lane phases: " + ", ".join(missing))

    matrix = np.asarray(probabilities, dtype=np.float32)
    availability = np.asarray(availability_seconds, dtype=np.float64).reshape(-1)
    if matrix.ndim != 2 or matrix.shape[0] == 0:
        raise ValueError("probabilities must be non-empty [frames, speakers]")
    if availability.size != matrix.shape[0]:
        raise ValueError("availability_seconds must align with probability frames")

    stats = {
        name: summarize_phase(
            matrix,
            seconds_per_frame=seconds_per_frame,
            phase=phases[name],
            threshold=threshold,
        )
        for name in required
    }
    owner_lane = stats["A1_OWNER_ONLY"].dominant_lane
    phone_lane = stats["B1_PHONE_ONLY"].dominant_lane

    overlap_mask = _phase_frame_mask(
        matrix.shape[0],
        seconds_per_frame=seconds_per_frame,
        phase=phases["G_OWNER_PLUS_PHONE"],
    )
    overlap_selected = matrix[overlap_mask]
    concurrent_fraction = float(
        np.mean(
            (overlap_selected[:, owner_lane] >= threshold)
            & (overlap_selected[:, phone_lane] >= threshold)
        )
    )

    return OwnerLaneAnalysis(
        owner_lane=owner_lane,
        phone_lane=phone_lane,
        owner_lane_reacquired=(stats["A2_OWNER_ONLY"].dominant_lane == owner_lane),
        phone_lane_stable=(stats["B2_PHONE_ONLY"].dominant_lane == phone_lane),
        owner_phone_lanes_distinct=(owner_lane != phone_lane),
        overlap_concurrent_fraction=concurrent_fraction,
        owner_first_onset_available_ms=_first_active_availability_ms(
            matrix,
            availability,
            lane=owner_lane,
            seconds_per_frame=seconds_per_frame,
            phase=phases["A1_OWNER_ONLY"],
            threshold=threshold,
        ),
        owner_reacquire_available_ms=_first_active_availability_ms(
            matrix,
            availability,
            lane=owner_lane,
            seconds_per_frame=seconds_per_frame,
            phase=phases["A2_OWNER_ONLY"],
            threshold=threshold,
        ),
        owner_first_offset_available_ms=_inactive_availability_ms(
            matrix,
            availability,
            lane=owner_lane,
            seconds_per_frame=seconds_per_frame,
            boundary_seconds=phases["A1_OWNER_ONLY"].end_seconds,
            threshold=threshold,
            consecutive_frames=inactive_consecutive_frames,
        ),
        owner_overlap_offset_available_ms=_inactive_availability_ms(
            matrix,
            availability,
            lane=owner_lane,
            seconds_per_frame=seconds_per_frame,
            boundary_seconds=phases["G_OWNER_PLUS_PHONE"].end_seconds,
            threshold=threshold,
            consecutive_frames=inactive_consecutive_frames,
        ),
        phase_stats=stats,
    )
