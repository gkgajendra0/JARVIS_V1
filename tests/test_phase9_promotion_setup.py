from __future__ import annotations

from types import SimpleNamespace

import pytest

from jarvis.engineering_substrate.secrets.store import SecretNotFoundError
from jarvis.machine_config import load_machine_settings
from jarvis.promotion import setup as promotion_setup


class FakeSecretStore:
    protector_id = "fake-dpapi"

    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}
        self.versions: dict[str, int] = {}

    def verified_descriptor(self, secret_id: str):
        if secret_id not in self.values:
            raise SecretNotFoundError(secret_id)
        return SimpleNamespace(
            secret_id=secret_id,
            version=self.versions[secret_id],
            allowed_consumers=("github.promotion.v1",),
            allowed_scopes=("repository.promotion",),
        )

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
        assert kind == "github-app-private-key"
        assert service == "github-promotion"
        assert allowed_consumers == ("github.promotion.v1",)
        assert allowed_scopes == ("repository.promotion",)
        self.values[secret_id] = value
        self.versions[secret_id] = 1
        return self.verified_descriptor(secret_id)

    def rotate(self, secret_id: str, *, value: bytes):
        self.values[secret_id] = value
        self.versions[secret_id] += 1
        return self.verified_descriptor(secret_id)


def _pem() -> bytes:
    return (
        b"-----BEGIN PRIVATE KEY-----\n"
        b"phase9-test-private-key-material\n"
        b"-----END PRIVATE KEY-----\n"
    )


def test_promotion_setup_seals_key_reference_and_persists_only_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(promotion_setup.sys, "platform", "win32")
    key_path = tmp_path / "github-app.pem"
    key_path.write_bytes(_pem())
    machine = tmp_path / "machine.json"
    store = FakeSecretStore()

    result = promotion_setup.configure_github_promotion(
        private_key_file=key_path,
        client_id="Iv1.phase9",
        installation_id=12345,
        repository_full_name="gkgajendra0/JARVIS_V1",
        machine_config_path=machine,
        secret_store=store,
    )

    assert result["status"] == "CONFIGURED"
    assert result["secret_disposition"] == "enrolled"
    assert store.values["github-promotion-private-key"] == _pem()
    assert _pem() not in machine.read_bytes()
    settings = load_machine_settings(machine)
    assert settings["JARVIS_GITHUB_PROMOTION_ENABLED"] == "true"
    assert settings["JARVIS_GITHUB_APP_SECRET_ID"] == "github-promotion-private-key"
    assert all("PRIVATE_KEY" not in key for key in settings)


def test_promotion_setup_rotates_existing_dpapi_secret(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(promotion_setup.sys, "platform", "win32")
    first = tmp_path / "first.pem"
    second = tmp_path / "second.pem"
    first.write_bytes(_pem())
    second.write_bytes(
        b"-----BEGIN PRIVATE KEY-----\nrotated\n-----END PRIVATE KEY-----\n"
    )
    store = FakeSecretStore()
    machine = tmp_path / "machine.json"

    promotion_setup.configure_github_promotion(
        private_key_file=first,
        client_id="Iv1.phase9",
        installation_id=12345,
        repository_full_name="gkgajendra0/JARVIS_V1",
        machine_config_path=machine,
        secret_store=store,
    )
    result = promotion_setup.configure_github_promotion(
        private_key_file=second,
        client_id="Iv1.phase9",
        installation_id=12345,
        repository_full_name="gkgajendra0/JARVIS_V1",
        machine_config_path=machine,
        secret_store=store,
    )

    assert result["secret_disposition"] == "rotated"
    assert result["secret_version"] == 2


def test_promotion_setup_rejects_non_pem_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(promotion_setup.sys, "platform", "win32")
    key_path = tmp_path / "bad.pem"
    key_path.write_text("not a private key", encoding="utf-8")

    with pytest.raises(promotion_setup.PromotionSetupError, match="PEM"):
        promotion_setup.configure_github_promotion(
            private_key_file=key_path,
            client_id="Iv1.phase9",
            installation_id=12345,
            repository_full_name="gkgajendra0/JARVIS_V1",
            machine_config_path=tmp_path / "machine.json",
            secret_store=FakeSecretStore(),
        )


def test_promotion_setup_rejects_non_windows(tmp_path) -> None:
    if promotion_setup.sys.platform == "win32":
        pytest.skip("non-Windows rejection is covered on Linux CI")
    key_path = tmp_path / "github-app.pem"
    key_path.write_bytes(_pem())

    with pytest.raises(promotion_setup.PromotionSetupError, match="Windows DPAPI"):
        promotion_setup.configure_github_promotion(
            private_key_file=key_path,
            client_id="Iv1.phase9",
            installation_id=12345,
            repository_full_name="gkgajendra0/JARVIS_V1",
            machine_config_path=tmp_path / "machine.json",
            secret_store=FakeSecretStore(),
        )
