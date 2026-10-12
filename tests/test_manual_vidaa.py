"""Tests for manual VIDAA controls without network access or pyvidaa installed."""

import sys
from argparse import Namespace
from types import ModuleType, SimpleNamespace

import pytest

from jarvis.vidaa.manual import (
    VidaaManualError,
    execute,
    make_parser,
    new_client,
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
        execute(
            args("pair"), client_factory=lambda _: client, cert_resolver=lambda: None
        )
    assert client.disconnected


def test_client_auto_reads_matching_tv_mac_for_dynamic_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_module = ModuleType("pyvidaa")
    observed: dict[str, object] = {}

    def mock_client(**kwargs: object) -> dict[str, object]:
        observed.update(kwargs)
        return observed

    def mock_probe(host: str, *, timeout: float) -> SimpleNamespace:
        assert timeout == 3.0
        return SimpleNamespace(
            ip=host,
            mac="AA:BB:CC:DD:EE:FF",
            protocol_version="3290",
        )

    mock_module.VidaaTV = mock_client  # type: ignore[attr-defined]
    mock_module.probe_ip = mock_probe  # type: ignore[attr-defined]
    mock_module.discover_udp = lambda **kwargs: {}  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pyvidaa", mock_module)
    new_client(args("status"))
    assert observed["mac_address"] == "AA:BB:CC:DD:EE:FF"
    assert observed["use_dynamic_auth"] is True
    assert observed["auto_detect_protocol"] is True
    assert observed["allow_static_auth"] is False


def test_modern_device_without_mac_requests_local_network_mac(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_module = ModuleType("pyvidaa")
    mock_module.VidaaTV = lambda **kwargs: kwargs  # type: ignore[attr-defined]
    mock_module.probe_ip = (  # type: ignore[attr-defined]
        lambda host, timeout: SimpleNamespace(
            ip=host, mac=None, protocol_version="3290"
        )
    )
    mock_module.discover_udp = lambda **kwargs: {}  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pyvidaa", mock_module)
    with pytest.raises(VidaaManualError, match="TV MAC unavailable"):
        new_client(args("pair"))


def test_explicit_mac_still_enables_dynamic_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_module = ModuleType("pyvidaa")
    observed: dict[str, object] = {}

    def mock_client(**kwargs: object) -> object:
        observed.update(kwargs)
        return object()

    def unexpected_probe(host: str, *, timeout: float) -> None:
        pytest.fail("Explicit MAC must not trigger network discovery")

    mock_module.VidaaTV = mock_client  # type: ignore[attr-defined]
    mock_module.probe_ip = unexpected_probe  # type: ignore[attr-defined]
    mock_module.discover_udp = unexpected_probe  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pyvidaa", mock_module)

    new_client(args("pair", mac="AA:BB:CC:DD:EE:FF"))
    assert observed["mac_address"] == "AA:BB:CC:DD:EE:FF"
    assert observed["use_dynamic_auth"] is True
    assert observed["allow_static_auth"] is False


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (4, "bad MQTT username/password"),
        (5, "MQTT not authorized"),
    ],
)
def test_connect_failure_reports_mqtt_rejection_without_secrets(
    code: int, expected: str
) -> None:
    class RejectedClient(FakeClient):
        _last_connack_rc = code

        def connect(self, *, timeout: float) -> bool:
            return False

    client = RejectedClient()
    with pytest.raises(VidaaManualError, match=expected) as failure:
        execute(
            args("pair"),
            client_factory=lambda _: client,
            cert_resolver=lambda: ("cert.pem", "secret.key"),
        )
    assert "secret.key" not in str(failure.value)
    assert client.disconnected


def test_connection_failure_without_connack_does_not_claim_auth_rejection() -> None:
    class DroppedClient(FakeClient):
        _last_connack_rc = None

        def connect(self, *, timeout: float) -> bool:
            return False

    client = DroppedClient()
    with pytest.raises(VidaaManualError, match="without an observed MQTT CONNACK"):
        execute(
            args("pair"),
            client_factory=lambda _: client,
            cert_resolver=lambda: ("cert.pem", "secret.key"),
        )
    assert client.disconnected


def test_udp_discovery_when_upnp_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = ModuleType("pyvidaa")
    observed: dict[str, object] = {}

    def construct(**kwargs: object) -> object:
        observed.update(kwargs)
        return object()

    module.VidaaTV = construct  # type: ignore[attr-defined]
    module.probe_ip = lambda host, timeout: None  # type: ignore[attr-defined]
    module.discover_udp = (  # type: ignore[attr-defined]
        lambda timeout, retries: {
            "192.168.1.10": SimpleNamespace(ip="192.168.1.10", mac="AABBCCDDEEFF")
        }
    )
    monkeypatch.setitem(sys.modules, "pyvidaa", module)
    new_client(args("pair"))
    assert observed["mac_address"] == "AA:BB:CC:DD:EE:FF"
    assert observed["allow_static_auth"] is False


