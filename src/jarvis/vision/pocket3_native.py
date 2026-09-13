"""DJI Osmo Pocket 3 native ActiveTrack transport for JARVIS.

The implementation mirrors the hardware-proven connection spine used during the
Pocket 3 research spike:

USB remains the canonical JARVIS video/audio path while this side channel uses
BLE for Wi-Fi provisioning, TCP/7001 to arm the datalink, and UDP/9004 for DUML
camera commands. Passwords are never logged or persisted by this module.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import socket
import struct
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from xml.sax.saxutils import escape as xml_escape

from jarvis.vision.models import BoundingBox
from jarvis.vision.owner_reacquisition import NativeTrackingStatus

LOGGER = logging.getLogger(__name__)

_FFF4 = "0000fff4-0000-1000-8000-00805f9b34fb"
_FFF5 = "0000fff5-0000-1000-8000-00805f9b34fb"
_CAMERA_IP = "192.168.2.1"
_TCP_PORT = 7001
_UDP_PORT = 9004

# Already approved JARVIS BLE identity from the protocol acceptance work.
_BLE_IDENTIFIER = "4a415256495350433030303030303031"
_BLE_TOKEN = "JARVIS"

# Captured Osmo datalink identity used by Mimo-compatible implementations.
_TCP_IDENTIFIER = "284ae5b8d76b3375a04a6417ad71bea3"
_TCP_TOKEN = "osmo"

_APP_PRESENCE = bytes(
    [
        0x17,
        0x00,
        0x46,
        0x23,
        0x7C,
        0x41,
        0x50,
        0x50,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x02,
    ]
)


@dataclass(frozen=True, slots=True)
class Pocket3NativeConfig:
    ble_name: str = "OsmoPocket3-C36F"
    connect_timeout_seconds: float = 25.0
    wifi_join_timeout_seconds: float = 15.0
    command_timeout_seconds: float = 1.5

    def __post_init__(self) -> None:
        if not self.ble_name.strip():
            raise ValueError("Pocket 3 BLE name must not be empty")
        for name in (
            "connect_timeout_seconds",
            "wifi_join_timeout_seconds",
            "command_timeout_seconds",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")


@dataclass(frozen=True, slots=True)
class NativeSubjectBox:
    bounds: BoundingBox
    observed_at: float


def _crc8(data: bytes | bytearray) -> int:
    crc = 0x77
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc >> 1) ^ 0x8C) if crc & 1 else crc >> 1
    return crc & 0xFF


def _crc16(data: bytes | bytearray) -> int:
    crc = 0x3692
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc >> 1) ^ 0x8408) if crc & 1 else crc >> 1
    return crc & 0xFFFF


def _pack_string(value: str) -> bytes:
    encoded = value.encode("utf-8")
    if len(encoded) > 255:
        raise ValueError("DUML pack-string is too long")
    return bytes([len(encoded)]) + encoded


def _build_duml(
    *,
    receiver: int,
    seq: int,
    flags: int,
    cmd_set: int,
    cmd_id: int,
    payload: bytes = b"",
) -> bytes:
    total = 13 + len(payload)
    frame = bytearray(
        [
            0x55,
            total & 0xFF,
            0x04 | ((total >> 8) & 0x03),
            0,
            0x02,
            receiver & 0xFF,
        ]
    )
    frame += struct.pack("<H", seq & 0xFFFF)
    frame += bytes([flags & 0xFF, cmd_set & 0xFF, cmd_id & 0xFF])
    frame += payload
    frame[3] = _crc8(frame[:3])
    frame += struct.pack("<H", _crc16(frame))
    return bytes(frame)


def _scan_duml(raw: bytes) -> tuple[dict[str, object], ...]:
    frames: list[dict[str, object]] = []
    offset = 0
    while offset + 13 <= len(raw):
        if raw[offset] != 0x55:
            offset += 1
            continue
        total = raw[offset + 1] | ((raw[offset + 2] & 0x03) << 8)
        if total < 13 or offset + total > len(raw) or raw[offset + 2] >> 2 != 1:
            offset += 1
            continue
        frame = raw[offset : offset + total]
        if _crc8(frame[:3]) != frame[3]:
            offset += 1
            continue
        if int.from_bytes(frame[-2:], "little") != _crc16(frame[:-2]):
            offset += 1
            continue
        frames.append(
            {
                "seq": int.from_bytes(frame[6:8], "little"),
                "flags": frame[8],
                "cmd_set": frame[9],
                "cmd_id": frame[10],
                "payload": frame[11:-2],
            }
        )
        offset += total
    return tuple(frames)


def _transport_header(
    pkt_type: int, payload_len: int, session_id: int, seq: int
) -> bytes:
    total = 8 + payload_len
    header = bytearray()
    header += struct.pack("<H", 0x8000 | (total & 0x3FFF))
    header += struct.pack("<H", session_id & 0xFFFF)
    header += struct.pack("<H", seq & 0xFFFF)
    header.append(pkt_type & 0xFF)
    checksum = 0
    for byte in header:
        checksum ^= byte
    header.append(checksum)
    return bytes(header)


def _handshake_payload(base_seq: int) -> bytes:
    payload = bytearray(
        [
            0x00,
            0x00,
            0x64,
            0x00,
            0x64,
            0x00,
            0xC0,
            0x05,
            0x14,
            0x00,
            0x00,
            0x64,
            0x00,
            0x00,
            0x01,
            0x90,
            0x01,
            0xC0,
            0x05,
            0x14,
            0x00,
            0x00,
            0x64,
            0x00,
            0x14,
            0x00,
            0x64,
            0x00,
            0xC0,
            0x05,
            0x14,
            0x00,
            0x00,
            0x64,
            0x00,
            0x01,
            0x01,
            0x04,
            0x01,
            0x02,
        ]
    )
    payload[0:2] = struct.pack("<H", base_seq & 0xFFFF)
    return bytes(payload)


def _routing_header(seq: int, counter: int) -> bytes:
    ack = (seq - 8) & 0xFFFF
    return struct.pack("<HHI", ack, seq & 0xFFFF, 0) + bytes(
        [counter & 0xFF, 0x01, 0x00, 0x00]
    )


def _ack_group(value: int) -> bytes:
    packed = struct.pack("<H", value & 0xFFFF)
    return packed + packed + b"\x00\x00\x00\x00"


def _app_device_info_payload() -> bytes:
    payload = bytearray(62)
    payload[1:4] = b"APP"
    payload[41] = 0x02
    payload[50] = 0x02
    payload[51] = 0x08
    return bytes(payload)


def _parse_status_string(payload: bytes) -> str | None:
    if len(payload) < 2 or payload[0] != 0:
        return None
    length = payload[1]
    if len(payload) < 2 + length:
        return None
    return payload[2 : 2 + length].decode("utf-8", errors="strict")


def _a5_active(payload: bytes) -> bool | None:
    """Decode known Pocket 3 A5 forms.

    Hardware acceptance observed 00 01 01 00 while older captures document
    00 01 00 00. The first two bytes are therefore the stable active/idle key.
    """
    if len(payload) < 2 or payload[0] != 0:
        return None
    if payload[1] == 1:
        return True
    if payload[1] == 0:
        return False
    return None


def _decode_subject_box(payload: bytes, observed_at: float) -> NativeSubjectBox | None:
    if len(payload) < 23:
        return None
    center_x, center_y, width, height = struct.unpack_from("<ffff", payload, 7)
    if not all(0 <= value <= 1 for value in (center_x, center_y, width, height)):
        return None
    left = max(0.0, center_x - width / 2)
    top = max(0.0, center_y - height / 2)
    right = min(1.0, center_x + width / 2)
    bottom = min(1.0, center_y + height / 2)
    if left >= right or top >= bottom:
        return None
    return NativeSubjectBox(
        bounds=BoundingBox(left=left, top=top, right=right, bottom=bottom),
        observed_at=observed_at,
    )


class Pocket3NativeTrackerClient:
    """Synchronous lifecycle wrapper around Pocket 3's native tracking datalink."""

    def __init__(self, config: Pocket3NativeConfig | None = None) -> None:
        self.config = config or Pocket3NativeConfig()
        self._lock = threading.RLock()
        self._io_lock = threading.RLock()
        self._stop = threading.Event()
        self._credentials_ready = threading.Event()
        self._ble_thread: threading.Thread | None = None
        self._udp_thread: threading.Thread | None = None
        self._ble_error: BaseException | None = None
        self._ssid: str | None = None
        self._password: str | None = None
        self._tcp: socket.socket | None = None
        self._udp: socket.socket | None = None
        self._connected = False
        self._session_id = 0
        self._base_seq = 0
        self._transport_seq = 0
        self._command_seq = 0xA000
        self._counter = 0
        self._video_cursor = 0
        self._acked_cursor = 0
        self._extra_cursor = 0
        self._has_acked = False
        self._has_extra = False
        self._tracking_active = False
        self._last_poll_at: float | None = None
        self._last_subject_push_at: float | None = None
        self._latest_subject_box: NativeSubjectBox | None = None
        self._tracking_id = 1
        self._a6_events: dict[int, tuple[threading.Event, list[bytes]]] = {}

    @property
    def connected(self) -> bool:
        with self._lock:
            return self._connected

    @property
    def latest_subject_box(self) -> NativeSubjectBox | None:
        with self._lock:
            return self._latest_subject_box

    def status(self) -> NativeTrackingStatus:
        with self._lock:
            return NativeTrackingStatus(
                connected=self._connected,
                active=self._tracking_active,
                last_poll_at=self._last_poll_at,
                last_subject_push_at=self._last_subject_push_at,
            )

    def start(self) -> None:
        with self._lock:
            if self._connected:
                return
        if os.name != "nt":
            raise RuntimeError("Pocket 3 native tracking currently requires Windows")

        self.close()
        self._stop.clear()
        self._credentials_ready.clear()
        self._ble_error = None
        self._ssid = None
        self._password = None
        self._ble_thread = threading.Thread(
            target=self._ble_thread_main,
            name="jarvis-pocket3-ble",
            daemon=True,
        )
        self._ble_thread.start()
        if not self._credentials_ready.wait(self.config.connect_timeout_seconds):
            self.close()
            raise TimeoutError("Pocket 3 BLE provisioning timed out")
        if self._ble_error is not None:
            error = self._ble_error
            self.close()
            raise RuntimeError("Pocket 3 BLE provisioning failed") from error
        ssid = self._ssid
        password = self._password
        if not ssid or not password:
            self.close()
            raise RuntimeError("Pocket 3 did not provide Wi-Fi credentials")

        try:
            self._join_windows_wifi(ssid, password)
            self._open_datalink()
        except Exception:
            self.close()
            raise

        self._udp_thread = threading.Thread(
            target=self._udp_loop,
            name="jarvis-pocket3-datalink",
            daemon=True,
        )
        with self._lock:
            self._connected = True
        self._udp_thread.start()
        self.poll_tracking()
        LOGGER.info("Pocket 3 native tracking datalink is ready")

    def set_target(self, bounds: BoundingBox) -> bool:
        if not self.connected:
            raise RuntimeError("Pocket 3 native tracking datalink is not connected")
        with self._lock:
            tracking_id = self._tracking_id
            self._tracking_id = (self._tracking_id + 1) & 0xFFFF
            if self._tracking_id == 0:
                self._tracking_id = 1
        payload = (
            b"\x01\x00\x00"
            + struct.pack("<H", tracking_id)
            + struct.pack(
                "<ffff",
                bounds.center_x,
                bounds.center_y,
                bounds.width,
                bounds.height,
            )
        )
        event = threading.Event()
        reply_holder: list[bytes] = []
        seq = self._send_command(
            receiver=0x01,
            flags=0x40,
            cmd_set=0x02,
            cmd_id=0xA6,
            payload=payload,
        )
        with self._lock:
            self._a6_events[seq] = (event, reply_holder)
        # A very fast reply could race registration above. Polling/0x89 still confirms
        # lock, so a missing direct ACK is non-fatal to the caller.
        if not event.wait(self.config.command_timeout_seconds):
            with self._lock:
                self._a6_events.pop(seq, None)
            LOGGER.warning("Pocket 3 A6 direct ACK timed out; awaiting A5/0x89 state")
            return False
        return bool(reply_holder and reply_holder[0][:1] == b"\x00")

    def clear_target(self) -> None:
        if not self.connected:
            return
        self._send_command(
            receiver=0x01,
            flags=0x40,
            cmd_set=0x02,
            cmd_id=0xA6,
            payload=bytes(21),
        )

    def poll_tracking(self) -> None:
        if not self.connected:
            return
        self._send_command(
            receiver=0x01,
            flags=0x40,
            cmd_set=0x02,
            cmd_id=0xA5,
            payload=b"\x00",
        )

    def close(self) -> None:
        self._stop.set()
        with self._lock:
            self._connected = False
        udp = self._udp
        self._udp = None
        if udp is not None:
            try:
                udp.close()
            except OSError:
                pass
        tcp = self._tcp
        self._tcp = None
        if tcp is not None:
            try:
                tcp.close()
            except OSError:
                pass
        current = threading.current_thread()
        for thread in (self._udp_thread, self._ble_thread):
            if thread is not None and thread is not current and thread.is_alive():
                thread.join(timeout=2.0)
        self._udp_thread = None
        self._ble_thread = None
        self._password = None

    def _ble_thread_main(self) -> None:
        try:
            asyncio.run(self._ble_session())
        except BaseException as exc:
            self._ble_error = exc
            LOGGER.exception("Pocket 3 BLE provisioning failed")
            self._credentials_ready.set()

    async def _ble_session(self) -> None:
        try:
            from bleak import BleakClient, BleakScanner
        except ImportError as exc:
            raise RuntimeError(
                "Pocket 3 native tracking needs the 'bleak' dependency"
            ) from exc

        pair_event = asyncio.Event()
        ssid_event = asyncio.Event()
        password_event = asyncio.Event()

        def notification_handler(_sender: object, incoming: bytearray) -> None:
            for frame in _scan_duml(bytes(incoming)):
                cmd_set = int(frame["cmd_set"])
                cmd_id = int(frame["cmd_id"])
                payload = bytes(frame["payload"])
                if cmd_set == 0x07 and cmd_id == 0x45:
                    if payload[:2] == b"\x00\x01":
                        pair_event.set()
                    elif payload[:2] == b"\x00\x02":
                        LOGGER.info("Approve the JARVIS pairing request on Pocket 3")
                elif cmd_set == 0x07 and cmd_id == 0x46 and payload[:1] == b"\x01":
                    pair_event.set()
                elif cmd_set == 0x07 and cmd_id == 0x07:
                    value = _parse_status_string(payload)
                    if value:
                        self._ssid = value
                        ssid_event.set()
                elif cmd_set == 0x07 and cmd_id == 0x0E:
                    value = _parse_status_string(payload)
                    if value:
                        self._password = value
                        password_event.set()

        device = await BleakScanner.find_device_by_name(
            self.config.ble_name,
            timeout=min(15.0, self.config.connect_timeout_seconds),
        )
        if device is None:
            raise RuntimeError(f"Pocket 3 BLE device not found: {self.config.ble_name}")

        async with BleakClient(device, timeout=20) as client:
            await client.start_notify(_FFF4, notification_handler)
            await client.write_gatt_char(
                _FFF5,
                _build_duml(
                    receiver=0xF0,
                    seq=0x802B,
                    flags=0x40,
                    cmd_set=0x00,
                    cmd_id=0x2B,
                    payload=b"\x04\x00",
                ),
                response=False,
            )
            await asyncio.sleep(0.4)
            await client.write_gatt_char(_FFF4, b"\x01\x00", response=True)
            await asyncio.sleep(0.2)
            await client.write_gatt_char(
                _FFF5,
                _build_duml(
                    receiver=0x07,
                    seq=0x8092,
                    flags=0x40,
                    cmd_set=0x07,
                    cmd_id=0x45,
                    payload=_pack_string(_BLE_IDENTIFIER) + _pack_string(_BLE_TOKEN),
                ),
                response=False,
            )
            await asyncio.wait_for(pair_event.wait(), timeout=12.0)
            await client.write_gatt_char(
                _FFF5,
                _build_duml(
                    receiver=0x07,
                    seq=0x8101,
                    flags=0x40,
                    cmd_set=0x07,
                    cmd_id=0x07,
                ),
                response=False,
            )
            await asyncio.wait_for(ssid_event.wait(), timeout=5.0)
            await client.write_gatt_char(
                _FFF5,
                _build_duml(
                    receiver=0x07,
                    seq=0x8102,
                    flags=0x40,
                    cmd_set=0x07,
                    cmd_id=0x0E,
                ),
                response=False,
            )
            await asyncio.wait_for(password_event.wait(), timeout=5.0)
            await client.write_gatt_char(
                _FFF5,
                _build_duml(
                    receiver=0x1C,
                    seq=0x8053,
                    flags=0x40,
                    cmd_set=0x53,
                    cmd_id=0x10,
                    payload=b"\x00\x00\x00\x00",
                ),
                response=False,
            )
            self._credentials_ready.set()

            keepalive = _build_duml(
                receiver=0xF0,
                seq=0x802B,
                flags=0x40,
                cmd_set=0x00,
                cmd_id=0x2B,
                payload=b"\x01\x01",
            )
            while not self._stop.is_set():
                await client.write_gatt_char(_FFF5, keepalive, response=False)
                await asyncio.sleep(1.0)

    def _join_windows_wifi(self, ssid: str, password: str) -> None:
        status = self._wlan_status()
        if self._status_has_ssid(status, ssid):
            return
        safe_ssid = xml_escape(ssid)
        safe_password = xml_escape(password)
        profile = f"""<?xml version="1.0"?>
<WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">
<name>{safe_ssid}</name><SSIDConfig><SSID><name>{safe_ssid}</name></SSID></SSIDConfig>
<connectionType>ESS</connectionType><connectionMode>manual</connectionMode>
<MSM><security><authEncryption><authentication>WPA2PSK</authentication>
<encryption>AES</encryption><useOneX>false</useOneX></authEncryption>
<sharedKey><keyType>passPhrase</keyType><protected>false</protected>
<keyMaterial>{safe_password}</keyMaterial></sharedKey></security></MSM></WLANProfile>"""
        fd, path = tempfile.mkstemp(prefix="jarvis_pocket3_", suffix=".xml")
        os.close(fd)
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(profile)
            subprocess.run(
                ["netsh", "wlan", "add", "profile", f"filename={path}", "user=current"],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["netsh", "wlan", "connect", f"name={ssid}", f"ssid={ssid}"],
                check=True,
                capture_output=True,
                text=True,
            )
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

        deadline = time.monotonic() + self.config.wifi_join_timeout_seconds
        while time.monotonic() < deadline:
            if self._status_has_ssid(self._wlan_status(), ssid):
                return
            time.sleep(0.5)
        raise TimeoutError(f"Windows did not associate with Pocket 3 Wi-Fi {ssid!r}")

    @staticmethod
    def _wlan_status() -> str:
        result = subprocess.run(
            ["netsh", "wlan", "show", "interfaces"],
            check=False,
            capture_output=True,
            text=True,
        )
        return result.stdout

    @staticmethod
    def _status_has_ssid(status: str, ssid: str) -> bool:
        return "State                  : connected" in status and (
            f"SSID                   : {ssid}" in status
        )

    def _open_datalink(self) -> None:
        tcp: socket.socket | None = None
        last_error: OSError | None = None
        for _ in range(4):
            candidate = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            candidate.settimeout(3.0)
            try:
                candidate.connect((_CAMERA_IP, _TCP_PORT))
                tcp = candidate
                break
            except OSError as exc:
                last_error = exc
                candidate.close()
                time.sleep(2.0)
        if tcp is None:
            raise RuntimeError("Pocket 3 TCP/7001 is unavailable") from last_error

        tcp.sendall(
            _build_duml(
                receiver=0x07,
                seq=0x8092,
                flags=0x40,
                cmd_set=0x07,
                cmd_id=0x45,
                payload=_pack_string(_TCP_IDENTIFIER) + _pack_string(_TCP_TOKEN),
            )
        )
        time.sleep(0.4)

        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp.bind(("0.0.0.0", 0))
        udp.connect((_CAMERA_IP, _UDP_PORT))
        udp.settimeout(0.10)

        self._tcp = tcp
        self._udp = udp
        self._session_id = random.randint(0x1000, 0xFFFE)
        self._base_seq = random.randint(0x1000, 0xF000) & 0xFFF8
        self._transport_seq = 0
        self._command_seq = 0xA000
        self._counter = 0
        self._video_cursor = self._base_seq
        self._acked_cursor = self._base_seq
        self._extra_cursor = self._base_seq
        self._has_acked = False
        self._has_extra = False

        handshake_ok = False
        for _ in range(5):
            seq = self._transport_seq
            payload = _handshake_payload(self._base_seq)
            udp.send(
                _transport_header(0x00, len(payload), self._session_id, seq) + payload
            )
            self._transport_seq = (self._transport_seq + 8) & 0xFFFF
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline:
                try:
                    data = udp.recv(65535)
                except TimeoutError:
                    continue
                self._ingest_transport(data)
                if len(data) >= 8 and data[6] == 0x00:
                    handshake_ok = True
                    break
            if handshake_ok:
                break
        if not handshake_ok:
            raise RuntimeError("Pocket 3 UDP/9004 handshake failed")

        deadline = time.monotonic() + 6.0
        while time.monotonic() < deadline:
            try:
                data = udp.recv(65535)
            except TimeoutError:
                continue
            self._ingest_transport(data)
            if len(data) == 34 and data[6] == 0x01:
                self._transport_seq = (
                    int.from_bytes(data[8:10], "little") + 8
                ) & 0xFFFF
                self._send_ack()
                break
        else:
            raise RuntimeError("Pocket 3 initial UDP control window was not received")

        self._send_command(
            receiver=0x48,
            flags=0x80,
            cmd_set=0x00,
            cmd_id=0x81,
            payload=_app_device_info_payload(),
        )
        self._send_ack()
        time.sleep(0.10)
        self._send_presence()
        self._send_ack()

    def _send_presence(self) -> None:
        self._send_command(
            receiver=0x28,
            flags=0x40,
            cmd_set=0x00,
            cmd_id=0x88,
            payload=_APP_PRESENCE,
        )

    def _send_command(
        self,
        *,
        receiver: int,
        flags: int,
        cmd_set: int,
        cmd_id: int,
        payload: bytes,
    ) -> int:
        udp = self._udp
        if udp is None:
            raise RuntimeError("Pocket 3 UDP socket is unavailable")
        with self._io_lock:
            duml_seq = self._command_seq
            self._command_seq = (self._command_seq + 1) & 0xFFFF
            self._counter = (self._counter + 1) & 0xFF
            transport_seq = self._transport_seq
            duml = _build_duml(
                receiver=receiver,
                seq=duml_seq,
                flags=flags,
                cmd_set=cmd_set,
                cmd_id=cmd_id,
                payload=payload,
            )
            wrapped = _routing_header(transport_seq, self._counter) + duml
            packet = (
                _transport_header(
                    0x05,
                    len(wrapped),
                    self._session_id,
                    transport_seq,
                )
                + wrapped
            )
            udp.send(packet)
            self._transport_seq = (self._transport_seq + 8) & 0xFFFF
            return duml_seq

    def _send_ack(self) -> None:
        udp = self._udp
        if udp is None:
            return
        with self._io_lock:
            payload = (
                _ack_group(self._video_cursor)
                + _ack_group(self._acked_cursor if self._has_acked else self._base_seq)
                + _ack_group(self._extra_cursor if self._has_extra else self._base_seq)
                + b"\x00\x00"
            )
            udp.send(
                _transport_header(0x04, len(payload), self._session_id, 0) + payload
            )

    def _ingest_transport(self, datagram: bytes) -> None:
        if len(datagram) < 8:
            return
        pkt_type = datagram[6]
        seq = int.from_bytes(datagram[4:6], "little")
        with self._lock:
            if pkt_type == 0x01 and len(datagram) >= 34:
                self._video_cursor = int.from_bytes(datagram[10:12], "little")
                if not self._has_acked:
                    self._acked_cursor = int.from_bytes(datagram[18:20], "little")
                    self._has_acked = True
                self._extra_cursor = int.from_bytes(datagram[26:28], "little")
                self._has_extra = True
            elif pkt_type == 0x03:
                self._acked_cursor = seq
                self._has_acked = True
            elif pkt_type == 0x02:
                self._video_cursor = seq

    def _udp_loop(self) -> None:
        last_ack = 0.0
        last_presence = time.monotonic()
        udp = self._udp
        if udp is None:
            return
        try:
            while not self._stop.is_set():
                now = time.monotonic()
                try:
                    data = udp.recv(65535)
                except TimeoutError:
                    data = b""
                except OSError:
                    if self._stop.is_set():
                        return
                    raise

                if data:
                    self._ingest_transport(data)
                    self._handle_duml_frames(data, now)

                if now - last_ack >= 0.04:
                    self._send_ack()
                    last_ack = now
                if now - last_presence >= 1.0:
                    self._send_presence()
                    last_presence = now
        except Exception:
            LOGGER.exception("Pocket 3 UDP datalink loop failed")
        finally:
            with self._lock:
                self._connected = False

    def _handle_duml_frames(self, data: bytes, now: float) -> None:
        for frame in _scan_duml(data):
            cmd_set = int(frame["cmd_set"])
            cmd_id = int(frame["cmd_id"])
            seq = int(frame["seq"])
            payload = bytes(frame["payload"])
            if cmd_set == 0x02 and cmd_id == 0xA5:
                active = _a5_active(payload)
                if active is not None:
                    with self._lock:
                        self._tracking_active = active
                        self._last_poll_at = now
            elif cmd_set == 0x02 and cmd_id == 0x89:
                subject = _decode_subject_box(payload, now)
                with self._lock:
                    self._tracking_active = True
                    self._last_subject_push_at = now
                    if subject is not None:
                        self._latest_subject_box = subject
            elif cmd_set == 0x02 and cmd_id == 0xA6:
                with self._lock:
                    pending = self._a6_events.pop(seq, None)
                if pending is not None:
                    event, holder = pending
                    holder.append(payload)
                    event.set()
