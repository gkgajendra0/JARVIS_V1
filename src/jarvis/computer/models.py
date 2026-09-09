"""Provider-neutral computer-use contracts."""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ComputerUseStatus(str, Enum):
    COMPLETED = "completed"
    CONFIRMATION_REQUIRED = "confirmation_required"
    BLOCKED = "blocked"
    STEP_LIMIT = "step_limit"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ScreenFrame:
    png_bytes: bytes
    left: int
    top: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if not self.png_bytes:
            raise ValueError("screen frame PNG must not be empty")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("screen frame dimensions must be positive")

    def data_url(self) -> str:
        encoded = base64.b64encode(self.png_bytes).decode("ascii")
        return f"data:image/png;base64,{encoded}"

    def normalized_to_desktop(self, x: int, y: int) -> tuple[int, int]:
        """Resolve Gemini 0..999 coordinates into virtual-desktop coordinates."""
        if not 0 <= x <= 999 or not 0 <= y <= 999:
            raise ValueError("normalized screen coordinates must be between 0 and 999")
        desktop_x = self.left + min(self.width - 1, int(x / 1000 * self.width))
        desktop_y = self.top + min(self.height - 1, int(y / 1000 * self.height))
        return desktop_x, desktop_y

    def pixel_to_desktop(self, x: int, y: int) -> tuple[int, int]:
        """Resolve screenshot-relative pixel coordinates into desktop coordinates."""
        if not 0 <= x < self.width or not 0 <= y < self.height:
            raise ValueError("pixel coordinates are outside the captured screen")
        return self.left + x, self.top + y


@dataclass(frozen=True, slots=True)
class ComputerAction:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    call_id: str | None = None
    intent: str | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("computer action name must not be empty")


@dataclass(frozen=True, slots=True)
class ActionExecutionResult:
    ok: bool
    detail: str

    def to_payload(self) -> dict[str, object]:
        return {"ok": self.ok, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class ComputerUseResult:
    status: ComputerUseStatus
    provider: str
    model: str
    steps: int
    summary: str = ""
    reason: str | None = None
    safety_message: str | None = None

    @property
    def ok(self) -> bool:
        return self.status is ComputerUseStatus.COMPLETED

    def to_tool_payload(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "operation": "computer_use",
            "status": self.status.value,
            "provider": self.provider,
            "model": self.model,
            "steps": self.steps,
            "summary": self.summary,
            "reason": self.reason,
            "safety_message": self.safety_message,
        }