def test_udp_identity_from_different_host_not_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = ModuleType("pyvidaa")
    module.VidaaTV = lambda **kwargs: object()  # type: ignore[attr-defined]
    module.probe_ip = lambda host, timeout: None  # type: ignore[attr-defined]
    module.discover_udp = (  # type: ignore[attr-defined]
        lambda timeout, retries: {
            "192.168.1.13": SimpleNamespace(ip="192.168.1.13", mac="AA:BB:CC:DD:EE:FF")
        }
    )
    monkeypatch.setitem(sys.modules, "pyvidaa", module)
    with pytest.raises(VidaaManualError, match="TV MAC unavailable"):
        new_client(args("pair"))


def test_discover_reports_unverified_targets_without_mac_secrets() -> None:
    def candidates(*, timeout: float, retries: int) -> dict[str, SimpleNamespace]:
        assert timeout == 4.0
        assert retries == 2
        return {
            "192.168.1.10": SimpleNamespace(
                name="Living Room TV", model=None, mac="AA:BB:CC:DD:EE:FF"
            ),
            "8.8.8.8": SimpleNamespace(name="Untrusted", model=None, mac="SECRET"),
        }

    result = execute(args("discover"), udp_discover=candidates)
    assert result["outcome"] == "vidaa_udp_candidates"
    assert len(result["candidates"]) == 1
    assert result["candidates"][0]["matches_requested_host"] is True
    assert result["candidates"][0]["tv_verified"] is False
    assert "AA:BB:CC:DD:EE:FF" not in str(result)


def test_no_udp_sightings_does_not_prove_no_tv() -> None:
    result = execute(args("discover"), udp_discover=lambda **kwargs: {})
    assert result["outcome"] == "no_vidaa_udp_candidates"
    assert result["candidates"] == []


def test_known_protocol_bypasses_upnp_detection_and_keeps_dynamic_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = ModuleType("pyvidaa")
    captured: dict[str, object] = {}

    def construct(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    def fail_if_discovery(*args: object, **kwargs: object) -> None:
        pytest.fail("Known MAC/protocol must not access UPnP or UDP discovery")

    module.VidaaTV = construct  # type: ignore[attr-defined]
    module.AuthMethod = SimpleNamespace(MODERN="modern")  # type: ignore[attr-defined]
    module.probe_ip = fail_if_discovery  # type: ignore[attr-defined]
    module.discover_udp = fail_if_discovery  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pyvidaa", module)

    new_client(
        args(
            "key",
            mac="50:BA:02:AE:0D:18",
            protocol_version=3290,
            persist_tokens=True,
        )
    )
    assert captured["auth_method"] == "modern"
    assert captured["auto_detect_protocol"] is False
    assert captured["use_dynamic_auth"] is True
    assert captured["allow_static_auth"] is False
    assert captured["enable_persistence"] is True


def test_default_protocol_still_auto_detects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = ModuleType("pyvidaa")
    captured: dict[str, object] = {}

    def construct(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    module.VidaaTV = construct  # type: ignore[attr-defined]
    module.probe_ip = lambda *args, **kwargs: None  # type: ignore[attr-defined]
    module.discover_udp = lambda *args, **kwargs: {}  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pyvidaa", module)
    new_client(args("key", mac="AA:BB:CC:DD:EE:FF"))
    assert captured["auto_detect_protocol"] is True
    assert "auth_method" not in captured


def test_session_reuses_one_authenticated_client() -> None:
    client = FakeClient()
    iterator = iter(("home", "volume-up", "exit"))

    result = execute(
        args("session"),
        client_factory=lambda _: client,
        command_reader=lambda _: next(iterator),
    )
    assert client.commands == ["KEY_HOME", "KEY_VOLUME_UP"]
    assert result["outcome"] == "remote_session_ended"
    assert result["keys_submitted"] == 2
    assert result["tv_effect_verified"] is False
    assert client.disconnected


def test_session_rejects_unknown_commands_without_sending() -> None:
    client = FakeClient()
    iterator = iter(("send-secret", "mute", "quit"))
    result = execute(
        args("session"),
        client_factory=lambda _: client,
        command_reader=lambda _: next(iterator),
    )
    assert client.commands == ["KEY_MUTE"]
    assert result["keys_submitted"] == 1
    assert client.disconnected


def test_protocol_argument_only_accepts_owner_verified_version() -> None:
    parser = make_parser()
    valid = parser.parse_args(
        [
            "--host",
            "192.168.1.6",
            "--mac",
            "50:BA:02:AE:0D:18",
            "--protocol-version",
            "3290",
            "session",
        ]
    )
    assert valid.protocol_version == 3290
    assert valid.command == "session"
    with pytest.raises(SystemExit):
        parser.parse_args(
            ["--host", "192.168.1.6", "--protocol-version", "1234", "key", "home"]
        )
