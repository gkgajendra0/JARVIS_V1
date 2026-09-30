"""Authoritative provider-model lifecycle reconciliation for Gemini Live."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import urllib.request
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

from google import genai
from google.genai import errors as genai_errors

from jarvis.config import JarvisConfig
from jarvis.machine_config import (
    default_machine_config_path,
    load_machine_settings,
    runtime_environment_overrides_enabled,
    save_machine_settings,
)

LOGGER = logging.getLogger(__name__)

GEMINI_DEPRECATIONS_URL = "https://ai.google.dev/gemini-api/docs/deprecations"
GEMINI_REALTIME_MODEL_SETTING = "JARVIS_GEMINI_REALTIME_MODEL"
DEFAULT_LIFECYCLE_FETCH_TIMEOUT_SECONDS = 8.0
DEFAULT_LIVE_PROBE_TIMEOUT_SECONDS = 10.0
MODEL_LIFECYCLE_STATE_SCHEMA_VERSION = 1
ROLLED_BACK_RETRY_COOLDOWN_SECONDS = 6 * 60 * 60

_MODEL_ID = re.compile(r"\bgemini-[a-z0-9][a-z0-9._-]*\b", re.IGNORECASE)

LifecycleFetcher = Callable[[str, float], str]
LiveProbe = Callable[[str, str, float], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class GeminiLiveLifecycleRecord:
    model: str
    release_date: str
    shutdown_date: str
    recommended_replacement: str | None
    source_url: str = GEMINI_DEPRECATIONS_URL


@dataclass(frozen=True, slots=True)
class GeminiLiveLifecycleResult:
    current_model: str
    status: str
    replacement_model: str | None = None
    source_url: str = GEMINI_DEPRECATIONS_URL
    detail: str = ""

    @property
    def migrated(self) -> bool:
        return self.status == "migrated"


@dataclass(frozen=True, slots=True)
class GeminiLiveMigrationJournal:
    previous_model: str
    candidate_model: str
    state: str
    recorded_at: str
    source_url: str = GEMINI_DEPRECATIONS_URL


def default_model_lifecycle_state_path() -> Path:
    return default_machine_config_path().with_name("provider_model_lifecycle.json")


def _load_migration_journal(
    path: Path | None = None,
) -> GeminiLiveMigrationJournal | None:
    target = path or default_model_lifecycle_state_path()
    if not target.exists():
        return None
    payload = json.loads(target.read_text(encoding="utf-8"))
    if payload.get("schema_version") != MODEL_LIFECYCLE_STATE_SCHEMA_VERSION:
        raise RuntimeError("unsupported provider model lifecycle state schema")
    migration = payload.get("migration")
    if not isinstance(migration, dict):
        raise TypeError("provider model lifecycle state migration must be an object")
    return GeminiLiveMigrationJournal(
        previous_model=str(migration["previous_model"]).strip().casefold(),
        candidate_model=str(migration["candidate_model"]).strip().casefold(),
        state=str(migration["state"]).strip().casefold(),
        recorded_at=str(migration["recorded_at"]).strip(),
        source_url=str(migration.get("source_url", GEMINI_DEPRECATIONS_URL)).strip(),
    )


def _write_migration_journal(
    journal: GeminiLiveMigrationJournal,
    path: Path | None = None,
) -> None:
    target = path or default_model_lifecycle_state_path()
    payload = {
        "schema_version": MODEL_LIFECYCLE_STATE_SCHEMA_VERSION,
        "migration": {
            "previous_model": journal.previous_model,
            "candidate_model": journal.candidate_model,
            "state": journal.state,
            "recorded_at": journal.recorded_at,
            "source_url": journal.source_url,
        },
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)


def _journal_now(
    previous_model: str,
    candidate_model: str,
    state: str,
) -> GeminiLiveMigrationJournal:
    return GeminiLiveMigrationJournal(
        previous_model=previous_model.strip().casefold(),
        candidate_model=candidate_model.strip().casefold(),
        state=state,
        recorded_at=datetime.now(UTC).isoformat(),
    )


def has_pending_gemini_live_migration(current_model: str) -> bool:
    journal = _load_migration_journal()
    return bool(
        journal is not None
        and journal.state == "pending"
        and journal.candidate_model == current_model.strip().casefold()
    )


def accept_pending_gemini_live_migration(current_model: str) -> bool:
    journal = _load_migration_journal()
    if (
        journal is None
        or journal.state != "pending"
        or journal.candidate_model != current_model.strip().casefold()
    ):
        return False
    _write_migration_journal(
        _journal_now(
            journal.previous_model,
            journal.candidate_model,
            "accepted",
        )
    )
    LOGGER.info(
        "Gemini lifecycle migration accepted after real conversation | "
        "previous=%s current=%s",
        journal.previous_model,
        journal.candidate_model,
    )
    return True


def rollback_pending_gemini_live_migration(current_model: str) -> bool:
    journal = _load_migration_journal()
    normalized = current_model.strip().casefold()
    if (
        journal is None
        or journal.state != "pending"
        or journal.candidate_model != normalized
    ):
        return False

    settings = load_machine_settings()
    persisted = settings.get(GEMINI_REALTIME_MODEL_SETTING, "").strip().casefold()
    if persisted != journal.candidate_model:
        return False

    settings[GEMINI_REALTIME_MODEL_SETTING] = journal.previous_model
    save_machine_settings(settings)
    _write_migration_journal(
        _journal_now(
            journal.previous_model,
            journal.candidate_model,
            "rolled_back",
        )
    )
    LOGGER.error(
        "Rolled back pending Gemini lifecycle migration | candidate=%s previous=%s",
        journal.candidate_model,
        journal.previous_model,
    )
    return True


async def validated_rollback_pending_gemini_live_migration(
    config: JarvisConfig,
    *,
    api_key: str,
    live_probe: LiveProbe | None = None,
    probe_timeout_seconds: float = DEFAULT_LIVE_PROBE_TIMEOUT_SECONDS,
) -> GeminiLiveLifecycleResult:
    """Restore the previous model only if it can still establish Gemini Live."""

    current = config.gemini_realtime_model.strip().casefold()
    journal = _load_migration_journal()
    if (
        journal is None
        or journal.state != "pending"
        or journal.candidate_model != current
    ):
        return GeminiLiveLifecycleResult(
            current_model=current,
            status="no_pending_migration",
        )

    rollback_model = journal.previous_model
    probe = live_probe or _probe_gemini_live_model
    try:
        await probe(api_key, rollback_model, probe_timeout_seconds)
    except asyncio.CancelledError:
        raise
    except (OSError, RuntimeError, ValueError, genai_errors.APIError) as exc:
        LOGGER.error(
            "Pending Gemini migration needs rollback but the previous model failed "
            "its Live handshake | candidate=%s previous=%s error_type=%s",
            current,
            rollback_model,
            type(exc).__name__,
        )
        return GeminiLiveLifecycleResult(
            current_model=current,
            status="rollback_probe_failed",
            replacement_model=rollback_model,
            detail=type(exc).__name__,
        )

    if not rollback_pending_gemini_live_migration(current):
        return GeminiLiveLifecycleResult(
            current_model=current,
            status="rollback_state_changed",
            replacement_model=rollback_model,
        )

    return GeminiLiveLifecycleResult(
        current_model=current,
        status="rolled_back",
        replacement_model=rollback_model,
    )


def _replacement_blocked_after_rollback(
    current_model: str,
    replacement_model: str,
    *,
    now: datetime | None = None,
) -> bool:
    journal = _load_migration_journal()
    if not (
        journal is not None
        and journal.state == "rolled_back"
        and journal.previous_model == current_model.strip().casefold()
        and journal.candidate_model == replacement_model.strip().casefold()
    ):
        return False

    try:
        recorded_at = datetime.fromisoformat(journal.recorded_at)
    except ValueError:
        return True
    if recorded_at.tzinfo is None:
        recorded_at = recorded_at.replace(tzinfo=UTC)
    current_time = now or datetime.now(UTC)
    elapsed = (current_time - recorded_at.astimezone(UTC)).total_seconds()
    return elapsed < ROLLED_BACK_RETRY_COOLDOWN_SECONDS


class _GeminiDeprecationParser(HTMLParser):
    """Extract only rows from Google's Live API model lifecycle table."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._heading_tag: str | None = None
        self._heading_parts: list[str] = []
        self._section = ""
        self._in_row = False
        self._cell_tag: str | None = None
        self._cell_parts: list[str] = []
        self._row: list[str] = []
        self.live_rows: list[tuple[str, ...]] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        del attrs
        lowered = tag.casefold()
        if lowered == "h2":
            self._heading_tag = lowered
            self._heading_parts = []
            return
        if lowered == "tr":
            self._in_row = True
            self._row = []
            return
        if self._in_row and lowered in {"td", "th"}:
            self._cell_tag = lowered
            self._cell_parts = []

    def handle_data(self, data: str) -> None:
        if self._heading_tag is not None:
            self._heading_parts.append(data)
        if self._cell_tag is not None:
            self._cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.casefold()
        if self._heading_tag == lowered:
            self._section = " ".join("".join(self._heading_parts).split()).casefold()
            self._heading_tag = None
            self._heading_parts = []
            return
        if self._cell_tag == lowered:
            cell = " ".join("".join(self._cell_parts).split())
            self._row.append(cell)
            self._cell_tag = None
            self._cell_parts = []
            return
        if lowered == "tr" and self._in_row:
            if "live api models" in self._section and self._row:
                self.live_rows.append(tuple(self._row))
            self._in_row = False
            self._row = []


