from __future__ import annotations

import json
from pathlib import Path

import pytest

from jarvis.capabilities.models import CapabilityCatalog
from jarvis.capability_acquisition.models import (
    AcquisitionStrategy,
    AcquisitionTrustClass,
    OwnerCapabilityGoalV1,
)
from jarvis.capability_acquisition.owner_sources import (
    OwnerSourceRegistryError,
    load_owner_source_registry,
    registered_source_adapters,
)
from jarvis.capability_acquisition.resolver import CapabilityAcquisitionResolver
from jarvis.capability_acquisition.source import (
    AcquisitionContextV1,
    CapabilitySourceRegistry,
)
from jarvis.capability_acquisition.standard_sources import (
    CustomBuildCapabilitySourceAdapter,
)


def _goal() -> OwnerCapabilityGoalV1:
    return OwnerCapabilityGoalV1.create(
        request="Get TV power control",
        requested_capability="TV control",
        required_operations=("power",),
        source_session_id="phase9-owner-source-test",
        source_turn_id="turn-1",
        now_epoch=1.0,
    )


def _context() -> AcquisitionContextV1:
    return AcquisitionContextV1(
        catalog=CapabilityCatalog(sources=(), capabilities=()),
        inventory=(),
    )


def _write(path: Path, source: dict[str, object]) -> None:
    path.write_text(
        json.dumps({"schema_version": 1, "sources": [source]}, sort_keys=True),
        encoding="utf-8",
    )


def _mcp_source() -> dict[str, object]:
    return {
        "source_kind": "mcp",
        "source_identity": "https://tv.example/mcp",
        "source_version": "1.0.0",
        "source_digest": "a" * 64,
        "supported_operations": ["power", "volume"],
        "dependency_refs": ["mcp-python-sdk==2"],
        "secret_scopes": ["tv.remote"],
        "network_scopes": ["https://tv.example"],
        "device_scopes": ["device:living-room-tv"],
        "discovery_scopes": [],
        "evidence_refs": ["owner-config:living-room-tv"],
        "license_id": "MIT",
        "provenance_refs": ["owner-config:source-v1"],
        "verification_requirements": ["mcp-tools-list-contract"],
        "external_acceptance_requirements": ["verify-tv-state"],
    }


def test_owner_configured_mcp_source_beats_custom_build(tmp_path: Path) -> None:
    registry_path = tmp_path / "sources.json"
    _write(registry_path, _mcp_source())
    sources = CapabilitySourceRegistry(
        (
            *registered_source_adapters(registry_path),
            CustomBuildCapabilitySourceAdapter(),
        )
    )

    result = CapabilityAcquisitionResolver(sources).resolve(_goal(), _context())

    selected = result.selected_candidate
    assert selected is not None
    assert selected.strategy is AcquisitionStrategy.WRAP
    assert selected.trust_class is AcquisitionTrustClass.OWNER_CONFIGURED
    assert selected.source_identity == "https://tv.example/mcp"
    assert selected.secret_scopes == ("tv.remote",)


def test_owner_source_registry_cannot_contain_execution_fields(tmp_path: Path) -> None:
    path = tmp_path / "sources.json"
    source = _mcp_source()
    source["command"] = "npx -y malicious-package"
    _write(path, source)

    with pytest.raises(OwnerSourceRegistryError, match="unsupported fields"):
        load_owner_source_registry(path)


def test_owner_source_registry_forces_owner_configured_trust(tmp_path: Path) -> None:
    path = tmp_path / "sources.json"
    source = _mcp_source()
    source["trust_class"] = "accepted_release"
    _write(path, source)

    with pytest.raises(OwnerSourceRegistryError, match="unsupported fields"):
        load_owner_source_registry(path)


def test_missing_owner_source_registry_is_empty_and_safe(tmp_path: Path) -> None:
    registry = load_owner_source_registry(tmp_path / "missing.json")

    assert registry.evidence == ()
    assert len(registry.adapters()) == 5


def test_owner_source_registry_rejects_non_sha_digest(tmp_path: Path) -> None:
    path = tmp_path / "sources.json"
    source = _mcp_source()
    source["source_digest"] = "not-a-digest"
    _write(path, source)

    with pytest.raises(OwnerSourceRegistryError, match="SHA-256"):
        load_owner_source_registry(path)
