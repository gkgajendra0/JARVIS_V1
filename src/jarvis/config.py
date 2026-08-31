"""Environment-backed configuration for JARVIS."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass

VALID_LOG_LEVELS = frozenset({"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"})
VALID_REALTIME_PROVIDERS = frozenset({"gemini", "openai"})
TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
FALSE_VALUES = frozenset({"0", "false", "no", "off"})


def _environment_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    raise ValueError(f"Unsupported {name}: {value!r}")


def _environment_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError(f"Unsupported {name}: {value!r}") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"Unsupported {name}: {value!r}")
    return parsed


def _optional_environment_text(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


@dataclass(frozen=True, slots=True)
class JarvisConfig:
    log_level: str = "INFO"
    realtime_provider: str = "openai"
    realtime_model: str = "gpt-realtime"
    realtime_voice: str = "marin"
    gemini_realtime_model: str = "gemini-3.1-flash-live-preview"
    gemini_realtime_voice: str = "Charon"
    show_transcript: bool = True
    startup_greeting_enabled: bool = True
    wake_model_path: str | None = None
    wake_threshold: float = 0.68
    wake_debounce_seconds: float = 2.0
    audio_input_device: str | None = None
    audio_output_device: str | None = None
    audio_ring_buffer_seconds: float = 2.5
    audio_pre_roll_seconds: float = 0.75
    wake_cooldown_seconds: float = 1.0
    initial_request_timeout_seconds: float = 8.0
    follow_up_timeout_seconds: float = 15.0
    max_utterance_seconds: float = 15.0
    vision_enabled: bool = False
    vision_head_model_path: str | None = None
    speaker_shadow_enabled: bool = False

    def __post_init__(self) -> None:
        normalized = str(self.log_level).strip().upper()
        if normalized not in VALID_LOG_LEVELS:
            raise ValueError(f"Unsupported JARVIS_LOG_LEVEL: {self.log_level!r}")
        object.__setattr__(self, "log_level", normalized)

        provider = str(self.realtime_provider).strip().lower()
        if provider not in VALID_REALTIME_PROVIDERS:
            raise ValueError(
                f"Unsupported JARVIS_REALTIME_PROVIDER: {self.realtime_provider!r}"
            )
        object.__setattr__(self, "realtime_provider", provider)

        for name in (
            "realtime_model",
            "realtime_voice",
            "gemini_realtime_model",
            "gemini_realtime_voice",
        ):
            value = str(getattr(self, name)).strip()
            if not value:
                raise ValueError(f"{name} must not be empty")
            object.__setattr__(self, name, value)

        for name in ("wake_model_path", "vision_head_model_path"):
            value = getattr(self, name)
            if value is not None:
                normalized_value = str(value).strip()
                object.__setattr__(self, name, normalized_value or None)

        for name in ("audio_input_device", "audio_output_device"):
            value = getattr(self, name)
            if value is not None:
                normalized_value = str(value).strip()
                object.__setattr__(self, name, normalized_value or None)

        if not 0 < self.wake_threshold <= 1:
            raise ValueError("wake_threshold must be greater than 0 and at most 1")
        positive_values = (
            "wake_debounce_seconds",
            "audio_ring_buffer_seconds",
            "wake_cooldown_seconds",
            "initial_request_timeout_seconds",
            "follow_up_timeout_seconds",
            "max_utterance_seconds",
        )
        for name in positive_values:
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be a positive finite number")
        if not math.isfinite(self.audio_pre_roll_seconds):
            raise ValueError("audio_pre_roll_seconds must be finite")
        if not 0 <= self.audio_pre_roll_seconds <= self.audio_ring_buffer_seconds:
            raise ValueError("audio pre-roll must fit inside the ring buffer")

    @classmethod
    def from_environment(cls) -> JarvisConfig:
        return cls(
            log_level=os.getenv("JARVIS_LOG_LEVEL", "INFO"),
            realtime_provider=os.getenv("JARVIS_REALTIME_PROVIDER", "openai"),
            realtime_model=os.getenv("JARVIS_REALTIME_MODEL", "gpt-realtime"),
            realtime_voice=os.getenv("JARVIS_REALTIME_VOICE", "marin"),
            gemini_realtime_model=os.getenv(
                "JARVIS_GEMINI_REALTIME_MODEL", "gemini-3.1-flash-live-preview"
            ),
            gemini_realtime_voice=os.getenv("JARVIS_GEMINI_REALTIME_VOICE", "Charon"),
            show_transcript=_environment_bool("JARVIS_SHOW_TRANSCRIPT", True),
            startup_greeting_enabled=_environment_bool("JARVIS_STARTUP_GREETING", True),
            wake_model_path=_optional_environment_text("JARVIS_WAKE_MODEL_PATH"),
            wake_threshold=_environment_float("JARVIS_WAKE_THRESHOLD", 0.68),
            wake_debounce_seconds=_environment_float(
                "JARVIS_WAKE_DEBOUNCE_SECONDS", 2.0
            ),
            audio_input_device=_optional_environment_text("JARVIS_AUDIO_INPUT_DEVICE"),
            audio_output_device=_optional_environment_text(
                "JARVIS_AUDIO_OUTPUT_DEVICE"
            ),
            audio_ring_buffer_seconds=_environment_float(
                "JARVIS_AUDIO_RING_BUFFER_SECONDS", 2.5
            ),
            audio_pre_roll_seconds=_environment_float(
                "JARVIS_AUDIO_PRE_ROLL_SECONDS", 0.75
            ),
            wake_cooldown_seconds=_environment_float(
                "JARVIS_WAKE_COOLDOWN_SECONDS", 1.0
            ),
            initial_request_timeout_seconds=_environment_float(
                "JARVIS_INITIAL_REQUEST_TIMEOUT_SECONDS", 8.0
            ),
            follow_up_timeout_seconds=_environment_float(
                "JARVIS_FOLLOW_UP_TIMEOUT_SECONDS", 15.0
            ),
            max_utterance_seconds=_environment_float(
                "JARVIS_MAX_UTTERANCE_SECONDS", 15.0
            ),
            vision_enabled=_environment_bool("JARVIS_VISION_ENABLED", False),
            vision_head_model_path=_optional_environment_text(
                "JARVIS_BLAZEFACE_MODEL_PATH"
            ),
            speaker_shadow_enabled=_environment_bool(
                "JARVIS_SPEAKER_SHADOW_ENABLED", False
            ),
        )