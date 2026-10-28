"""Content diagnostics selected by the existing transcript setting."""

from __future__ import annotations

import json
import logging
import os

from jarvis.observability.redaction import redact_data

from .explicit import MemorySecretRejectedError, reject_prohibited_secret

LOGGER = logging.getLogger(__name__)
_CREDENTIAL_ENV_PARTS = (
    "API_KEY",
    "ACCESS_TOKEN",
    "REFRESH_TOKEN",
    "PASSWORD",
    "CLIENT_SECRET",
    "PRIVATE_KEY",
    "SECRET_ACCESS_KEY",
)


def content_for_log(value):
    """Keep conversation/fact text, while retaining the credential guard."""
    if isinstance(value, dict):
        if "label" in value and "value" in value:
            try:
                reject_prohibited_secret(
                    predicate=str(value["label"]), value=str(value["value"])
                )
            except MemorySecretRejectedError:
                return "[REDACTED credentials]"
        return redact_data({key: content_for_log(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return [content_for_log(item) for item in value]
    if isinstance(value, str):
        # Opaque credentials (for example Exa keys) need not have a recognizable
        # token prefix. Mask the process's configured values as well.
        secrets = sorted(
            {
                item
                for name, item in tuple(os.environ.items())
                if len(item) >= 8
                and any(part in name.upper() for part in _CREDENTIAL_ENV_PARTS)
            },
            key=len,
            reverse=True,
        )
        for secret in secrets:
            value = value.replace(secret, "[REDACTED credentials]")
        try:
            reject_prohibited_secret(predicate="", value=value)
        except MemorySecretRejectedError:
            return "[REDACTED credentials]"
    return redact_data(value)


def log_learning(enabled, source, stage, outcome, **details):
    if not enabled:
        return
    event = {
        "session_id": source.session_id,
        "turn_id": source.turn_id,
        "receipt_id": source.receipt_id,
        "stage": stage,
        "outcome": outcome,
        **content_for_log(details),
    }
    # JSON quoting keeps spoken newlines from impersonating additional log rows.
    LOGGER.info("Memory decision | %s", json.dumps(event, ensure_ascii=False))
