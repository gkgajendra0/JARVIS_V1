from __future__ import annotations

import pytest

from jarvis.identity.active_speaker_paired_live import _insufficient, _select_source
from jarvis.sensors.models import (
    AVSourceDescriptor,
    MediaEndpoint,
    MediaKind,
    SensorCapability,
)


def _source(source_id: str) -> AVSourceDescriptor:
    return AVSourceDescriptor(
        source_id=source_id,
        display_name="Pocket3",
        video_endpoint=MediaEndpoint(MediaKind.VIDEO, "video-id", "Pocket3"),
        audio_endpoint=MediaEndpoint(MediaKind.AUDIO, "audio-id", "Pocket3 Mic"),
        capabilities=frozenset({SensorCapability.VIDEO, SensorCapability.AUDIO}),
    )


def test_select_source_requires_unique_source_without_explicit_id() -> None:
    first = _source("one")
    second = _source("two")

    with pytest.raises(RuntimeError, match="exactly one paired AV source"):
        _select_source((first, second), None)

    assert _select_source((first, second), "two") is second


def test_insufficient_result_never_promotes_authority_or_prototype() -> None:
    source = _source("one")

    result = _insufficient(
        label="tv-speaking",
        source=source,
        pipeline_clock="GstAudioSrcClock",
        reason="paired_visual_window_insufficient",
    )

    assert result["state"] == "insufficient"
    assert result["active_speaker_confirmed"] is False
    assert result["prototype_admission"] is False
