from __future__ import annotations

import ctypes
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from typing import Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class IdentityCryptoError(RuntimeError):
    pass


class KeyProtectionError(IdentityCryptoError):
    pass


class TemplateIntegrityError(IdentityCryptoError):
    pass


class KeyProtector(Protocol):
    protector_id: str

    def seal(self, plaintext: bytes, *, purpose: str) -> bytes: ...

    def unseal(self, sealed: bytes, *, purpose: str) -> bytes: ...


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


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.c_uint32),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


class WindowsDpapiKeyProtector:
    """User-scoped Windows DPAPI key protector with purpose-bound entropy."""

    protector_id = "windows-dpapi-user-v1"
    _CRYPTPROTECT_UI_FORBIDDEN = 0x1

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise KeyProtectionError("Windows DPAPI is available only on Windows")
        self._crypt32 = ctypes.WinDLL("Crypt32.dll", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("Kernel32.dll", use_last_error=True)
        self._configure_signatures()

    def seal(self, plaintext: bytes, *, purpose: str) -> bytes:
        if not plaintext:
            raise KeyProtectionError("cannot seal an empty key")
        entropy = self._purpose_entropy(purpose)
        in_blob, in_buffer = self._blob(plaintext)
        entropy_blob, entropy_buffer = self._blob(entropy)
        out_blob = _DataBlob()
        _ = in_buffer, entropy_buffer
        ok = self._crypt32.CryptProtectData(
            ctypes.byref(in_blob),
            None,
            ctypes.byref(entropy_blob),
            None,
            None,
            self._CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(out_blob),
        )
        if not ok:
            self._raise_last_error("CryptProtectData failed")
        return self._copy_and_free(out_blob)

    def unseal(self, sealed: bytes, *, purpose: str) -> bytes:
        if not sealed:
            raise KeyProtectionError("sealed key must not be empty")
        entropy = self._purpose_entropy(purpose)
        in_blob, in_buffer = self._blob(sealed)
        entropy_blob, entropy_buffer = self._blob(entropy)
        out_blob = _DataBlob()
        _ = in_buffer, entropy_buffer
        ok = self._crypt32.CryptUnprotectData(
            ctypes.byref(in_blob),
            None,
            ctypes.byref(entropy_blob),
            None,
            None,
            self._CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(out_blob),
        )
        if not ok:
            self._raise_last_error("CryptUnprotectData failed")
        return self._copy_and_free(out_blob)

    def _configure_signatures(self) -> None:
        blob_ptr = ctypes.POINTER(_DataBlob)
        self._crypt32.CryptProtectData.argtypes = [
            blob_ptr,
            ctypes.c_wchar_p,
            blob_ptr,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint32,
            blob_ptr,
        ]
        self._crypt32.CryptProtectData.restype = ctypes.c_int
        self._crypt32.CryptUnprotectData.argtypes = [
            blob_ptr,
            ctypes.c_void_p,
            blob_ptr,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint32,
            blob_ptr,
        ]
        self._crypt32.CryptUnprotectData.restype = ctypes.c_int
        self._kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        self._kernel32.LocalFree.restype = ctypes.c_void_p

    @staticmethod
    def _purpose_entropy(purpose: str) -> bytes:
        normalized = purpose.strip()
        if not normalized:
            raise KeyProtectionError("DPAPI purpose must not be empty")
        return hashlib.sha256(f"jarvis:{normalized}".encode()).digest()

    @staticmethod
    def _blob(data: bytes) -> tuple[_DataBlob, ctypes.Array[ctypes.c_char]]:
        buffer = ctypes.create_string_buffer(data, len(data))
        pointer = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
        return _DataBlob(len(data), pointer), buffer

    def _copy_and_free(self, blob: _DataBlob) -> bytes:
        try:
            if not blob.pbData or blob.cbData == 0:
                raise KeyProtectionError("DPAPI returned empty output")
            return ctypes.string_at(blob.pbData, blob.cbData)
        finally:
            if blob.pbData:
                self._kernel32.LocalFree(blob.pbData)

    @staticmethod
    def _raise_last_error(message: str) -> None:
        code = ctypes.get_last_error()
        detail = ctypes.WinError(code)
        raise KeyProtectionError(f"{message}: {detail}")
