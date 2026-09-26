"""DPAPI-backed local SecretStore with metadata/envelope integrity binding."""

from __future__ import annotations

import base64
import json
import os
import pathlib
import sqlite3
import threading
import time
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Final

from jarvis.engineering_substrate.canonical import canonical_payload
from jarvis.engineering_substrate.contracts import (
    SecretDescriptor,
    SecretLifecycleState,
)
from jarvis.security import KeyProtectionError, KeyProtector, WindowsDpapiKeyProtector

_SECRET_SCHEMA_VERSION: Final = 1
_ENVELOPE_SCHEMA_VERSION: Final = 1


class SecretStoreError(RuntimeError):
    """Base error for the encrypted local secret store."""


class SecretAlreadyExistsError(SecretStoreError):
    """A secret ID already exists and cannot be silently replaced."""


class SecretNotFoundError(SecretStoreError):
    """The requested secret ID does not exist."""


class SecretIntegrityError(SecretStoreError):
    """Encrypted envelope and indexed metadata disagree or cannot be verified."""


class SecretStateError(SecretStoreError):
    """The requested secret lifecycle transition is invalid."""


@dataclass(frozen=True, slots=True)
class SecretMaterial:
    descriptor: SecretDescriptor
    value: bytes = dataclass_field(repr=False)


def default_secret_store_path() -> pathlib.Path:
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
    return (base / "JARVIS" / "secrets" / "secrets.sqlite").resolve()


