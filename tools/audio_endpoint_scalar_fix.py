from pathlib import Path

path = Path("src/jarvis/capabilities/windows_native.py")
text = path.read_text(encoding="utf-8")
old = '''    def state(self) -> dict[str, Any]:
        device = self._device()
        return {
            "device": str(device.FriendlyName),
            "volume_percent": round(float(device.volume_percent), 1),
            "muted": bool(device.EndpointVolume.GetMute()),
        }

    def set_volume(self, percent: float) -> None:
        device = self._device()
        device.volume_percent = float(percent)
'''
new = '''    def state(self) -> dict[str, Any]:
        device = self._device()
        endpoint = device.EndpointVolume
        return {
            "device": str(device.FriendlyName),
            "volume_percent": round(float(endpoint.GetMasterVolumeLevelScalar()) * 100.0, 1),
            "muted": bool(endpoint.GetMute()),
        }

    def set_volume(self, percent: float) -> None:
        endpoint = self._device().EndpointVolume
        endpoint.SetMasterVolumeLevelScalar(float(percent) / 100.0, None)
'''
if text.count(old) != 1:
    raise SystemExit("expected PycawAudioBackend anchor not found exactly once")
path.write_text(text.replace(old, new, 1), encoding="utf-8")

# Add an adapter-contract regression that matches current pycaw's documented surface.
test_path = Path("tests/test_windows_native_capabilities.py")
test = test_path.read_text(encoding="utf-8")
test = test.replace(
    "    MediaPlaybackExecutor,\n",
    "    MediaPlaybackExecutor,\n    PycawAudioBackend,\n",
    1,
)
anchor = '''class FakeAudio:
'''
addition = '''class _FakeEndpointVolume:
    def __init__(self) -> None:
        self.scalar = 0.5
        self.muted = False

    def GetMasterVolumeLevelScalar(self):
        return self.scalar

    def SetMasterVolumeLevelScalar(self, value, _context):
        self.scalar = float(value)

    def GetMute(self):
        return self.muted

    def SetMute(self, muted, _context):
        self.muted = bool(muted)


class _FakeAudioDevice:
    def __init__(self) -> None:
        self.FriendlyName = "Fake speakers"
        self.EndpointVolume = _FakeEndpointVolume()


class _ContractPycawBackend(PycawAudioBackend):
    device = _FakeAudioDevice()

    @staticmethod
    def _device():
        return _ContractPycawBackend.device


def test_pycaw_backend_uses_endpoint_scalar_contract_not_audio_device_convenience_property() -> None:
    backend = _ContractPycawBackend()

    assert backend.state()["volume_percent"] == 50.0
    backend.set_volume(30.0)
    assert backend.state()["volume_percent"] == 30.0


'''
if anchor not in test:
    raise SystemExit("FakeAudio anchor missing")
test_path.write_text(test.replace(anchor, addition + anchor, 1), encoding="utf-8")

print("Core Audio scalar compatibility fix applied")
