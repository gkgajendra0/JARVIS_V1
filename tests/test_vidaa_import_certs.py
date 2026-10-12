"""Offline acceptance tests for owner-supplied APK certificate import."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zipfile import ZipFile

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

from jarvis.vidaa.import_certs import (
    APP_KEYSTORE_PASSWORD,
    CertImportError,
    import_from_apk,
)


def create_test_keystore(
    *, subject_cn: str = "VidaaAppAndroidV01"
) -> tuple[bytes, bytes]:
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    client_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "RemoteCA")])
    now = datetime.now(timezone.utc)
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    client = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, subject_cn)]))
        .issuer_name(ca_name)
        .public_key(client_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=365))
        .sign(ca_key, hashes.SHA256())
    )
    p12 = pkcs12.serialize_key_and_certificates(
        b"VIDAA",
        client_key,
        client,
        [ca],
        serialization.BestAvailableEncryption(APP_KEYSTORE_PASSWORD),
    )
    return p12, ca.public_bytes(serialization.Encoding.PEM)


def make_apk(path: Path, entries: dict[str, bytes]) -> None:
    with ZipFile(path, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)


def test_imports_expected_signed_identity_without_exposing_key(tmp_path: Path) -> None:
    p12, ca = create_test_keystore()
    apk = tmp_path / "owner_app.apk"
    make_apk(apk, {"res/3R.p12": p12, "../ignore.txt": b"nothing"})
    destination = tmp_path / "owner_private"
    result = import_from_apk(apk, destination, trust_anchor_pem=ca)
    assert result["outcome"] == "local_vidaa_client_credentials_imported"
    assert result["pairing_completed"] is False
    assert "PRIVATE KEY" not in str(result)
    assert (
        (destination / "vidaa_client.pem")
        .read_bytes()
        .startswith(b"-----BEGIN CERTIFICATE-----")
    )
    assert (
        (destination / "vidaa_client.key")
        .read_bytes()
        .startswith(b"-----BEGIN PRIVATE KEY-----")
    )
    assert not (tmp_path / "ignore.txt").exists()
    if os.name != "nt":
        assert (destination / "vidaa_client.key").stat().st_mode & 0o077 == 0


def test_refuses_to_overwrite_existing_pair(tmp_path: Path) -> None:
    p12, ca = create_test_keystore()
    apk = tmp_path / "owner_app.apk"
    make_apk(apk, {"assets/client_mobile_android.p12": p12})
    destination = tmp_path / "certs"
    import_from_apk(apk, destination, trust_anchor_pem=ca)
    with pytest.raises(CertImportError, match="refusing to overwrite"):
        import_from_apk(apk, destination, trust_anchor_pem=ca)


def test_rejects_unknown_client_identity(tmp_path: Path) -> None:
    p12, ca = create_test_keystore(subject_cn="UnknownApp")
    apk = tmp_path / "owner_app.apk"
    make_apk(apk, {"res/3R.p12": p12})
    with pytest.raises(CertImportError, match="No valid"):
        import_from_apk(apk, tmp_path / "certs", trust_anchor_pem=ca)
    assert not (tmp_path / "certs").exists()


def test_rejects_wrong_remote_ca(tmp_path: Path) -> None:
    p12, _ = create_test_keystore()
    _, wrong_ca = create_test_keystore()
    apk = tmp_path / "owner_app.apk"
    make_apk(apk, {"res/3R.p12": p12})
    with pytest.raises(CertImportError, match="No valid"):
        import_from_apk(apk, tmp_path / "certs", trust_anchor_pem=wrong_ca)


def test_rejects_missing_pkcs12_without_creating_secret_files(tmp_path: Path) -> None:
    _, ca = create_test_keystore()
    apk = tmp_path / "owner_app.apk"
    make_apk(apk, {"other.txt": b"not a key"})
    with pytest.raises(CertImportError, match="No valid"):
        import_from_apk(apk, tmp_path / "certs", trust_anchor_pem=ca)
    assert not (tmp_path / "certs").exists()


def test_rejects_invalid_apk_file(tmp_path: Path) -> None:
    _, ca = create_test_keystore()
    apk = tmp_path / "owner_app.apk"
    apk.write_text("not a zip")
    with pytest.raises(CertImportError, match="valid APK"):
        import_from_apk(apk, tmp_path / "certs", trust_anchor_pem=ca)
