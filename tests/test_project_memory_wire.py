import json
from types import SimpleNamespace

import pytest

from jarvis.voice.project_answer_provider import ProjectAnswerProvider


@pytest.mark.asyncio
async def test_context_reaches_real_adapter_as_lossless_object_without_nested_json_escaping():
    from jarvis.hands.provider_adapters import GeminiStructuredOutputClient

    sent = []

    class Endpoint:
        async def create(self, **kwargs):
            sent.append(kwargs["input"])
            return SimpleNamespace(
                output_text='{"response":{"answer":"Approved."}}', usage={}
            )

    sdk = GeminiStructuredOutputClient(
        client=SimpleNamespace(aio=SimpleNamespace(interactions=Endpoint())),
        model="configured-model",
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

    evidence = {
        "project_id": "p",
        "thread_id": "t",
        "coverage": "partial",
        "sources": [
            {
                "source_id": "original",
                "role": "user",
                "text": 'नेपाल trip: "permit approved". Keep literal \\ path.',
            }
        ],
        "omitted_source_ids": ["older"],
        "personal": {"status": "not_requested", "facts": []},
    }
    context = json.dumps(evidence, ensure_ascii=False, separators=(",", ":"))
    packet = SimpleNamespace(request_id="r", revision="hash", context=context)
    await ProjectAnswerProvider(Router()).step(
        packet,
        question="What did I decide?",
        check=lambda: True,
        operation_id="reply-0",
        available_tools={
            "search_available": True,
            "read_source_ids": [],
            "personal_available": True,
            "remaining_steps": 4,
        },
    )
    payload = json.loads(sent[0])
    assert payload["context"] == evidence
    legacy = {**payload, "context": context}
    assert len(sent[0].encode()) < len(
        json.dumps(legacy, ensure_ascii=False, sort_keys=True, default=str).encode()
    )
    assert len(sent) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("context", ["not JSON", "[]", "null", '"plain string"'])
async def test_invalid_context_never_reaches_provider(context):
    class NoDispatch:
        calls = 0

        async def parse_with_telemetry(self, **kwargs):
            self.calls += 1

    client = NoDispatch()
    packet = SimpleNamespace(request_id="r", revision="h", context=context)
    with pytest.raises(ValueError):
        await ProjectAnswerProvider(client).step(
            packet,
            question="question",
            check=lambda: True,
            operation_id="reply-0",
            available_tools={
                "search_available": True,
                "read_source_ids": [],
                "personal_available": True,
                "remaining_steps": 4,
            },
        )
    assert client.calls == 0
