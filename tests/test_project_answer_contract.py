import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from jarvis.voice.project_answer_provider import (
    ProjectAnswerProvider,
    ProjectAnswerStep,
)


@pytest.mark.parametrize(
    "payload",
    [
        {"answer": "Interview is on Monday.", "source_ids": ["saved-turn"]},
        {"answer": "Draft", "search_query": "interview"},
        {"response": {"answer": "Draft", "source_ids": ["saved-turn"]}},
        {"response": {"search_query": "interview", "source_ids": ["saved-turn"]}},
        {},
        {"response": {}},
        {"response": {"answer": ""}},
        {"response": {"answer": "   "}},
        {"response": {"search_query": ""}},
        {"response": {"source_ids": []}},
        {"response": {"personal_requests": []}},
    ],
)
def test_contract_rejects_mixed_or_empty_steps(payload):
    with pytest.raises(ValidationError):
        ProjectAnswerStep.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize(
    "payload,expected",
    [
        (
            {"answer": "Interview is on Monday."},
            ("Interview is on Monday.", None, [], []),
        ),
        ({"search_query": "interview"}, ("", "interview", [], [])),
        ({"source_ids": ["saved-turn"]}, ("", None, ["saved-turn"], [])),
        (
            {"personal_requests": [{"scope_key": "owned_item.vehicle"}]},
            ("", None, [], ["owned_item.vehicle"]),
        ),
    ],
)
def test_each_wire_variant_yields_exactly_one_coordinator_action(payload, expected):
    step = ProjectAnswerStep.model_validate_json(json.dumps({"response": payload}))
    actual = (
        step.answer,
        step.search_query,
        step.source_ids,
        [r.scope_key for r in step.personal_requests],
    )
    assert actual == expected


@pytest.mark.asyncio
async def test_real_gemini_adapter_receives_closed_variant_schema_and_parses_reply():
    from jarvis.hands.provider_adapters import GeminiStructuredOutputClient

    requests = []

    class Endpoint:
        async def create(self, **kwargs):
            requests.append(kwargs)
            return SimpleNamespace(
                output_text='{"response":{"answer":"Monday."}}', usage={}
            )

    sdk = GeminiStructuredOutputClient(
        client=SimpleNamespace(aio=SimpleNamespace(interactions=Endpoint())),
        model="existing-configured-model",
    )

    class Router:
        async def parse_with_telemetry(self, **kwargs):
            await kwargs["before_dispatch"]()
            return await sdk.parse_with_telemetry(
                **{
                    k: kwargs[k]
                    for k in ("system_prompt", "input_payload", "response_model")
                }
            )

    packet = SimpleNamespace(
        request_id="request", revision="revision", context="saved context"
    )
    result = await ProjectAnswerProvider(Router()).step(
        packet, question="When?", check=lambda: True, operation_id="reply-0"
    )
    assert result.parsed.answer == "Monday."
    assert len(requests) == 1
    schema = requests[0]["response_format"]["schema"]
    assert (
        schema["required"] == ["response"] and schema["additionalProperties"] is False
    )
    choices = schema["properties"]["response"]["anyOf"]
    variants = [schema["$defs"][c["$ref"].rsplit("/", 1)[-1]] for c in choices]
    assert {tuple(v["required"]) for v in variants} == {
        ("answer",),
        ("search_query",),
        ("source_ids",),
        ("personal_requests",),
    }
    assert all(
        v["additionalProperties"] is False and len(v["properties"]) == 1
        for v in variants
    )
    assert requests[0]["store"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"answer": "Monday.", "source_ids": ["turn-id"]},
        {"response": {"answer": "Monday.", "source_ids": ["turn-id"]}},
    ],
)
async def test_real_adapter_rejects_observed_mixture_without_retry(payload):
    from jarvis.hands.provider_adapters import (
        GeminiStructuredOutputClient,
        StructuredOutputError,
    )

    requests = []

    class Endpoint:
        async def create(self, **kwargs):
            requests.append(kwargs)
            return SimpleNamespace(output_text=json.dumps(payload), usage={})

    sdk = GeminiStructuredOutputClient(
        client=SimpleNamespace(aio=SimpleNamespace(interactions=Endpoint())),
        model="existing-configured-model",
    )
    with pytest.raises(StructuredOutputError):
        await sdk.parse_with_telemetry(
            system_prompt="answer", input_payload={}, response_model=ProjectAnswerStep
        )
    assert len(requests) == 1
