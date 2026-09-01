"""Windows sensor discovery using PnP ContainerId + WASAPI capability."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

from jarvis.sensors.models import (
    AVSourceDescriptor,
    MediaEndpoint,
    MediaKind,
    SensorCapability,
)

_PNP_CLASSES = {"camera", "audioendpoint", "media", "usb"}

_POWERSHELL_DISCOVERY = r"""
$ErrorActionPreference = 'Stop'
$classes = @('Camera', 'AudioEndpoint', 'MEDIA', 'USB')
$devices = Get-PnpDevice -PresentOnly | Where-Object {
    $classes -contains $_.Class
}
$result = foreach ($d in $devices) {
    $container = Get-PnpDeviceProperty `
        -InstanceId $d.InstanceId `
        -KeyName 'DEVPKEY_Device_ContainerId' `
        -ErrorAction SilentlyContinue
    if ($null -eq $container.Data) {
        continue
    }
    [PSCustomObject]@{
        Class = $d.Class
        FriendlyName = $d.FriendlyName
        InstanceId = $d.InstanceId
        ContainerId = $container.Data.ToString()
    }
}
@($result) | ConvertTo-Json -Depth 3 -Compress
"""


@dataclass(frozen=True, slots=True)
class WindowsDeviceNode:
    pnp_class: str
    friendly_name: str
    instance_id: str
    container_id: str

    def __post_init__(self) -> None:
        pnp_class = self.pnp_class.strip().casefold()
        if pnp_class not in _PNP_CLASSES:
            raise ValueError(f"unsupported PnP class: {self.pnp_class!r}")
        if not self.friendly_name.strip():
            raise ValueError("friendly_name must not be empty")
        if not self.instance_id.strip():
            raise ValueError("instance_id must not be empty")
        normalized = str(UUID(self.container_id.strip().strip("{}")))
        object.__setattr__(self, "pnp_class", pnp_class)
        object.__setattr__(self, "container_id", normalized)


def build_av_sources(
    nodes: Iterable[WindowsDeviceNode],
    *,
    wasapi_input_names: Iterable[str],
) -> tuple[AVSourceDescriptor, ...]:
    """Build unvalidated AV descriptors from physical Windows containers.

    ContainerId provides physical-device grouping. WASAPI input capability is
    used only to identify capture endpoints; MMDevice endpoint IDs stay opaque.
    Ambiguous containers fail closed and are omitted.
    """

    inputs = {name.strip().casefold() for name in wasapi_input_names if name.strip()}
    grouped: dict[str, list[WindowsDeviceNode]] = {}
    for node in nodes:
        grouped.setdefault(node.container_id, []).append(node)

    sources: list[AVSourceDescriptor] = []
    for container_id, members in sorted(grouped.items()):
        cameras = [member for member in members if member.pnp_class == "camera"]
        capture_endpoints = [
            member
            for member in members
            if member.pnp_class == "audioendpoint"
            and member.friendly_name.strip().casefold() in inputs
        ]
        if len(cameras) != 1 or len(capture_endpoints) != 1:
            continue

        camera = cameras[0]
        microphone = capture_endpoints[0]
        sources.append(
            AVSourceDescriptor(
                source_id=f"windows-container:{container_id}",
                display_name=camera.friendly_name,
                video_endpoint=MediaEndpoint(
                    kind=MediaKind.VIDEO,
                    stable_id=camera.instance_id,
                    display_name=camera.friendly_name,
                ),
                audio_endpoint=MediaEndpoint(
                    kind=MediaKind.AUDIO,
                    stable_id=microphone.instance_id,
                    display_name=microphone.friendly_name,
                ),
                capabilities=frozenset(
                    {SensorCapability.VIDEO, SensorCapability.AUDIO}
                ),
                physical_device_id=container_id,
            )
        )

    return tuple(sources)


def discover_windows_device_nodes() -> tuple[WindowsDeviceNode, ...]:
    if sys.platform != "win32":
        raise RuntimeError("Windows sensor discovery requires Windows")

    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            _POWERSHELL_DISCOVERY,
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    payload = result.stdout.strip()
    if not payload:
        return ()
    decoded = json.loads(payload)
    records = decoded if isinstance(decoded, list) else [decoded]

    nodes: list[WindowsDeviceNode] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        try:
            nodes.append(
                WindowsDeviceNode(
                    pnp_class=str(record["Class"]),
                    friendly_name=str(record["FriendlyName"]),
                    instance_id=str(record["InstanceId"]),
                    container_id=str(record["ContainerId"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return tuple(nodes)


def discover_wasapi_input_names() -> frozenset[str]:
    if sys.platform != "win32":
        raise RuntimeError("WASAPI discovery requires Windows")

    import sounddevice as sd

    hostapis = sd.query_hostapis()
    devices = sd.query_devices()
    names: set[str] = set()
    for device in devices:
        if int(device["max_input_channels"]) <= 0:
            continue
        hostapi = hostapis[int(device["hostapi"])]
        if str(hostapi["name"]).strip().casefold() != "windows wasapi":
            continue
        name = str(device["name"]).strip()
        if name:
            names.add(name)
    return frozenset(names)


def discover_windows_av_sources() -> tuple[AVSourceDescriptor, ...]:
    return build_av_sources(
        discover_windows_device_nodes(),
        wasapi_input_names=discover_wasapi_input_names(),
    )


def main() -> int:
    sources = discover_windows_av_sources()
    payload = [
        {
            "source_id": source.source_id,
            "display_name": source.display_name,
            "physical_device_id": source.physical_device_id,
            "video": source.video_endpoint.display_name,
            "audio": source.audio_endpoint.display_name,
            "sync": source.sync.state.value,
            "usable_for_av_evidence": source.usable_for_av_evidence,
        }
        for source in sources
    ]
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
