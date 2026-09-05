"""Fail-fast startup validation for the production JARVIS runtime."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jarvis.ai_provider import credential_environment_name, provider_api_key
from jarvis.config import JarvisConfig
from jarvis.voice.audio import DEVICE_CHANNELS, DEVICE_SAMPLE_RATE, LocalAudioRuntime


@dataclass(frozen=True, slots=True)
class PreflightCheck:
    label: str
    ok: bool
    detail: str


class StartupPreflightError(RuntimeError):
    """Raised after all startup checks have been evaluated and reported."""


def _audio_devices() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    import sounddevice as sd

    devices: list[dict[str, Any]] = []
    for index, raw in enumerate(sd.query_devices()):
        item = dict(raw)
        item["index"] = index
        devices.append(item)
    inputs = [item for item in devices if int(item.get("max_input_channels", 0)) > 0]
    outputs = [item for item in devices if int(item.get("max_output_channels", 0)) > 0]
    return (
        LocalAudioRuntime._attach_host_api_names(inputs),
        LocalAudioRuntime._attach_host_api_names(outputs),
    )


def _check_file(label: str, value: str | None) -> PreflightCheck:
    if value is None:
        return PreflightCheck(label, False, "not configured; run jarvis-setup")
    path = Path(value).expanduser()
    if not path.is_file():
        return PreflightCheck(label, False, f"file not found: {path}")
    return PreflightCheck(label, True, str(path))


def _credential_check(config: JarvisConfig) -> PreflightCheck:
    name = credential_environment_name(config.ai_provider)
    if provider_api_key(config.ai_provider) is not None:
        return PreflightCheck(
            "Cloud AI credentials",
            True,
            f"active provider={config.ai_provider}; {name} is available",
        )
    return PreflightCheck(
        "Cloud AI credentials",
        False,
        f"active provider={config.ai_provider}; {name} is missing from the "
        "process/Windows user environment",
    )


def _audio_checks(config: JarvisConfig) -> list[PreflightCheck]:
    import sounddevice as sd

    checks: list[PreflightCheck] = []
    if config.audio_input_device is None:
        checks.append(
            PreflightCheck(
                "Conversation microphone",
                False,
                "no stable input selector configured; run jarvis-setup",
            )
        )
    if config.audio_output_device is None:
        checks.append(
            PreflightCheck(
                "Conversation speaker",
                False,
                "no stable output selector configured; run jarvis-setup",
            )
        )
    if checks:
        return checks

    try:
        inputs, outputs = _audio_devices()
    except Exception as exc:  # noqa: BLE001 - hardware boundary must fail closed
        return [PreflightCheck("Audio inventory", False, str(exc))]

    try:
        input_index = LocalAudioRuntime._resolve_device(
            inputs,
            config.audio_input_device,
            kind="input",
        )
        assert input_index is not None
        sd.check_input_settings(
            device=input_index,
            channels=DEVICE_CHANNELS,
            dtype="int16",
            samplerate=DEVICE_SAMPLE_RATE,
        )
        input_info = next(item for item in inputs if int(item["index"]) == input_index)
        checks.append(
            PreflightCheck(
                "Conversation microphone",
                True,
                f"{input_info['name']} @ {DEVICE_SAMPLE_RATE} Hz",
            )
        )
    except Exception as exc:  # noqa: BLE001 - hardware boundary must fail closed
        checks.append(PreflightCheck("Conversation microphone", False, str(exc)))

    try:
        output_index = LocalAudioRuntime._resolve_device(
            outputs,
            config.audio_output_device,
            kind="output",
        )
        assert output_index is not None
        sd.check_output_settings(
            device=output_index,
            channels=DEVICE_CHANNELS,
            dtype="int16",
            samplerate=DEVICE_SAMPLE_RATE,
        )
        output_info = next(
            item for item in outputs if int(item["index"]) == output_index
        )
        checks.append(
            PreflightCheck(
                "Conversation speaker",
                True,
                f"{output_info['name']} @ {DEVICE_SAMPLE_RATE} Hz",
            )
        )
    except Exception as exc:  # noqa: BLE001 - hardware boundary must fail closed
        checks.append(
            PreflightCheck(
                "Conversation speaker",
                False,
                f"48 kHz production output unavailable: {exc}",
            )
        )
    return checks


def run_startup_preflight(config: JarvisConfig) -> list[PreflightCheck]:
    checks = [
        _check_file("Wake model", config.wake_model_path),
        _credential_check(config),
        *_audio_checks(config),
    ]

    if config.speaker_shadow_enabled:
        checks.append(
            PreflightCheck(
                "Speaker shadow mode",
                True,
                "audio-only speaker shadow does not require vision",
            )
        )

    if config.active_speaker_shadow_enabled:
        checks.append(_check_file("LR-ASD model", config.active_speaker_model_path))
        if not config.speaker_shadow_enabled:
            checks.append(
                PreflightCheck(
                    "Active-speaker dependency",
                    False,
                    "active-speaker shadow requires speaker shadow",
                )
            )
        elif not config.vision_enabled:
            checks.append(
                PreflightCheck(
                    "Active-speaker dependency",
                    False,
                    "active-speaker shadow requires vision",
                )
            )
        else:
            checks.append(
                PreflightCheck(
                    "Active-speaker dependency",
                    True,
                    "vision + speaker shadow enabled",
                )
            )

    return checks


def print_preflight(checks: list[PreflightCheck]) -> None:
    print("JARVIS startup preflight")
    for check in checks:
        marker = "OK" if check.ok else "FAIL"
        print(f"[{marker:4}] {check.label}: {check.detail}")


def require_startup_preflight(config: JarvisConfig) -> None:
    checks = run_startup_preflight(config)
    print_preflight(checks)
    failures = [check for check in checks if not check.ok]
    if failures:
        raise StartupPreflightError(
            f"JARVIS startup blocked by {len(failures)} preflight failure(s). "
            "Run jarvis-setup after fixing the reported item(s)."
        )
    print("Preflight passed. Starting JARVIS...\n")
