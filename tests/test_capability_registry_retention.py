from __future__ import annotations

import json
import pathlib

import pytest

from jarvis.capability_registry.contracts import parse_capability_package_v1
from jarvis.capability_registry.models import (
    CapabilityLifecycleEventKind,
    DesiredActivationState,
)
from jarvis.capability_registry.retention import (
    CapabilityArtifactRetentionError,
    CapabilityArtifactRetentionPlanner,
)
from jarvis.capability_registry.source import ReleaseCapabilityPackageSource
from jarvis.capability_registry.store import CapabilityRegistryStore
from jarvis.promotion.release import ReleaseRecord

RELEASE_SHA = "a" * 40


def _package(version: str, digest: str, *, runtime_api_version: int = 1):
    return parse_capability_package_v1(
        {
            "schema_version": 1,
            "package_id": "example.package",
            "package_version": version,
            "capability_id": "example.capability",
            "package_kind": "extension_source",
            "manifest_id": f"manifest.{version}",
            "manifest_version": 1,
            "manifest_digest": "b" * 64,
            "runtime_api_id": "jarvis.capability_runtime",
            "runtime_api_version": runtime_api_version,
            "artifacts": [
                {
                    "role": "payload",
                    "sha256": digest,
                    "size_bytes": 10,
                    "media_type": "application/octet-stream",
                    "provenance_refs": [],
                }
            ],
            "attestation_refs": [],
            "sbom_refs": [],
        }
    )


def _release(tmp_path) -> ReleaseRecord:
    root = tmp_path / "release"
    (root / "capability_packages").mkdir(parents=True)
    return ReleaseRecord(
        release_sha=RELEASE_SHA,
        release_root=str(root),
        promotion_attempt_id="promotion_retention_test",
        promotion_evidence_digest="c" * 64,
        config_digest="d" * 64,
        schema_versions=(("capability_registry", 1),),
        accepted_at_epoch=1.0,
    )


def _write(release: ReleaseRecord, package) -> pathlib.Path:
    path = (
        pathlib.Path(release.release_root)
        / "capability_packages"
        / f"{package.package_version.replace('.', '_')}.json"
    )
    path.write_text(
        json.dumps(package.model_dump(mode="json"), sort_keys=True),
        encoding="utf-8",
    )
    return path


def test_retention_keeps_current_selected_rollback_and_unresolved_artifacts(
    tmp_path,
) -> None:
    release = _release(tmp_path)
    v1 = _package("1.0.0", "1" * 64)
    v2 = _package("2.0.0", "2" * 64)
    _write(release, v2)

    store = CapabilityRegistryStore(tmp_path / "registry.sqlite3")
    store.admit_package(
        v1,
        admitted_release_sha=RELEASE_SHA,
        evidence_digest="e" * 64,
    )
    store.admit_package(
        v2,
        admitted_release_sha=RELEASE_SHA,
        evidence_digest="f" * 64,
    )
    state = store.require_registry("example.capability")
    state = store.transition_registry(
        "example.capability",
        expected_generation=state.generation,
        desired_state=DesiredActivationState.DISABLED,
        selected_package_id="example.package",
        selected_package_version="1.0.0",
        event_kind=CapabilityLifecycleEventKind.VERSION_SELECTED,
        reason_code="select_v1",
    )
    store.transition_registry(
        "example.capability",
        expected_generation=state.generation,
        desired_state=DesiredActivationState.DISABLED,
        selected_package_id="example.package",
        selected_package_version="2.0.0",
        event_kind=CapabilityLifecycleEventKind.VERSION_SELECTED,
        reason_code="select_v2",
    )

    planner = CapabilityArtifactRetentionPlanner(
        store=store,
        package_source=ReleaseCapabilityPackageSource(release),
        rollback_depth=1,
    )
    refs = planner.references(
        unresolved_artifact_sha256=("3" * 64,),
    )

    assert refs.referenced_sha256 == ("1" * 64, "2" * 64, "3" * 64)


def test_zero_rollback_depth_does_not_retain_absent_old_release_artifact(
    tmp_path,
) -> None:
    release = _release(tmp_path)
    v1 = _package("1.0.0", "1" * 64)
    v2 = _package("2.0.0", "2" * 64)
    _write(release, v2)
    store = CapabilityRegistryStore(tmp_path / "registry.sqlite3")
    store.admit_package(
        v1,
        admitted_release_sha=RELEASE_SHA,
        evidence_digest="e" * 64,
    )
    store.admit_package(
        v2,
        admitted_release_sha=RELEASE_SHA,
        evidence_digest="f" * 64,
    )
    state = store.require_registry("example.capability")
    state = store.transition_registry(
        "example.capability",
        expected_generation=state.generation,
        desired_state=DesiredActivationState.DISABLED,
        selected_package_id="example.package",
        selected_package_version="1.0.0",
        event_kind=CapabilityLifecycleEventKind.VERSION_SELECTED,
        reason_code="select_v1",
    )
    store.transition_registry(
        "example.capability",
        expected_generation=state.generation,
        desired_state=DesiredActivationState.DISABLED,
        selected_package_id="example.package",
        selected_package_version="2.0.0",
        event_kind=CapabilityLifecycleEventKind.VERSION_SELECTED,
        reason_code="select_v2",
    )

    refs = CapabilityArtifactRetentionPlanner(
        store=store,
        package_source=ReleaseCapabilityPackageSource(release),
        rollback_depth=0,
    ).references()

    assert refs.referenced_sha256 == ("2" * 64,)


def test_retention_fails_closed_on_active_release_descriptor_conflict(
    tmp_path,
) -> None:
    release = _release(tmp_path)
    admitted = _package("1.0.0", "1" * 64)
    conflicting = _package(
        "1.0.0",
        "1" * 64,
        runtime_api_version=2,
    )
    _write(release, conflicting)
    store = CapabilityRegistryStore(tmp_path / "registry.sqlite3")
    store.admit_package(
        admitted,
        admitted_release_sha=RELEASE_SHA,
        evidence_digest="e" * 64,
    )

    planner = CapabilityArtifactRetentionPlanner(
        store=store,
        package_source=ReleaseCapabilityPackageSource(release),
    )

    with pytest.raises(
        CapabilityArtifactRetentionError,
        match="conflicts",
    ):
        planner.references()
