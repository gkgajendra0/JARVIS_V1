"""At-rest protection for sensitive persistent-work payloads."""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from jarvis.security import KeyProtectionError, KeyProtector, WindowsDpapiKeyProtector

_KEY_BYTES = 32
_NONCE_BYTES = 12
_KEY_PURPOSE = "work-payload-master-key-v1"
_AAD = b"jarvis-work-payload-v1"
_PREFIX = "enc:v1:"


class WorkPayloadProtectionError(RuntimeError):
    pass


class WorkPayloadCodec(Protocol):
    protects_at_rest: bool

    def encode(self, value: str) -> str: ...

    def decode(self, value: str) -> str: ...

    def is_protected(self, value: str) -> bool: ...


class PlaintextWorkPayloadCodec:
    protects_at_rest = False

    def encode(self, value: str) -> str:
        return value

    def decode(self, value: str) -> str:
        return value

    def is_protected(self, value: str) -> bool:
        del value
        return False


class ProtectedWorkPayloadCodec:
    """AES-GCM field protection using a separately protected local master key."""

    protects_at_rest = True

    def __init__(self, key: bytes) -> None:
        if len(key) != _KEY_BYTES:
            raise WorkPayloadProtectionError("work payload key must be 32 bytes")
        self._cipher = AESGCM(bytes(key))

    def encode(self, value: str) -> str:
        if self.is_protected(value):
            return value
        nonce = os.urandom(_NONCE_BYTES)
        ciphertext = self._cipher.encrypt(nonce, value.encode("utf-8"), _AAD)
        token = base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")
        return _PREFIX + token

    def decode(self, value: str) -> str:
        if not self.is_protected(value):
            return value
        token = value[len(_PREFIX) :]
        try:
            raw = base64.urlsafe_b64decode(token.encode("ascii"))
            if len(raw) <= _NONCE_BYTES:
                raise ValueError("encrypted payload is too short")
            plaintext = self._cipher.decrypt(
                raw[:_NONCE_BYTES],
                raw[_NONCE_BYTES:],
                _AAD,
            )
            return plaintext.decode("utf-8")
        except Exception as exc:
            raise WorkPayloadProtectionError(
                "persistent work payload could not be decrypted"
            ) from exc

    def is_protected(self, value: str) -> bool:
        return value.startswith(_PREFIX)


class WorkPayloadKeyStore:
    """Persist only a KeyProtector-sealed work-payload key."""

    def __init__(
        self,
        path: str | Path,
        *,
        key_protector: KeyProtector,
        random_bytes=os.urandom,
    ) -> None:
        self._path = Path(path).expanduser().resolve()
        self._protector = key_protector
        self._random_bytes = random_bytes

    def load_or_create(self) -> bytes:
        if self._path.exists():
            try:
                sealed = self._path.read_bytes()
                key = self._protector.unseal(sealed, purpose=_KEY_PURPOSE)
            except (OSError, KeyProtectionError) as exc:
                raise WorkPayloadProtectionError(
                    "protected work payload key could not be loaded"
                ) from exc
            if len(key) != _KEY_BYTES:
                raise WorkPayloadProtectionError(
                    "unsealed work payload key must be 32 bytes"
                )
            return key

        key = self._random_bytes(_KEY_BYTES)
        if len(key) != _KEY_BYTES:
            raise WorkPayloadProtectionError(
                "work payload key generator did not return 32 bytes"
            )
        try:
            sealed = self._protector.seal(key, purpose=_KEY_PURPOSE)
        except KeyProtectionError as exc:
            raise WorkPayloadProtectionError(
                "work payload key could not be protected"
            ) from exc
        if not sealed:
            raise WorkPayloadProtectionError("protected work payload key is empty")

        self._path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        try:
            descriptor = os.open(self._path, flags, 0o600)
        except OSError as exc:
            raise WorkPayloadProtectionError(
                "protected work payload key could not be created"
            ) from exc
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(sealed)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            self._path.unlink(missing_ok=True)
            raise
        return key


def default_work_payload_key_path(database_path: str | Path) -> Path:
    path = Path(database_path)
    return path.with_name(f"{path.stem}.key.dpapi")


def build_protected_work_payload_codec(
    database_path: str | Path,
    *,
    key_protector: KeyProtector,
    random_bytes=os.urandom,
) -> ProtectedWorkPayloadCodec:
    key = WorkPayloadKeyStore(
        default_work_payload_key_path(database_path),
        key_protector=key_protector,
        random_bytes=random_bytes,
    ).load_or_create()
    try:
        return ProtectedWorkPayloadCodec(key)
    finally:
        del key


def build_default_work_payload_codec(
    database_path: str | Path,
) -> WorkPayloadCodec:
    """Use user-scoped DPAPI on Windows; direct non-Windows tests stay explicit/plain."""

    if os.name != "nt":
        return PlaintextWorkPayloadCodec()
    return build_protected_work_payload_codec(
        database_path,
        key_protector=WindowsDpapiKeyProtector(),
    )
