"""Environment-backed configuration for the Step-0 application."""

from __future__ import annotations

import os
from dataclasses import dataclass


VALID_LOG_LEVELS = frozenset({"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"})


@dataclass(frozen=True, slots=True)
class JarvisConfig:
    log_level: str = "INFO"

    def __post_init__(self) -> None:
        normalized = str(self.log_level).strip().upper()
        if normalized not in VALID_LOG_LEVELS:
            raise ValueError(f"Unsupported JARVIS_LOG_LEVEL: {self.log_level!r}")
        object.__setattr__(self, "log_level", normalized)

    @classmethod
    def from_environment(cls) -> "JarvisConfig":
        return cls(log_level=os.getenv("JARVIS_LOG_LEVEL", "INFO"))
