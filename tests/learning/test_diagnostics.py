import asyncio
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from jarvis.config import JarvisConfig
from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.learning_contracts import (
    AcceptedLearningSource,
    LearningAdmissionResult,
    LearningBatch,
    LearningResolution,
    LearningResolutionBatch,
)
from jarvis.memory.learning_extractors import LearningProviderAdapter
from jarvis.memory.learning_reconciliation import LearningReconciler
from jarvis.memory.learning_runtime import PersonalLearningRuntime


def source(text="I own a City"):
    c = ConversationSession()
    c.start()
    t = c.accept_turn(ConversationRole.USER, text)
    return AcceptedLearningSource.from_turn("runtime", c, t, now=100)


def events(caplog):
    return [
        json.loads(r.getMessage().split(" | ", 1)[1])
        for r in caplog.records
        if r.getMessage().startswith("Memory decision | ")
    ]


def test_explicit_transcript_option_survives_apply():
    assert JarvisConfig(
        personal_learning_mode="apply", show_transcript=True
    ).show_transcript
    assert (
        JarvisConfig(
            personal_learning_mode="apply", show_transcript=False
        ).show_transcript
        is False
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text,quote,reason",
    [
        ("I own a City", "I have a City", "quote_not_found"),
        ("City City", "City", "quote_ambiguous"),
    ],
)
async def test_extractor_reports_proposed_fact_and_grounding_reason(
    caplog, text, quote, reason
):
    s = source(text)
    payload = {
        "candidates": [
            {
                "category": "owned_item",
                "intent": "new",
                "label": "City",
                "value": "City",
                "evidence": [{"turn_id": s.turn_id, "quote": quote}],
            }
        ]
    }
    client = SimpleNamespace(
        aio=SimpleNamespace(
            interactions=SimpleNamespace(
                create=AsyncMock(
                    return_value=SimpleNamespace(output_text=json.dumps(payload))
                )
            )
        )
    )
    a = LearningProviderAdapter("gemini", client, "model", diagnostics=True)
    with caplog.at_level(logging.INFO):
        assert not (await a.extract(s)).candidates
    rows = events(caplog)
    assert any(e["stage"] == "proposal" and e["fact"]["value"] == "City" for e in rows)
    assert any(
        e["outcome"] == "rejected"
        and e["reason"] == reason
        and e["turn_id"] == s.turn_id
        for e in rows
    )
    client.aio.interactions.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_memory_decisions_show_rejection_duplicate_and_actual_commit(
    learning, caplog
):
    from jarvis.memory.learning_contracts import EvidenceSpan, LearningCandidate

    mode = ["new"]

    async def extract(s):
        return LearningBatch(
            candidates=[
                LearningCandidate(
                    category="owned_item",
                    kind="vehicle",
                    intent="new",
                    label="City",
                    value="City",
                    state="owned",
                    qualification="hypothetical"
                    if mode[0] == "hypothetical"
                    else "direct",
                    evidence=[EvidenceSpan(turn_id=s.turn_id, start=8, end=12)],
                )
            ]
        )

    async def resolve(s, batch, catalog):
        return LearningResolutionBatch(
            resolutions=[
                LearningResolution(
                    candidate_index=0,
                    decision="duplicate" if mode[0] == "duplicate" else "new",
                    target_id=catalog.entries[0].assertion_id
                    if catalog.entries
                    else None,
                )
            ]
        )

    r = PersonalLearningRuntime(
        learning.authority,
        learning.service,
        SimpleNamespace(extract=extract),
        SimpleNamespace(resolve=resolve),
        LearningReconciler(
            learning.service.canonical_reader, learning.authority, diagnostics=True
        ),
        clock=lambda: 100,
        diagnostics=True,
    )

    async def run():
        c = ConversationSession()
        c.start()
        r.bind(c, learning.grant)(c.accept_turn(ConversationRole.USER, "I own a City"))
        await asyncio.wait_for(r.drain(), 3)

    try:
        with caplog.at_level(logging.INFO):
            mode[0] = "hypothetical"
            await run()
            assert await learning.count() == 0
            mode[0] = "new"
            await run()
            assert await learning.count() == 1
            mode[0] = "duplicate"
            await run()
            assert await learning.count() == 1
        rows = events(caplog)
        assert any(e.get("reason") == "not_direct_standard" for e in rows)
        assert any(e.get("reason") == "duplicate" for e in rows)
        saved = [
            e for e in rows if e["stage"] == "storage" and e["outcome"] == "committed"
        ]
        assert len(saved) == 1 and len(saved[0]["assertion_ids"]) == 1
        assert saved[0]["mutations"][0]["stored_value"]["value"] == "City"
    finally:
        await r.close()