def parse_gemini_live_lifecycle(html: str) -> tuple[GeminiLiveLifecycleRecord, ...]:
    if not isinstance(html, str):
        raise TypeError("Gemini lifecycle HTML must be text")
    parser = _GeminiDeprecationParser()
    parser.feed(html)

    records: list[GeminiLiveLifecycleRecord] = []
    seen: set[str] = set()
    for row in parser.live_rows:
        if len(row) < 4:
            continue
        model_match = _MODEL_ID.search(row[0])
        if model_match is None:
            continue
        model = model_match.group(0).casefold()
        if model in seen:
            continue
        replacement_match = _MODEL_ID.search(row[3])
        replacement = (
            replacement_match.group(0).casefold()
            if replacement_match is not None
            else None
        )
        records.append(
            GeminiLiveLifecycleRecord(
                model=model,
                release_date=row[1].strip(),
                shutdown_date=row[2].strip(),
                recommended_replacement=replacement,
            )
        )
        seen.add(model)
    return tuple(records)


def _fetch_text(url: str, timeout_seconds: float) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": "JARVIS-Provider-Lifecycle/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        content_type = response.headers.get_content_type()
        if content_type not in {"text/html", "application/xhtml+xml"}:
            raise RuntimeError(
                f"unexpected Gemini lifecycle content type: {content_type}"
            )
        payload = response.read(2_000_000)
    return payload.decode("utf-8", errors="strict")


