"""Transition-based observability for the JARVIS vision runtime."""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import asdict, dataclass
from threading import RLock

from jarvis.vision.runtime import VisionSnapshot

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class VisionDiagnosticEvent:
    sequence: int
    observed_at: float
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class VisionDiagnosticStatus:
    running: bool = False
    frame_id: int | None = None
    captured_at: float | None = None
    visible_people: int = 0
    visible_heads: int = 0
    target_id: int | None = None
    target_visible: bool = False
    armed: bool = False
    framing_source: str | None = None
    last_pan_command: float = 0.0
    last_tilt_command: float = 0.0
    last_error: str | None = None


class VisionDiagnostics:
    """Keep current vision health plus a bounded history of meaningful transitions."""

    def __init__(self, *, max_events: int = 64) -> None:
        if max_events < 1:
            raise ValueError("max_events must be at least 1")
        self._lock = RLock()
        self._events: deque[VisionDiagnosticEvent] = deque(maxlen=max_events)
        self._status = VisionDiagnosticStatus()
        self._sequence = 0
        self._seen_snapshot = False

    @property
    def status(self) -> VisionDiagnosticStatus:
        with self._lock:
            return self._status

    def set_running(self, running: bool) -> None:
        with self._lock:
            if self._status.running == running:
                return
            self._status = VisionDiagnosticStatus(
                **{**asdict(self._status), "running": running}
            )
            self._append(
                observed_at=self._status.captured_at or 0.0,
                code="vision_started" if running else "vision_stopped",
                message=(
                    "Vision runtime started."
                    if running
                    else "Vision runtime stopped."
                ),
            )

    def record_action(self, *, code: str, message: str) -> None:
        with self._lock:
            self._append(
                observed_at=self._status.captured_at or 0.0,
                code=code,
                message=message,
            )

    def record_error(self, error: BaseException) -> None:
        message = f"{type(error).__name__}: {error}"
        with self._lock:
            self._status = VisionDiagnosticStatus(
                **{**asdict(self._status), "last_error": message}
            )
            self._append(
                observed_at=self._status.captured_at or 0.0,
                code="vision_error",
                message=message,
                log_level=logging.ERROR,
            )

    def observe(self, snapshot: VisionSnapshot) -> None:
        target = snapshot.target
        target_id = target.track_id if target is not None else None
        target_visible = bool(target is not None and target.visible)
        framing_source = (
            snapshot.framing_target.source
            if snapshot.framing_target is not None
            else None
        )
        new_status = VisionDiagnosticStatus(
            running=self._status.running,
            frame_id=snapshot.frame_id,
            captured_at=snapshot.captured_at,
            visible_people=len(snapshot.tracks),
            visible_heads=len(snapshot.heads),
            target_id=target_id,
            target_visible=target_visible,
            armed=snapshot.armed,
            framing_source=framing_source,
            last_pan_command=snapshot.command.pan,
            last_tilt_command=snapshot.command.tilt,
            last_error=self._status.last_error,
        )

        with self._lock:
            previous = self._status
            self._status = new_status
            if not self._seen_snapshot:
                self._seen_snapshot = True
                self._append(
                    observed_at=snapshot.captured_at,
                    code="vision_ready",
                    message=(
                        "Vision produced its first frame: "
                        f"{new_status.visible_people} person track(s), "
                        f"{new_status.visible_heads} head detection(s)."
                    ),
                )
                return

            if previous.visible_people != new_status.visible_people:
                self._append(
                    observed_at=snapshot.captured_at,
                    code="people_count_changed",
                    message=(
                        "Visible person tracks changed from "
                        f"{previous.visible_people} to {new_status.visible_people}."
                    ),
                )

            if previous.target_id != new_status.target_id:
                if new_status.target_id is None:
                    self._append(
                        observed_at=snapshot.captured_at,
                        code="target_cleared_or_expired",
                        message=f"Target {previous.target_id} is no longer selected.",
                    )
                elif previous.target_id is None:
                    self._append(
                        observed_at=snapshot.captured_at,
                        code="target_selected",
                        message=f"Target {new_status.target_id} is selected.",
                    )
                else:
                    self._append(
                        observed_at=snapshot.captured_at,
                        code="target_changed",
                        message=(
                            f"Target changed from {previous.target_id} "
                            f"to {new_status.target_id}."
                        ),
                        log_level=logging.WARNING,
                    )

            if (
                previous.target_id == new_status.target_id
                and new_status.target_id is not None
                and previous.target_visible != new_status.target_visible
            ):
                if new_status.target_visible:
                    self._append(
                        observed_at=snapshot.captured_at,
                        code="target_reacquired",
                        message=f"Target {new_status.target_id} became visible again.",
                    )
                else:
                    self._append(
                        observed_at=snapshot.captured_at,
                        code="target_temporarily_lost",
                        message=(
                            f"Target {new_status.target_id} is temporarily not visible; "
                            "no target switch is permitted."
                        ),
                    )

            if previous.armed != new_status.armed:
                self._append(
                    observed_at=snapshot.captured_at,
                    code="follow_armed" if new_status.armed else "follow_disarmed",
                    message=(
                        "Vision follow is armed."
                        if new_status.armed
                        else "Vision follow is disarmed."
                    ),
                )

            if (
                new_status.target_id is not None
                and previous.framing_source != new_status.framing_source
            ):
                if new_status.framing_source == "head":
                    message = (
                        f"Target {new_status.target_id} framing switched to HEAD anchor."
                    )
                elif new_status.framing_source == "body":
                    message = (
                        f"Target {new_status.target_id} lost usable head evidence; "
                        "using the same locked BODY track as fallback."
                    )
                else:
                    message = (
                        f"Target {new_status.target_id} currently has no framing anchor."
                    )
                self._append(
                    observed_at=snapshot.captured_at,
                    code="framing_source_changed",
                    message=message,
                )

    def report(self, *, event_limit: int = 12) -> dict[str, object]:
        if event_limit < 1:
            raise ValueError("event_limit must be at least 1")
        with self._lock:
            events = list(self._events)[-event_limit:]
            return {
                "status": asdict(self._status),
                "recent_events": [asdict(event) for event in events],
            }

    def _append(
        self,
        *,
        observed_at: float,
        code: str,
        message: str,
        log_level: int = logging.INFO,
    ) -> None:
        self._sequence += 1
        event = VisionDiagnosticEvent(
            sequence=self._sequence,
            observed_at=observed_at,
            code=code,
            message=message,
        )
        self._events.append(event)
        LOGGER.log(log_level, "VISION [%s] %s", code, message)
