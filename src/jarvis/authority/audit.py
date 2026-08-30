from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class AuditError(RuntimeError):
    pass


_ALLOWED_VALUE_TYPES = (str, int, float, bool, type(None))
_FORBIDDEN_KEY_PARTS = (
    "password",
    "secret",
    "token",
    "embedding",
    "raw_audio",
    "raw_video",
    "audio_pcm",
    "face_crop",
    "gaze_vector",
    "iris_coordinate",
)


def _validated_metadata(
    metadata: Mapping[str, object],
) -> dict[str, object]:
    safe: dict[str, object] = {}
    for key, value in metadata.items():
        if not isinstance(key, str):
            raise AuditError("audit metadata keys must be strings")
        lowered = key.lower()
        if any(part in lowered for part in _FORBIDDEN_KEY_PARTS):
            raise AuditError(f"forbidden audit metadata key: {key}")
        if not isinstance(value, _ALLOWED_VALUE_TYPES):
            raise AuditError(f"unsupported audit metadata value for {key}")
        safe[key] = value
    return safe


@dataclass(frozen=True, slots=True)
class AuditEvent:
    event_id: str
    event_type: str
    occurred_at_epoch: float
    session_id: str | None
    proposal_id: str | None
    proposal_fingerprint: str | None
    reason_codes: tuple[str, ...]
    component: str
    metadata_json: str

    @classmethod
    def create(
        cls,
        *,
        event_type: str,
        component: str,
        session_id: str | None = None,
        proposal_id: str | None = None,
        proposal_fingerprint: str | None = None,
        reason_codes: tuple[str, ...] = (),
        metadata: Mapping[str, object] | None = None,
        now_epoch: float | None = None,
    ) -> AuditEvent:
        if not event_type.strip():
            raise AuditError("audit event_type must not be empty")
        if not component.strip():
            raise AuditError("audit component must not be empty")
        safe_metadata = _validated_metadata(metadata or {})
        return cls(
            event_id=str(uuid.uuid4()),
            event_type=event_type,
            occurred_at_epoch=(time.time() if now_epoch is None else now_epoch),
            session_id=session_id,
            proposal_id=proposal_id,
            proposal_fingerprint=proposal_fingerprint,
            reason_codes=tuple(reason_codes),
            component=component,
            metadata_json=json.dumps(
                safe_metadata,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ),
        )


class AuditEventStore(Protocol):
    def append(self, event: AuditEvent) -> None: ...


class InMemoryAuditEventStore:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []
        self._lock = threading.Lock()

    def append(self, event: AuditEvent) -> None:
        with self._lock:
            self.events.append(event)


class SqliteAuditEventStore:
    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        self._lock = threading.Lock()
        self._connection = sqlite3.connect(
            self._path,
            check_same_thread=False,
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS authority_audit_event (
                event_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                occurred_at_epoch REAL NOT NULL,
                session_id TEXT,
                proposal_id TEXT,
                proposal_fingerprint TEXT,
                reason_codes_json TEXT NOT NULL,
                component TEXT NOT NULL,
                metadata_json TEXT NOT NULL
            )
            """
        )
        self._connection.commit()

    def append(self, event: AuditEvent) -> None:
        with self._lock:
            try:
                self._connection.execute(
                    """
                    INSERT INTO authority_audit_event (
                        event_id,
                        event_type,
                        occurred_at_epoch,
                        session_id,
                        proposal_id,
                        proposal_fingerprint,
                        reason_codes_json,
                        component,
                        metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.event_type,
                        event.occurred_at_epoch,
                        event.session_id,
                        event.proposal_id,
                        event.proposal_fingerprint,
                        json.dumps(event.reason_codes),
                        event.component,
                        event.metadata_json,
                    ),
                )
                self._connection.commit()
            except sqlite3.Error as exc:
                raise AuditError("failed to persist audit event") from exc

    def close(self) -> None:
        with self._lock:
            self._connection.close()
