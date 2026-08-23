"""Minimal console logging configuration for JARVIS V1."""

from __future__ import annotations

import logging


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(level=level, format="%(message)s", force=True)
