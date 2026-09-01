from __future__ import annotations

import pytest

from jarvis.sensors.gstreamer_av import (
    GStreamerPairedAVConfig,
    _mmdevice_id_from_pnp_instance,
    build_pipeline_description,
)
from jarvis.sensors.models import (
    AVSourceDescriptor,
    MediaEndpoint,
    MediaKind,
    SensorCapability,
)


def _source() -> AVSourceDescriptor:
    return AVSourceDescriptor(
        source_id="windows-container:test",
        display_name="OsmoPocket3",
        video_endpoint=MediaEndpoint(
            kind=MediaKind.VIDEO,
            stable_id=r"USB\VID_2CA3&PID_0023&MI_00\camera",
            display_name="OsmoPocket3",
        ),
        audio_endpoint=MediaEndpoint(
            kind=MediaKind.AUDIO,
            stable_id=(
                r"SWD\MMDEVAPI\{0.0.1.00000000}."
                r"{2789c851-7a26-4474-bdd7-c82256ca1fa6}"
            ),
            display_name="Capture Input terminal (OsmoPocket3)",
        ),
        capabilities=frozenset(
            {SensorCapability.VIDEO, SensorCapability.AUDIO}
        ),
        physical_device_id="19310408-e485-53ca-aea4-84f5edd68ed8",
    )


def test_mmdevice_endpoint_id_is_kept_opaque() -> None:
    endpoint = (
        r"SWD\MMDEVAPI\{0.0.1.00000000}."
        r"{2789c851-7a26-4474-bdd7-c82256ca1fa6}"
    )

    assert _mmdevice_id_from_pnp_instance(endpoint) == (
        r"{0.0.1.00000000}.{2789c851-7a26-4474-bdd7-c82256ca1fa6}"
    )


def test_non_mmdevice_endpoint_fails_closed() -> None:
    with pytest.raises(ValueError, match="MMDevice"):
        _mmdevice_id_from_pnp_instance("USB\\not-an-audio-endpoint")


def test_pipeline_captures_paired_video_and_raw_mono_audio_once() -> None:
    pipeline = build_pipeline_description(_source(), GStreamerPairedAVConfig())

    assert 'mfvideosrc device-name="OsmoPocket3"' in pipeline
    assert "video/x-raw,format=NV12,width=1280,height=720,framerate=30/1" in pipeline
    assert "video/x-raw,format=BGR,width=1280,height=720,framerate=30/1" in pipeline
    assert "appsink name=video_sink" in pipeline
    assert (
        'wasapi2src device="{0.0.1.00000000}.'
        '{2789c851-7a26-4474-bdd7-c82256ca1fa6}"'
    ) in pipeline
    assert "provide-clock=true" in pipeline
    assert "audio/x-raw,format=S16LE,rate=48000,channels=1" in pipeline
    assert "audio/x-raw,format=S16LE,rate=16000,channels=1" in pipeline
    assert "appsink name=audio_sink" in pipeline
    assert "clean_audio_sink" not in pipeline
    assert "webrtcechoprobe" not in pipeline


def test_full_duplex_pipeline_keeps_echo_reference_before_render_resampling() -> None:
    render_id = r"{0.0.0.00000000}.{e3d2566b-352f-4c62-ac3c-f3d8f790ff87}"
    pipeline = build_pipeline_description(
        _source(),
        GStreamerPairedAVConfig(
            audio_rate=48_000,
            playback_device_id=render_id,
        ),
    )

    assert "appsrc name=playback_src" in pipeline
    assert "webrtcechoprobe name=echo_probe" in pipeline
    assert "webrtcdsp name=aec_dsp probe=echo_probe echo-cancel=true" in pipeline
    assert "noise-suppression=false" in pipeline
    assert "gain-control=false" in pipeline
    assert "high-pass-filter=false" in pipeline
    assert "appsink name=clean_audio_sink" in pipeline
    assert f'wasapi2sink device="{render_id}" low-latency=true' in pipeline

    probe_index = pipeline.index("webrtcechoprobe name=echo_probe")
    render_resample_index = pipeline.index("audioresample", probe_index)
    render_sink_index = pipeline.index("wasapi2sink", render_resample_index)
    assert probe_index < render_resample_index < render_sink_index

    raw_sink_index = pipeline.index("appsink name=audio_sink")
    clean_sink_index = pipeline.index("appsink name=clean_audio_sink")
    assert raw_sink_index != clean_sink_index


def test_config_rejects_non_positive_values_and_empty_render_endpoint() -> None:
    with pytest.raises(ValueError):
        GStreamerPairedAVConfig(width=0)
    with pytest.raises(ValueError):
        GStreamerPairedAVConfig(audio_rate=0)
    with pytest.raises(ValueError, match="playback device"):
        GStreamerPairedAVConfig(playback_device_id="   ")
