"""Guided one-time machine setup for JARVIS."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

from jarvis.config import FALSE_VALUES, TRUE_VALUES, JarvisConfig
from jarvis.machine_config import (
    PERSISTABLE_SETTINGS,
    configured_text,
    default_machine_config_path,
    load_machine_settings,
    save_machine_settings,
)
from jarvis.preflight import print_preflight, run_startup_preflight
from jarvis.voice.audio import DEVICE_CHANNELS, DEVICE_SAMPLE_RATE, LocalAudioRuntime


def _device_inventory(kind: str) -> list[dict[str, Any]]:
    import sounddevice as sd

    channel_key = "max_input_channels" if kind == "input" else "max_output_channels"
    devices: list[dict[str, Any]] = []
    for index, raw in enumerate(sd.query_devices()):
        item = dict(raw)
        item["index"] = index
        if int(item.get(channel_key, 0)) > 0:
            devices.append(item)
    return LocalAudioRuntime._attach_host_api_names(devices)


def _supports_48k(device: dict[str, Any], kind: str) -> bool:
    import sounddevice as sd

    check = sd.check_input_settings if kind == "input" else sd.check_output_settings
    try:
        check(
            device=int(device["index"]),
            channels=DEVICE_CHANNELS,
            dtype="int16",
            samplerate=DEVICE_SAMPLE_RATE,
        )
        return True
    except Exception:
        return False


def _selector(device: dict[str, Any]) -> str:
    return (
        f"name:{device['name']}|"
        f"hostapi:{device.get('hostapi_name', device.get('hostapi', 'unknown'))}"
    )


def _preferred_score(device: dict[str, Any], kind: str) -> int:
    name = str(device["name"]).casefold().replace(" ", "")
    host = str(device.get("hostapi_name", "")).casefold()
    score = 10 if "wasapi" in host else 0
    if kind == "input":
        if "osmopocket3" in name:
            score += 100
        elif "osmo" in name and "pocket" in name:
            score += 80
    else:
        if "24'tv" in name or '24"tv' in name:
            score += 100
        if "nvidia" in name:
            score += 40
    return score


def _is_stable_selector(value: str | None) -> bool:
    if not value:
        return False
    normalized = value.strip().casefold()
    return normalized.startswith("name:") and "|hostapi:" in normalized


def _choose_device(
    kind: str,
    existing_selector: str | None,
) -> str:
    devices = _device_inventory(kind)
    compatible = [device for device in devices if _supports_48k(device, kind)]
    if not compatible:
        raise RuntimeError(f"No {kind} device accepting 48000 Hz was found")

    # Legacy index:N selectors are intentionally not reused. PortAudio indices
    # move when Windows devices appear/disappear, which is exactly the startup
    # fragility this setup flow removes.
    if _is_stable_selector(existing_selector):
        try:
            resolved = LocalAudioRuntime._resolve_device(
                devices,
                existing_selector,
                kind=kind,
            )
            if resolved is not None:
                device = next(
                    candidate
                    for candidate in compatible
                    if int(candidate["index"]) == resolved
                )
                print(f"Using configured {kind}: {device['name']}")
                return _selector(device)
        except (RuntimeError, StopIteration):
            pass

    ranked = sorted(
        compatible,
        key=lambda device: (_preferred_score(device, kind), -int(device["index"])),
        reverse=True,
    )
    best_score = _preferred_score(ranked[0], kind)
    best = [device for device in ranked if _preferred_score(device, kind) == best_score]
    if best_score > 0 and len(best) == 1:
        device = best[0]
        print(f"Auto-detected {kind}: {device['name']}")
        return _selector(device)

    print(f"\nAvailable 48 kHz {kind} devices:")
    for device in compatible:
        print(
            f"  {device['index']}: {device['name']} "
            f"[{device.get('hostapi_name', 'unknown')}]"
        )
    while True:
        raw = input(f"Select {kind} device index: ").strip()
        try:
            selected = int(raw)
        except ValueError:
            print("Enter one of the listed numeric indexes.")
            continue
        match = next(
            (device for device in compatible if int(device["index"]) == selected),
            None,
        )
        if match is not None:
            return _selector(match)
        print("That index is not one of the compatible devices.")


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().casefold()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    return default


def _ask_bool(prompt: str, default: bool) -> bool:
    suffix = "Y/n" if default else "y/N"
    while True:
        raw = input(f"{prompt} [{suffix}]: ").strip().casefold()
        if not raw:
            return default
        if raw in TRUE_VALUES or raw == "y":
            return True
        if raw in FALSE_VALUES or raw == "n":
            return False
        print("Please answer y or n.")


def _existing_file_or_prompt(
    label: str,
    current: str | None,
    *,
    required: bool,
) -> str | None:
    if current:
        candidate = Path(current).expanduser()
        if candidate.is_file():
            print(f"Using configured {label}: {candidate}")
            return str(candidate)

    while True:
        raw = input(
            f"{label} path{' (required)' if required else ' (blank to skip)'}: "
        ).strip()
        if not raw and not required:
            return None
        candidate = Path(raw).expanduser()
        if candidate.is_file():
            return str(candidate)
        print(f"File not found: {candidate}")


def _build_settings(existing: dict[str, str]) -> dict[str, str]:
    # First capture every allow-listed legacy runtime value so migration does not
    # silently discard tuned thresholds, voices, timeouts, or model locations.
    settings = dict(existing)
    for name in PERSISTABLE_SETTINGS:
        value = os.getenv(name)
        if value is not None:
            settings[name] = value.strip()

    provider = configured_text("JARVIS_REALTIME_PROVIDER", existing, "gemini")
    provider = (provider or "gemini").strip().casefold()
    if provider not in {"gemini", "openai"}:
        provider = "gemini"
    settings["JARVIS_REALTIME_PROVIDER"] = provider
    print(f"Realtime provider: {provider}")

    wake_current = configured_text("JARVIS_WAKE_MODEL_PATH", existing)
    wake_path = _existing_file_or_prompt("Wake model", wake_current, required=True)
    assert wake_path is not None
    settings["JARVIS_WAKE_MODEL_PATH"] = wake_path

    input_current = configured_text("JARVIS_AUDIO_INPUT_DEVICE", existing)
    output_current = configured_text("JARVIS_AUDIO_OUTPUT_DEVICE", existing)
    settings["JARVIS_AUDIO_INPUT_DEVICE"] = _choose_device("input", input_current)
    settings["JARVIS_AUDIO_OUTPUT_DEVICE"] = _choose_device("output", output_current)

    vision_default = _parse_bool(
        configured_text("JARVIS_VISION_ENABLED", existing),
        True,
    )
    vision_enabled = _ask_bool("Enable JARVIS vision", vision_default)
    settings["JARVIS_VISION_ENABLED"] = str(vision_enabled).lower()

    speaker_default = _parse_bool(
        configured_text("JARVIS_SPEAKER_SHADOW_ENABLED", existing),
        vision_enabled,
    )
    speaker_enabled = (
        _ask_bool("Enable passive speaker-identity shadow", speaker_default)
        if vision_enabled
        else False
    )
    settings["JARVIS_SPEAKER_SHADOW_ENABLED"] = str(speaker_enabled).lower()

    active_default = _parse_bool(
        configured_text("JARVIS_ACTIVE_SPEAKER_SHADOW_ENABLED", existing),
        False,
    )
    active_enabled = (
        _ask_bool("Enable Step-3 active-speaker shadow", active_default)
        if speaker_enabled
        else False
    )
    settings["JARVIS_ACTIVE_SPEAKER_SHADOW_ENABLED"] = str(active_enabled).lower()

    if active_enabled:
        active_current = configured_text("JARVIS_LR_ASD_MODEL_PATH", existing)
        active_path = _existing_file_or_prompt(
            "LR-ASD model",
            active_current,
            required=True,
        )
        assert active_path is not None
        settings["JARVIS_LR_ASD_MODEL_PATH"] = active_path
    else:
        settings.pop("JARVIS_LR_ASD_MODEL_PATH", None)

    head_model = configured_text("JARVIS_BLAZEFACE_MODEL_PATH", existing)
    if head_model and Path(head_model).expanduser().is_file():
        settings["JARVIS_BLAZEFACE_MODEL_PATH"] = str(Path(head_model).expanduser())

    return settings


def _print_saved(path: Path) -> None:
    print(f"\nSaved non-secret machine configuration to:\n  {path}")
    print("API keys are NOT stored in this file.")


def _legacy_runtime_overrides() -> list[str]:
    return sorted(name for name in PERSISTABLE_SETTINGS if os.getenv(name) is not None)


def _remove_windows_user_overrides(names: list[str]) -> None:
    if os.name != "nt":
        return

    import winreg

    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            "Environment",
            0,
            winreg.KEY_SET_VALUE,
        )
    except OSError as exc:
        raise RuntimeError("Unable to open Windows User environment for migration") from exc

    with key:
        for name in names:
            try:
                winreg.DeleteValue(key, name)
            except FileNotFoundError:
                pass


def _migrate_legacy_overrides() -> None:
    legacy = _legacy_runtime_overrides()
    if not legacy:
        return

    print("\nLegacy JARVIS runtime environment overrides detected:")
    for name in legacy:
        print(f"  {name}")
    if os.name != "nt":
        print(
            "They still override the machine profile. Remove them from your shell "
            "environment when migration is complete."
        )
        return

    if not _ask_bool(
        "Remove these non-secret JARVIS overrides from Windows User environment",
        True,
    ):
        print("Legacy overrides retained; they remain higher priority than machine.json.")
        return

    _remove_windows_user_overrides(legacy)
    # Ensure this setup process validates the newly persisted profile rather than
    # the legacy values it inherited from its parent PowerShell. The parent shell
    # cannot be changed by a child process, so a fresh shell is still required.
    for name in legacy:
        os.environ.pop(name, None)
    print("Legacy Windows User overrides removed for future shells.")
    print("Open a fresh PowerShell after setup before normal JARVIS use.")


def run_setup(*, show_only: bool = False) -> int:
    target = default_machine_config_path()
    existing = load_machine_settings(target)
    if show_only:
        print(f"JARVIS machine configuration: {target}")
        if not existing:
            print("No persisted settings. Run jarvis-setup.")
            return 1
        for key, value in sorted(existing.items()):
            print(f"{key}={value}")
        return 0

    print("JARVIS one-time machine setup")
    print("Secrets stay in the Windows user/process environment.\n")
    settings = _build_settings(existing)
    path = save_machine_settings(settings, target)
    _print_saved(path)
    _migrate_legacy_overrides()

    config = JarvisConfig.from_environment()
    checks = run_startup_preflight(config)
    print()
    print_preflight(checks)
    failures = [check for check in checks if not check.ok]
    if failures:
        print(
            "\nSetup was saved, but startup is not ready yet. "
            "Fix the failed item(s) above and rerun jarvis-setup."
        )
        return 2

    print("\nSetup complete. Normal startup is now: jarvis-voice")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure this PC for JARVIS")
    parser.add_argument(
        "--show",
        action="store_true",
        help="show the persisted non-secret machine configuration",
    )
    args = parser.parse_args()
    try:
        return run_setup(show_only=args.show)
    except (RuntimeError, OSError) as exc:
        print(f"jarvis-setup error: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
