"""Zero-network contract tests for the three-call synthetic Gemini smoke."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from tools.research.step4_contextual_gemini_three_call_smoke import (
    DELAY_BETWEEN_CALLS_SECONDS,
    MAX_PROVIDER_CALLS,
    SYNTHETIC_CASES,
    _case_context,
    main,
    run_smoke,
)

from jarvis.memory.candidates import (
    MemoryCandidateType,
    MemoryExtractionIntent,
    MemoryExtractionProposal,
    MemoryExtractionSensitivity,
)


def _proposal(
    intent: MemoryExtractionIntent,
    kind: MemoryCandidateType,
    predicate: str | None,
    value: str | None,
) -> MemoryExtractionProposal:
    return MemoryExtractionProposal(
        intent=intent,
        candidate_type=kind,
        durable_candidate=bool(value),
        subject="owner" if value else None,
        predicate=predicate,
        value=value,
        sensitivity=MemoryExtractionSensitivity.NORMAL,
        confidence=0.85,
    )


class FakeExtractor:
    def __init__(self, *, fail_on: int | None = None) -> None:
        self.fail_on = fail_on
        self.calls: list[dict[str, str]] = []

    async def extract_contextual(
        self, *, text: str, context: str
    ) -> MemoryExtractionProposal:
        self.calls.append({"text": text, "context": context})
        if len(self.calls) == self.fail_on:
            raise RuntimeError("never emit this fake provider detail")
        if len(self.calls) == 1:
            return _proposal(
                MemoryExtractionIntent.CORRECTION,
                MemoryCandidateType.FACT_CORRECTION,
                "weekly_workshop_recap_format",
                "Written checklist",
            )
        if len(self.calls) == 2:
            return _proposal(
                MemoryExtractionIntent.HISTORICAL_CHANGE,
                MemoryCandidateType.FACT_CHANGE,
                "weekly_project_report_day",
                "गुरुवार",
            )
        return _proposal(
            MemoryExtractionIntent.NONE, MemoryCandidateType.NONE, None, None
        )


@pytest.mark.asyncio
async def test_smoke_calls_exactly_three_in_order_with_no_retries_or_real_data():
    extractor = FakeExtractor()
    delays: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        delays.append(seconds)

    result = await run_smoke(extractor, sleep=fake_sleep)
    assert len(extractor.calls) == MAX_PROVIDER_CALLS == 3
    assert result["provider_calls_attempted"] == 3
    assert [case["pass"] for case in result["cases"]] == [True, True, True]
    assert delays == [DELAY_BETWEEN_CALLS_SECONDS] * 2
    assert all("fictional" in str(c) or c["language"] != "en" for c in SYNTHETIC_CASES)
    assert all(c["status"] == "completed" for c in result["cases"])
    for call in extractor.calls:
        assert len(call["text"]) < 1200
        data = json.loads(call["context"])
        assert set(data) == {
            "recent_accepted_owner_turns",
            "verified_current_memory_candidates",
        }
        assert "password" not in call["context"].casefold()


@pytest.mark.asyncio
async def test_smoke_provider_failure_stops_without_retry_or_leaked_error():
    extractor = FakeExtractor(fail_on=2)
    delays: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        delays.append(seconds)

    result = await run_smoke(extractor, sleep=fake_sleep)
    assert len(extractor.calls) == 2
    assert result["provider_calls_attempted"] == 2
    assert result["cases"][1]["status"] == "provider_failure_stop"
    assert result["cases"][1]["error_class"] == "RuntimeError"
    assert "never emit this fake provider detail" not in json.dumps(result)
    assert delays == [DELAY_BETWEEN_CALLS_SECONDS]


@pytest.mark.asyncio
async def test_smoke_refuses_other_synthetic_or_user_supplied_corpora():
    fake = FakeExtractor()
    with pytest.raises(ValueError, match="three pinned"):
        await run_smoke(fake, cases=SYNTHETIC_CASES[:1], sleep=asyncio.sleep)
    assert fake.calls == []


def test_smoke_default_is_dry_run_without_google_credentials(
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    main([])
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "dry_run_no_provider_calls"
    assert output["max_calls"] == 3
    assert len(output["pinned_synthetic_cases"]) == 3


def test_smoke_requires_verified_free_tier_and_never_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-no-network")
    with pytest.raises(SystemExit) as error:
        main(["--allow-three-calls"])
    assert error.value.code == 2


def test_smoke_context_only_includes_fixed_synthetic_data():
    case = SYNTHETIC_CASES[2]
    context = json.loads(_case_context(case))
    assert len(context["verified_current_memory_candidates"]) == 2
    assert len(context["recent_accepted_owner_turns"]) == 2
    assert "Hall B" in json.dumps(context)
