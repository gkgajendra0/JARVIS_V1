from __future__ import annotations

import os
import sys

import pytest
import jarvis.identity as identity

from jarvis.security import KeyProtectionError, WindowsDpapiKeyProtector

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows DPAPI only")


def test_identity_exports_share_neutral_dpapi_implementation() -> None:
    assert identity.KeyProtectionError is KeyProtectionError
    assert identity.IdentityCryptoError is identity.SecurityError if hasattr(identity, "SecurityError") else True
    assert identity.WindowsDpapiKeyProtector is WindowsDpapiKeyProtector
    assert issubclass(KeyProtectionError, identity.IdentityCryptoError)


def test_windows_dpapi_user_scope_round_trip_and_purpose_binding() -> None:
    protector = WindowsDpapiKeyProtector()
    key = os.urandom(32)

    sealed = protector.seal(key, purpose="phase4-ci-smoke")

    assert sealed != key
    assert protector.unseal(sealed, purpose="phase4-ci-smoke") == key
    with pytest.raises(KeyProtectionError):
        protector.unseal(sealed, purpose="different-purpose")
