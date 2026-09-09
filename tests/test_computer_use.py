from __future__ import annotations

from types import SimpleNamespace

import pytest

from jarvis.computer import (
    ActionExecutionResult,
    ComputerUseService,
    ComputerUseStatus,
    GeminiComputerUseProvider,
    OpenAIComputerUseProvider,
    ScreenFrame,
)


class FakeExecutor:
    def __init__(self) -> None:
        self.frame = ScreenFrame(
            png_bytes=b"fake-png",
            left=-1920,
            top=0,
            width=3840,
            height=1080,
        )
        self.actions = []
        self.captures = 0

    def capture_screen(self) -> ScreenFrame:
        self.captures += 1
        return self.frame

    def execute(self, action):
        self.actions.append(action)
        return ActionExecutionResult(ok=True, detail=f"executed:{action.name}")


class QueueInteractions:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


class FakeGeminiClient:
    def __init__(self, responses):
        self.interactions = QueueInteractions(responses)


class QueueResponses:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


class FakeOpenAIClient:
    def __init__(self, responses):
        self.responses = QueueResponses(responses)


def model_output(text: str):
    return SimpleNamespace(
        type="model_output",
        content=[SimpleNamespace(type="text", text=text)],
    )


def test_screen_frame_resolves_multimonitor_coordinates() -> None:
    frame = ScreenFrame(
        png_bytes=b"x",
        left=-1920,
        top=-100,
        width=3840,
        height=1080,
    )

    assert frame.normalized_to_desktop(500, 500) == (0, 440)
    assert frame.pixel_to_desktop(1920, 100) == (0, 0)


@pytest.mark.asyncio
async def test_gemini_executes_normalized_desktop_action_and_returns_summary() -> None:
    first = SimpleNamespace(
        id="interaction-1",
        steps=[
            SimpleNamespace(
                type="function_call",
                name="click",
                id="call-1",
                arguments={"x": 500, "y": 500, "intent": "open target"},
            )
        ],
    )
    second = SimpleNamespace(
        id="interaction-2",
        steps=[model_output("Done.")],
    )
    client = FakeGeminiClient([first, second])
    provider = GeminiComputerUseProvider(client=client)
    executor = FakeExecutor()

    result = await provider.execute("Open the target", executor=executor, max_steps=4)

    assert result.status is ComputerUseStatus.COMPLETED
    assert result.summary == "Done."
    assert result.steps == 1
    assert len(executor.actions) == 1
    assert executor.actions[0].name == "click"
    assert executor.actions[0].arguments["x"] == 0
    assert executor.actions[0].arguments["y"] == 540
    assert client.interactions.calls[0]["tools"][0]["environment"] == "desktop"
    assert (
        client.interactions.calls[0]["tools"][0]["enable_prompt_injection_detection"]
        is True
    )
    assert client.interactions.calls[1]["previous_interaction_id"] == "interaction-1"
    assert client.interactions.calls[1]["input"][0]["type"] == "function_result"


@pytest.mark.asyncio
async def test_gemini_never_executes_provider_confirmation_checkpoint() -> None:
    interaction = SimpleNamespace(
        id="interaction-1",
        steps=[
            SimpleNamespace(
                type="function_call",
                name="click",
                id="call-1",
                arguments={
                    "x": 1,
                    "y": 1,
                    "safety_decision": {
                        "decision": "require_confirmation",
                        "explanation": "Sensitive action",
                    },
                },
            )
        ],
    )
    provider = GeminiComputerUseProvider(
        client=FakeGeminiClient([interaction]),
    )
    executor = FakeExecutor()

    result = await provider.execute("Do something", executor=executor, max_steps=4)

    assert result.status is ComputerUseStatus.CONFIRMATION_REQUIRED
    assert result.safety_message == "Sensitive action"
    assert executor.actions == []


@pytest.mark.asyncio
async def test_openai_executes_pixel_action_and_returns_summary() -> None:
    first = SimpleNamespace(
        id="response-1",
        output=[
            SimpleNamespace(
                type="computer_call",
                call_id="call-1",
                pending_safety_checks=[],
                action=SimpleNamespace(
                    type="click",
                    x=1920,
                    y=540,
                    button="left",
                    keys=None,
                ),
                actions=None,
            )
        ],
        output_text="",
    )
    second = SimpleNamespace(id="response-2", output=[], output_text="Done.")
    client = FakeOpenAIClient([first, second])
    provider = OpenAIComputerUseProvider(client=client)
    executor = FakeExecutor()

    result = await provider.execute("Click it", executor=executor, max_steps=4)

    assert result.status is ComputerUseStatus.COMPLETED
    assert result.summary == "Done."
    assert result.steps == 1
    assert executor.actions[0].name == "click"
    assert executor.actions[0].arguments["x"] == 0
    assert executor.actions[0].arguments["y"] == 540
    assert client.responses.calls[0]["tools"] == [{"type": "computer"}]
    assert client.responses.calls[1]["previous_response_id"] == "response-1"
    output = client.responses.calls[1]["input"][0]
    assert output["type"] == "computer_call_output"
    assert output["call_id"] == "call-1"
    assert output["output"]["type"] == "computer_screenshot"


@pytest.mark.asyncio
async def test_openai_never_acknowledges_pending_safety_check() -> None:
    first = SimpleNamespace(
        id="response-1",
        output=[
            SimpleNamespace(
                type="computer_call",
                call_id="call-1",
                pending_safety_checks=[SimpleNamespace(message="Confirmation needed")],
                action=SimpleNamespace(
                    type="click",
                    x=1,
                    y=1,
                    button="left",
                ),
                actions=None,
            )
        ],
        output_text="",
    )
    provider = OpenAIComputerUseProvider(client=FakeOpenAIClient([first]))
    executor = FakeExecutor()

    result = await provider.execute("Click it", executor=executor, max_steps=4)

    assert result.status is ComputerUseStatus.CONFIRMATION_REQUIRED
    assert result.safety_message == "Confirmation needed"
    assert executor.actions == []


class ExplodingProvider:
    provider_name = "fake"
    model_name = "fake-model"

    async def execute(self, task, *, executor, max_steps):
        raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_service_returns_truthful_failure() -> None:
    service = ComputerUseService(
        provider=ExplodingProvider(),
        executor=FakeExecutor(),
        max_steps=2,
    )

    result = await service.execute("test")

    assert result.status is ComputerUseStatus.FAILED
    assert result.ok is False
    assert "RuntimeError: boom" == result.reason


@pytest.mark.asyncio
async def test_service_rejects_empty_or_unbounded_tasks() -> None:
    service = ComputerUseService(
        provider=ExplodingProvider(),
        executor=FakeExecutor(),
        max_steps=2,
    )

    with pytest.raises(ValueError, match="must not be empty"):
        await service.execute(" ")
    with pytest.raises(ValueError, match="bounded input"):
        await service.execute("x" * 4001)