@pytest.mark.asyncio
async def test_failure_reports_stage_without_exception_payload(learning, caplog):
    async def extract(s):
        raise RuntimeError("PRIVATE PROVIDER BODY")

    r = PersonalLearningRuntime(
        learning.authority,
        learning.service,
        SimpleNamespace(extract=extract),
        SimpleNamespace(),
        SimpleNamespace(),
        clock=lambda: 100,
        diagnostics=True,
    )
    c = ConversationSession()
    c.start()
    try:
        with caplog.at_level(logging.INFO):
            r.bind(c, learning.grant)(
                c.accept_turn(ConversationRole.USER, "I own a City")
            )
            await asyncio.wait_for(r.drain(), 3)
        assert any(
            e["stage"] == "extraction" and e["outcome"] == "failed"
            for e in events(caplog)
        )
        assert "PRIVATE PROVIDER BODY" not in caplog.text
    finally:
        await r.close()


def test_diagnostic_content_masks_credentials_but_keeps_everyday_text():
    from jarvis.memory.learning_diagnostics import content_for_log

    assert content_for_log("I own a City") == "I own a City"
    key = "AIza" + "a" * 35
    assert key not in content_for_log("Here is " + key)
    assert "abc123" not in content_for_log("my password is abc123")


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["denied", "exception"])
async def test_storage_failure_never_claims_a_save(
    learning, caplog, monkeypatch, status
):
    async def extract(s):
        from jarvis.memory.learning_contracts import EvidenceSpan, LearningCandidate

        return LearningBatch(
            candidates=[
                LearningCandidate(
                    category="owned_item",
                    kind="vehicle",
                    intent="new",
                    label="City",
                    value="City",
                    state="owned",
                    evidence=[EvidenceSpan(turn_id=s.turn_id, start=8, end=12)],
                )
            ]
        )

    async def resolve(*args):
        return LearningResolutionBatch(
            resolutions=[LearningResolution(candidate_index=0, decision="new")]
        )

    async def admit(*args):
        if status == "exception":
            raise RuntimeError("PROVIDER-SECRET-BODY")
        return LearningAdmissionResult("denied")

    monkeypatch.setattr(learning.service, "admit_learning", admit)
    r = PersonalLearningRuntime(
        learning.authority,
        learning.service,
        SimpleNamespace(extract=extract),
        SimpleNamespace(resolve=resolve),
        LearningReconciler(
            learning.service.canonical_reader, learning.authority, diagnostics=True
        ),
        clock=lambda: 100,
        diagnostics=True,
    )
    c = ConversationSession()
    c.start()
    try:
        with caplog.at_level(logging.INFO):
            r.bind(c, learning.grant)(
                c.accept_turn(ConversationRole.USER, "I own a City")
            )
            await asyncio.wait_for(r.drain(), 3)
        assert await learning.count() == 0
        assert not any(e["outcome"] == "committed" for e in events(caplog))
        assert any(
            e["stage"] == "storage"
            and e["outcome"] == ("failed" if status == "exception" else "denied")
            for e in events(caplog)
        )
        assert "PROVIDER-SECRET-BODY" not in caplog.text
    finally:
        await r.close()


@pytest.mark.asyncio
async def test_timeout_shows_stage_and_does_not_retry(learning, caplog, monkeypatch):
    import jarvis.memory.learning_runtime as module

    monkeypatch.setattr(module, "INFERENCE_TIMEOUT", 0.01)
    calls = []

    async def extract(s):
        calls.append(s)
        await asyncio.sleep(5)

    r = PersonalLearningRuntime(
        learning.authority,
        learning.service,
        SimpleNamespace(extract=extract),
        SimpleNamespace(),
        SimpleNamespace(),
        clock=lambda: 100,
        diagnostics=True,
    )
    c = ConversationSession()
    c.start()
    try:
        with caplog.at_level(logging.INFO):
            r.bind(c, learning.grant)(
                c.accept_turn(ConversationRole.USER, "I own a City")
            )
            await asyncio.wait_for(r.drain(), 3)
        assert len(calls) == 1
        assert any(
            e["stage"] == "extraction" and e["outcome"] == "timeout"
            for e in events(caplog)
        )
    finally:
        await r.close()


