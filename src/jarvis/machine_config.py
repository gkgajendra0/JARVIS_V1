"""Persistent non-secret machine configuration for JARVIS.

The machine configuration stores stable hardware selectors, model paths, and
feature switches that belong to one installed PC. Secrets never belong here;
provider API keys remain in the process/Windows user environment.

Environment variables intentionally remain supported as higher-priority runtime
overrides so development and diagnostics do not require rewriting the persisted
machine profile.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Mapping

MACHINE_CONFIG_PATH_ENV = "JARVIS_MACHINE_CONFIG"
MACHINE_CONFIG_SCHEMA_VERSION = 1

# Explicit allow-list prevents an API key or other secret from being persisted by
# a future caller merely because it starts with JARVIS_.
PERSISTABLE_SETTINGS = frozenset(
    {
        "JARVIS_LOG_LEVEL",
        "JARVIS_REALTIME_PROVIDER",
        "JARVIS_REALTIME_MODEL",
        "JARVIS_REALTIME_VOICE",
        "JARVIS_GEMINI_REALTIME_MODEL",
        "JARVIS_GEMINI_REALTIME_VOICE",
        "JARVIS_SHOW_TRANSCRIPT",
        "JARVIS_STARTUP_GREETING",
        "JARVIS_WAKE_MODEL_PATH",
        "JARVIS_WAKE_THRESHOLD",
        "JARVIS_WAKE_DEBOUNCE_SECONDS",
        "JARVIS_AUDIO_INPUT_DEVICE",
        "JARVIS_AUDIO_OUTPUT_DEVICE",
        "JARVIS_AUDIO_RING_BUFFER_SECONDS",
        "JARVIS_AUDIO_PRE_ROLL_SECONDS",
        "JARVIS_WAKE_COOLDOWN_SECONDS",
        "JARVIS_INITIAL_REQUEST_TIMEOUT_SECONDS",
        "JARVIS_FOLLOW_UP_TIMEOUT_SECONDS",
        "JARVIS_MAX_UTTERANCE_SECONDS",
        "JARVIS_VISION_ENABLED",
        "JARVIS_BLAZEFACE_MODEL_PATH",
        "JARVIS_SPEAKER_SHADOW_ENABLED",
        "JARVIS_ACTIVE_SPEAKER_SHADOW_ENABLED",
        "JARVIS_LR_ASD_MODEL_PATH",
    }
)


def default_machine_config_path() -> Path:
    override = os.getenv(MACHINE_CONFIG_PATH_ENV)
    if override and override.strip():
        return Path(override.strip()).expanduser()

    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data and local_app_data.strip():
        return Path(local_app_data) / "JARVIS" / "machine.json"
    return Path.home() / ".jarvis" / "machine.json"


def load_machine_settings(path: Path | None = None) -> dict[str, str]:
    target = path or default_machine_config_path()
    if not target.exists():
        return {}

    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Unable to read JARVIS machine configuration at {target}. "
            "Run jarvis-setup to repair it."
        ) from exc

    if not isinstance(payload, dict):
        raise RuntimeError(
            f"Invalid JARVIS machine configuration at {target}: root must be an object"
        )
    if payload.get("schema_version") != MACHINE_CONFIG_SCHEMA_VERSION:
        raise RuntimeError(
            f"Unsupported JARVIS machine configuration schema at {target}; "
            "run jarvis-setup to regenerate it"
        )

    raw_settings = payload.get("settings")
    if not isinstance(raw_settings, dict):
        raise RuntimeError(
            f"Invalid JARVIS machine configuration at {target}: settings must be an object"
        )

    settings: dict[str, str] = {}
    for key, value in raw_settings.items():
        if key not in PERSISTABLE_SETTINGS:
            raise RuntimeError(
                f"Unsupported persisted JARVIS setting {key!r} in {target}; "
                "run jarvis-setup to regenerate the machine configuration"
            )
        if not isinstance(value, str):
            raise RuntimeError(
                f"Invalid persisted JARVIS setting {key!r} in {target}: value must be text"
            )
        settings[key] = value
    return settings


def save_machine_settings(
    settings: Mapping[str, str],
    path: Path | None = None,
) -> Path:
    target = path or default_machine_config_path()
    normalized: dict[str, str] = {}
    for key, value in settings.items():
        if key not in PERSISTABLE_SETTINGS:
            raise ValueError(f"JARVIS setting may not be persisted: {key}")
        if not isinstance(value, str):
            raise TypeError(f"Persisted JARVIS setting must be text: {key}")
        normalized[key] = value.strip()

    payload = {
        "schema_version": MACHINE_CONFIG_SCHEMA_VERSION,
        "settings": dict(sorted(normalized.items())),
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)
    return target


def configured_text(
    name: str,
    machine_settings: Mapping[str, str],
    default: str | None = None,
) -> str | None:
    """Return environment override, then persisted setting, then default."""

    environment_value = os.getenv(name)
    if environment_value is not None:
        return environment_value
    if name in machine_settings:
        return machine_settings[name]
    return default
