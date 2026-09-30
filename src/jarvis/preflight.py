"""Fail-fast startup validation for the production JARVIS runtime."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from jarvis.ai_provider import (
    credential_environment_name,
    provider_api_key,
    tts_credential_environment_name,
    tts_credential_is_separated,
    tts_credential_source,
)
from jarvis.authority.tooling import authority_tool_readiness
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


def _version_triplet(value: str) -> tuple[int, int, int]:
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", value.strip())
    if match is None:
        return (0, 0, 0)
    return tuple(int(part) for part in match.groups())


def _gemini_realtime_compatibility_check(config: JarvisConfig) -> PreflightCheck:
    """Fail fast when Gemini 3.1 is paired with an incompatible LiveKit plugin."""

    if config.ai_provider != "gemini":
        return PreflightCheck(
            "Gemini realtime compatibility",
            True,
            "not applicable for the active provider",
        )
    if not config.gemini_realtime_model.startswith("gemini-3.1-"):
        return PreflightCheck(
            "Gemini realtime compatibility",
            True,
            f"model={config.gemini_realtime_model}; Gemini 3.1 compatibility gate not required",
        )

    required = (1, 8, 2)
    try:
        installed = version("livekit-plugins-google")
    except PackageNotFoundError:
        return PreflightCheck(
            "Gemini realtime compatibility",
            False,
            "livekit-plugins-google is not installed; Gemini 3.1 requires >=1.8.2",
        )

    compatible = _version_triplet(installed) >= required
    return PreflightCheck(
        "Gemini realtime compatibility",
        compatible,
        (
            f"model={config.gemini_realtime_model}; "
            f"livekit-plugins-google={installed}; required>=1.8.2"
        ),
    )


def _realtime_lifecycle_voice_check(config: JarvisConfig) -> PreflightCheck:
    """Confirm lifecycle speech shares the normal realtime conversation lane."""

    name = credential_environment_name(config.ai_provider)
    available = provider_api_key(config.ai_provider) is not None
    return PreflightCheck(
        "Lifecycle voice",
        available,
        (
            f"provider={config.ai_provider}; startup, standby, update prompts, and "
            "background notifications share the realtime conversation model/voice; "
            "no separate scripted TTS request"
            if available
            else (
                f"provider={config.ai_provider}; {name} is missing, so realtime "
                "lifecycle speech is unavailable"
            )
        ),
    )


def _tts_lane_check(config: JarvisConfig) -> PreflightCheck:
    provider = config.tts_provider
    dedicated_name = tts_credential_environment_name(provider)
    source = tts_credential_source(provider)
    if source == "dedicated":
        return PreflightCheck(
            "Scripted TTS lane",
            True,
            f"provider={provider}; {dedicated_name} is available; "
            "credential is separated from brain reasoning; "
            f"project_billing_isolation_verified="
            f"{config.tts_project_billing_isolation_verified}",
        )
    if source == "shared_compatibility":
        return PreflightCheck(
            "Scripted TTS lane",
            True,
            f"provider={provider}; compatibility credential is available; "
            f"set {dedicated_name} before paid-brain experiments",
        )
    return PreflightCheck(
        "Scripted TTS lane",
        True,
        f"provider={provider}; cloud TTS credential unavailable; "
        "Windows-local lifecycle speech remains the fallback",
    )


def paid_brain_tts_isolation_check(config: JarvisConfig) -> PreflightCheck:
    """Fail closed for paid-brain experiments until TTS project billing is verified."""

    provider = config.tts_provider
    if not tts_credential_is_separated(provider):
        return PreflightCheck(
            "Paid experiment TTS isolation",
            False,
            "scripted TTS does not use a dedicated credential",
        )
    if not config.tts_project_billing_isolation_verified:
        return PreflightCheck(
            "Paid experiment TTS isolation",
            False,
            "dedicated TTS credential exists but project-level billing isolation "
            "has not been owner-verified in AI Studio/Cloud Billing",
        )
    return PreflightCheck(
        "Paid experiment TTS isolation",
        True,
        "dedicated TTS credential and owner-verified project billing isolation",
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


def _authority_checks() -> list[PreflightCheck]:
    if os.name != "nt":
        return []
    checks: list[PreflightCheck] = []
    for readiness in authority_tool_readiness():
        detail = readiness.detail
        if readiness.path is not None:
            detail = f"{readiness.path} | {detail}"
        checks.append(
            PreflightCheck(
                readiness.label,
                readiness.ok,
                detail,
            )
        )
    return checks


def run_startup_preflight(config: JarvisConfig) -> list[PreflightCheck]:
    checks = [
        _check_file("Wake model", config.wake_model_path),
        _credential_check(config),
        _gemini_realtime_compatibility_check(config),
        _realtime_lifecycle_voice_check(config),
        *_audio_checks(config),
        *_authority_checks(),
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
