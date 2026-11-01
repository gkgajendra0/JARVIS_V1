"""Stable, non-reversible experiment fingerprints (no raw owner data in reports)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .bridge import ExperimentConfig


def fingerprint(value: Any) -> str:
    """SHA-256 of canonical JSON; callers must supply JSON-compatible data."""
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def config_fingerprint(config: ExperimentConfig) -> str:
    return fingerprint(
        {
            "command": config.command,
            "cwd": config.cwd,
            "timeout": config.timeout,
            "operations": config.operations,
        }
    )
