"""Offline VIDAA screen-observation reconnaissance tests; never need a TV."""

from __future__ import annotations

import json

import pytest

from jarvis.vidaa.manual import execute, make_parser
from jarvis.vidaa.observation import observe_software, probe_legacy_inspector


class FakeObservationTV:
    def get_state(self, *, timeout: float) -> dict[str, str]:
        assert timeout == 2.0
        return {
            "statetype": "remote_launcher",
            "source": "tv",
            "privateToken": "never-log-me",
        }

    def get_tv_info(self, *, timeout: float) -> dict[str, str]:
        assert timeout == 2.0
        return {"brand": "Hisense", "deviceid": "private-serial-123"}

    def get_device_info(self, *, timeout: float) -> dict[str, str]:
        return {"model_name": "U7N", "ip": "192.168.1.6", "account": "secret"}

    def get_capability(self, *, timeout: float) -> dict[str, str]:
        return {"resolution": "3840x2160", "devicemsg": "sensitive device metadata"}


class FakeSocket:
    def __init__(self, response: bytes) -> None:
        self.response = response
        self.sent = b""
        self.closed = False
        self.timeout = None

    def settimeout(self, seconds: float) -> None:
        self.timeout = seconds

    def sendall(self, payload: bytes) -> None:
        self.sent = payload

    def recv(self, max_bytes: int) -> bytes:
        assert max_bytes <= 8192
        return self.response

    def close(self) -> None:
        self.closed = True


def test_metadata_diagnostic_does_not_claim_screen_or_leak_secrets() -> None:
    result = observe_software(
        FakeObservationTV(),
        "192.168.1.6",
        inspector_probe=lambda host: {
            "port": 9226,
            "result": "unreachable_or_no_response",
            "inspector_confirmed": False,
        },
    )
    assert result["outcome"] == "software_observation_probe_complete"
    assert result["signal_inventory"]["tv_state"]["state_type"] == "remote_launcher"
    assert result["signal_inventory"]["tv_info"]["available_fields"] == ["brand"]
    assert result["signal_inventory"]["device_info"]["available_fields"] == [
        "model_name"
    ]
    assert result["screen_observation"]["screenshot"] == "not_observed"
    assert result["screen_observation"]["ui_tree"] == "not_observed"
    assert result["software_ui_navigation_ready"] is False
    raw = json.dumps(result)
    for secret in (
        "never-log-me",
        "private-serial-123",
        "sensitive device metadata",
        "secret",
    ):
        assert secret not in raw


def test_inaccessible_sdk_metadata_is_not_fabricated() -> None:
    result = observe_software(
        object(),
        "192.168.1.6",
        inspector_probe=lambda host: {
            "port": 9226,
            "result": "unreachable_or_no_response",
            "inspector_confirmed": False,
        },
    )
    for section in ("tv_state", "tv_info", "device_info", "capability"):
        assert (
            result["signal_inventory"][section]["status"] == "sdk_method_not_available"
        )
    assert result["software_ui_navigation_ready"] is False


def test_sanitizer_rejects_untrusted_tv_state_strings() -> None:
    class Client(FakeObservationTV):
        def get_state(self, *, timeout: float) -> dict[str, str]:
            return {"statetype": "account:secret", "source": "browser url.com"}

    result = observe_software(
        Client(),
        "192.168.1.6",
        inspector_probe=lambda host: {
            "port": 9226,
            "result": "unreachable_or_no_response",
            "inspector_confirmed": False,
        },
    )
    assert result["signal_inventory"]["tv_state"]["state_type"] is None
    assert result["signal_inventory"]["tv_state"]["state_source"] is None


def test_inspector_probe_detects_only_protocol_signature() -> None:
    response = (
        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n"
        b'{"Browser":"Chrome/99","Protocol-Version":"1.3",'
        b'"webSocketDebuggerUrl":"ws://private-access"}'
    )
    sock = FakeSocket(response)

    def connector(address: tuple[str, int], *, timeout: float) -> FakeSocket:
        assert address == ("192.168.1.6", 9226)
        assert timeout == 0.8
        return sock

    result = probe_legacy_inspector("192.168.1.6", connector=connector)
    assert result == {
        "port": 9226,
        "result": "cdp_version_endpoint_detected",
        "inspector_confirmed": True,
    }
    assert sock.closed
    assert b"GET /json/version" in sock.sent
    assert b"Connection: close" in sock.sent


def test_html_response_does_not_claim_cdp_endpoint() -> None:
    sock = FakeSocket(b"HTTP/1.1 200 OK\r\n\r\n<html>login</html>")
    result = probe_legacy_inspector("192.168.1.6", connector=lambda *a, **k: sock)
    assert result["result"] == "http_service_unidentified"
    assert result["inspector_confirmed"] is False


