"""Structured logging configuration for JARVIS V1."""

from __future__ import annotations

from pathlib import Path

from jarvis.observability.logging import configure_structured_logging


def configure_logging(
    level: str = "INFO",
    *,
    jsonl_path: str | Path | None = None,
) -> Path | None:
    return configure_structured_logging(level, jsonl_path=jsonl_path)
