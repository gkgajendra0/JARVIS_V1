"""Provider-neutral sensor metadata and A/V synchronization contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class MediaKind(StrEnum):
    VIDEO = "video"
    AUDIO = "audio"


class SensorCapability(StrEnum):
    VIDEO = "video"
    AUDIO = "audio"
    PTZ = "ptz"
    FIXED = "fixed"
    DEPTH = "depth"
    INFRARED = "infrared"


class SensorHealth(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class AVSyncState(StrEnum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass(frozen=True, slots=True)
class MediaEndpoint:
    kind: MediaKind
    stable_id: str
    display_name: str

    def __post_init__(self) -> None:
        if not self.stable_id.strip():
            raise ValueError("media endpoint stable_id must not be empty")
        if not self.display_name.strip():
            raise ValueError("media endpoint display_name must not be empty")


@dataclass(frozen=True, slots=True)
class AVSyncStatus:
    state: AVSyncState = AVSyncState.UNKNOWN
    offset_ms: float | None = None
    drift_ppm: float | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.reason is not None and not self.reason.strip():
            raise ValueError("sync reason must be meaningful when provided")

    @property
    def usable_for_av_evidence(self) -> bool:
        return self.state is AVSyncState.HEALTHY


@dataclass(frozen=True, slots=True)
class AVSourceDescriptor:
    """Identity and health for one physical paired audio/video source.

    This is intentionally metadata-only. It does not own capture devices and is
    safe to introduce before any existing JARVIS camera/audio runtime is changed.
    """

    source_id: str
    display_name: str
    video_endpoint: MediaEndpoint
    audio_endpoint: MediaEndpoint
    capabilities: frozenset[SensorCapability]
    health: SensorHealth = SensorHealth.HEALTHY
    sync: AVSyncStatus = AVSyncStatus()
    physical_device_id: str | None = None

    def __post_init__(self) -> None:
        if not self.source_id.strip():
            raise ValueError("source_id must not be empty")
        if not self.display_name.strip():
            raise ValueError("source display_name must not be empty")
        if self.video_endpoint.kind is not MediaKind.VIDEO:
            raise ValueError("video_endpoint must be a video endpoint")
        if self.audio_endpoint.kind is not MediaKind.AUDIO:
            raise ValueError("audio_endpoint must be an audio endpoint")
        if SensorCapability.VIDEO not in self.capabilities:
            raise ValueError("AV source must declare video capability")
        if SensorCapability.AUDIO not in self.capabilities:
            raise ValueError("AV source must declare audio capability")
        if self.physical_device_id is not None and not self.physical_device_id.strip():
            raise ValueError("physical_device_id must be meaningful when provided")

    @property
    def usable_for_av_evidence(self) -> bool:
        return self.health is SensorHealth.HEALTHY and self.sync.usable_for_av_evidence
