from __future__ import annotations

import os
import sys

import pytest

from jarvis.identity import KeyProtectionError, WindowsDpapiKeyProtector

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows DPAPI only")


def test_windows_dpapi_user_scope_round_trip_and_purpose_binding() -> None:
    protector = WindowsDpapiKeyProtector()
    key = os.urandom(32)

    sealed = protector.seal(key, purpose="phase3b-ci-smoke")

    assert sealed != key
    assert protector.unseal(sealed, purpose="phase3b-ci-smoke") == key
    with pytest.raises(KeyProtectionError):
        protector.unseal(sealed, purpose="different-purpose")
