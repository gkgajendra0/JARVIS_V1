from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from jarvis.promotion.setup import (
    PromotionSetupError,
    configure_github_promotion,
)


class _FakeSecretStore:
    protector_id = "fake-dpapi"

    def __init__(self) -> None:
        self.descriptor = None
        self.enrolled_value: bytes | None = None
        self.rotated_value: bytes | None = None

    def verified_descriptor(self, secret_id: str):
        if self.descriptor is None:
            from jarvis.engineering_substrate.secrets.store import SecretNotFoundError

            raise SecretNotFoundError(secret_id)
        return self.descriptor

    def enroll(
        self,
        *,
        secret_id: str,
        kind: str,
        service: str,
        allowed_consumers: tuple[str, ...],
        allowed_scopes: tuple[str, ...],
        value: bytes,
    ):
        self.enrolled_value = value
        self.descriptor = SimpleNamespace(
            secret_id=secret_id,
            version=1,
            allowed_consumers=allowed_consumers,
            allowed_scopes=allowed_scopes,
        )
        return self.descriptor

    def rotate(self, secret_id: str, *, value: bytes):
        assert self.descriptor is not None
        assert secret_id == self.descriptor.secret_id
        self.rotated_value = value
        self.descriptor = SimpleNamespace(
            secret_id=secret_id,
            version=self.descriptor.version + 1,
            allowed_consumers=self.descriptor.allowed_consumers,
            allowed_scopes=self.descriptor.allowed_scopes,
        )
        return self.descriptor


def _pem(path: Path, marker: bytes = b"phase9-private") -> bytes:
    payload = (
        b"-----BEGIN PRIVATE KEY-----\n" + marker + b"\n-----END PRIVATE KEY-----\n"
    )
    path.write_bytes(payload)
    return payload


def test_github_promotion_setup_seals_key_and_persists_only_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    key_path = tmp_path / "app.pem"
    key = _pem(key_path)
    machine = tmp_path / "machine.json"
    store = _FakeSecretStore()

    result = configure_github_promotion(
        private_key_file=key_path,
        client_id="Iv1.phase9",
        installation_id=12345,
        repository_full_name="gkgajendra0/JARVIS_V1",
        machine_config_path=machine,
        secret_store=store,
    )

    assert result["status"] == "CONFIGURED"
    assert result["secret_disposition"] == "enrolled"
    assert result["private_key_persisted_in_machine_config"] is False
    assert store.enrolled_value == key
    persisted = machine.read_bytes()
    assert key not in persisted
    settings = json.loads(persisted)
    assert settings["JARVIS_GITHUB_PROMOTION_ENABLED"] == "true"
    assert settings["JARVIS_GITHUB_APP_SECRET_ID"] == "github-promotion-private-key"
    assert "PRIVATE_KEY" not in settings


def test_repeat_github_promotion_setup_rotates_same_scoped_secret(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    store = _FakeSecretStore()
    machine = tmp_path / "machine.json"
    first = tmp_path / "first.pem"
    second = tmp_path / "second.pem"
    _pem(first, b"first")
    second_value = _pem(second, b"second")

    configure_github_promotion(
        private_key_file=first,
        client_id="Iv1.phase9",
        installation_id=12345,
        repository_full_name="gkgajendra0/JARVIS_V1",
        machine_config_path=machine,
        secret_store=store,
    )
    result = configure_github_promotion(
        private_key_file=second,
        client_id="Iv1.phase9",
        installation_id=12345,
        repository_full_name="gkgajendra0/JARVIS_V1",
        machine_config_path=machine,
        secret_store=store,
    )

    assert result["secret_disposition"] == "rotated"
    assert result["secret_version"] == 2
    assert store.rotated_value == second_value


def test_github_promotion_setup_rejects_non_windows(
    tmp_path: Path,
) -> None:
    key_path = tmp_path / "app.pem"
    _pem(key_path)

    if sys.platform == "win32":
        pytest.skip("non-Windows rejection is covered on Linux CI")
    with pytest.raises(PromotionSetupError, match="Windows DPAPI"):
        configure_github_promotion(
            private_key_file=key_path,
            client_id="Iv1.phase9",
            installation_id=12345,
            repository_full_name="gkgajendra0/JARVIS_V1",
            machine_config_path=tmp_path / "machine.json",
            secret_store=_FakeSecretStore(),
        )


def test_github_promotion_setup_rejects_non_pem_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    key_path = tmp_path / "app.pem"
    key_path.write_text("not a private key", encoding="utf-8")

    with pytest.raises(PromotionSetupError, match="PEM"):
        configure_github_promotion(
            private_key_file=key_path,
            client_id="Iv1.phase9",
            installation_id=12345,
            repository_full_name="gkgajendra0/JARVIS_V1",
            machine_config_path=tmp_path / "machine.json",
            secret_store=_FakeSecretStore(),
        )
