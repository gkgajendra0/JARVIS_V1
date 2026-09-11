"""Semantic contracts for provider-neutral JARVIS Hands."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class HandsDomain(str, Enum):
    SYSTEM_STATUS = "system.status"
    SYSTEM_AUDIO = "system.audio"
    MEDIA_PLAYBACK = "media.playback"
    APP_LIFECYCLE = "app.lifecycle"
    APP_UI = "app.ui"
    WINDOW_MANAGEMENT = "window.management"
    CLIPBOARD = "system.clipboard"
    FILES_READ = "files.read"
    FILES_WRITE = "files.write"
    DOCUMENTS = "documents"
    BROWSER = "browser"
    DEVICES = "devices"
    PRODUCTIVITY = "productivity"
    COMMUNICATION = "communication"
    DEVELOPMENT = "development"
    SOFTWARE = "software"
    VISUAL_COMPUTER = "visual.computer"


class ExecutionSubstrate(str, Enum):
    NATIVE_API = "native_api"
    DEDICATED_INTEGRATION = "dedicated_integration"
    STRUCTURED_AUTOMATION = "structured_automation"
    VISUAL_FALLBACK = "visual_fallback"
    HUMAN = "human"


@dataclass(frozen=True, slots=True)
class HandsOperation:
    operation: str
    domain: HandsDomain
    description: str
    preferred_substrates: tuple[ExecutionSubstrate, ...]
    requires_verification: bool = True

    def __post_init__(self) -> None:
        if not self.operation.strip():
            raise ValueError("hands operation must not be empty")
        if not self.description.strip():
            raise ValueError("hands operation description must not be empty")
        if not self.preferred_substrates:
            raise ValueError("hands operation must declare an execution preference")


@dataclass(frozen=True, slots=True)
class HandsWorkflowStep:
    operation: str
    parameters: dict[str, Any]

    def __post_init__(self) -> None:
        if not self.operation.strip():
            raise ValueError("workflow operation must not be empty")
        if not isinstance(self.parameters, dict):
            raise TypeError("workflow parameters must be an object")


@dataclass(frozen=True, slots=True)
class HandsWorkflowResult:
    ok: bool
    completed_steps: int
    results: tuple[Any, ...]
    failed_operation: str | None = None
    reason: str | None = None
