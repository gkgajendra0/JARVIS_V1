from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest

from jarvis import provider_model_lifecycle as lifecycle
from jarvis.config import JarvisConfig
from jarvis.provider_model_lifecycle import (
    GEMINI_DEPRECATIONS_URL,
    parse_gemini_live_lifecycle,
    reconcile_gemini_live_model,
)


def lifecycle_html(
    *,
    current: str = "gemini-3.1-flash-live-preview",
    replacement: str = "gemini-3.8-live",
) -> str:
    return f"""
    <html><body>
      <h2>Gemini 3 models</h2>
      <table>
        <tr><th>Model</th><th>Release</th><th>Shutdown</th><th>Replacement</th></tr>
        <tr>
          <td><code>gemini-3.1-flash</code></td>
          <td>May 2026</td><td>No shutdown date announced</td>
          <td><code>gemini-3.5-flash</code></td>
        </tr>
      </table>
      <h2>Live API models</h2>
      <table>
        <tr><th>Model</th><th>Release date</th><th>Shutdown date</th>
            <th>Recommended replacement</th></tr>
        <tr><td colspan="4"><h3>Preview models</h3></td></tr>
        <tr>
          <td><code>{current}</code></td>
          <td>March 11, 2026</td>
          <td>No shutdown date announced</td>
          <td><code>{replacement}</code></td>
        </tr>
        <tr>
          <td><code>gemini-3.8-live</code></td>
          <td>September 15, 2026</td>
          <td>No shutdown date announced</td>
          <td></td>
        </tr>
      </table>
      <h2>Audio models</h2>
      <table>
        <tr>
          <td><code>gemini-3.1-flash-tts-preview</code></td>
          <td>April 2026</td><td>None</td>
          <td><code>gemini-3.8-flash-tts</code></td>
        </tr>
      </table>
    </body></html>
    """


def fetcher_for(html: str) -> Callable[[str, float], str]:
    def fetch(url: str, timeout_seconds: float) -> str:
        assert url == GEMINI_DEPRECATIONS_URL
        assert timeout_seconds > 0
        return html

    return fetch


def test_parser_reads_only_live_api_rows() -> None:
    records = parse_gemini_live_lifecycle(lifecycle_html())

    assert [record.model for record in records] == [
        "gemini-3.1-flash-live-preview",
        "gemini-3.8-live",
    ]
    assert records[0].recommended_replacement == "gemini-3.8-live"
    assert records[1].recommended_replacement is None


@pytest.mark.asyncio
async def test_reconcile_keeps_current_stable_live_model_without_probe() -> None:
    probes: list[str] = []

    async def probe(api_key: str, model: str, timeout_seconds: float) -> None:
        del api_key, timeout_seconds
        probes.append(model)

    result = await reconcile_gemini_live_model(
        JarvisConfig(
            ai_provider="gemini",
            gemini_realtime_model="gemini-3.8-live",
        ),
        api_key="test-key",
        fetcher=fetcher_for(lifecycle_html()),
        live_probe=probe,
    )

    assert result.status == "current"
    assert result.migrated is False
    assert probes == []


@pytest.mark.asyncio
async def test_reconcile_requires_probe_before_persisting_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, str]] = []

    async def probe(api_key: str, model: str, timeout_seconds: float) -> None:
        assert api_key == "test-key"
        assert timeout_seconds > 0
        events.append(("probe", model))

    def persist(*, current_model: str, replacement_model: str) -> None:
        events.append(("persist", f"{current_model}->{replacement_model}"))

    monkeypatch.setattr(
        "jarvis.provider_model_lifecycle._persist_replacement",
        persist,
    )

    result = await reconcile_gemini_live_model(
        JarvisConfig(
            ai_provider="gemini",
            gemini_realtime_model="gemini-3.1-flash-live-preview",
        ),
        api_key="test-key",
        fetcher=fetcher_for(lifecycle_html()),
        live_probe=probe,
    )

    assert result.status == "migrated"
    assert result.replacement_model == "gemini-3.8-live"
    assert events == [
        ("probe", "gemini-3.8-live"),
        (
            "persist",
            "gemini-3.1-flash-live-preview->gemini-3.8-live",
        ),
    ]


@pytest.mark.asyncio
async def test_probe_failure_keeps_existing_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    persisted = False

    async def probe(api_key: str, model: str, timeout_seconds: float) -> None:
        del api_key, model, timeout_seconds
        raise RuntimeError("candidate cannot establish Live session")

    def persist(*, current_model: str, replacement_model: str) -> None:
        del current_model, replacement_model
        nonlocal persisted
        persisted = True

    monkeypatch.setattr(
        "jarvis.provider_model_lifecycle._persist_replacement",
        persist,
    )

    result = await reconcile_gemini_live_model(
        JarvisConfig(
            ai_provider="gemini",
            gemini_realtime_model="gemini-3.1-flash-live-preview",
        ),
        api_key="test-key",
        fetcher=fetcher_for(lifecycle_html()),
        live_probe=probe,
    )

    assert result.status == "replacement_probe_failed"
    assert persisted is False


@pytest.mark.asyncio
async def test_non_live_replacement_is_rejected_without_probe() -> None:
    probed = False

    async def probe(api_key: str, model: str, timeout_seconds: float) -> None:
        del api_key, model, timeout_seconds
        nonlocal probed
        probed = True

    result = await reconcile_gemini_live_model(
        JarvisConfig(
            ai_provider="gemini",
            gemini_realtime_model="gemini-3.1-flash-live-preview",
        ),
        api_key="test-key",
        fetcher=fetcher_for(lifecycle_html(replacement="gemini-3.8-flash")),
        live_probe=probe,
    )

    assert result.status == "replacement_rejected"
    assert probed is False


