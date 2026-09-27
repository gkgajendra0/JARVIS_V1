from __future__ import annotations

import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier

import pytest

from jarvis.capability_registry import (
    CapabilityPackageV1,
    parse_capability_package_v1,
)
from jarvis.capability_registry.migration_runner import (
    CapabilityRegistryMigration,
    CapabilityRegistryMigrationIntegrityError,
    CapabilityRegistryMigrationRunner,
    CapabilityRegistrySchemaTooNewError,
    discover_capability_registry_migrations,
)
from jarvis.capability_registry.models import (
    CapabilityLifecycleEventKind,
    DesiredActivationState,
    PackageDisposition,
)
from jarvis.capability_registry.store import (
    CapabilityRegistryIntegrityError,
    CapabilityRegistrySelectionError,
    CapabilityRegistryStore,
    PackageVersionReuseConflict,
    StaleRegistryGenerationError,
)

_RELEASE_SHA = "a" * 40
_EVIDENCE_DIGEST = "e" * 64
_FIXED_TIME = datetime(2026, 9, 27, 10, 0, tzinfo=UTC)


def _clock() -> datetime:
    return _FIXED_TIME


def _package(
    *,
    package_id: str = "example.tools",
    package_version: str = "1.0.0",
    capability_id: str = "example.capability",
    manifest_digest: str = "b" * 64,
) -> CapabilityPackageV1:
    return parse_capability_package_v1(
        {
            "schema_version": 1,
            "package_id": package_id,
            "package_version": package_version,
            "capability_id": capability_id,
            "package_kind": "extension_source",
            "manifest_id": f"manifest.{capability_id}",
            "manifest_version": 1,
            "manifest_digest": manifest_digest,
            "runtime_api_id": "jarvis.capability_runtime",
            "runtime_api_version": 1,
            "artifacts": [],
            "attestation_refs": [],
            "sbom_refs": [],
        }
    )


def _store(tmp_path) -> CapabilityRegistryStore:
    return CapabilityRegistryStore(tmp_path / "registry.sqlite3", clock=_clock)


def test_initial_migration_is_checksummed_and_versioned(tmp_path) -> None:
    store = _store(tmp_path)

    with sqlite3.connect(store.path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        row = connection.execute(
            """
            SELECT version, name, sha256
            FROM jarvis_capability_schema_migration
            """
        ).fetchone()

    packaged = discover_capability_registry_migrations()[0]
    assert row == (packaged.version, packaged.name, packaged.sha256)


def test_changed_applied_migration_checksum_fails_closed(tmp_path) -> None:
    store = _store(tmp_path)
    packaged = discover_capability_registry_migrations()[0]
    altered_sql = packaged.sql + "\n-- altered after application\n"
    altered = CapabilityRegistryMigration(
        version=packaged.version,
        name=packaged.name,
        sql=altered_sql,
        sha256=hashlib.sha256(altered_sql.encode("utf-8")).hexdigest(),
    )

    with pytest.raises(CapabilityRegistryMigrationIntegrityError):
        CapabilityRegistryStore(
            store.path,
            migration_runner=CapabilityRegistryMigrationRunner((altered,)),
            clock=_clock,
        )


def test_newer_unknown_schema_fails_closed(tmp_path) -> None:
    path = tmp_path / "registry.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version=99")

    with pytest.raises(CapabilityRegistrySchemaTooNewError):
        CapabilityRegistryStore(path, clock=_clock)


def test_admission_creates_disabled_unselected_registry_and_event(tmp_path) -> None:
    store = _store(tmp_path)
    package = _package()

    admitted = store.admit_package(
        package,
        admitted_release_sha=_RELEASE_SHA,
        evidence_digest=_EVIDENCE_DIGEST,
    )
    state = store.require_registry(package.capability_id)
    events = store.list_events(package.capability_id)

    assert admitted.package_digest == package.digest
    assert admitted.disposition is PackageDisposition.AVAILABLE
    assert state.desired_state is DesiredActivationState.DISABLED
    assert state.generation == 1
    assert not state.has_selection
    assert len(events) == 1
    assert events[0].event_kind is CapabilityLifecycleEventKind.PACKAGE_ADMITTED
    assert events[0].previous_generation == 0
    assert events[0].new_generation == 1


