"""Import VIDAA Android app client credentials locally from an owner-provided APK.

This tool NEVER downloads APKs, exposes keys on stdout, or commits secrets.
It supports documented PKCS#12 entries in the official VIDAA Android APK.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

EXPECTED_CLIENT_CN = "VidaaAppAndroidV01"
EXPECTED_CA_CN = "RemoteCA"
# Documented in the upstream pyvidaa protocol analysis; not a user credential.
APP_KEYSTORE_PASSWORD = b"186e990688070325a1c4b0ce275d2388"
CERT_NAME = "vidaa_client.pem"
KEY_NAME = "vidaa_client.key"
MAX_P12_SIZE = 1024 * 1024
MAX_P12_CANDIDATES = 25


class CertImportError(RuntimeError):
    """A locally recoverable APK/certificate import problem."""


def _common_name(name: x509.Name) -> str | None:
    values = name.get_attributes_for_oid(NameOID.COMMON_NAME)
    return values[0].value if values else None


def _default_trust_anchor() -> bytes:
    try:
        from pyvidaa.certs import bundled_ca_path
    except ImportError as exc:
        raise CertImportError("pyvidaa is not installed") from exc
    ca_path = bundled_ca_path()
    if not ca_path:
        raise CertImportError("pyvidaa RemoteCA trust anchor is missing")
    return Path(ca_path).read_bytes()


def _candidate_credentials(
    apk_path: Path, trust_anchor_pem: bytes
) -> tuple[bytes, bytes, str]:
    """Load only the expected client identity, signed by pyvidaa's RemoteCA."""
    try:
        ca = x509.load_pem_x509_certificate(trust_anchor_pem)
    except ValueError as exc:
        raise CertImportError("Invalid or missing trusted VIDAA RemoteCA") from exc
    if _common_name(ca.subject) != EXPECTED_CA_CN:
        raise CertImportError("Unexpected VIDAA CA identity")

    matches: dict[bytes, tuple[bytes, bytes, str]] = {}
    try:
        with ZipFile(apk_path) as archive:
            candidates = [
                info
                for info in archive.infolist()
                if not info.is_dir() and info.filename.lower().endswith(".p12")
            ]
            if len(candidates) > MAX_P12_CANDIDATES:
                raise CertImportError("Too many PKCS#12 entries in APK")
            for info in candidates:
                if info.file_size > MAX_P12_SIZE:
                    continue
                try:
                    with archive.open(info) as stream:
                        raw = stream.read(MAX_P12_SIZE + 1)
                    if len(raw) > MAX_P12_SIZE:
                        continue
                    key, cert, _ = pkcs12.load_key_and_certificates(
                        raw, APP_KEYSTORE_PASSWORD
                    )
                except (ValueError, TypeError):
                    continue
                if key is None or cert is None:
                    continue
                if (
                    _common_name(cert.subject) != EXPECTED_CLIENT_CN
                    or _common_name(cert.issuer) != EXPECTED_CA_CN
                ):
                    continue
                try:
                    cert.verify_directly_issued_by(ca)
                except (ValueError, InvalidSignature):
                    continue
                now = datetime.now(UTC)
                if not cert.not_valid_before_utc <= now < cert.not_valid_after_utc:
                    continue
                try:
                    private_key_bytes = key.private_bytes(
                        serialization.Encoding.PEM,
                        serialization.PrivateFormat.PKCS8,
                        serialization.NoEncryption(),
                    )
                    public_a = key.public_key().public_bytes(
                        serialization.Encoding.DER,
                        serialization.PublicFormat.SubjectPublicKeyInfo,
                    )
                    public_b = cert.public_key().public_bytes(
                        serialization.Encoding.DER,
                        serialization.PublicFormat.SubjectPublicKeyInfo,
                    )
                except (TypeError, ValueError):
                    continue
                if public_a != public_b:
                    continue
                pem = cert.public_bytes(serialization.Encoding.PEM)
                fingerprint = cert.fingerprint(hashes.SHA256())
                matches[fingerprint] = (
                    pem,
                    private_key_bytes,
                    cert.not_valid_after_utc.date().isoformat(),
                )
    except (BadZipFile, OSError) as exc:
        raise CertImportError("Unable to read a valid APK archive") from exc
    if not matches:
        raise CertImportError(
            "No valid, RemoteCA-signed VIDAA Android client keystore found in APK"
        )
    if len(matches) != 1:
        raise CertImportError("Multiple differing VIDAA client identities in APK")
    return next(iter(matches.values()))


def _write_exclusive(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    if os.name != "nt":
        path.chmod(0o600)


def import_from_apk(
    apk_path: Path,
    output_dir: Path | None = None,
    *,
    trust_anchor_pem: bytes | None = None,
) -> dict[str, str | bool]:
    """Validate app certificate against expected CA before any file is written."""
    apk_path = Path(apk_path)
    if not apk_path.is_file() or apk_path.suffix.lower() != ".apk":
        raise CertImportError(
            "Provide a local .apk file from your own app installation"
        )
    if apk_path.stat().st_size > 500 * 1024 * 1024:
        raise CertImportError("APK exceeds maximum supported size")

    ca_pem = (
        trust_anchor_pem if trust_anchor_pem is not None else _default_trust_anchor()
    )
    cert_bytes, key_bytes, expires_on = _candidate_credentials(apk_path, ca_pem)
    directory = output_dir or (Path.home() / ".config" / "pyvidaa" / "certs")
    directory = Path(directory).expanduser()
    cert_path = directory / CERT_NAME
    key_path = directory / KEY_NAME
    if cert_path.exists() or key_path.exists():
        raise CertImportError(
            "Client cert or key already exists; refusing to overwrite local credentials"
        )

    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        directory.chmod(0o700)
    created: list[Path] = []
    try:
        _write_exclusive(key_path, key_bytes)
        created.append(key_path)
        _write_exclusive(cert_path, cert_bytes)
        created.append(cert_path)
    except OSError as exc:
        for item in created:
            item.unlink(missing_ok=True)
        raise CertImportError(
            "Could not securely create new certificate files"
        ) from exc
    return {
        "outcome": "local_vidaa_client_credentials_imported",
        "directory": str(directory),
        "certificate_expires_on": expires_on,
        "tv_authenticated": False,
        "pairing_completed": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Import owner-sourced VIDAA Android APK certificate (offline only)."
    )
    parser.add_argument("--apk", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = import_from_apk(args.apk)
    except CertImportError as exc:
        print(json.dumps({"outcome": "blocked", "reason": str(exc)}))
        return 2
    except Exception as exc:  # noqa: BLE001 - never leak raw PKCS#12 data
        print(json.dumps({"outcome": "error", "error_type": type(exc).__name__}))
        return 3
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
