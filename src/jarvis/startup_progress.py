"""Startup progress heartbeat from the voice runtime to its supervisor.

The voice runtime builds everything (wake models, vision, LR-ASD on CUDA,
memory, capabilities, project-memory Windows Hello) before its control channel
connects. A cold first load can take minutes and varies widely between starts,
so a fixed deadline for the whole build either kills a healthy start or hides
a hang.

Instead the supervisor watches progress: every log record the startup
(main) thread emits is a completed step. The runtime records the latest one in
a small file the supervisor names (``JARVIS_STARTUP_PROGRESS_FILE``). The
supervisor fails startup only when that progress stops for the stall window,
the child exits, or an overall cap is reached.

Only the main thread counts: background threads keep logging even if the
startup thread is stuck. Nothing about the log content is written, only a
counter, the process id and a time.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path

STARTUP_PROGRESS_FILE_ENV = "JARVIS_STARTUP_PROGRESS_FILE"
_MIN_INTERVAL_SECONDS = 1.0


class StartupProgressHandler(logging.Handler):
    def __init__(self, path: Path) -> None:
        super().__init__(level=logging.DEBUG)
        self._path = path
        self._main = threading.main_thread()
        self._sequence = 0
        self._written_at = 0.0

    def emit(self, record: logging.LogRecord) -> None:
        if threading.current_thread() is not self._main:
            return
        self._sequence += 1
        now = time.monotonic()
        if now - self._written_at < _MIN_INTERVAL_SECONDS:
            return
        self._written_at = now
        write_progress(self._path, self._sequence)

    def finish(self) -> None:
        self._sequence += 1
        write_progress(self._path, self._sequence, ready=True)


def write_progress(path: Path, sequence: int, *, ready: bool = False) -> None:
    payload = {"pid": os.getpid(), "sequence": sequence, "ready": ready}
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(temporary, path)
    except OSError:
        # The supervisor may be reading the file; the next step writes again.
        pass


_handler: StartupProgressHandler | None = None


def install() -> None:
    """Report startup progress if a supervisor asked for it (idempotent).

    Call after logging is configured: configuring logging clears handlers.
    """

    global _handler
    raw = os.environ.get(STARTUP_PROGRESS_FILE_ENV, "").strip()
    if not raw:
        return
    root = logging.getLogger()
    if _handler is not None:
        root.removeHandler(_handler)
    _handler = StartupProgressHandler(Path(raw))
    root.addHandler(_handler)
    write_progress(Path(raw), 0)


def finish() -> None:
    """Startup finished; the control channel takes over."""

    global _handler
    handler, _handler = _handler, None
    if handler is not None:
        logging.getLogger().removeHandler(handler)
        handler.finish()


def read_progress(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None
