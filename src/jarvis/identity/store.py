from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from collections.abc import Callable, Iterable
from pathlib import Path

from .crypto import (
    EncryptedPayload,
    EnvelopeCipher,
    KeyProtectionError,
    KeyProtector,
    TemplateIntegrityError,
    canonical_aad,
)
from .types import (
    OWNER_PROFILE_ID,
    BiometricModality,
    DecryptedTemplate,
    OwnerProfile,
    TemplateInput,
    TemplateMetadata,
)


class OwnerProfileStoreError(RuntimeError):
    pass


class OwnerProfileAlreadyExists(OwnerProfileStoreError):
    pass


class OwnerProfileNotFound(OwnerProfileStoreError):
    pass


class TemplateNotFound(OwnerProfileStoreError):
    pass


class KeyProtectorMismatch(OwnerProfileStoreError):
    pass


class SqliteOwnerProfileStore:
    """Single-OWNER encrypted biometric-template store."""

    _DEK_PURPOSE = "owner-profile-dek:v1"

    def __init__(
        self,
        db_path: str | Path,
        *,
        key_protector: KeyProtector,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._protector = key_protector
        self._clock = clock
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self._path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._configure_database()
        self._create_schema()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def has_owner(self) -> bool:
        with self._lock:
            row = self._connection.execute(
                "SELECT 1 FROM owner_profile WHERE profile_id = ?",
                (OWNER_PROFILE_ID,),
            ).fetchone()
            return row is not None

    def get_owner(self) -> OwnerProfile:
        with self._lock:
            row = self._owner_row_locked()
            modalities = tuple(
                BiometricModality(item["modality"])
                for item in self._connection.execute(
                    """
                    SELECT modality
                    FROM owner_biometric_template
                    WHERE profile_id = ?
                    ORDER BY modality
                    """,
                    (OWNER_PROFILE_ID,),
                ).fetchall()
            )
            return OwnerProfile(
                profile_id=row["profile_id"],
                profile_version=row["profile_version"],
                created_at_epoch=row["created_at_epoch"],
                updated_at_epoch=row["updated_at_epoch"],
                modalities=modalities,
            )

    def create_owner(self, templates: Iterable[TemplateInput]) -> OwnerProfile:
        normalized = self._normalize_templates(templates)
        with self._lock:
            if self.has_owner():
                raise OwnerProfileAlreadyExists("OWNER profile already exists")
            now = self._clock()
            profile_version = 1
            dek = EnvelopeCipher.generate_dek()
            sealed_dek = self._protector.seal(dek, purpose=self._DEK_PURPOSE)
            prepared = self._prepare_templates(
                templates=normalized,
                dek=dek,
                profile_version=profile_version,
                now=now,
            )
            try:
                with self._connection:
                    self._connection.execute(
                        """
                        INSERT INTO owner_profile (
                            profile_id,
                            profile_version,
                            created_at_epoch,
                            updated_at_epoch,
                            key_protector_id,
                            sealed_dek
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            OWNER_PROFILE_ID,
                            profile_version,
                            now,
                            now,
                            self._protector.protector_id,
                            sealed_dek,
                        ),
                    )
                    self._insert_prepared_locked(prepared)
            finally:
                del dek
            return self.get_owner()

    def replace_owner(self, templates: Iterable[TemplateInput]) -> OwnerProfile:
        normalized = self._normalize_templates(templates)
        with self._lock:
            current = self._owner_row_locked()
            profile_version = int(current["profile_version"]) + 1
            now = self._clock()
            dek = EnvelopeCipher.generate_dek()
            sealed_dek = self._protector.seal(dek, purpose=self._DEK_PURPOSE)
            prepared = self._prepare_templates(
                templates=normalized,
                dek=dek,
                profile_version=profile_version,
                now=now,
            )
            try:
                with self._connection:
                    self._connection.execute(
                        "DELETE FROM owner_biometric_template WHERE profile_id = ?",
                        (OWNER_PROFILE_ID,),
                    )
                    self._connection.execute(
                        """
                        UPDATE owner_profile
                        SET profile_version = ?,
                            updated_at_epoch = ?,
                            key_protector_id = ?,
                            sealed_dek = ?
                        WHERE profile_id = ?
                        """,
                        (
                            profile_version,
                            now,
                            self._protector.protector_id,
                            sealed_dek,
                            OWNER_PROFILE_ID,
                        ),
                    )
                    self._insert_prepared_locked(prepared)
            finally:
                del dek
            return self.get_owner()

    def delete_owner(self) -> bool:
        with self._lock:
            if not self.has_owner():
                return False
            with self._connection:
                self._connection.execute(
                    "DELETE FROM owner_profile WHERE profile_id = ?",
                    (OWNER_PROFILE_ID,),
                )
            self._connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            return True

    def load_template(self, modality: BiometricModality) -> DecryptedTemplate:
        with self._lock:
            owner = self._owner_row_locked()
            row = self._connection.execute(
                """
                SELECT *
                FROM owner_biometric_template
                WHERE profile_id = ? AND modality = ?
                """,
                (OWNER_PROFILE_ID, modality.value),
            ).fetchone()
            if row is None:
                raise TemplateNotFound(f"no {modality.value} OWNER template")
            if owner["key_protector_id"] != self._protector.protector_id:
                raise KeyProtectorMismatch(
                    "configured key protector does not match profile"
                )
            try:
                dek = self._protector.unseal(
                    owner["sealed_dek"],
                    purpose=self._DEK_PURPOSE,
                )
            except KeyProtectionError as exc:
                raise OwnerProfileStoreError(
                    "OWNER profile key could not be unsealed"
                ) from exc
            metadata = self._metadata_from_row(row)
            aad = self._template_aad(
                template_id=row["template_id"],
                profile_version=owner["profile_version"],
                metadata=metadata,
            )
            try:
                plaintext = EnvelopeCipher.decrypt(
                    dek=dek,
                    payload=EncryptedPayload(
                        nonce=row["nonce"],
                        ciphertext=row["ciphertext"],
                    ),
                    aad=aad,
                )
            except TemplateIntegrityError as exc:
                raise OwnerProfileStoreError(
                    "OWNER template integrity check failed"
                ) from exc
            finally:
                del dek
            return DecryptedTemplate(
                template_id=row["template_id"],
                profile_version=owner["profile_version"],
                metadata=metadata,
                payload=plaintext,
                created_at_epoch=row["created_at_epoch"],
            )

    def _configure_database(self) -> None:
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA synchronous = FULL")
        self._connection.execute("PRAGMA secure_delete = ON")

    def _create_schema(self) -> None:
        with self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS owner_profile (
                    profile_id TEXT PRIMARY KEY
                        CHECK (profile_id = 'OWNER'),
                    profile_version INTEGER NOT NULL
                        CHECK (profile_version >= 1),
                    created_at_epoch REAL NOT NULL,
                    updated_at_epoch REAL NOT NULL,
                    key_protector_id TEXT NOT NULL,
                    sealed_dek BLOB NOT NULL
                        CHECK (length(sealed_dek) > 0)
                )
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS owner_biometric_template (
                    template_id TEXT PRIMARY KEY,
                    profile_id TEXT NOT NULL
                        CHECK (profile_id = 'OWNER'),
                    modality TEXT NOT NULL,
                    provider_id TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    model_version TEXT NOT NULL,
                    model_sha256 TEXT NOT NULL,
                    embedding_dimension INTEGER NOT NULL
                        CHECK (embedding_dimension > 0),
                    calibration_version TEXT NOT NULL,
                    enrollment_compatibility_version TEXT NOT NULL,
                    template_format TEXT NOT NULL,
                    nonce BLOB NOT NULL CHECK (length(nonce) = 12),
                    ciphertext BLOB NOT NULL
                        CHECK (length(ciphertext) > 16),
                    created_at_epoch REAL NOT NULL,
                    UNIQUE(profile_id, modality),
                    FOREIGN KEY(profile_id)
                        REFERENCES owner_profile(profile_id)
                        ON DELETE CASCADE
                )
                """
            )

    def _owner_row_locked(self) -> sqlite3.Row:
        row = self._connection.execute(
            "SELECT * FROM owner_profile WHERE profile_id = ?",
            (OWNER_PROFILE_ID,),
        ).fetchone()
        if row is None:
            raise OwnerProfileNotFound("OWNER profile is not enrolled")
        return row

    @staticmethod
    def _normalize_templates(
        templates: Iterable[TemplateInput],
    ) -> tuple[TemplateInput, ...]:
        normalized = tuple(templates)
        if not normalized:
            raise OwnerProfileStoreError("OWNER enrollment requires a template")
        modalities = [item.metadata.modality for item in normalized]
        if len(set(modalities)) != len(modalities):
            raise OwnerProfileStoreError("duplicate biometric modality in enrollment")
        return normalized

    def _prepare_templates(
        self,
        *,
        templates: tuple[TemplateInput, ...],
        dek: bytes,
        profile_version: int,
        now: float,
    ) -> tuple[tuple[object, ...], ...]:
        prepared: list[tuple[object, ...]] = []
        for item in templates:
            template_id = str(uuid.uuid4())
            aad = self._template_aad(
                template_id=template_id,
                profile_version=profile_version,
                metadata=item.metadata,
            )
            encrypted = EnvelopeCipher.encrypt(
                dek=dek,
                plaintext=item.payload,
                aad=aad,
            )
            metadata = item.metadata
            prepared.append(
                (
                    template_id,
                    OWNER_PROFILE_ID,
                    metadata.modality.value,
                    metadata.provider_id,
                    metadata.model_id,
                    metadata.model_version,
                    metadata.model_sha256.lower(),
                    metadata.embedding_dimension,
                    metadata.calibration_version,
                    metadata.enrollment_compatibility_version,
                    metadata.template_format,
                    encrypted.nonce,
                    encrypted.ciphertext,
                    now,
                )
            )
        return tuple(prepared)

    def _insert_prepared_locked(self, prepared: tuple[tuple[object, ...], ...]) -> None:
        self._connection.executemany(
            """
            INSERT INTO owner_biometric_template (
                template_id,
                profile_id,
                modality,
                provider_id,
                model_id,
                model_version,
                model_sha256,
                embedding_dimension,
                calibration_version,
                enrollment_compatibility_version,
                template_format,
                nonce,
                ciphertext,
                created_at_epoch
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            prepared,
        )

    @staticmethod
    def _metadata_from_row(row: sqlite3.Row) -> TemplateMetadata:
        return TemplateMetadata(
            modality=BiometricModality(row["modality"]),
            provider_id=row["provider_id"],
            model_id=row["model_id"],
            model_version=row["model_version"],
            model_sha256=row["model_sha256"],
            embedding_dimension=row["embedding_dimension"],
            calibration_version=row["calibration_version"],
            enrollment_compatibility_version=row[
                "enrollment_compatibility_version"
            ],
            template_format=row["template_format"],
        )

    @staticmethod
    def _template_aad(
        *,
        template_id: str,
        profile_version: int,
        metadata: TemplateMetadata,
    ) -> bytes:
        return canonical_aad(
            {
                "schema_version": 1,
                "profile_id": OWNER_PROFILE_ID,
                "profile_version": profile_version,
                "template_id": template_id,
                "metadata": metadata.manifest_view(),
            }
        )
