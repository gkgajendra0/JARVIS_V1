from __future__ import annotations

import json
import subprocess

import pytest

from jarvis.capabilities import (
    CapabilityDescriptor,
    CapabilityDiscoverySourceError,
    CapabilityKind,
    CapabilityResolver,
    DiscoverySnapshot,
    DiscoveryState,
    WinAppCliSchemaSource,
    WindowsOdrSource,
)


class Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        self.value += 0.01
        return self.value


def test_winapp_discovers_only_ui_schema_and_never_shells(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("platform.system", lambda: "Windows")
    calls = []
    schema = {
        "name": "winapp",
        "version": "0.6.1",
        "schemaVersion": "1.0",
        "subcommands": {
            "package": {
                "description": "Package apps",
                "subcommands": {"install": {"description": "Dangerous here"}},
            },
            "ui": {
                "description": "Inspect and interact with running Windows app UIs",
                "subcommands": {
                    "inspect": {"description": "Inspect", "hidden": False},
                    "invoke": {"description": "Invoke", "hidden": False},
                    "send-keys": {"description": "Type", "hidden": False},
                    "internal": {"description": "Hidden", "hidden": True},
                },
            },
        },
    }

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(schema),
            stderr="",
        )

    source = WinAppCliSchemaSource(
        executable=r"C:\Tools\winapp.exe",
        runner=runner,
        monotonic=Clock(),
    )
    snapshot = source.discover()

    assert snapshot.state is DiscoveryState.AVAILABLE
    assert calls[0][0] == [r"C:\Tools\winapp.exe", "--cli-schema"]
    assert calls[0][1]["shell"] is False
    assert len(snapshot.capabilities) == 1
    capability = snapshot.capabilities[0]
    assert capability.key == "windows.winapp:desktop.ui"
    assert capability.operations == ("inspect", "invoke", "send-keys")
    assert "package" not in capability.operations
    assert "internal" not in capability.operations
    assert capability.execution_enabled is False


def test_winapp_malformed_schema_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("platform.system", lambda: "Windows")

    def runner(command, **kwargs):
        return subprocess.CompletedProcess(
            command,
            0,
            stdout='{"subcommands":{}}',
            stderr="",
        )

    source = WinAppCliSchemaSource(
        executable="winapp.exe",
        runner=runner,
        monotonic=Clock(),
    )
    snapshot = source.discover()

    assert snapshot.state is DiscoveryState.FAILED
    assert snapshot.capabilities == ()
    assert "missing ui" in (snapshot.reason or "")


def test_odr_inventory_is_read_only_and_never_runs_servers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("platform.system", lambda: "Windows")
    calls = []
    registry = [
        {
            "id": "File Explorer",
            "description": "Windows file connector",
            "manifest": {
                "server": {
                    "mcp_config": {
                        "command": "contained-server.exe",
                        "args": ["--server"],
                    }
                }
            },
        },
        {
            "name": "Weather.Tools",
            "manifest": {"server": {"mcp_config": {"transport": "http"}}},
        },
    ]

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(registry),
            stderr="",
        )

    source = WindowsOdrSource(
        executable=r"C:\Windows\System32\odr.exe",
        runner=runner,
        monotonic=Clock(),
    )
    snapshot = source.discover()

    assert snapshot.state is DiscoveryState.AVAILABLE
    assert calls == [
        (
            [r"C:\Windows\System32\odr.exe", "list"],
            {
                "capture_output": True,
                "text": True,
                "encoding": "utf-8",
                "errors": "replace",
                "timeout": 8.0,
                "shell": False,
            },
        )
    ]
    assert {capability.name for capability in snapshot.capabilities} == {
        "File Explorer",
        "Weather.Tools",
    }
    assert all(not capability.execution_enabled for capability in snapshot.capabilities)
    assert all(capability.operations == () for capability in snapshot.capabilities)


def test_odr_unavailable_is_truthful(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("platform.system", lambda: "Windows")
    monkeypatch.setattr("shutil.which", lambda _: None)

    snapshot = WindowsOdrSource().discover()

    assert snapshot.state is DiscoveryState.UNAVAILABLE
    assert snapshot.capabilities == ()
    assert "not available" in (snapshot.reason or "")


def test_resolver_isolates_declared_source_failure_and_keeps_other_capabilities() -> None:
    capability = CapabilityDescriptor.create(
        capability_id="safe.read",
        source_id="source.good",
        kind=CapabilityKind.NATIVE_API,
        name="Safe read",
        description="Read-only test capability",
        operations=("read",),
    )

    class GoodSource:
        source_id = "source.good"

        def discover(self) -> DiscoverySnapshot:
            return DiscoverySnapshot(
                source_id=self.source_id,
                state=DiscoveryState.AVAILABLE,
                capabilities=(capability,),
            )

    class BrokenSource:
        source_id = "source.broken"

        def discover(self) -> DiscoverySnapshot:
            raise CapabilityDiscoverySourceError("boom")

    catalog = CapabilityResolver((BrokenSource(), GoodSource())).refresh()

    assert catalog.by_key("source.good:safe.read") == capability
    states = {source.source_id: source.state for source in catalog.sources}
    assert states == {
        "source.broken": DiscoveryState.FAILED,
        "source.good": DiscoveryState.AVAILABLE,
    }
    assert catalog.search("read") == (capability,)


def test_resolver_does_not_hide_programming_errors() -> None:
    class BrokenSource:
        source_id = "source.programming-bug"

        def discover(self) -> DiscoverySnapshot:
            raise RuntimeError("unexpected bug")

    with pytest.raises(RuntimeError, match="unexpected bug"):
        CapabilityResolver((BrokenSource(),)).refresh()


def test_resolver_rejects_duplicate_source_ids() -> None:
    class Source:
        source_id = "same"

        def discover(self) -> DiscoverySnapshot:
            return DiscoverySnapshot(
                source_id=self.source_id,
                state=DiscoveryState.AVAILABLE,
            )

    with pytest.raises(ValueError, match="source ids must be unique"):
        CapabilityResolver((Source(), Source()))


def test_resolver_rejects_duplicate_capability_identity() -> None:
    capability = CapabilityDescriptor.create(
        capability_id="duplicate",
        source_id="source",
        kind=CapabilityKind.NATIVE_API,
        name="Duplicate",
        description="Duplicate identity test",
    )

    class Source:
        source_id = "source"

        def discover(self) -> DiscoverySnapshot:
            return DiscoverySnapshot(
                source_id=self.source_id,
                state=DiscoveryState.AVAILABLE,
                capabilities=(capability, capability),
            )

    with pytest.raises(ValueError, match="duplicate discovered capability identity"):
        CapabilityResolver((Source(),)).refresh()
