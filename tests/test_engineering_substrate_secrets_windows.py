from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest

from jarvis.engineering_substrate import SecretIntegrityError, SecretStore

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows DPAPI only")


def test_windows_user_dpapi_secret_store_round_trip_and_plaintext_absence(
    tmp_path: Path,
) -> None:
    store = SecretStore(tmp_path / "secrets.sqlite")
    value = f"phase5e-ci-{uuid.uuid4()}".encode()

    descriptor = store.enroll(
        secret_id="windows-dpapi-smoke",
        kind="disposable-test-token",
        service="phase5e-ci",
        allowed_consumers=("phase5e.test.v1",),
        allowed_scopes=("test.read",),
        value=value,
    )

    assert store.materialize(descriptor.secret_id).value == value
    assert value not in store.path.read_bytes()


def test_windows_dpapi_sealed_blob_tamper_fails_closed(tmp_path: Path) -> None:
    import sqlite3

    store = SecretStore(tmp_path / "secrets.sqlite")
    store.enroll(
        secret_id="windows-dpapi-tamper",
        kind="disposable-test-token",
        service="phase5e-ci",
        allowed_consumers=("phase5e.test.v1",),
        allowed_scopes=("test.read",),
        value=os.urandom(32).hex().encode("ascii"),
    )

    with sqlite3.connect(store.path) as connection:
        row = connection.execute(
            "SELECT sealed_envelope FROM secrets WHERE secret_id = ?",
            ("windows-dpapi-tamper",),
        ).fetchone()
        assert row is not None
        blob = bytearray(row[0])
        blob[len(blob) // 2] ^= 0x01
        connection.execute(
            "UPDATE secrets SET sealed_envelope = ? WHERE secret_id = ?",
            (bytes(blob), "windows-dpapi-tamper"),
        )

    with pytest.raises(SecretIntegrityError, match="unsealing"):
        store.materialize("windows-dpapi-tamper")