def test_exact_readmission_is_idempotent_and_does_not_duplicate_event(tmp_path) -> None:
    store = _store(tmp_path)
    package = _package()

    first = store.admit_package(
        package,
        admitted_release_sha=_RELEASE_SHA,
        evidence_digest=_EVIDENCE_DIGEST,
    )
    second = store.admit_package(
        package,
        admitted_release_sha="c" * 40,
        evidence_digest="d" * 64,
    )

    assert second == first
    assert len(store.list_events(package.capability_id)) == 1
    assert store.require_registry(package.capability_id).generation == 1


def test_same_version_with_changed_content_is_rejected(tmp_path) -> None:
    store = _store(tmp_path)
    original = _package(manifest_digest="b" * 64)
    changed = _package(manifest_digest="c" * 64)
    store.admit_package(
        original,
        admitted_release_sha=_RELEASE_SHA,
        evidence_digest=_EVIDENCE_DIGEST,
    )

    with pytest.raises(PackageVersionReuseConflict):
        store.admit_package(
            changed,
            admitted_release_sha=_RELEASE_SHA,
            evidence_digest="f" * 64,
        )


def test_new_package_version_does_not_auto_select_or_change_desired_state(
    tmp_path,
) -> None:
    store = _store(tmp_path)
    first = _package(package_version="1.0.0")
    second = _package(package_version="1.1.0")
    store.admit_package(
        first,
        admitted_release_sha=_RELEASE_SHA,
        evidence_digest=_EVIDENCE_DIGEST,
    )
    store.admit_package(
        second,
        admitted_release_sha=_RELEASE_SHA,
        evidence_digest="f" * 64,
    )

    state = store.require_registry(first.capability_id)
    assert state.generation == 1
    assert state.desired_state is DesiredActivationState.DISABLED
    assert not state.has_selection
    assert len(store.list_events(first.capability_id)) == 2


def test_registry_transition_commits_state_and_event_together(tmp_path) -> None:
    store = _store(tmp_path)
    package = _package()
    store.admit_package(
        package,
        admitted_release_sha=_RELEASE_SHA,
        evidence_digest=_EVIDENCE_DIGEST,
    )

    updated = store.transition_registry(
        package.capability_id,
        expected_generation=1,
        desired_state=DesiredActivationState.ENABLED,
        selected_package_id=package.package_id,
        selected_package_version=package.package_version,
        event_kind=CapabilityLifecycleEventKind.VERSION_SELECTED,
        reason_code="owner_selected_version",
        authority_ref="permit:test",
        evidence_ref=package.digest,
    )

    assert updated.generation == 2
    assert updated.desired_state is DesiredActivationState.ENABLED
    assert updated.selected_package_digest == package.digest
    persisted = store.require_registry(package.capability_id)
    assert persisted == updated
    events = store.list_events(package.capability_id)
    assert len(events) == 2
    assert events[-1].previous_generation == 1
    assert events[-1].new_generation == 2
    assert events[-1].authority_ref == "permit:test"


def test_stale_cas_changes_neither_state_nor_event_history(tmp_path) -> None:
    store = _store(tmp_path)
    package = _package()
    store.admit_package(
        package,
        admitted_release_sha=_RELEASE_SHA,
        evidence_digest=_EVIDENCE_DIGEST,
    )
    store.transition_registry(
        package.capability_id,
        expected_generation=1,
        desired_state=DesiredActivationState.ENABLED,
        selected_package_id=package.package_id,
        selected_package_version=package.package_version,
        event_kind=CapabilityLifecycleEventKind.VERSION_SELECTED,
        reason_code="select",
    )
    before = store.require_registry(package.capability_id)
    before_events = store.list_events(package.capability_id)

    with pytest.raises(StaleRegistryGenerationError):
        store.transition_registry(
            package.capability_id,
            expected_generation=1,
            desired_state=DesiredActivationState.DISABLED,
            selected_package_id=package.package_id,
            selected_package_version=package.package_version,
            event_kind=CapabilityLifecycleEventKind.DESIRED_STATE_CHANGED,
            reason_code="stale_disable",
        )

    assert store.require_registry(package.capability_id) == before
    assert store.list_events(package.capability_id) == before_events