def test_content_masks_configured_credential_values_even_without_a_key_prefix(
    monkeypatch,
):
    from jarvis.memory.learning_diagnostics import content_for_log

    secret = "fictional-opaque-credential-123456"
    monkeypatch.setenv("EXA_API_KEY", secret)
    assert secret not in content_for_log("The value is " + secret)
    assert content_for_log("I own a City") == "I own a City"


@pytest.mark.parametrize(
    "credential",
    [
        "Authorization: Basic dXNlcjpwYXNz",
        "github_pat_" + "a" * 82,
    ],
)
def test_content_masks_additional_credential_formats(credential):
    from jarvis.memory.learning_diagnostics import content_for_log

    assert credential not in content_for_log(credential)
    assert "dXNlcjpwYXNz" not in content_for_log(credential)


@pytest.mark.asyncio
async def test_indices_map_proposal_to_grounded_to_eligible_candidate(learning, caplog):
    from jarvis.memory.learning_contracts import EvidenceSpan, LearningCandidate

    s = source()
    payload = {
        "candidates": [
            {
                "category": "owned_item",
                "kind": "vehicle",
                "intent": "new",
                "label": "City",
                "value": "City",
                "evidence": [{"turn_id": s.turn_id, "quote": quote}],
            }
            for quote in ["absent", s.text]
        ]
    }
    client = SimpleNamespace(
        aio=SimpleNamespace(
            interactions=SimpleNamespace(
                create=AsyncMock(
                    return_value=SimpleNamespace(output_text=json.dumps(payload))
                )
            )
        )
    )
    adapter = LearningProviderAdapter("gemini", client, "model", diagnostics=True)
    with caplog.at_level(logging.INFO):
        assert len((await adapter.extract(s)).candidates) == 1
    rows = events(caplog)
    assert any(
        e["stage"] == "grounding"
        and e["outcome"] == "rejected"
        and e["proposal_index"] == 0
        for e in rows
    )
    assert any(
        e["stage"] == "grounding"
        and e["outcome"] == "accepted"
        and e["proposal_index"] == 1
        and e["grounded_index"] == 0
        for e in rows
    )
    caplog.clear()

    async def extract(s):
        return LearningBatch(
            candidates=[
                LearningCandidate(
                    category="owned_item",
                    kind="vehicle",
                    intent="new",
                    label="City",
                    value="City",
                    state="owned",
                    qualification=q,
                    evidence=[EvidenceSpan(turn_id=s.turn_id, start=8, end=12)],
                )
                for q in ["hypothetical", "direct"]
            ]
        )

    async def resolve(*args):
        return LearningResolutionBatch(
            resolutions=[LearningResolution(candidate_index=0, decision="new")]
        )

    r = PersonalLearningRuntime(
        learning.authority,
        learning.service,
        SimpleNamespace(extract=extract),
        SimpleNamespace(resolve=resolve),
        LearningReconciler(
            learning.service.canonical_reader, learning.authority, diagnostics=True
        ),
        clock=lambda: 100,
        diagnostics=True,
    )
    c = ConversationSession()
    c.start()
    try:
        with caplog.at_level(logging.INFO):
            r.bind(c, learning.grant)(
                c.accept_turn(ConversationRole.USER, "I own a City")
            )
            await asyncio.wait_for(r.drain(), 3)
        eligible = [e for e in events(caplog) if e["stage"] == "eligibility"]
        assert (
            eligible[0]["grounded_index"] == 0
            and eligible[0]["candidate_index"] is None
        )
        assert (
            eligible[1]["grounded_index"] == 1 and eligible[1]["candidate_index"] == 0
        )
        assert await learning.count() == 1
    finally:
        await r.close()


def test_diagnostic_structured_fields_retain_credential_key_masking():
    from jarvis.memory.learning_diagnostics import content_for_log

    assert "opaque-demo-value" not in str(
        content_for_log({"api_key": "opaque-demo-value"})
    )


def test_plain_basic_description_is_not_masked():
    from jarvis.memory.learning_diagnostics import content_for_log

    text = "I prefer basic explanations"
    assert content_for_log(text) == text
