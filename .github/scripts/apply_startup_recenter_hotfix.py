from pathlib import Path


def replace_once(path: str, old: str, new: str, label: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    assert count == 1, f"{label} drifted: {count} matches"
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "src/jarvis/voice/runtime.py",
    "StartupGreetingFactory = Callable[[], str]\n",
    "StartupGreetingFactory = Callable[[], str]\nStartupReadinessWaiter = Callable[[float], bool]\n",
    "startup readiness type alias",
)
replace_once(
    "src/jarvis/voice/runtime.py",
    "        startup_greeting_factory: StartupGreetingFactory = select_startup_greeting,\n    ) -> None:\n",
    "        startup_greeting_factory: StartupGreetingFactory = select_startup_greeting,\n"
    "        startup_readiness_waiter: StartupReadinessWaiter | None = None,\n"
    "        startup_readiness_timeout_seconds: float = 30.0,\n"
    "    ) -> None:\n",
    "voice runtime constructor signature",
)
replace_once(
    "src/jarvis/voice/runtime.py",
    "        self._startup_greeting_factory = startup_greeting_factory\n\n    @property\n",
    "        self._startup_greeting_factory = startup_greeting_factory\n"
    "        if startup_readiness_timeout_seconds <= 0:\n"
    '            raise ValueError("startup_readiness_timeout_seconds must be positive")\n'
    "        self._startup_readiness_waiter = startup_readiness_waiter\n"
    "        self._startup_readiness_timeout_seconds = startup_readiness_timeout_seconds\n\n"
    "    @property\n",
    "voice runtime startup readiness fields",
)
replace_once(
    "src/jarvis/voice/runtime.py",
    "    async def _speak_startup_greeting(self) -> None:\n",
    '''    async def _wait_for_startup_readiness(self) -> bool:
        if self._startup_readiness_waiter is None:
            return True
        timeout = self._startup_readiness_timeout_seconds
        LOGGER.info(
            "JARVIS startup waiting up to %.1fs for trusted camera tracking lock",
            timeout,
        )
        ready = await asyncio.to_thread(self._startup_readiness_waiter, timeout)
        if ready:
            LOGGER.info("JARVIS startup camera tracking lock is ready")
            return True
        LOGGER.warning(
            "JARVIS startup camera tracking lock was not confirmed within %.1fs; "
            "entering wake mode silently",
            timeout,
        )
        return False

    async def _speak_startup_greeting(self) -> None:
''',
    "voice runtime startup readiness method",
)
replace_once(
    "src/jarvis/voice/runtime.py",
    "            await self._speak_startup_greeting()\n            self._state = VoiceRuntimeState.IDLE\n",
    '''            startup_ready = await self._wait_for_startup_readiness()
            if startup_ready:
                await self._speak_startup_greeting()
            else:
                LOGGER.info(
                    "JARVIS startup greeting skipped until a trusted camera lock exists"
                )
            self._state = VoiceRuntimeState.IDLE
''',
    "voice runtime readiness before greeting",
)

replace_once(
    "src/jarvis/vision/native_owner_tracking.py",
    "        self._recovery_succeeded: bool | None = None\n        self._closing = threading.Event()\n",
    "        self._recovery_succeeded: bool | None = None\n"
    "        self._closing = threading.Event()\n"
    "        self._startup_lock_event = threading.Event()\n",
    "tracking observer startup event",
)
replace_once(
    "src/jarvis/vision/native_owner_tracking.py",
    "    def perception_fps_hint(self) -> float:\n",
    '''    def wait_for_startup_lock(self, timeout_seconds: float) -> bool:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        return self._startup_lock_event.wait(timeout_seconds)

    def perception_fps_hint(self) -> float:
''',
    "tracking observer startup wait method",
)
replace_once(
    "src/jarvis/vision/native_owner_tracking.py",
    '''        decision = self.controller.step(
            now=now,
            owner_bounds=owner_bounds,
            owner_observed_at=owner_observed_at,
            native=native_status,
        )
        if decision.state is not self._last_logged_state:
''',
    '''        decision = self.controller.step(
            now=now,
            owner_bounds=owner_bounds,
            owner_observed_at=owner_observed_at,
            native=native_status,
        )
        if decision.state is ReacquisitionState.LOCKED:
            self._startup_lock_event.set()
        if decision.state is not self._last_logged_state:
''',
    "tracking observer lock event set",
)
replace_once(
    "src/jarvis/vision/native_owner_tracking.py",
    "        self._target_attempts_without_native_lock = 0\n\n    def _reconnect_due(self, now: float) -> bool:\n",
    "        self._target_attempts_without_native_lock = 0\n"
    "        self._startup_lock_event.clear()\n\n"
    "    def _reconnect_due(self, now: float) -> bool:\n",
    "tracking observer startup event clear",
)