async def _probe_gemini_live_model(
    api_key: str,
    model: str,
    timeout_seconds: float,
) -> None:
    """Require the candidate to complete a real Gemini Live setup handshake."""

    async def connect_once() -> None:
        client = genai.Client(api_key=api_key)
        try:
            async with client.aio.live.connect(
                model=model,
                config={"response_modalities": ["AUDIO"]},
            ):
                return
        finally:
            await client.aio.aclose()

    await asyncio.wait_for(connect_once(), timeout=timeout_seconds)


def _candidate_record(
    records: tuple[GeminiLiveLifecycleRecord, ...],
    current_model: str,
) -> GeminiLiveLifecycleRecord | None:
    normalized = current_model.strip().casefold()
    return next((record for record in records if record.model == normalized), None)


def _persist_replacement(
    *,
    current_model: str,
    replacement_model: str,
) -> None:
    if runtime_environment_overrides_enabled() and os.getenv(
        GEMINI_REALTIME_MODEL_SETTING
    ):
        raise RuntimeError(
            "runtime environment overrides own the Gemini realtime model; "
            "automatic persisted migration is inhibited"
        )

    settings = load_machine_settings()
    persisted = settings.get(GEMINI_REALTIME_MODEL_SETTING)
    if (
        persisted is not None
        and persisted.strip().casefold() != current_model.casefold()
    ):
        raise RuntimeError(
            "persisted Gemini realtime model changed during lifecycle reconciliation"
        )
    _write_migration_journal(
        _journal_now(
            current_model,
            replacement_model,
            "pending",
        )
    )
    settings[GEMINI_REALTIME_MODEL_SETTING] = replacement_model
    try:
        save_machine_settings(settings)
    except Exception:
        _write_migration_journal(
            _journal_now(
                current_model,
                replacement_model,
                "persistence_failed",
            )
        )
        raise


