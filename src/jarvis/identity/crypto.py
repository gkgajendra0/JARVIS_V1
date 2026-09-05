from __future__ import annotations

import json
import os
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from jarvis.security import (
    KeyProtectionError as KeyProtectionError,
    KeyProtector as KeyProtector,
    SecurityError as IdentityCryptoError,
    WindowsDpapiKeyProtector as WindowsDpapiKeyProtector,
)


class TemplateIntegrityError(IdentityCryptoError):
    pass


@dataclass(frozen=True, slots=True)
class EncryptedPayload:
    nonce: bytes
    ciphertext: bytes


class EnvelopeCipher:
    KEY_BYTES = 32
    NONCE_BYTES = 12

    @staticmethod
    def generate_dek() -> bytes:
        return AESGCM.generate_key(bit_length=256)

    @staticmethod
    def encrypt(*, dek: bytes, plaintext: bytes, aad: bytes) -> EncryptedPayload:
        if len(dek) != EnvelopeCipher.KEY_BYTES:
            raise IdentityCryptoError("profile DEK must be 256 bits")
        if not plaintext:
            raise IdentityCryptoError("plaintext must not be empty")
        nonce = os.urandom(EnvelopeCipher.NONCE_BYTES)
        ciphertext = AESGCM(dek).encrypt(nonce, plaintext, aad)
        return EncryptedPayload(nonce=nonce, ciphertext=ciphertext)

    @staticmethod
    def decrypt(*, dek: bytes, payload: EncryptedPayload, aad: bytes) -> bytes:
        if len(dek) != EnvelopeCipher.KEY_BYTES:
            raise IdentityCryptoError("profile DEK must be 256 bits")
        if len(payload.nonce) != EnvelopeCipher.NONCE_BYTES:
            raise TemplateIntegrityError("encrypted template nonce is invalid")
        try:
            return AESGCM(dek).decrypt(payload.nonce, payload.ciphertext, aad)
        except InvalidTag as exc:
            raise TemplateIntegrityError(
                "encrypted template authentication failed"
            ) from exc


def canonical_aad(value: dict[str, object]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