replace_once(
    "src/jarvis/voice/production_runtime.py",
    "_NATIVE_TRACKING_EVIDENCE_MAX_GAP_SECONDS = 2.0\n",
    "_NATIVE_TRACKING_EVIDENCE_MAX_GAP_SECONDS = 2.0\n"
    "_POCKET3_STARTUP_LOCK_WAIT_SECONDS = 30.0\n",
    "production startup lock timeout",
)
replace_once(
    "src/jarvis/voice/production_runtime.py",
    "        capability_runtime=capability_runtime,\n"
    "        session_factory=production_session_factory,\n"
    "    )\n",
    "        capability_runtime=capability_runtime,\n"
    "        session_factory=production_session_factory,\n"
    "        startup_readiness_waiter=(\n"
    "            tracking_observer.wait_for_startup_lock\n"
    "            if tracking_observer is not None\n"
    "            else None\n"
    "        ),\n"
    "        startup_readiness_timeout_seconds=_POCKET3_STARTUP_LOCK_WAIT_SECONDS,\n"
    "    )\n",
    "production startup lock wiring",
)

p = Path("src/jarvis/vision/pocket3_recovery.py")
text = p.read_text(encoding="utf-8")
start = text.index("    def set_target(self, bounds: BoundingBox) -> bool:\n")
end = text.index("    def _try_saved_wifi_fast_path(self) -> bool:\n", start)
replacement = r'''    def _send_a6_with_ack(self, payload: bytes, *, timeout_message: str) -> bool:
        if not self.connected:
            raise RuntimeError("Pocket 3 native tracking datalink is not connected")
        event = threading.Event()
        reply_holder: list[bytes] = []

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
            LOGGER.warning(timeout_message)
            return False
        with self._lock:
            self._a6_events.pop(expected_seq, None)
        return bool(reply_holder and reply_holder[0][:1] == b"\x00")

    def set_target(self, bounds: BoundingBox) -> bool:
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
        return self._send_a6_with_ack(
            payload,
            timeout_message=(
                "Pocket 3 A6 direct ACK timed out; awaiting A5/0x89 state"
            ),
        )

    def clear_target(self) -> None:
        if not self.connected:
            return
        direct_ack = self._send_a6_with_ack(
            bytes(21),
            timeout_message=(
                "Pocket 3 A6 clear-target ACK timed out; continuing with recenter"
            ),
        )
        LOGGER.info("Pocket 3 A6 clear target completed: direct_ack=%s", direct_ack)

'''
p.write_text(text[:start] + replacement + text[end:], encoding="utf-8")

test_path = Path("tests/test_voice_runtime.py")
tests = test_path.read_text(encoding="utf-8")
marker = "    return runtime, session, conversation, audio, scripted_speech\n\n\n@pytest.mark.parametrize(\n"
assert tests.count(marker) == 1, "voice runtime test insertion anchor drifted"
addition = '''    return runtime, session, conversation, audio, scripted_speech


@pytest.mark.asyncio
async def test_startup_greeting_waits_for_tracking_readiness() -> None:
    import threading

    class Detector:
        async def wait_for_detection(self):
            await asyncio.Event().wait()

    class StartupAudio(FakeAudio):
        def __init__(self) -> None:
            super().__init__()
            self.detector = Detector()
            self.started = asyncio.Event()

        def set_overflow_handler(self, handler) -> None:
            del handler

        async def start(self) -> None:
            self.started.set()

        async def resume_wake(self, *, cooldown_seconds: float) -> None:
            del cooldown_seconds

        async def aclose(self) -> None:
            return None

    audio = StartupAudio()
    scripted_speech = FakeScriptedSpeech()
    readiness = threading.Event()
    calls: list[float] = []

    def wait_for_ready(timeout_seconds: float) -> bool:
        calls.append(timeout_seconds)
        return readiness.wait(timeout_seconds)

    runtime = VoiceRuntimeController(
        JarvisConfig(),
        audio,  # type: ignore[arg-type]
        scripted_speech=scripted_speech,
        startup_readiness_waiter=wait_for_ready,
        startup_readiness_timeout_seconds=1.0,
    )
    task = asyncio.create_task(runtime.run())
    await asyncio.wait_for(audio.started.wait(), timeout=1)
    await asyncio.sleep(0.05)
    assert scripted_speech.started.is_set() is False

    readiness.set()
    await asyncio.wait_for(scripted_speech.started.wait(), timeout=1)
    assert calls == [1.0]

    scripted_speech.release.set()
    runtime.request_shutdown()
    await asyncio.wait_for(task, timeout=1)


@pytest.mark.asyncio
async def test_startup_readiness_timeout_skips_greeting() -> None:
    class Detector:
        async def wait_for_detection(self):
            await asyncio.Event().wait()

    class StartupAudio(FakeAudio):
        def __init__(self) -> None:
            super().__init__()
            self.detector = Detector()

        def set_overflow_handler(self, handler) -> None:
            del handler

        async def start(self) -> None:
            return None

        async def resume_wake(self, *, cooldown_seconds: float) -> None:
            del cooldown_seconds

        async def aclose(self) -> None:
            return None

    audio = StartupAudio()
    scripted_speech = FakeScriptedSpeech()
    runtime = VoiceRuntimeController(
        JarvisConfig(),
        audio,  # type: ignore[arg-type]
        scripted_speech=scripted_speech,
        startup_readiness_waiter=lambda _timeout: False,
        startup_readiness_timeout_seconds=0.01,
    )
    task = asyncio.create_task(runtime.run())
    await asyncio.sleep(0.05)
    assert scripted_speech.started.is_set() is False
    runtime.request_shutdown()
    await asyncio.wait_for(task, timeout=1)


@pytest.mark.parametrize(
'''
test_path.write_text(tests.replace(marker, addition, 1), encoding="utf-8")

