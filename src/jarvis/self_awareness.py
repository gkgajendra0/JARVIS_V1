"""Composition layer for JARVIS operational self-awareness evidence."""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import Any

from jarvis.incidents import IncidentService, SqliteIncidentStore
from jarvis.self_model.defaults import build_default_self_model
from jarvis.self_model.health import HealthObservation, HealthRegistry, HealthState
from jarvis.self_model.registry import ComponentSnapshot, SelfModelRegistry


def default_incident_store_path() -> Path:
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
    return base / "JARVIS" / "operations" / "incidents.sqlite3"


class SelfAwarenessRuntime:
    """JARVIS-owned operational truth composed from deterministic evidence."""

    def __init__(
        self,
        *,
        self_model: SelfModelRegistry | None = None,
        health: HealthRegistry | None = None,
        incident_store_path: str | Path | None = None,
    ) -> None:
        self.self_model = self_model or build_default_self_model()
        self.health = health or HealthRegistry()
        self._incident_store: SqliteIncidentStore | None = None
        self.incidents: IncidentService | None = None
        path = (
            Path(incident_store_path).expanduser()
            if incident_store_path is not None
            else default_incident_store_path()
        )
        try:
            self._incident_store = SqliteIncidentStore(path)
        except (OSError, sqlite3.Error):
            self._incident_store = None
        else:
            self.incidents = IncidentService(self._incident_store)

    @property
    def incident_persistence_available(self) -> bool:
        return self._incident_store is not None

    def observe(
        self,
        *,
        component_id: str,
        source: str,
        state: HealthState,
        reason_code: str,
        summary: str,
        ttl_seconds: float = 60.0,
        metadata: dict[str, Any] | None = None,
        observed_at_epoch: float | None = None,
    ) -> ComponentSnapshot:
        now = time.time() if observed_at_epoch is None else observed_at_epoch
        before = self.self_model.snapshot(component_id, self.health, now_epoch=now)
        self.health.record(
            HealthObservation.create(
                component_id=component_id,
                source=source,
                state=state,
                reason_code=reason_code,
                summary=summary,
                ttl_seconds=ttl_seconds,
                metadata=metadata,
                observed_at_epoch=now,
            )
        )
        after = self.self_model.snapshot(component_id, self.health, now_epoch=now)
        if self.incidents is not None:
            self.incidents.record_health_transition(before.health, after.health)
        return after

    def component_snapshot(
        self,
        component_id: str,
        *,
        now_epoch: float | None = None,
    ) -> ComponentSnapshot:
        return self.self_model.snapshot(
            component_id,
            self.health,
            now_epoch=now_epoch,
        )

    def system_snapshot(
        self,
        *,
        now_epoch: float | None = None,
    ) -> tuple[ComponentSnapshot, ...]:
        return self.self_model.system_snapshot(self.health, now_epoch=now_epoch)

    def close(self) -> None:
        if self._incident_store is not None:
            self._incident_store.close()
            self._incident_store = None
            self.incidents = None
