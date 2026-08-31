from __future__ import annotations

from jarvis.sensors.models import AVSyncState
from jarvis.sensors.windows_discovery import (
    WindowsDeviceNode,
    build_av_sources,
)

_CONTAINER = "{19310408-E485-53CA-AEA4-84F5EDD68ED8}"


def _node(pnp_class: str, name: str, instance_id: str, container: str = _CONTAINER):
    return WindowsDeviceNode(
        pnp_class=pnp_class,
        friendly_name=name,
        instance_id=instance_id,
        container_id=container,
    )


def test_same_container_pairs_camera_with_wasapi_capture_only() -> None:
    nodes = [
        _node("Camera", "OsmoPocket3", r"USB\CAMERA"),
        _node(
            "AudioEndpoint",
            "Capture Input terminal (OsmoPocket3)",
            r"SWD\MMDEVAPI\CAPTURE",
        ),
        _node(
            "AudioEndpoint",
            "Speakers (OsmoPocket3)",
            r"SWD\MMDEVAPI\RENDER",
        ),
        _node("MEDIA", "OsmoPocket3", r"USB\MEDIA"),
    ]

    sources = build_av_sources(
        nodes,
        wasapi_input_names={"Capture Input terminal (OsmoPocket3)"},
    )

    assert len(sources) == 1
    source = sources[0]
    assert source.display_name == "OsmoPocket3"
    assert source.video_endpoint.stable_id == r"USB\CAMERA"
    assert source.audio_endpoint.stable_id == r"SWD\MMDEVAPI\CAPTURE"
    assert source.physical_device_id == "19310408-e485-53ca-aea4-84f5edd68ed8"
    assert source.sync.state is AVSyncState.UNKNOWN
    assert source.usable_for_av_evidence is False


def test_different_containers_do_not_cross_pair() -> None:
    nodes = [
        _node("Camera", "Camera", r"USB\CAMERA"),
        _node(
            "AudioEndpoint",
            "Microphone",
            r"SWD\MMDEVAPI\CAPTURE",
            "{00000000-0000-0000-0000-000000000001}",
        ),
    ]

    sources = build_av_sources(nodes, wasapi_input_names={"Microphone"})

    assert sources == ()


def test_ambiguous_capture_endpoints_fail_closed() -> None:
    nodes = [
        _node("Camera", "Camera", r"USB\CAMERA"),
        _node("AudioEndpoint", "Mic A", r"SWD\MMDEVAPI\A"),
        _node("AudioEndpoint", "Mic B", r"SWD\MMDEVAPI\B"),
    ]

    sources = build_av_sources(
        nodes,
        wasapi_input_names={"Mic A", "Mic B"},
    )

    assert sources == ()


def test_render_only_container_is_not_an_av_source() -> None:
    nodes = [
        _node("Camera", "Camera", r"USB\CAMERA"),
        _node("AudioEndpoint", "Speakers", r"SWD\MMDEVAPI\RENDER"),
    ]

    sources = build_av_sources(nodes, wasapi_input_names=set())

    assert sources == ()
