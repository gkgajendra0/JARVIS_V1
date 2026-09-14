"""Structured operational logging with readable console and bounded JSONL."""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import structlog

from jarvis.observability.context import current_correlation
from jarvis.observability.redaction import redact_event_dict

_MAX_BYTES = 25 * 1024 * 1024
_BACKUP_COUNT = 4


def default_jsonl_log_path() -> Path:
    if os.name == "nt":
        base = Path(
            os.environ.get(
                "LOCALAPPDATA",
                str(Path.home() / "AppData" / "Local"),
            )
        )
    else:
        base = Path(
            os.environ.get(
                "XDG_STATE_HOME",
                str(Path.home() / ".local" / "state"),
            )
        )
    return base / "JARVIS" / "logs" / "jarvis.jsonl"


def _add_correlation(
    _logger: Any,
    _method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    for key, value in current_correlation().as_dict().items():
        event_dict.setdefault(key, value)
    return event_dict


def _redact(
    _logger: Any,
    _method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    return redact_event_dict(event_dict)


def configure_structured_logging(
    level: str = "INFO",
    *,
    jsonl_path: str | Path | None = None,
) -> Path | None:
    shared = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _add_correlation,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        _redact,
    ]
    structlog.configure(
        processors=[
            *shared,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    console = logging.StreamHandler()
    console.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processor=structlog.dev.ConsoleRenderer(colors=False),
            foreign_pre_chain=shared,
        )
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(str(level).upper())
    root.addHandler(console)

    target = Path(jsonl_path).expanduser() if jsonl_path else default_jsonl_log_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            target,
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(
            structlog.stdlib.ProcessorFormatter(
                processor=structlog.processors.JSONRenderer(
                    sort_keys=True,
                    ensure_ascii=False,
                    default=str,
                ),
                foreign_pre_chain=shared,
            )
        )
        root.addHandler(file_handler)
    except OSError as exc:
        root.warning("JARVIS structured log file unavailable: %s", exc)
        return None

    logging.captureWarnings(True)
    return target


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
