from __future__ import annotations

from types import SimpleNamespace

import pytest

from jarvis.work.prompt_compression import (
    LLMLingua2WorkPayloadCompressor,
    PromptCompressionError,
)


class _Engine:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict[str, object]]] = []

    def compress_prompt(self, context: list[str], **kwargs):
        self.calls.append((list(context), dict(kwargs)))
        compressed = [f"compressed {index}" for index, _value in enumerate(context)]
        return {
            "compressed_prompt_list": compressed,
            "origin_tokens": 100,
            "compressed_tokens": 25,
        }


def _payload() -> dict:
    return {
        "work": {
            "work_id": "work-123",
            "type": "research",
            "request": "Preserve this owner request exactly.",
            "state": "running",
            "status_detail": None,
        },
        "purpose": "choose the next bounded step",
        "allowed_actions": [
            {
                "name": "acq_record_candidate",
                "description": "x" * 2000,
                "parameter_schema": {
                    "type": "object",
                    "properties": {"source_version": {"type": "string"}},
                },
            }
        ],
        "recent_steps": [
            {
                "step_id": "step-1",
                "kind": "research_web",
                "summary": "short step summary",
                "state": "completed",
                "input": {"query": "official sdk 2.4.1"},
                "observation": {
                    "summary": "A" * 2000,
                    "text": "def exact_source_code():\n    return 'do not compress'\n"
                    * 100,
                    "evidence_refs": ["evidence-2", "evidence-4"],
                },
                "error": None,
            }
        ],
        "evidence": [
            {
                "summary": "B" * 1800,
                "source_identity": "example-device-sdk",
                "source_version": "2.4.1",
            }
        ],
    }


def test_llmlingua_payload_compression_preserves_structure_and_protected_values() -> (
    None
):
    engine = _Engine()
    payload = _payload()
    compressor = LLMLingua2WorkPayloadCompressor(
        min_string_chars=600,
        engine_factory=lambda: engine,
    )

    result = compressor.compress_payload(payload)

    assert result.reduced is True
    assert result.candidate_strings == 2
    assert result.compressed_strings == 2
    assert result.changed_paths == (
        "recent_steps[0].observation.summary",
        "evidence[0].summary",
    )
    assert result.payload["work"] == payload["work"]
    assert result.payload["purpose"] == payload["purpose"]
    assert result.payload["allowed_actions"] == payload["allowed_actions"]
    assert (
        result.payload["recent_steps"][0]["observation"]["text"]
        == payload["recent_steps"][0]["observation"]["text"]
    )
    assert result.payload["recent_steps"][0]["observation"]["evidence_refs"] == [
        "evidence-2",
        "evidence-4",
    ]
    assert result.payload["evidence"][0]["source_identity"] == "example-device-sdk"
    assert result.payload["evidence"][0]["source_version"] == "2.4.1"
    assert len(engine.calls) == 1
    _context, kwargs = engine.calls[0]
    assert kwargs["use_context_level_filter"] is False
    assert kwargs["use_token_level_filter"] is True
    assert kwargs["force_reserve_digit"] is True


def test_llmlingua_payload_compression_does_not_load_engine_without_candidates() -> (
    None
):
    calls = 0

    def _factory():
        nonlocal calls
        calls += 1
        return _Engine()

    compressor = LLMLingua2WorkPayloadCompressor(
        min_string_chars=600,
        engine_factory=_factory,
    )

    result = compressor.compress_payload(
        {
            "work": {"request": "short"},
            "recent_steps": [{"observation": {"summary": "also short"}}],
        }
    )

    assert result.reduced is False
    assert result.candidate_strings == 0
    assert calls == 0


def test_llmlingua_payload_compression_keeps_larger_replacements_original() -> None:
    class _Larger:
        def compress_prompt(self, context, **_kwargs):
            return {
                "compressed_prompt_list": [value + ("x" * 100) for value in context],
                "origin_tokens": 10,
                "compressed_tokens": 12,
            }

    payload = _payload()
    compressor = LLMLingua2WorkPayloadCompressor(
        engine_factory=_Larger,
    )

    result = compressor.compress_payload(payload)

    assert result.reduced is False
    assert result.compressed_strings == 0
    assert result.payload == payload


def test_llmlingua_payload_compression_rejects_malformed_batch_shape() -> None:
    class _Malformed:
        def compress_prompt(self, _context, **_kwargs):
            return {"compressed_prompt_list": []}

    compressor = LLMLingua2WorkPayloadCompressor(
        engine_factory=_Malformed,
    )

    with pytest.raises(PromptCompressionError, match="compressed_prompt_list"):
        compressor.compress_payload(_payload())


@pytest.mark.asyncio
async def test_reasoner_payload_override_is_explicit_and_decision_stays_validated() -> (
    None
):
    from jarvis.work.brain import BrainAction, BrainRequest
    from jarvis.work.models import WorkItem, WorkType
    from jarvis.work.reasoner import (
        _WorkDecisionModel,
        evaluate_structured_work_request,
    )

    work = WorkItem(
        request="Inspect research evidence.",
        work_type=WorkType.RESEARCH,
        source_session_id="session",
        source_turn_id="turn",
    )
    request = BrainRequest(
        work=work,
        recent_steps=(),
        purpose="choose the next bounded step",
        allowed_actions=(
            BrainAction(
                name="research_web",
                description="Research one bounded query",
                parameter_schema={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                },
            ),
        ),
    )
    override = {"compressed": "payload"}

    class _Client:
        async def parse_with_telemetry(self, **kwargs):
            assert kwargs["input_payload"] is override
            return SimpleNamespace(
                parsed=_WorkDecisionModel(
                    action="research_web",
                    summary="Research the exact source.",
                    parameters_json='{"query":"official source"}',
                    goal_complete=False,
                    needs_owner=False,
                    owner_question=None,
                ),
                usage={},
                usage_observed=False,
                latency_ms=1.0,
            )

    decision, telemetry = await evaluate_structured_work_request(
        _Client(),
        request,
        provider_payload_override=override,
    )

    assert decision.action == "research_web"
    assert decision.parameters == {"query": "official source"}
    assert telemetry.latency_ms == 1.0