async def reconcile_gemini_live_model(
    config: JarvisConfig,
    *,
    api_key: str,
    fetcher: LifecycleFetcher = _fetch_text,
    live_probe: LiveProbe = _probe_gemini_live_model,
    fetch_timeout_seconds: float = DEFAULT_LIFECYCLE_FETCH_TIMEOUT_SECONDS,
    probe_timeout_seconds: float = DEFAULT_LIVE_PROBE_TIMEOUT_SECONDS,
) -> GeminiLiveLifecycleResult:
    """Migrate only from authoritative Google replacement evidence.

    The operation is deliberately narrow: no replacement is guessed, no moving
    latest alias is accepted, and a candidate is persisted only after a real
    Live setup handshake succeeds with the currently installed SDK stack.
    """

    current = config.gemini_realtime_model.strip().casefold()
    if config.ai_provider != "gemini":
        return GeminiLiveLifecycleResult(
            current_model=current,
            status="not_applicable",
            detail="active AI provider is not Gemini",
        )

    try:
        html = await asyncio.to_thread(
            fetcher,
            GEMINI_DEPRECATIONS_URL,
            fetch_timeout_seconds,
        )
        records = parse_gemini_live_lifecycle(html)
    except asyncio.CancelledError:
        raise
    except (OSError, RuntimeError, UnicodeError) as exc:
        LOGGER.warning(
            "Gemini lifecycle evidence unavailable; keeping current model | "
            "model=%s error_type=%s",
            current,
            type(exc).__name__,
        )
        return GeminiLiveLifecycleResult(
            current_model=current,
            status="evidence_unavailable",
            detail=type(exc).__name__,
        )

    record = _candidate_record(records, current)
    if record is None:
        LOGGER.info(
            "Gemini lifecycle table has no Live row for configured model; "
            "no automatic migration attempted | model=%s",
            current,
        )
        return GeminiLiveLifecycleResult(
            current_model=current,
            status="unlisted",
        )

    replacement = record.recommended_replacement
    if replacement is None or replacement == current:
        return GeminiLiveLifecycleResult(
            current_model=current,
            status="current",
            detail=f"shutdown={record.shutdown_date or 'unknown'}",
        )

    if _replacement_blocked_after_rollback(current, replacement):
        LOGGER.error(
            "Gemini lifecycle replacement was recently rolled back; "
            "automatic retry is cooling down | current=%s replacement=%s",
            current,
            replacement,
        )
        return GeminiLiveLifecycleResult(
            current_model=current,
            status="replacement_blocked_after_rollback",
            replacement_model=replacement,
            detail="previous_automatic_migration_in_cooldown",
        )

    if "live" not in replacement:
        LOGGER.error(
            "Gemini lifecycle replacement is not a Live model; refusing migration | "
            "current=%s replacement=%s",
            current,
            replacement,
        )
        return GeminiLiveLifecycleResult(
            current_model=current,
            status="replacement_rejected",
            replacement_model=replacement,
            detail="replacement_not_live",
        )

    try:
        await live_probe(api_key, replacement, probe_timeout_seconds)
    except asyncio.CancelledError:
        raise
    except (
        OSError,
        RuntimeError,
        TimeoutError,
        ValueError,
        genai_errors.APIError,
    ) as exc:
        LOGGER.error(
            "Gemini recommended replacement failed Live handshake; keeping current "
            "model | current=%s replacement=%s error_type=%s",
            current,
            replacement,
            type(exc).__name__,
        )
        return GeminiLiveLifecycleResult(
            current_model=current,
            status="replacement_probe_failed",
            replacement_model=replacement,
            detail=type(exc).__name__,
        )

    try:
        _persist_replacement(
            current_model=current,
            replacement_model=replacement,
        )
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        LOGGER.error(
            "Gemini replacement passed Live handshake but persistence failed | "
            "current=%s replacement=%s error_type=%s",
            current,
            replacement,
            type(exc).__name__,
        )
        return GeminiLiveLifecycleResult(
            current_model=current,
            status="persistence_failed",
            replacement_model=replacement,
            detail=type(exc).__name__,
        )

    LOGGER.warning(
        "Gemini realtime model lifecycle migration persisted | current=%s "
        "replacement=%s source=%s",
        current,
        replacement,
        GEMINI_DEPRECATIONS_URL,
    )
    return GeminiLiveLifecycleResult(
        current_model=current,
        status="migrated",
        replacement_model=replacement,
        detail=f"shutdown={record.shutdown_date or 'unknown'}",
    )