def test_package_from_another_capability_cannot_be_selected(tmp_path) -> None:
    store = _store(tmp_path)
    first = _package(package_id="pkg.one", capability_id="cap.one")
    second = _package(package_id="pkg.two", capability_id="cap.two")
    for package in (first, second):
        store.admit_package(
            package,
            admitted_release_sha=_RELEASE_SHA,
            evidence_digest=package.digest,
        )

    with pytest.raises(CapabilityRegistrySelectionError):
        store.transition_registry(
            first.capability_id,
            expected_generation=1,
            desired_state=DesiredActivationState.ENABLED,
            selected_package_id=second.package_id,
            selected_package_version=second.package_version,
            event_kind=CapabilityLifecycleEventKind.VERSION_SELECTED,
            reason_code="wrong_capability",
        )


def test_non_available_package_cannot_be_selected(tmp_path) -> None:
    store = _store(tmp_path)
    package = _package()
    store.admit_package(
        package,
        admitted_release_sha=_RELEASE_SHA,
        evidence_digest=_EVIDENCE_DIGEST,
        disposition=PackageDisposition.RETIRED,
    )

    with pytest.raises(CapabilityRegistrySelectionError):
        store.transition_registry(
            package.capability_id,
            expected_generation=1,
            desired_state=DesiredActivationState.ENABLED,
            selected_package_id=package.package_id,
            selected_package_version=package.package_version,
            event_kind=CapabilityLifecycleEventKind.VERSION_SELECTED,
            reason_code="retired_selection",
        )


def test_registry_survives_store_restart(tmp_path) -> None:
    path = tmp_path / "registry.sqlite3"
    first_store = CapabilityRegistryStore(path, clock=_clock)
    package = _package()
    first_store.admit_package(
        package,
        admitted_release_sha=_RELEASE_SHA,
        evidence_digest=_EVIDENCE_DIGEST,
    )
    first_store.transition_registry(
        package.capability_id,
        expected_generation=1,
        desired_state=DesiredActivationState.ENABLED,
        selected_package_id=package.package_id,
        selected_package_version=package.package_version,
        event_kind=CapabilityLifecycleEventKind.VERSION_SELECTED,
        reason_code="select",
    )

    restarted = CapabilityRegistryStore(path, clock=_clock)

    assert restarted.get_package(package.package_id, package.package_version) is not None
    assert restarted.require_registry(package.capability_id).generation == 2
    assert len(restarted.list_events(package.capability_id)) == 2


def test_tampered_package_json_fails_integrity_on_read(tmp_path) -> None:
    store = _store(tmp_path)
    package = _package()
    store.admit_package(
        package,
        admitted_release_sha=_RELEASE_SHA,
        evidence_digest=_EVIDENCE_DIGEST,
    )
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            """
            UPDATE capability_packages
            SET package_json=?
            WHERE package_id=? AND package_version=?
            """,
            (
                json.dumps({"schema_version": 1}),
                package.package_id,
                package.package_version,
            ),
        )

    with pytest.raises(CapabilityRegistryIntegrityError):
        store.get_package(package.package_id, package.package_version)


def test_two_writers_with_same_generation_produce_one_winner(tmp_path) -> None:
    path = tmp_path / "registry.sqlite3"
    first_store = CapabilityRegistryStore(path, clock=_clock)
    second_store = CapabilityRegistryStore(path, clock=_clock)
    package = _package()
    first_store.admit_package(
        package,
        admitted_release_sha=_RELEASE_SHA,
        evidence_digest=_EVIDENCE_DIGEST,
    )
    barrier = Barrier(2)

    def transition(
        store: CapabilityRegistryStore,
        desired: DesiredActivationState,
        reason: str,
    ) -> str:
        barrier.wait()
        try:
            result = store.transition_registry(
                package.capability_id,
                expected_generation=1,
                desired_state=desired,
                selected_package_id=package.package_id,
                selected_package_version=package.package_version,
                event_kind=CapabilityLifecycleEventKind.DESIRED_STATE_CHANGED,
                reason_code=reason,
            )
        except StaleRegistryGenerationError:
            return "stale"
        return f"winner:{result.desired_state.value}"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = {
            pool.submit(
                transition,
                first_store,
                DesiredActivationState.ENABLED,
                "writer_one",
            ).result(),
            pool.submit(
                transition,
                second_store,
                DesiredActivationState.DISABLED,
                "writer_two",
            ).result(),
        }

    assert "stale" in outcomes
    assert len(outcomes) == 2
    assert first_store.require_registry(package.capability_id).generation == 2
    assert len(first_store.list_events(package.capability_id)) == 2
