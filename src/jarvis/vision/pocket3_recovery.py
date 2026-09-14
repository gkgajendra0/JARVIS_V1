"""Resilient Pocket 3 connection lifecycle for Windows.

The hardware-proven DUML transport remains in ``pocket3_native``. This module only
adds connection recovery around it: reuse an existing Windows WLAN profile when
possible, retry transient BLE discovery/provisioning, retry WLAN association, and
rebuild the native datalink after a dropped session.

JARVIS does not persist the Pocket Wi-Fi passphrase itself. The existing native
transport installs the current credentials into the user's Windows WLAN profile;
this recovery layer only asks Windows to reuse that profile on later starts.
"""

from __future__ import annotations

import asyncio
import logging
import os
import struct
import subprocess
import threading
import time
from dataclasses import dataclass

from jarvis.vision.models import BoundingBox
from jarvis.vision.pocket3_native import Pocket3NativeConfig, Pocket3NativeTrackerClient

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Pocket3RecoveryConfig:
    """Bounded recovery policy for Pocket 3 startup and reconnection."""

    saved_wifi_wait_seconds: float = 6.0
    ble_attempts: int = 5
    ble_retry_pause_seconds: float = 1.0
    ble_provision_timeout_seconds: float = 120.0
    wifi_join_attempts: int = 6
    wifi_retry_pause_seconds: float = 1.0

    def __post_init__(self) -> None:
        for name in (
            "saved_wifi_wait_seconds",
            "ble_retry_pause_seconds",
            "ble_provision_timeout_seconds",
            "wifi_retry_pause_seconds",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.ble_attempts <= 0:
            raise ValueError("ble_attempts must be positive")
        if self.wifi_join_attempts <= 0:
            raise ValueError("wifi_join_attempts must be positive")


class ResilientPocket3NativeTrackerClient(Pocket3NativeTrackerClient):
    """Pocket native tracker with self-healing Windows connection startup."""

    def __init__(
        self,
        config: Pocket3NativeConfig | None = None,
        recovery_config: Pocket3RecoveryConfig | None = None,
    ) -> None:
        super().__init__(config)
        self.recovery_config = recovery_config or Pocket3RecoveryConfig()

    def start(self) -> None:
        with self._lock:
            if self._connected:
                return
        if os.name != "nt":
            raise RuntimeError("Pocket 3 native tracking currently requires Windows")

        if self._try_saved_wifi_fast_path():
            return

        self._start_with_ble_fallback()

    def close(self) -> None:
        """Close transport and invalidate all native tracking evidence atomically."""

        super().close()
        with self._lock:
            pending = tuple(self._a6_events.values())
            self._a6_events.clear()
            self._tracking_active = False
            self._last_poll_at = None
            self._last_subject_push_at = None
            self._latest_subject_box = None
        for event, _holder in pending:
            event.set()

    def recover_tracking_session(self) -> None:
        """Rebuild a stale DJI control session using the saved Windows Wi-Fi profile."""

        LOGGER.warning(
            "Pocket 3 rebuilding native tracking session after failed reacquisition"
        )
        self.close()
        self.start()

    def set_target(self, bounds: BoundingBox) -> bool:
        """Send A6 with its ACK waiter installed before the UDP packet can be received."""

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

        # The base transport serializes command sequence allocation with _io_lock.
        # Hold that same re-entrant lock while reserving the next sequence so the A6
        # waiter exists before udp.send() can produce a fast camera reply.
        with self._io_lock:
            with self._lock:
                expected_seq = self._command_seq
                self._a6_events[expected_seq] = (event, reply_holder)
            try:
                actual_seq = super()._send_command(
                    receiver=0x01,
                    flags=0x40,
                    cmd_set=0x02,
                    cmd_id=0xA6,
                    payload=payload,
                )
            except Exception:
                with self._lock:
                    self._a6_events.pop(expected_seq, None)
                raise

        if actual_seq != expected_seq:
            with self._lock:
                self._a6_events.pop(expected_seq, None)
            raise RuntimeError("Pocket 3 A6 sequence reservation drifted unexpectedly")

        if not event.wait(self.config.command_timeout_seconds):
            with self._lock:
                self._a6_events.pop(expected_seq, None)
            LOGGER.warning("Pocket 3 A6 direct ACK timed out; awaiting A5/0x89 state")
            return False
        with self._lock:
            self._a6_events.pop(expected_seq, None)
        return bool(reply_holder and reply_holder[0][:1] == b"\x00")

    def _try_saved_wifi_fast_path(self) -> bool:
        ssid = self.config.ble_name
        already_connected = self._status_has_ssid(self._wlan_status(), ssid)
        if not already_connected and not self._join_saved_windows_wifi(ssid):
            return False

        self.close()
        self._stop.clear()
        try:
            self._open_datalink()
        except Exception:
            self.close()
            if already_connected or self._status_has_ssid(self._wlan_status(), ssid):
                LOGGER.warning(
                    "Pocket 3 Wi-Fi is associated but the DJI datalink is not ready; "
                    "a later reconnect attempt will retry without operator action"
                )
                raise
            return False

        self._finish_connected_start()
        LOGGER.info("Pocket 3 reused the existing Windows Wi-Fi profile")
        return True

    def _start_with_ble_fallback(self) -> None:
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

        wait_seconds = max(
            self.config.connect_timeout_seconds,
            self.recovery_config.ble_provision_timeout_seconds,
        )
        if not self._credentials_ready.wait(wait_seconds):
            self.close()
            raise TimeoutError("Pocket 3 BLE provisioning timed out after retries")
        if self._ble_error is not None:
            error = self._ble_error
            self.close()
            raise RuntimeError(
                "Pocket 3 BLE provisioning failed after retries"
            ) from error

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

        self._finish_connected_start()
        LOGGER.info("Pocket 3 native tracking datalink is ready")

    def _finish_connected_start(self) -> None:
        self._udp_thread = threading.Thread(
            target=self._udp_loop,
            name="jarvis-pocket3-datalink",
            daemon=True,
        )
        with self._lock:
            self._connected = True
        self._udp_thread.start()
        self.poll_tracking()

    def _join_saved_windows_wifi(self, ssid: str) -> bool:
        result = subprocess.run(
            ["netsh", "wlan", "connect", f"name={ssid}", f"ssid={ssid}"],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return False

        deadline = time.monotonic() + self.recovery_config.saved_wifi_wait_seconds
        while time.monotonic() < deadline:
            if self._status_has_ssid(self._wlan_status(), ssid):
                return True
            time.sleep(0.5)
        return False

    async def _ble_session(self) -> None:
        last_error: BaseException | None = None
        for attempt in range(1, self.recovery_config.ble_attempts + 1):
            if self._stop.is_set():
                return
            self._ssid = None
            self._password = None
            try:
                await super()._ble_session()
                return
            except BaseException as exc:
                if self._credentials_ready.is_set():
                    raise
                last_error = exc
                if attempt >= self.recovery_config.ble_attempts:
                    break
                LOGGER.warning(
                    "Pocket 3 BLE provisioning attempt %d/%d failed; retrying",
                    attempt,
                    self.recovery_config.ble_attempts,
                )
                await asyncio.sleep(self.recovery_config.ble_retry_pause_seconds)

        assert last_error is not None
        raise last_error

    def _join_windows_wifi(self, ssid: str, password: str) -> None:
        last_error: Exception | None = None
        recoverable_errors = (TimeoutError, subprocess.SubprocessError, OSError)
        for attempt in range(1, self.recovery_config.wifi_join_attempts + 1):
            if self._status_has_ssid(self._wlan_status(), ssid):
                return
            try:
                super()._join_windows_wifi(ssid, password)
                return
            except recoverable_errors as exc:
                last_error = exc
                if attempt >= self.recovery_config.wifi_join_attempts:
                    break
                LOGGER.warning(
                    "Pocket 3 Wi-Fi association attempt %d/%d failed (%s: %s); retrying",
                    attempt,
                    self.recovery_config.wifi_join_attempts,
                    type(exc).__name__,
                    exc,
                )
                time.sleep(self.recovery_config.wifi_retry_pause_seconds)

        assert last_error is not None
        raise TimeoutError(
            f"Windows could not associate with Pocket 3 Wi-Fi {ssid!r} after retries"
        ) from last_error


class ResilientPocket3NativeOwnerTrackingClient(ResilientPocket3NativeTrackerClient):
    """Resilient Pocket transport plus the proven native gimbal recenter command."""

    def recenter_gimbal(self) -> None:
        if not self.connected:
            return
        self._send_command(
            receiver=0x04,
            flags=0x40,
            cmd_set=0x04,
            cmd_id=0x4C,
            payload=bytes((0xFE, 0x08)),
        )
