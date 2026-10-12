"""Tests for manual VIDAA controls without network access or pyvidaa installed."""

from argparse import Namespace
from types import SimpleNamespace

import pytest

from jarvis.vidaa.manual import (
    VidaaManualError,
    execute,
    make_parser,
    validate_target,
)


def args(command: str, **extra: object) -> Namespace:
    values = {
        "host": "192.168.1.10",
        "port": 36669,
        "mac": None,
        "persist_tokens": False,
        "command": command,
        "key": None,
        "app": None,
    }
    values.update(extra)
    return Namespace(**values)


class FakeClient:
    def __init__(self) -> None:
        self.connected = False
        self.disconnected = False
        self.commands: list[str] = []
        self.authenticated = False

    def connect(self, *, timeout: float) -> bool:
        self.connected = True
        return True

    def disconnect(self) -> None:
        self.disconnected = True

    def start_pairing(self) -> None:
        self.commands.append("pair_requested")

    def authenticate(self, pin: str) -> bool:
        self.authenticated = pin == "1234"
        return self.authenticated

    def get_state(self) -> dict[str, str]:
        return {"statetype": "livetv"}

    def get_volume(self) -> int:
        return 25

    def get_apps(self) -> list[dict[str, str]]:
        return [{"name": "YouTube"}, {"name": "Disney+ Hotstar"}]

    def send_key(self, key: str) -> None:
        self.commands.append(key)

    def launch_app(self, app: str) -> None:
        self.commands.append("launch:" + app)


@pytest.mark.parametrize("host", ["8.8.8.8", "127.0.0.1", "fe80::1", "example.com"])
def test_rejects_non_lan_hosts(host: str) -> None:
    with pytest.raises(VidaaManualError):
        validate_target(host, 36669, None)


def test_probe_does_not_identify_tv() -> None:
    class Socket:
        def close(self) -> None:
            pass

    def connector(address: object, *, timeout: float) -> Socket:
        assert address == ("192.168.1.10", 36669)
        return Socket()

    result = execute(args("probe"), socket_connector=connector)
    assert result["outcome"] == "tcp_reachable_only"
    assert result["tv_verified"] is False


def test_pair_requires_screen_pin_and_closes() -> None:
    client = FakeClient()
    result = execute(
        args("pair", persist_tokens=True),
        client_factory=lambda _: client,
        pin_reader=lambda _: "1234",
    )
    assert result["outcome"] == "sdk_pairing_acknowledged"
    assert result["tokens_persisted_by_sdk"] is True
    assert "1234" not in str(result)
    assert client.disconnected


def test_bad_pin_fails_and_disconnects() -> None:
    client = FakeClient()
    with pytest.raises(VidaaManualError, match="PIN"):
        execute(
            args("pair"),
            client_factory=lambda _: client,
            pin_reader=lambda _: "abc",
        )
    assert client.disconnected


def test_key_uses_allowlisted_protocol_constant() -> None:
    client = FakeClient()
    result = execute(args("key", key="home"), client_factory=lambda _: client)
    assert client.commands == ["KEY_HOME"]
    assert result["tv_effect_verified"] is False
    assert client.disconnected


def test_app_must_be_reported_by_tv() -> None:
    client = FakeClient()
    with pytest.raises(VidaaManualError, match="not confirmed"):
        execute(
            args("launch", app="Unknown"),
            client_factory=lambda _: client,
        )
    assert client.commands == []
    assert client.disconnected


def test_app_launch_uses_exact_advertised_name() -> None:
    client = FakeClient()
    result = execute(
        args("launch", app="disney+ hotstar"), client_factory=lambda _: client
    )
    assert client.commands == ["launch:Disney+ Hotstar"]
    assert result["outcome"] == "launch_submitted_unverified"


def test_parser_only_accepts_supported_key_names() -> None:
    parser = make_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--host", "192.168.1.10", "key", "dangerous_unknown"])


def test_status_does_not_claim_visual_confirmation() -> None:
    result = execute(args("status"), client_factory=lambda _: FakeClient())
    assert result["state"]["statetype"] == "livetv"
    assert result["tv_effect_verified"] is False


def test_identify_detects_vidaa_descriptor_without_pairing() -> None:
    def fake_probe(host: str, *, timeout: float) -> SimpleNamespace:
        assert host == "192.168.1.10"
        assert timeout == 3.0
        return SimpleNamespace(
            name="Living Room",
            model="Hisense U7N",
            brand="Hisense",
            protocol_version="3290",
        )

    result = execute(args("identify"), device_probe=fake_probe)
    assert result["outcome"] == "vidaa_upnp_candidate"
    assert result["model"] == "Hisense U7N"
    assert result["tv_verified"] is False
    assert result["control_verified"] is False


def test_identify_no_descriptor_is_not_negative_proof() -> None:
    result = execute(args("identify"), device_probe=lambda host, timeout: None)
    assert result["outcome"] == "vidaa_upnp_not_observed"
    assert result["tv_verified"] is False


def test_certificate_check_never_returns_key_material() -> None:
    result = execute(args("certs"), cert_resolver=lambda: ("cert.pem", "secret.key"))
    assert result["tls_files_found"] is True
    assert "secret.key" not in str(result)
    assert result["tls_handshake_verified"] is False


def test_certificate_check_reports_missing_without_connecting() -> None:
    result = execute(args("certs"), cert_resolver=lambda: None)
    assert result["outcome"] == "client_certificate_pair_missing"
    assert result["tls_files_found"] is False


def test_connect_failure_without_certs_explains_transport_blocker() -> None:
    class FailingClient(FakeClient):
        def connect(self, *, timeout: float) -> bool:
            return False

    client = FailingClient()
    with pytest.raises(VidaaManualError, match="mutual TLS"):
        execute(args("pair"), client_factory=lambda _: client, cert_resolver=lambda: None)
    assert client.disconnected
