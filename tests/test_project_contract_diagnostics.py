import json
from types import SimpleNamespace

import pytest

from jarvis.hands.provider_adapters import (
    GeminiStructuredOutputClient,
    StructuredOutputError,
)
from jarvis.voice.project_answer_provider import ProjectAnswerStep
from jarvis.voice.project_contract_diagnostics import (
    DevelopmentCaseFailure,
    observe_contract_failures,
)


def client_for(text):
    calls = []

    class Endpoint:
        async def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(output_text=text, usage={})

    return GeminiStructuredOutputClient(
        client=SimpleNamespace(aio=SimpleNamespace(interactions=Endpoint())),
        model="configured-model",
    ), calls


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text,reason,target_type",
    [
        (
            '{"response":{"personal_requests":[{"scope_key":"food_preference","target_quote":null}]}}',
            "validation_failed",
            "null",
        ),
        (
            '{"response":{"personal_requests":[{"scope_key":"food_preference","target_quote":"PRIVATE_TARGET"}]}}',
            "validation_failed",
            "string",
        ),
        ('{"PRIVATE_FIELD":"PRIVATE_VALUE"}', "validation_failed", None),
        ("PRIVATE_NOT_JSON", "validation_failed", None),
        ("", "missing_output", None),
    ],
)
async def test_observer_reports_safe_shape_before_routed_boundary_and_restores(
    text, reason, target_type
):
    client, calls = client_for(text)
    original = GeminiStructuredOutputClient.parse_with_telemetry
    emitted = []
    with (
        observe_contract_failures(emit=emitted.append) as observations,
        pytest.raises(StructuredOutputError),
    ):
        await client.parse_with_telemetry(
            system_prompt="PRIVATE_PROMPT",
            input_payload={},
            response_model=ProjectAnswerStep,
        )
    assert len(calls) == len(observations) == len(emitted) == 1
    assert observations[0]["reason"] == reason
    if target_type is not None:
        assert observations[0]["personal_target_types"] == [target_type]
        assert observations[0]["personal_scope_keys"] == ["food_preference"]
    assert "PRIVATE" not in json.dumps(observations) + "".join(emitted)
    assert GeminiStructuredOutputClient.parse_with_telemetry is original


@pytest.mark.asyncio
async def test_observer_preserves_success_and_exception_identity_when_output_breaks():
    client, calls = client_for('{"response":{"answer":"PRIVATE_ANSWER"}}')
    failure = StructuredOutputError("PRIVATE_FAILURE")

    def broken(_):
        raise BrokenPipeError("PRIVATE_OUTPUT")

    with observe_contract_failures(emit=broken) as observations:
        success = await client.parse_with_telemetry(
            system_prompt="test", input_payload={}, response_model=ProjectAnswerStep
        )
        assert success.parsed.answer == "PRIVATE_ANSWER" and not observations
    assert len(calls) == 1

    class Adapter:
        async def parse_with_telemetry(self, **kwargs):
            raise failure

    original = Adapter.parse_with_telemetry
    with (
        observe_contract_failures(adapter_type=Adapter, emit=broken) as observations,
        pytest.raises(StructuredOutputError) as caught,
    ):
        await Adapter().parse_with_telemetry()
    assert caught.value is failure
    assert len(observations) == 1
    assert Adapter.parse_with_telemetry is original


def test_terminal_case_failure_keeps_stage_normalized_kind_and_no_exception_message(
    tmp_path,
):
    from pathlib import Path

    from jarvis.model_routing.invoker import RoutedInferenceFailure
    from jarvis.provider_resilience import ProviderFailure, ProviderFailureKind
    from jarvis.voice.project_memory_development import (
        load_cases,
        run_development_batch,
    )

    failure = RoutedInferenceFailure(
        ProviderFailure("gemini", ProviderFailureKind.RESPONSE_CONTRACT_INVALID)
    )
    coordinator = SimpleNamespace(
        diagnostics=lambda: {"stage": "generating", "request_id": "unused"}
    )
    cases = load_cases(Path(__file__).resolve().parents[1])[-1:]

    def run(case, root):
        raise DevelopmentCaseFailure(
            failure, coordinator, [{"reason": "validation_failed"}]
        )

    summary = run_development_batch(
        tmp_path / "batch", cases, run, source_commit="a" * 40, model="configured-model"
    )
    row = json.loads((tmp_path / "batch/results.jsonl").read_text())
    assert summary["failed"] == 1
    assert row["error"] == "RoutedInferenceFailure" and row["stage"] == "generating"
    assert row["routing_failure_kind"] == "response_contract_invalid"
    assert row["contract_observations"] == [{"reason": "validation_failed"}]
    assert row["usage"] is None