def test_closed_debug_port_is_not_reported_as_missing_tv() -> None:
    def offline(*args: object, **kwargs: object) -> None:
        raise ConnectionRefusedError("do not log the raw exception")

    result = probe_legacy_inspector("192.168.1.6", connector=offline)
    assert result["result"] == "unreachable_or_no_response"
    assert result["inspector_confirmed"] is False


@pytest.mark.parametrize("host", ["127.0.0.1", "8.8.8.8", "169.254.1.2"])
def test_inspector_rejects_nonprivate_target(host: str) -> None:
    with pytest.raises(ValueError):
        probe_legacy_inspector(host)


def test_cli_observe_requires_no_new_pairing_or_remote_keys() -> None:
    class Paired(FakeObservationTV):
        def __init__(self) -> None:
            self.connected = False
            self.disconnected = False

        def connect(self, *, timeout: float) -> bool:
            self.connected = True
            return True

        def disconnect(self) -> None:
            self.disconnected = True

        def send_key(self, key: str) -> None:
            pytest.fail("Observation must not send TV keys")

        def start_pairing(self) -> None:
            pytest.fail("Observation must not request pairing")

    args = make_parser().parse_args(
        [
            "--host",
            "192.168.1.6",
            "--mac",
            "50:ba:02:ae:0d:18",
            "--protocol-version",
            "3290",
            "--persist-tokens",
            "observe",
        ]
    )
    assert args.command == "observe"
    # Verify the CLI dispatch against patched observation boundary (no LAN).
    from jarvis.vidaa import observation

    original = observation.observe_software
    observed: list[str] = []
    try:

        def fake_observe(client: object, host: str) -> dict[str, object]:
            observed.append(host)
            return {"outcome": "software_observation_probe_complete"}

        observation.observe_software = fake_observe
        client = Paired()
        result = execute(args, client_factory=lambda _: client)
        assert result["outcome"] == "software_observation_probe_complete"
        assert observed == ["192.168.1.6"]
        assert client.connected is True
        assert client.disconnected is True
    finally:
        observation.observe_software = original


def test_documented_alternate_9222_port_is_only_second_try(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jarvis.vidaa import observation

    observed_ports: list[int] = []

    def probe(host: str, *, port: int = 9226) -> dict[str, object]:
        assert host == "192.168.1.6"
        observed_ports.append(port)
        return {
            "port": port,
            "result": "unreachable_or_no_response",
            "inspector_confirmed": False,
        }

    monkeypatch.setattr(observation, "probe_legacy_inspector", probe)
    result = observe_software(FakeObservationTV(), "192.168.1.6")
    assert observed_ports == [9226, 9222]
    assert result["legacy_developer_inspector"]["inspector_confirmed"] is False
    assert result["alternate_legacy_inspector"]["inspector_confirmed"] is False
    assert result["software_ui_navigation_ready"] is False


def test_alternate_port_skipped_after_documented_inspector_detected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jarvis.vidaa import observation

    observed_ports: list[int] = []

    def probe(host: str, *, port: int = 9226) -> dict[str, object]:
        observed_ports.append(port)
        return {
            "port": port,
            "result": "cdp_version_endpoint_detected",
            "inspector_confirmed": True,
        }

    monkeypatch.setattr(observation, "probe_legacy_inspector", probe)
    result = observe_software(FakeObservationTV(), "192.168.1.6")
    assert observed_ports == [9226]
    assert (
        result["alternate_legacy_inspector"]["result"]
        == "not_needed_primary_inspector_detected"
    )
    assert result["software_ui_navigation_ready"] is False


def test_documented_alternate_debug_port_request_is_bounded() -> None:
    response = (
        b"HTTP/1.1 200 OK\\r\\nContent-Type: application/json\\r\\n\\r\\n"
        b'{"Browser":"Chrome/99","Protocol-Version":"1.3"}'
    )
    sock = FakeSocket(response)

    def connector(address: tuple[str, int], *, timeout: float) -> FakeSocket:
        assert address == ("192.168.1.6", 9222)
        assert timeout == 0.8
        return sock

    result = probe_legacy_inspector(
        "192.168.1.6", port=9222, connector=connector
    )
    assert result["inspector_confirmed"] is True
    assert result["port"] == 9222
    assert b"Host: 192.168.1.6:9222" in sock.sent
    assert sock.closed


def test_debug_port_scan_is_not_permitted() -> None:
    with pytest.raises(ValueError, match="Only documented"):
        probe_legacy_inspector("192.168.1.6", port=22)
