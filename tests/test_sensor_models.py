from __future__ import annotations

import pytest

from jarvis.sensors import (
    AVSourceDescriptor,
    AVSyncState,
    AVSyncStatus,
    MediaEndpoint,
    MediaKind,
    SensorCapability,
    SensorHealth,
)


def _video() -> MediaEndpoint:
    return MediaEndpoint(MediaKind.VIDEO, "video-1", "Camera")


def _audio() -> MediaEndpoint:
    return MediaEndpoint(MediaKind.AUDIO, "audio-1", "Microphone")


def test_av_source_requires_paired_audio_video_capabilities() -> None:
    with pytest.raises(ValueError, match="audio capability"):
        AVSourceDescriptor(
            source_id="camera-1",
            display_name="Camera 1",
            video_endpoint=_video(),
            audio_endpoint=_audio(),
            capabilities=frozenset({SensorCapability.VIDEO}),
        )


def test_av_source_rejects_swapped_endpoint_kinds() -> None:
    with pytest.raises(ValueError, match="video_endpoint"):
        AVSourceDescriptor(
            source_id="camera-1",
            display_name="Camera 1",
            video_endpoint=_audio(),
            audio_endpoint=_video(),
            capabilities=frozenset(
                {SensorCapability.VIDEO, SensorCapability.AUDIO}
            ),
        )


def test_av_evidence_requires_healthy_source_and_sync() -> None:
    capabilities = frozenset({SensorCapability.VIDEO, SensorCapability.AUDIO})
    healthy = AVSourceDescriptor(
        source_id="camera-1",
        display_name="Camera 1",
        video_endpoint=_video(),
        audio_endpoint=_audio(),
        capabilities=capabilities,
        sync=AVSyncStatus(state=AVSyncState.HEALTHY),
    )
    degraded = AVSourceDescriptor(
        source_id="camera-1",
        display_name="Camera 1",
        video_endpoint=_video(),
        audio_endpoint=_audio(),
        capabilities=capabilities,
        health=SensorHealth.DEGRADED,
        sync=AVSyncStatus(state=AVSyncState.HEALTHY),
    )
    unknown_sync = AVSourceDescriptor(
        source_id="camera-1",
        display_name="Camera 1",
        video_endpoint=_video(),
        audio_endpoint=_audio(),
        capabilities=capabilities,
    )

    assert healthy.usable_for_av_evidence is True
    assert degraded.usable_for_av_evidence is False
    assert unknown_sync.usable_for_av_evidence is False


def test_sync_status_keeps_diagnostics_without_making_them_authoritative() -> None:
    status = AVSyncStatus(
        state=AVSyncState.HEALTHY,
        offset_ms=15.7,
        drift_ppm=2.5,
        reason="measured on source clock",
    )

    assert status.offset_ms == 15.7
    assert status.drift_ppm == 2.5
    assert status.usable_for_av_evidence is True