@pytest.mark.asyncio
async def test_missing_authoritative_row_does_not_guess_replacement() -> None:
    html = lifecycle_html(
        current="gemini-some-other-live",
        replacement="gemini-3.8-live",
    )

    async def forbidden_probe(
        api_key: str,
        model: str,
        timeout_seconds: float,
    ) -> None:
        del api_key, model, timeout_seconds
        raise AssertionError("probe must not run without provider evidence")

    result = await reconcile_gemini_live_model(
        JarvisConfig(
            ai_provider="gemini",
            gemini_realtime_model="gemini-custom-live",
        ),
        api_key="test-key",
        fetcher=fetcher_for(html),
        live_probe=forbidden_probe,
    )

    assert result.status == "unlisted"


def test_pending_migration_survives_restart_detection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = lifecycle.GeminiLiveMigrationJournal(
        previous_model="gemini-old-live",
        candidate_model="gemini-new-live",
        state="pending",
        recorded_at="2026-09-30T00:00:00+00:00",
    )
    monkeypatch.setattr(lifecycle, "_load_migration_journal", lambda: journal)

    assert lifecycle.has_pending_gemini_live_migration("gemini-new-live") is True
    assert lifecycle.has_pending_gemini_live_migration("gemini-old-live") is False


def test_pending_migration_acceptance_is_persisted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = lifecycle.GeminiLiveMigrationJournal(
        previous_model="gemini-old-live",
        candidate_model="gemini-new-live",
        state="pending",
        recorded_at="2026-09-30T00:00:00+00:00",
    )
    written = []
    monkeypatch.setattr(lifecycle, "_load_migration_journal", lambda: journal)
    monkeypatch.setattr(lifecycle, "_write_migration_journal", written.append)

    assert lifecycle.accept_pending_gemini_live_migration("gemini-new-live") is True
    assert len(written) == 1
    assert written[0].state == "accepted"
    assert written[0].previous_model == "gemini-old-live"
    assert written[0].candidate_model == "gemini-new-live"


def test_pending_migration_rolls_back_persisted_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = lifecycle.GeminiLiveMigrationJournal(
        previous_model="gemini-old-live",
        candidate_model="gemini-new-live",
        state="pending",
        recorded_at="2026-09-30T00:00:00+00:00",
    )
    saved = []
    written = []
    monkeypatch.setattr(lifecycle, "_load_migration_journal", lambda: journal)
    monkeypatch.setattr(
        lifecycle,
        "load_machine_settings",
        lambda: {"JARVIS_GEMINI_REALTIME_MODEL": "gemini-new-live"},
    )
    monkeypatch.setattr(lifecycle, "save_machine_settings", saved.append)
    monkeypatch.setattr(lifecycle, "_write_migration_journal", written.append)

    assert lifecycle.rollback_pending_gemini_live_migration("gemini-new-live") is True
    assert saved == [{"JARVIS_GEMINI_REALTIME_MODEL": "gemini-old-live"}]
    assert written[-1].state == "rolled_back"


@pytest.mark.asyncio
async def test_rolled_back_replacement_is_not_retried_automatically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = lifecycle.GeminiLiveMigrationJournal(
        previous_model="gemini-3.1-flash-live-preview",
        candidate_model="gemini-3.8-live",
        state="rolled_back",
        recorded_at=datetime.now(UTC).isoformat(),
    )
    monkeypatch.setattr(lifecycle, "_load_migration_journal", lambda: journal)

    async def forbidden_probe(
        api_key: str,
        model: str,
        timeout_seconds: float,
    ) -> None:
        del api_key, model, timeout_seconds
        raise AssertionError("rolled-back candidate must not be probed automatically")

    result = await reconcile_gemini_live_model(
        JarvisConfig(
            ai_provider="gemini",
            gemini_realtime_model="gemini-3.1-flash-live-preview",
        ),
        api_key="test-key",
        fetcher=fetcher_for(lifecycle_html()),
        live_probe=forbidden_probe,
    )

    assert result.status == "replacement_blocked_after_rollback"


def test_rolled_back_replacement_becomes_retryable_after_cooldown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = lifecycle.GeminiLiveMigrationJournal(
        previous_model="gemini-old-live",
        candidate_model="gemini-new-live",
        state="rolled_back",
        recorded_at=(
            datetime.now(UTC)
            - timedelta(seconds=lifecycle.ROLLED_BACK_RETRY_COOLDOWN_SECONDS + 1)
        ).isoformat(),
    )
    monkeypatch.setattr(lifecycle, "_load_migration_journal", lambda: journal)

    assert (
        lifecycle._replacement_blocked_after_rollback(
            "gemini-old-live",
            "gemini-new-live",
        )
        is False
    )


@pytest.mark.asyncio
async def test_non_gemini_provider_does_not_fetch() -> None:
    def forbidden_fetch(url: str, timeout_seconds: float) -> str:
        del url, timeout_seconds
        raise AssertionError("lifecycle fetch must not run")

    async def forbidden_probe(
        api_key: str,
        model: str,
        timeout_seconds: float,
    ) -> None:
        del api_key, model, timeout_seconds
        raise AssertionError("probe must not run")

    result = await reconcile_gemini_live_model(
        JarvisConfig(ai_provider="openai"),
        api_key="unused",
        fetcher=forbidden_fetch,
        live_probe=forbidden_probe,
    )

    assert result.status == "not_applicable"