def _required_text(value: object, *, field: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


def _purpose(secret_id: str, version: int) -> str:
    return f"engineering-secret:{secret_id}:v{version}"


def _descriptor_payload(descriptor: SecretDescriptor) -> dict[str, object]:
    payload = canonical_payload(descriptor)
    if not isinstance(payload, dict):
        raise SecretIntegrityError("secret descriptor canonical payload is invalid")
    return dict(payload)


def _descriptor_from_payload(payload: object) -> SecretDescriptor:
    if not isinstance(payload, dict):
        raise SecretIntegrityError("sealed secret descriptor is not an object")
    try:
        return SecretDescriptor(
            secret_id=str(payload["secret_id"]),
            kind=str(payload["kind"]),
            service=str(payload["service"]),
            allowed_consumers=tuple(str(item) for item in payload["allowed_consumers"]),
            allowed_scopes=tuple(str(item) for item in payload["allowed_scopes"]),
            lifecycle_state=SecretLifecycleState(str(payload["lifecycle_state"])),
            version=int(payload["version"]),
            created_at_epoch=float(payload["created_at_epoch"]),
            updated_at_epoch=float(payload["updated_at_epoch"]),
            schema_version=int(payload["schema_version"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise SecretIntegrityError("sealed secret descriptor is invalid") from exc


class SecretStore:
    """Store encrypted secret envelopes; SQLite never receives plaintext secret values."""

    def __init__(
        self,
        path: pathlib.Path | str | None = None,
        *,
        protector: KeyProtector | None = None,
        clock=time.time,
    ) -> None:
        self.path = pathlib.Path(path or default_secret_store_path()).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._protector = (
            protector if protector is not None else WindowsDpapiKeyProtector()
        )
        if not isinstance(getattr(self._protector, "protector_id", None), str):
            raise TypeError("secret protector must expose protector_id")
        self._clock = clock
        self._lock = threading.RLock()
        self._initialize()
        self._harden_permissions()

    @property
    def protector_id(self) -> str:
        return self._protector.protector_id

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            current_version = int(
                connection.execute("PRAGMA user_version").fetchone()[0]
            )
            if current_version not in {0, _SECRET_SCHEMA_VERSION}:
                raise SecretStoreError(
                    f"unsupported secret-store schema version: {current_version}"
                )
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS secrets (
                    secret_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    service TEXT NOT NULL,
                    allowed_consumers_json TEXT NOT NULL,
                    allowed_scopes_json TEXT NOT NULL,
                    lifecycle_state TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    created_at_epoch REAL NOT NULL,
                    updated_at_epoch REAL NOT NULL,
                    protector_id TEXT NOT NULL,
                    sealed_envelope BLOB NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_secrets_service
                    ON secrets(service, lifecycle_state);
                """
            )
            connection.execute(f"PRAGMA user_version = {_SECRET_SCHEMA_VERSION}")

    def _harden_permissions(self) -> None:
        try:
            os.chmod(self.path.parent, 0o700)
            if self.path.exists():
                os.chmod(self.path, 0o600)
        except OSError:
            # DPAPI remains the confidentiality boundary on Windows.
            pass

    @staticmethod
    def _projection(descriptor: SecretDescriptor) -> tuple[object, ...]:
        return (
            descriptor.secret_id,
            descriptor.kind,
            descriptor.service,
            json.dumps(
                list(descriptor.allowed_consumers),
                ensure_ascii=True,
                separators=(",", ":"),
            ),
            json.dumps(
                list(descriptor.allowed_scopes),
                ensure_ascii=True,
                separators=(",", ":"),
            ),
            descriptor.lifecycle_state.value,
            descriptor.version,
            descriptor.created_at_epoch,
            descriptor.updated_at_epoch,
        )

    @staticmethod
    def _descriptor_from_row(row: sqlite3.Row) -> SecretDescriptor:
        try:
            consumers = json.loads(str(row["allowed_consumers_json"]))
            scopes = json.loads(str(row["allowed_scopes_json"]))
            if not isinstance(consumers, list) or not isinstance(scopes, list):
                raise TypeError("scope projections must be lists")
            return SecretDescriptor(
                secret_id=str(row["secret_id"]),
                kind=str(row["kind"]),
                service=str(row["service"]),
                allowed_consumers=tuple(str(item) for item in consumers),
                allowed_scopes=tuple(str(item) for item in scopes),
                lifecycle_state=SecretLifecycleState(str(row["lifecycle_state"])),
                version=int(row["version"]),
                created_at_epoch=float(row["created_at_epoch"]),
                updated_at_epoch=float(row["updated_at_epoch"]),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise SecretIntegrityError("secret metadata projection is invalid") from exc

    def _seal(self, descriptor: SecretDescriptor, value: bytes) -> bytes:
        if not isinstance(value, bytes) or not value:
            raise ValueError("secret value must be non-empty bytes")
        envelope = {
            "schema_version": _ENVELOPE_SCHEMA_VERSION,
            "protector_id": self.protector_id,
            "descriptor": _descriptor_payload(descriptor),
            "secret_b64": base64.b64encode(value).decode("ascii"),
        }
        encoded = json.dumps(
            envelope,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        try:
            return self._protector.seal(
                encoded,
                purpose=_purpose(descriptor.secret_id, descriptor.version),
            )
        except KeyProtectionError as exc:
            raise SecretIntegrityError("secret envelope sealing failed") from exc

    def _unseal(
        self,
        row: sqlite3.Row,
        descriptor: SecretDescriptor,
    ) -> SecretMaterial:
        protector_id = str(row["protector_id"])
        if protector_id != self.protector_id:
            raise SecretIntegrityError("secret protector identity changed")
        sealed = bytes(row["sealed_envelope"])
        try:
            encoded = self._protector.unseal(
                sealed,
                purpose=_purpose(descriptor.secret_id, descriptor.version),
            )
        except KeyProtectionError as exc:
            raise SecretIntegrityError("secret envelope unsealing failed") from exc
        try:
            envelope = json.loads(encoded.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise SecretIntegrityError("secret envelope payload is invalid") from exc
        if not isinstance(envelope, dict):
            raise SecretIntegrityError("secret envelope payload is not an object")
        if int(envelope.get("schema_version", 0)) != _ENVELOPE_SCHEMA_VERSION:
            raise SecretIntegrityError("secret envelope schema version is unsupported")
        if str(envelope.get("protector_id") or "") != self.protector_id:
            raise SecretIntegrityError("sealed secret protector identity mismatch")

        sealed_descriptor = _descriptor_from_payload(envelope.get("descriptor"))
        if _descriptor_payload(sealed_descriptor) != _descriptor_payload(descriptor):
            raise SecretIntegrityError(
                "secret metadata projection does not match sealed envelope"
            )
        try:
            value = base64.b64decode(
                str(envelope["secret_b64"]),
                validate=True,
            )
        except (KeyError, ValueError) as exc:
            raise SecretIntegrityError(
                "sealed secret value encoding is invalid"
            ) from exc
        if not value:
            raise SecretIntegrityError("sealed secret value is empty")
        return SecretMaterial(descriptor=descriptor, value=value)

    def _require_row(
        self, connection: sqlite3.Connection, secret_id: str
    ) -> sqlite3.Row:
        key = _required_text(secret_id, field="secret_id")
        row = connection.execute(
            "SELECT * FROM secrets WHERE secret_id = ?",
            (key,),
        ).fetchone()
        if row is None:
            raise SecretNotFoundError(f"unknown secret: {key}")
        return row

    def enroll(
        self,
        *,
        secret_id: str,
        kind: str,
        service: str,
        allowed_consumers: tuple[str, ...],
        allowed_scopes: tuple[str, ...],
        value: bytes,
        now_epoch: float | None = None,
    ) -> SecretDescriptor:
        now = float(self._clock() if now_epoch is None else now_epoch)
        descriptor = SecretDescriptor(
            secret_id=secret_id,
            kind=kind,
            service=service,
            allowed_consumers=allowed_consumers,
            allowed_scopes=allowed_scopes,
            lifecycle_state=SecretLifecycleState.ACTIVE,
            version=1,
            created_at_epoch=now,
            updated_at_epoch=now,
        )
        sealed = self._seal(descriptor, value)
        with self._lock, self._connect() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO secrets(
                        secret_id, kind, service, allowed_consumers_json,
                        allowed_scopes_json, lifecycle_state, version,
                        created_at_epoch, updated_at_epoch, protector_id,
                        sealed_envelope
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (*self._projection(descriptor), self.protector_id, sealed),
                )
            except sqlite3.IntegrityError as exc:
                raise SecretAlreadyExistsError(
                    f"secret already exists: {descriptor.secret_id}"
                ) from exc
        self._harden_permissions()
        return descriptor

    def _replace(
        self,
        *,
        previous: SecretMaterial,
        descriptor: SecretDescriptor,
        value: bytes,
    ) -> SecretDescriptor:
        sealed = self._seal(descriptor, value)
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE secrets
                SET kind = ?, service = ?, allowed_consumers_json = ?,
                    allowed_scopes_json = ?, lifecycle_state = ?, version = ?,
                    created_at_epoch = ?, updated_at_epoch = ?,
                    protector_id = ?, sealed_envelope = ?
                WHERE secret_id = ? AND version = ?
                """,
                (
                    descriptor.kind,
                    descriptor.service,
                    json.dumps(
                        list(descriptor.allowed_consumers),
                        ensure_ascii=True,
                        separators=(",", ":"),
                    ),
                    json.dumps(
                        list(descriptor.allowed_scopes),
                        ensure_ascii=True,
                        separators=(",", ":"),
                    ),
                    descriptor.lifecycle_state.value,
                    descriptor.version,
                    descriptor.created_at_epoch,
                    descriptor.updated_at_epoch,
                    self.protector_id,
                    sealed,
                    descriptor.secret_id,
                    previous.descriptor.version,
                ),
            )
            if cursor.rowcount != 1:
                raise SecretStoreError("secret changed concurrently")
        self._harden_permissions()
        return descriptor

    def rotate(
        self,
        secret_id: str,
        *,
        value: bytes,
        now_epoch: float | None = None,
    ) -> SecretDescriptor:
        previous = self.materialize(secret_id, require_active=True)
        now = float(self._clock() if now_epoch is None else now_epoch)
        descriptor = SecretDescriptor(
            secret_id=previous.descriptor.secret_id,
            kind=previous.descriptor.kind,
            service=previous.descriptor.service,
            allowed_consumers=previous.descriptor.allowed_consumers,
            allowed_scopes=previous.descriptor.allowed_scopes,
            lifecycle_state=SecretLifecycleState.ACTIVE,
            version=previous.descriptor.version + 1,
            created_at_epoch=previous.descriptor.created_at_epoch,
            updated_at_epoch=now,
        )
        return self._replace(previous=previous, descriptor=descriptor, value=value)

    def revoke(
        self,
        secret_id: str,
        *,
        now_epoch: float | None = None,
    ) -> SecretDescriptor:
        previous = self.materialize(secret_id, require_active=True)
        now = float(self._clock() if now_epoch is None else now_epoch)
        descriptor = SecretDescriptor(
            secret_id=previous.descriptor.secret_id,
            kind=previous.descriptor.kind,
            service=previous.descriptor.service,
            allowed_consumers=previous.descriptor.allowed_consumers,
            allowed_scopes=previous.descriptor.allowed_scopes,
            lifecycle_state=SecretLifecycleState.REVOKED,
            version=previous.descriptor.version + 1,
            created_at_epoch=previous.descriptor.created_at_epoch,
            updated_at_epoch=now,
        )
        return self._replace(
            previous=previous,
            descriptor=descriptor,
            value=previous.value,
        )

    def descriptor(self, secret_id: str) -> SecretDescriptor:
        """Return indexed metadata only; callers must not treat it as integrity verified."""

        with self._lock, self._connect() as connection:
            return self._descriptor_from_row(self._require_row(connection, secret_id))

    def verified_descriptor(self, secret_id: str) -> SecretDescriptor:
        """Cross-check indexed metadata against the sealed DPAPI envelope."""

        return self.materialize(secret_id, require_active=False).descriptor

    def list_descriptors(self) -> tuple[SecretDescriptor, ...]:
        """List only descriptors whose indexed projection matches the sealed envelope."""

        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM secrets ORDER BY service, secret_id"
            ).fetchall()
            return tuple(
                self._unseal(row, self._descriptor_from_row(row)).descriptor
                for row in rows
            )

    def materialize(
        self,
        secret_id: str,
        *,
        require_active: bool = True,
    ) -> SecretMaterial:
        with self._lock, self._connect() as connection:
            row = self._require_row(connection, secret_id)
            descriptor = self._descriptor_from_row(row)
            material = self._unseal(row, descriptor)
        if (
            require_active
            and material.descriptor.lifecycle_state is not SecretLifecycleState.ACTIVE
        ):
            raise SecretStateError("secret is revoked")
        return material
