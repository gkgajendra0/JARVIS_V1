"""SQLite canonical truth for Phase-8 capability package lifecycle state."""

from __future__ import annotations

import json
import os
import pathlib
import re
import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from jarvis.capability_registry.contracts import (
    CapabilityPackageContractError,
    CapabilityPackageV1,
    parse_capability_package_v1,
)
from jarvis.capability_registry.migration_runner import (
    CapabilityRegistryMigrationRunner,
)
from jarvis.capability_registry.models import (
    AdmittedCapabilityPackage,
    CapabilityLifecycleEvent,
    CapabilityLifecycleEventKind,
    CapabilityRegistryState,
    DesiredActivationState,
    PackageDisposition,
)
from jarvis.engineering_substrate.canonical import canonical_bytes, canonical_digest

_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class CapabilityRegistryStoreError(RuntimeError):
    pass


class CapabilityRegistryIntegrityError(CapabilityRegistryStoreError):
    pass


class PackageVersionReuseConflict(CapabilityRegistryStoreError):
    pass


class UnknownCapabilityPackageError(CapabilityRegistryStoreError):
    pass


class UnknownManagedCapabilityError(CapabilityRegistryStoreError):
    pass


class StaleRegistryGenerationError(CapabilityRegistryStoreError):
    pass


class CapabilityRegistrySelectionError(CapabilityRegistryStoreError):
    pass


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _timestamp_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(
            "capability registry clock must return a timezone-aware datetime"
        )
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _require_timestamp(value: object, *, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise CapabilityRegistryIntegrityError(f"{field} must not be empty")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise CapabilityRegistryIntegrityError(f"{field} is not ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CapabilityRegistryIntegrityError(f"{field} must be timezone-aware")
    return text


def _token(value: object, *, field: str, max_length: int = 240) -> str:
    normalized = str(value or "").strip().casefold()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    if len(normalized) > max_length:
        raise ValueError(f"{field} exceeds {max_length} characters")
    if any(ord(character) < 32 for character in normalized):
        raise ValueError(f"{field} contains control characters")
    return normalized


def _optional_ref(value: object | None, *, field: str) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    if len(normalized) > 1000:
        raise ValueError(f"{field} exceeds 1000 characters")
    if any(ord(character) < 32 for character in normalized):
        raise ValueError(f"{field} contains control characters")
    return normalized


def _sha256(value: object, *, field: str) -> str:
    normalized = str(value or "").strip().casefold()
    if _SHA256.fullmatch(normalized) is None:
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return normalized


def _release_sha(value: object) -> str:
    normalized = str(value or "").strip().casefold()
    if _GIT_SHA.fullmatch(normalized) is None:
        raise ValueError("admitted_release_sha must be an exact lowercase Git SHA")
    return normalized


def default_capability_registry_state_dir() -> pathlib.Path:
    if os.name == "nt":
        base = pathlib.Path(
            os.environ.get(
                "LOCALAPPDATA",
                str(pathlib.Path.home() / "AppData" / "Local"),
            )
        )
    else:
        base = pathlib.Path(
            os.environ.get(
                "XDG_STATE_HOME",
                str(pathlib.Path.home() / ".local" / "state"),
            )
        )
    path = base / "JARVIS" / "capabilities"
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def default_capability_registry_path() -> pathlib.Path:
    return default_capability_registry_state_dir() / "registry.sqlite3"


class CapabilityRegistryStore:
    """JARVIS-owned capability lifecycle truth; DBOS is not canonical state."""

    def __init__(
        self,
        path: str | pathlib.Path | None = None,
        *,
        migration_runner: CapabilityRegistryMigrationRunner | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.path = (
            pathlib.Path(path or default_capability_registry_path())
            .expanduser()
            .resolve()
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migration_runner = migration_runner or CapabilityRegistryMigrationRunner()
        self._clock = clock
        self._lock = threading.RLock()
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30.0)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA journal_mode=WAL")
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _write_transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except BaseException:
                connection.rollback()
                raise
            else:
                connection.commit()

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            self._migration_runner.apply(connection)

    @staticmethod
    def _event_payload(
        *,
        capability_id: str,
        package_id: str | None,
        package_version: str | None,
        package_digest: str | None,
        event_kind: CapabilityLifecycleEventKind,
        previous_generation: int,
        new_generation: int,
        reason_code: str,
        authority_ref: str | None,
        evidence_ref: str | None,
        occurred_at: str,
    ) -> dict[str, object]:
        return {
            "capability_id": capability_id,
            "package_id": package_id,
            "package_version": package_version,
            "package_digest": package_digest,
            "event_kind": event_kind.value,
            "previous_generation": previous_generation,
            "new_generation": new_generation,
            "reason_code": reason_code,
            "authority_ref": authority_ref,
            "evidence_ref": evidence_ref,
            "occurred_at": occurred_at,
        }

    def _append_event(
        self,
        connection: sqlite3.Connection,
        *,
        capability_id: str,
        package_id: str | None,
        package_version: str | None,
        package_digest: str | None,
        event_kind: CapabilityLifecycleEventKind,
        previous_generation: int,
        new_generation: int,
        reason_code: str,
        authority_ref: str | None = None,
        evidence_ref: str | None = None,
        occurred_at: str,
    ) -> CapabilityLifecycleEvent:
        normalized_capability = _token(capability_id, field="capability_id")
        normalized_reason = _token(reason_code, field="reason_code")
        normalized_authority = _optional_ref(authority_ref, field="authority_ref")
        normalized_evidence = _optional_ref(evidence_ref, field="evidence_ref")
        if previous_generation < 0 or new_generation <= 0:
            raise ValueError("lifecycle event generations are invalid")
        if package_digest is not None:
            package_digest = _sha256(package_digest, field="package_digest")

        payload = self._event_payload(
            capability_id=normalized_capability,
            package_id=package_id,
            package_version=package_version,
            package_digest=package_digest,
            event_kind=event_kind,
            previous_generation=previous_generation,
            new_generation=new_generation,
            reason_code=normalized_reason,
            authority_ref=normalized_authority,
            evidence_ref=normalized_evidence,
            occurred_at=occurred_at,
        )
        digest = canonical_digest(payload)
        event_id = f"capability_event_{digest[:24]}"
        connection.execute(
            """
            INSERT INTO capability_lifecycle_events (
                event_id, capability_id, package_id, package_version,
                package_digest, event_kind, previous_generation, new_generation,
                reason_code, authority_ref, evidence_ref, occurred_at, event_digest
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                normalized_capability,
                package_id,
                package_version,
                package_digest,
                event_kind.value,
                previous_generation,
                new_generation,
                normalized_reason,
                normalized_authority,
                normalized_evidence,
                occurred_at,
                digest,
            ),
        )
        return CapabilityLifecycleEvent(
            event_id=event_id,
            capability_id=normalized_capability,
            package_id=package_id,
            package_version=package_version,
            package_digest=package_digest,
            event_kind=event_kind,
            previous_generation=previous_generation,
            new_generation=new_generation,
            reason_code=normalized_reason,
            authority_ref=normalized_authority,
            evidence_ref=normalized_evidence,
            occurred_at=occurred_at,
            event_digest=digest,
        )

    @staticmethod
    def _package_from_row(row: sqlite3.Row) -> AdmittedCapabilityPackage:
        try:
            payload = json.loads(str(row["package_json"]))
            package = parse_capability_package_v1(payload)
            disposition = PackageDisposition(str(row["disposition"]))
        except (
            json.JSONDecodeError,
            CapabilityPackageContractError,
            ValueError,
            TypeError,
        ) as exc:
            raise CapabilityRegistryIntegrityError(
                "stored capability package is malformed"
            ) from exc

        encoded = canonical_bytes(package.canonical_payload()).decode("utf-8")
        if encoded != str(row["package_json"]):
            raise CapabilityRegistryIntegrityError(
                "stored capability package JSON is not canonical"
            )
        expected = (
            package.package_id,
            package.package_version,
            package.digest,
            package.capability_id,
            package.manifest_id,
            package.manifest_version,
            package.manifest_digest,
        )
        observed = (
            str(row["package_id"]),
            str(row["package_version"]),
            str(row["package_digest"]),
            str(row["capability_id"]),
            str(row["manifest_id"]),
            int(row["manifest_version"]),
            str(row["manifest_digest"]),
        )
        if observed != expected:
            raise CapabilityRegistryIntegrityError(
                "stored capability package identity does not match package JSON"
            )
        try:
            release_sha = _release_sha(row["admitted_release_sha"])
            evidence_digest = _sha256(row["evidence_digest"], field="evidence_digest")
            admitted_at = _require_timestamp(row["admitted_at"], field="admitted_at")
        except (ValueError, CapabilityRegistryIntegrityError) as exc:
            raise CapabilityRegistryIntegrityError(
                "stored capability package admission metadata is invalid"
            ) from exc
        return AdmittedCapabilityPackage(
            package=package,
            package_digest=package.digest,
            admitted_release_sha=release_sha,
            disposition=disposition,
            admitted_at=admitted_at,
            evidence_digest=evidence_digest,
        )

    @staticmethod
    def _registry_from_row(row: sqlite3.Row) -> CapabilityRegistryState:
        capability_id = _token(row["capability_id"], field="capability_id")
        selected = (
            row["selected_package_id"],
            row["selected_package_version"],
            row["selected_package_digest"],
        )
        present = tuple(item is not None for item in selected)
        if any(present) and not all(present):
            raise CapabilityRegistryIntegrityError(
                "stored capability selection is only partially populated"
            )
        generation = int(row["generation"])
        if generation <= 0:
            raise CapabilityRegistryIntegrityError(
                "stored capability generation must be positive"
            )
        try:
            desired = DesiredActivationState(str(row["desired_state"]))
        except ValueError as exc:
            raise CapabilityRegistryIntegrityError(
                "stored desired activation state is invalid"
            ) from exc
        updated_at = _require_timestamp(row["updated_at"], field="updated_at")
        digest = (
            None
            if row["selected_package_digest"] is None
            else _sha256(
                row["selected_package_digest"],
                field="selected_package_digest",
            )
        )
        return CapabilityRegistryState(
            capability_id=capability_id,
            selected_package_id=(
                None
                if row["selected_package_id"] is None
                else str(row["selected_package_id"])
            ),
            selected_package_version=(
                None
                if row["selected_package_version"] is None
                else str(row["selected_package_version"])
            ),
            selected_package_digest=digest,
            desired_state=desired,
            generation=generation,
            updated_at=updated_at,
        )

    def _verify_registry_selection(
        self,
        connection: sqlite3.Connection,
        state: CapabilityRegistryState,
    ) -> None:
        if not state.has_selection:
            return
        row = connection.execute(
            """
            SELECT *
            FROM capability_packages
            WHERE package_id=? AND package_version=?
            """,
            (state.selected_package_id, state.selected_package_version),
        ).fetchone()
        if row is None:
            raise CapabilityRegistryIntegrityError(
                "selected package is missing from admitted package truth"
            )
        admitted = self._package_from_row(row)
        if admitted.package.capability_id != state.capability_id:
            raise CapabilityRegistryIntegrityError(
                "selected package belongs to another capability"
            )
        if admitted.package_digest != state.selected_package_digest:
            raise CapabilityRegistryIntegrityError(
                "selected package digest does not match admitted package"
            )

    def _event_from_row(self, row: sqlite3.Row) -> CapabilityLifecycleEvent:
        try:
            event_kind = CapabilityLifecycleEventKind(str(row["event_kind"]))
        except ValueError as exc:
            raise CapabilityRegistryIntegrityError(
                "stored lifecycle event kind is invalid"
            ) from exc

        package_id = None if row["package_id"] is None else str(row["package_id"])
        package_version = (
            None if row["package_version"] is None else str(row["package_version"])
        )
        package_digest = (
            None
            if row["package_digest"] is None
            else _sha256(row["package_digest"], field="package_digest")
        )
        capability_id = _token(row["capability_id"], field="capability_id")
        reason_code = _token(row["reason_code"], field="reason_code")
        occurred_at = _require_timestamp(row["occurred_at"], field="occurred_at")
        previous_generation = int(row["previous_generation"])
        new_generation = int(row["new_generation"])
        authority_ref = _optional_ref(row["authority_ref"], field="authority_ref")
        evidence_ref = _optional_ref(row["evidence_ref"], field="evidence_ref")
        payload = self._event_payload(
            capability_id=capability_id,
            package_id=package_id,
            package_version=package_version,
            package_digest=package_digest,
            event_kind=event_kind,
            previous_generation=previous_generation,
            new_generation=new_generation,
            reason_code=reason_code,
            authority_ref=authority_ref,
            evidence_ref=evidence_ref,
            occurred_at=occurred_at,
        )
        digest = canonical_digest(payload)
        event_id = f"capability_event_{digest[:24]}"
        if str(row["event_digest"]) != digest or str(row["event_id"]) != event_id:
            raise CapabilityRegistryIntegrityError(
                "stored lifecycle event digest is invalid"
            )
        return CapabilityLifecycleEvent(
            event_id=event_id,
            capability_id=capability_id,
            package_id=package_id,
            package_version=package_version,
            package_digest=package_digest,
            event_kind=event_kind,
            previous_generation=previous_generation,
            new_generation=new_generation,
            reason_code=reason_code,
            authority_ref=authority_ref,
            evidence_ref=evidence_ref,
            occurred_at=occurred_at,
            event_digest=digest,
        )

    def admit_package(
        self,
        package: CapabilityPackageV1,
        *,
        admitted_release_sha: str,
        evidence_digest: str,
        disposition: PackageDisposition = PackageDisposition.AVAILABLE,
    ) -> AdmittedCapabilityPackage:
        if not isinstance(package, CapabilityPackageV1):
            raise TypeError("package must be CapabilityPackageV1")
        if not isinstance(disposition, PackageDisposition):
            raise TypeError("disposition must be PackageDisposition")
        release_sha = _release_sha(admitted_release_sha)
        evidence = _sha256(evidence_digest, field="evidence_digest")
        package_json = canonical_bytes(package.canonical_payload()).decode("utf-8")
        package_digest = package.digest
        occurred_at = _timestamp_text(self._clock())

        with self._write_transaction() as connection:
            existing = connection.execute(
                """
                SELECT *
                FROM capability_packages
                WHERE package_id=? AND package_version=?
                """,
                (package.package_id, package.package_version),
            ).fetchone()
            if existing is not None:
                admitted = self._package_from_row(existing)
                if admitted.package_digest != package_digest:
                    raise PackageVersionReuseConflict(
                        "capability package version was reused with different content"
                    )
                registry_row = connection.execute(
                    "SELECT * FROM capability_registry WHERE capability_id=?",
                    (package.capability_id,),
                ).fetchone()
                if registry_row is None:
                    raise CapabilityRegistryIntegrityError(
                        "admitted package is missing managed capability state"
                    )
                registry = self._registry_from_row(registry_row)
                self._verify_registry_selection(connection, registry)
                return admitted

            connection.execute(
                """
                INSERT INTO capability_packages (
                    package_id, package_version, package_digest, capability_id,
                    manifest_id, manifest_version, manifest_digest,
                    admitted_release_sha, disposition, package_json,
                    admitted_at, evidence_digest
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    package.package_id,
                    package.package_version,
                    package_digest,
                    package.capability_id,
                    package.manifest_id,
                    package.manifest_version,
                    package.manifest_digest,
                    release_sha,
                    disposition.value,
                    package_json,
                    occurred_at,
                    evidence,
                ),
            )

            registry_row = connection.execute(
                "SELECT * FROM capability_registry WHERE capability_id=?",
                (package.capability_id,),
            ).fetchone()
            if registry_row is None:
                connection.execute(
                    """
                    INSERT INTO capability_registry (
                        capability_id, selected_package_id,
                        selected_package_version, selected_package_digest,
                        desired_state, generation, updated_at
                    ) VALUES (?, NULL, NULL, NULL, ?, 1, ?)
                    """,
                    (
                        package.capability_id,
                        DesiredActivationState.DISABLED.value,
                        occurred_at,
                    ),
                )
                generation = 1
            else:
                registry = self._registry_from_row(registry_row)
                self._verify_registry_selection(connection, registry)
                generation = registry.generation

            self._append_event(
                connection,
                capability_id=package.capability_id,
                package_id=package.package_id,
                package_version=package.package_version,
                package_digest=package_digest,
                event_kind=CapabilityLifecycleEventKind.PACKAGE_ADMITTED,
                previous_generation=0 if registry_row is None else generation,
                new_generation=generation,
                reason_code="package_admitted",
                evidence_ref=evidence,
                occurred_at=occurred_at,
            )

        return AdmittedCapabilityPackage(
            package=package,
            package_digest=package_digest,
            admitted_release_sha=release_sha,
            disposition=disposition,
            admitted_at=occurred_at,
            evidence_digest=evidence,
        )

    def get_package(
        self,
        package_id: str,
        package_version: str,
    ) -> AdmittedCapabilityPackage | None:
        normalized_id = _token(package_id, field="package_id")
        version = str(package_version).strip()
        if not version:
            raise ValueError("package_version must not be empty")
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM capability_packages
                WHERE package_id=? AND package_version=?
                """,
                (normalized_id, version),
            ).fetchone()
        return None if row is None else self._package_from_row(row)

    def list_packages(
        self,
        *,
        capability_id: str | None = None,
    ) -> tuple[AdmittedCapabilityPackage, ...]:
        with self._lock, self._connect() as connection:
            if capability_id is None:
                rows = connection.execute(
                    """
                    SELECT *
                    FROM capability_packages
                    ORDER BY capability_id, package_id, package_version
                    """
                ).fetchall()
            else:
                normalized = _token(capability_id, field="capability_id")
                rows = connection.execute(
                    """
                    SELECT *
                    FROM capability_packages
                    WHERE capability_id=?
                    ORDER BY package_id, package_version
                    """,
                    (normalized,),
                ).fetchall()
        return tuple(self._package_from_row(row) for row in rows)

    def get_registry(
        self,
        capability_id: str,
    ) -> CapabilityRegistryState | None:
        normalized = _token(capability_id, field="capability_id")
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM capability_registry WHERE capability_id=?",
                (normalized,),
            ).fetchone()
            if row is None:
                return None
            state = self._registry_from_row(row)
            self._verify_registry_selection(connection, state)
            return state

    def require_registry(self, capability_id: str) -> CapabilityRegistryState:
        state = self.get_registry(capability_id)
        if state is None:
            raise UnknownManagedCapabilityError(
                f"unknown managed capability: {capability_id}"
            )
        return state

    def list_registry(self) -> tuple[CapabilityRegistryState, ...]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM capability_registry ORDER BY capability_id"
            ).fetchall()
            states = tuple(self._registry_from_row(row) for row in rows)
            for state in states:
                self._verify_registry_selection(connection, state)
            return states

    def transition_registry(
        self,
        capability_id: str,
        *,
        expected_generation: int,
        desired_state: DesiredActivationState,
        selected_package_id: str | None,
        selected_package_version: str | None,
        event_kind: CapabilityLifecycleEventKind,
        reason_code: str,
        authority_ref: str | None = None,
        evidence_ref: str | None = None,
    ) -> CapabilityRegistryState:
        normalized_capability = _token(capability_id, field="capability_id")
        if type(expected_generation) is not int or expected_generation <= 0:
            raise ValueError("expected_generation must be a positive integer")
        if not isinstance(desired_state, DesiredActivationState):
            raise TypeError("desired_state must be DesiredActivationState")
        if not isinstance(event_kind, CapabilityLifecycleEventKind):
            raise TypeError("event_kind must be CapabilityLifecycleEventKind")
        if (selected_package_id is None) != (selected_package_version is None):
            raise ValueError(
                "selected package identity requires both package_id and package_version"
            )

        occurred_at = _timestamp_text(self._clock())
        normalized_reason = _token(reason_code, field="reason_code")

        with self._write_transaction() as connection:
            row = connection.execute(
                "SELECT * FROM capability_registry WHERE capability_id=?",
                (normalized_capability,),
            ).fetchone()
            if row is None:
                raise UnknownManagedCapabilityError(
                    f"unknown managed capability: {normalized_capability}"
                )
            current = self._registry_from_row(row)
            self._verify_registry_selection(connection, current)
            if current.generation != expected_generation:
                raise StaleRegistryGenerationError(
                    f"stale capability registry generation: expected "
                    f"{expected_generation}, observed {current.generation}"
                )

            target_package: AdmittedCapabilityPackage | None = None
            if selected_package_id is not None:
                normalized_package_id = _token(
                    selected_package_id,
                    field="selected_package_id",
                )
                package_version = str(selected_package_version).strip()
                if not package_version:
                    raise ValueError("selected_package_version must not be empty")
                package_row = connection.execute(
                    """
                    SELECT *
                    FROM capability_packages
                    WHERE package_id=? AND package_version=?
                    """,
                    (normalized_package_id, package_version),
                ).fetchone()
                if package_row is None:
                    raise UnknownCapabilityPackageError(
                        "selected capability package is not admitted"
                    )
                target_package = self._package_from_row(package_row)
                if target_package.package.capability_id != normalized_capability:
                    raise CapabilityRegistrySelectionError(
                        "selected package belongs to another capability"
                    )
                if target_package.disposition is not PackageDisposition.AVAILABLE:
                    raise CapabilityRegistrySelectionError(
                        "selected package is not AVAILABLE"
                    )

            target_id = (
                None if target_package is None else target_package.package.package_id
            )
            target_version = (
                None
                if target_package is None
                else target_package.package.package_version
            )
            target_digest = (
                None if target_package is None else target_package.package_digest
            )
            if (
                current.desired_state is desired_state
                and current.selected_package_id == target_id
                and current.selected_package_version == target_version
                and current.selected_package_digest == target_digest
            ):
                return current

            new_generation = current.generation + 1
            cursor = connection.execute(
                """
                UPDATE capability_registry
                SET selected_package_id=?,
                    selected_package_version=?,
                    selected_package_digest=?,
                    desired_state=?,
                    generation=?,
                    updated_at=?
                WHERE capability_id=? AND generation=?
                """,
                (
                    target_id,
                    target_version,
                    target_digest,
                    desired_state.value,
                    new_generation,
                    occurred_at,
                    normalized_capability,
                    expected_generation,
                ),
            )
            if cursor.rowcount != 1:
                raise StaleRegistryGenerationError(
                    "capability registry CAS update lost a concurrent writer"
                )

            event_package_id = (
                target_id if target_id is not None else current.selected_package_id
            )
            event_package_version = (
                target_version
                if target_version is not None
                else current.selected_package_version
            )
            event_package_digest = (
                target_digest
                if target_digest is not None
                else current.selected_package_digest
            )
            self._append_event(
                connection,
                capability_id=normalized_capability,
                package_id=event_package_id,
                package_version=event_package_version,
                package_digest=event_package_digest,
                event_kind=event_kind,
                previous_generation=current.generation,
                new_generation=new_generation,
                reason_code=normalized_reason,
                authority_ref=authority_ref,
                evidence_ref=evidence_ref,
                occurred_at=occurred_at,
            )
            return CapabilityRegistryState(
                capability_id=normalized_capability,
                selected_package_id=target_id,
                selected_package_version=target_version,
                selected_package_digest=target_digest,
                desired_state=desired_state,
                generation=new_generation,
                updated_at=occurred_at,
            )

    def list_events(
        self,
        capability_id: str,
    ) -> tuple[CapabilityLifecycleEvent, ...]:
        normalized = _token(capability_id, field="capability_id")
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM capability_lifecycle_events
                WHERE capability_id=?
                ORDER BY occurred_at, event_id
                """,
                (normalized,),
            ).fetchall()
        return tuple(self._event_from_row(row) for row in rows)
