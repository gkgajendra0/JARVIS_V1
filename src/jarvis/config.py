"""Environment-backed configuration for JARVIS."""

from __future__ import annotations

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


@dataclass(frozen=True, slots=True)
class JarvisConfig:
    log_level: str = "INFO"
    realtime_provider: str = "openai"
    realtime_model: str = "gpt-realtime"
    realtime_voice: str = "marin"
    gemini_realtime_model: str = "gemini-3.1-flash-live-preview"
    gemini_realtime_voice: str = "Charon"
    show_transcript: bool = True

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
        )
