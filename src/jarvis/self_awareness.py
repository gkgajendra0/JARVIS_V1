"""Composition layer for JARVIS operational self-awareness evidence."""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import Any

from jarvis.incidents import IncidentService, SqliteIncidentStore
from jarvis.observability.evidence_query import (
    EvidenceQueryResult,
    LocalOperationalEvidenceQuery,
    recent_since_epoch,
)
from jarvis.observability.logging import get_logger
from jarvis.self_model.defaults import build_default_self_model
from jarvis.self_model.health import HealthObservation, HealthRegistry, HealthState
from jarvis.self_model.registry import ComponentSnapshot, SelfModelRegistry

LOGGER = get_logger(__name__)


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
        operational_log_path: str | Path | None = None,
    ) -> None:
        self.self_model = self_model or build_default_self_model()
        self.health = health or HealthRegistry()
        self.operational_evidence = LocalOperationalEvidenceQuery(operational_log_path)
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
        LOGGER.info(
            "health_observation",
            component_id=component_id,
            health_source=source,
            state=state.value,
            reason_code=reason_code,
            summary=summary,
            metadata=metadata or {},
        )
        if self.incidents is not None:
            incident = self.incidents.record_health_transition(before.health, after.health)
            if incident is not None:
                LOGGER.warning(
                    "engineering_incident_recorded",
                    component_id=component_id,
                    incident_id=incident.incident_id,
                    state=after.health.state.value,
                    reason_code=reason_code,
                    status=incident.status.value,
                )
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
        health_surface_only: bool = False,
    ) -> tuple[ComponentSnapshot, ...]:
        return self.self_model.system_snapshot(
            self.health,
            now_epoch=now_epoch,
            health_surface_only=health_surface_only,
        )

    def query_operational_evidence(
        self,
        *,
        component_id: str,
        since_seconds: float = 15 * 60,
        severity: str = "",
        reason_code: str = "",
        session_id: str = "",
        turn_id: str = "",
        incident_id: str = "",
        query: str = "",
        max_results: int = 30,
        now_epoch: float | None = None,
    ) -> EvidenceQueryResult:
        descriptor = self.self_model.component(component_id)
        if descriptor is None:
            raise KeyError(f"unknown component: {component_id}")
        return self.operational_evidence.query(
            component_id=descriptor.component_id,
            logger_prefixes=descriptor.logger_prefixes,
            since_epoch=recent_since_epoch(since_seconds, now_epoch=now_epoch),
            severity=severity,
            reason_code=reason_code,
            session_id=session_id,
            turn_id=turn_id,
            incident_id=incident_id,
            query=query,
            max_results=max_results,
        )

    def close(self) -> None:
        if self._incident_store is not None:
            self._incident_store.close()
            self._incident_store = None
            self.incidents = None
