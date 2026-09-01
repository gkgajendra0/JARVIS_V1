from __future__ import annotations

import sqlite3
import uuid

import pytest

from jarvis.identity import (
    BiometricModality,
    KeyProtectorMismatch,
    OwnerProfileAlreadyExists,
    OwnerProfileNotFound,
    OwnerProfileStoreError,
    SqliteOwnerProfileStore,
    TemplateInput,
    TemplateMetadata,
)


class TestKeyProtector:
    protector_id = "test-key-protector-v1"

    def seal(self, plaintext: bytes, *, purpose: str) -> bytes:
        return b"sealed:" + purpose.encode() + b":" + plaintext

    def unseal(self, sealed: bytes, *, purpose: str) -> bytes:
        prefix = b"sealed:" + purpose.encode() + b":"
        if not sealed.startswith(prefix):
            raise RuntimeError("test key cannot be unsealed")
        return sealed[len(prefix) :]


class DifferentKeyProtector(TestKeyProtector):
    protector_id = "different-key-protector-v1"


def face_template(payload: bytes = b"face-template-secret") -> TemplateInput:
    return TemplateInput(
        metadata=TemplateMetadata(
            modality=BiometricModality.FACE,
            provider_id="opencv-sface",
            model_id="sface-test",
            model_version="1",
            model_sha256="a" * 64,
            embedding_dimension=128,
            calibration_version="unaccepted-test",
            enrollment_compatibility_version="sface-v1",
        ),
        payload=payload,
    )


def test_owner_template_round_trip_is_encrypted_at_rest(tmp_path) -> None:
    db_path = tmp_path / "identity.db"
    plaintext = b"super-secret-face-vector-material"
    store = SqliteOwnerProfileStore(
        db_path,
        key_protector=TestKeyProtector(),
    )
    owner = store.create_owner([face_template(plaintext)])
    loaded = store.load_template(BiometricModality.FACE)
    store.close()

    assert owner.profile_id == "OWNER"
    assert owner.profile_version == 1
    assert owner.modalities == (BiometricModality.FACE,)
    assert loaded.payload == plaintext
    assert loaded.metadata.modality is BiometricModality.FACE

    database_bytes = db_path.read_bytes()
    assert plaintext not in database_bytes
    wal_path = db_path.with_name(f"{db_path.name}-wal")
    if wal_path.exists():
        assert plaintext not in wal_path.read_bytes()


def test_only_one_owner_profile_can_exist(tmp_path) -> None:
    store = SqliteOwnerProfileStore(
        tmp_path / "identity.db",
        key_protector=TestKeyProtector(),
    )
    store.create_owner([face_template()])
    with pytest.raises(OwnerProfileAlreadyExists):
        store.create_owner([face_template(b"another-template")])
    store.close()


def test_replace_rotates_profile_and_replaces_template(tmp_path) -> None:
    store = SqliteOwnerProfileStore(
        tmp_path / "identity.db",
        key_protector=TestKeyProtector(),
    )
    first = store.create_owner([face_template(b"face-v1")])
    first_template = store.load_template(BiometricModality.FACE)

    second = store.replace_owner([face_template(b"face-v2")])
    second_template = store.load_template(BiometricModality.FACE)
    store.close()

    assert first.profile_version == 1
    assert second.profile_version == 2
    assert first_template.template_id != second_template.template_id
    assert second_template.payload == b"face-v2"


def test_delete_removes_live_profile_key_and_templates(tmp_path) -> None:
    store = SqliteOwnerProfileStore(
        tmp_path / "identity.db",
        key_protector=TestKeyProtector(),
    )
    store.create_owner([face_template()])

    assert store.delete_owner()
    assert not store.has_owner()
    assert not store.delete_owner()
    with pytest.raises(OwnerProfileNotFound):
        store.get_owner()
    with pytest.raises(OwnerProfileNotFound):
        store.load_template(BiometricModality.FACE)
    store.close()


def test_corrupt_ciphertext_fails_closed(tmp_path) -> None:
    db_path = tmp_path / "identity.db"
    store = SqliteOwnerProfileStore(db_path, key_protector=TestKeyProtector())
    store.create_owner([face_template()])

    connection = sqlite3.connect(db_path)
    row = connection.execute(
        "SELECT template_id, ciphertext FROM owner_biometric_template"
    ).fetchone()
    assert row is not None
    corrupted = bytearray(row[1])
    corrupted[-1] ^= 0x01
    connection.execute(
        "UPDATE owner_biometric_template SET ciphertext = ? WHERE template_id = ?",
        (bytes(corrupted), row[0]),
    )
    connection.commit()
    connection.close()

    with pytest.raises(OwnerProfileStoreError, match="integrity"):
        store.load_template(BiometricModality.FACE)
    store.close()


def test_metadata_tamper_fails_aead_binding(tmp_path) -> None:
    db_path = tmp_path / "identity.db"
    store = SqliteOwnerProfileStore(db_path, key_protector=TestKeyProtector())
    store.create_owner([face_template()])

    connection = sqlite3.connect(db_path)
    connection.execute("UPDATE owner_biometric_template SET model_version = 'tampered'")
    connection.commit()
    connection.close()

    with pytest.raises(OwnerProfileStoreError, match="integrity"):
        store.load_template(BiometricModality.FACE)
    store.close()


def test_key_protector_id_mismatch_fails_closed(tmp_path) -> None:
    db_path = tmp_path / "identity.db"
    original = SqliteOwnerProfileStore(db_path, key_protector=TestKeyProtector())
    original.create_owner([face_template()])
    original.close()

    reopened = SqliteOwnerProfileStore(
        db_path,
        key_protector=DifferentKeyProtector(),
    )
    with pytest.raises(KeyProtectorMismatch):
        reopened.load_template(BiometricModality.FACE)
    reopened.close()


def test_profile_database_enforces_single_owner_identifier(tmp_path) -> None:
    db_path = tmp_path / "identity.db"
    store = SqliteOwnerProfileStore(db_path, key_protector=TestKeyProtector())
    store.close()

    connection = sqlite3.connect(db_path)
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
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
            ("GUEST", 1, 1.0, 1.0, "test", uuid.uuid4().bytes),
        )
    connection.close()