test_path = Path("tests/test_native_owner_tracking.py")
tests = test_path.read_text(encoding="utf-8")
marker = "\n\ndef test_observer_never_targets_unconfirmed_visible_person() -> None:\n"
assert tests.count(marker) == 1, "owner recenter test insertion anchor drifted"
addition = '''

def test_observer_recenters_after_confirmed_owner_loss() -> None:
    owner = OwnerContextState()
    client = FakeNativeClient()
    observer = NativeOwnerTrackingObserver(owner_context=owner, client=client)  # type: ignore[arg-type]
    bounds = BoundingBox(0.20, 0.15, 0.55, 0.85)

    owner.publish(live_owner(track_id=7, observed_at=10.0))
    observer.observe(frame(1, 10.0), snapshot(1, 10.0, track(7, bounds, 10.0)))
    client.native_status = NativeTrackingStatus(
        connected=True,
        active=True,
        last_poll_at=10.4,
        last_subject_push_at=10.45,
    )
    owner.publish(live_owner(track_id=7, observed_at=10.5))
    observer.observe(frame(2, 10.5), snapshot(2, 10.5, track(7, bounds, 10.5)))
    assert observer.wait_for_startup_lock(0.001) is True
    assert observer.controller.state is ReacquisitionState.LOCKED

    owner.invalidate("owner_left_frame")
    client.native_status = NativeTrackingStatus(
        connected=True,
        active=False,
        last_poll_at=13.0,
        last_subject_push_at=11.0,
    )
    observer.observe(frame(3, 13.0), snapshot(3, 13.0))
    assert observer.controller.state is ReacquisitionState.REACQUIRING
    assert client.recenters == 0

    observer.observe(frame(4, 14.1), snapshot(4, 14.1))
    assert client.clears == 1
    assert client.recenters == 1


def test_observer_never_targets_unconfirmed_visible_person() -> None:
'''
test_path.write_text(tests.replace(marker, addition, 1), encoding="utf-8")

test_path = Path("tests/test_pocket3_recovery.py")
tests = test_path.read_text(encoding="utf-8")
marker = "\n\ndef test_close_invalidates_stale_native_tracking_and_wakes_a6_waiters() -> None:\n"
assert tests.count(marker) == 1, "clear target test insertion anchor drifted"
addition = r'''

def test_clear_target_waits_for_fast_a6_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    with client._lock:
        client._connected = True

    def immediate_reply_send(
        self: Pocket3NativeTrackerClient,
        *,
        receiver: int,
        flags: int,
        cmd_set: int,
        cmd_id: int,
        payload: bytes,
    ) -> int:
        del receiver, flags, cmd_set, cmd_id, payload
        seq = self._command_seq
        self._command_seq = (self._command_seq + 1) & 0xFFFF
        pending = self._a6_events.get(seq)
        assert pending is not None
        event, holder = pending
        holder.append(b"\x00")
        event.set()
        return seq

    monkeypatch.setattr(Pocket3NativeTrackerClient, "_send_command", immediate_reply_send)
    client.clear_target()
    assert client._a6_events == {}


def test_close_invalidates_stale_native_tracking_and_wakes_a6_waiters() -> None:
'''
test_path.write_text(tests.replace(marker, addition, 1), encoding="utf-8")
