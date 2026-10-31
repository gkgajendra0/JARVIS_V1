import asyncio
import json
import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest


def load_probe():
    return runpy.run_path(
        str(Path(__file__).parents[1] / "tools/project_memory_failure_probe.py")
    )


def test_probe_reports_only_shape_and_preserves_failed_call_and_exception():
    probe = load_probe()
    rows = []
    failure = ValueError("one memory tool or answer per model step required")

    class Provider:
        calls = 0

        async def step(self, *args, **kwargs):
            self.calls += 1
            return SimpleNamespace(
                parsed=SimpleNamespace(
                    answer="PRIVATE_ANSWER",
                    search_query="PRIVATE_QUERY",
                    source_ids=[],
                    personal_requests=[],
                )
            )

    class Coordinator:
        async def respond(self, provider):
            await provider.step(operation_id="reply-0")
            raise failure

    original_step, original_respond = Provider.step, Coordinator.respond
    provider = Provider()
    with (
        probe["trace_calls"](Provider, Coordinator, emit=rows.append),
        pytest.raises(ValueError) as caught,
    ):
        asyncio.run(Coordinator().respond(provider))
    assert caught.value is failure
    assert provider.calls == 1
    assert Provider.step is original_step and Coordinator.respond is original_respond
    step = json.loads(rows[0].split(" ", 1)[1])
    assert step == {
        "answer_present": True,
        "search_present": True,
        "source_count": 0,
        "personal_count": 0,
        "action_count": 1,
    }
    error = json.loads(rows[1].split(" ", 1)[1])
    assert error["reason"] == "mixed_answer_or_tools"
    assert error["frames"][-1]["function"] == "respond"
    assert "PRIVATE_" not in "\n".join(rows)


def test_probe_never_prints_unknown_exception_message_or_frame_locals():
    probe = load_probe()
    rows = []

    class Provider:
        async def step(self):
            secret = "PRIVATE_API_KEY"
            raise ValueError(secret)

    class Coordinator:
        async def respond(self):
            return await Provider().step()

    with (
        probe["trace_calls"](Provider, Coordinator, emit=rows.append),
        pytest.raises(ValueError, match="PRIVATE_API_KEY"),
    ):
        asyncio.run(Coordinator().respond())
    report = json.loads(rows[-1].split(" ", 1)[1])
    assert report["reason"] == "unclassified"
    assert report["error"] == "ValueError"
    assert report["frames"][-1]["function"] == "step"
    assert "PRIVATE_" not in "\n".join(rows)


def test_probe_preserves_success_without_retries():
    probe = load_probe()
    rows = []
    result = object()

    class Provider:
        async def step(self):
            return SimpleNamespace(
                parsed=SimpleNamespace(
                    answer="PRIVATE_ANSWER",
                    search_query=None,
                    source_ids=[],
                    personal_requests=[],
                )
            )

    class Coordinator:
        async def respond(self):
            await Provider().step()
            return result

    with probe["trace_calls"](Provider, Coordinator, emit=rows.append):
        assert asyncio.run(Coordinator().respond()) is result
    assert len(rows) == 1 and "PRIVATE_" not in rows[0]


def test_probe_requires_resuming_existing_lab(monkeypatch):
    probe = load_probe()
    monkeypatch.setattr("sys.argv", ["probe.py"])
    with pytest.raises(SystemExit, match="requires --resume-lab"):
        probe["main"]()


def test_broken_diagnostic_output_never_changes_result_or_original_failure():
    probe = load_probe()
    result = object()
    failure = ValueError("PRIVATE_ORIGINAL_ERROR")

    def broken_output(_):
        raise BrokenPipeError("PRIVATE_OUTPUT_ERROR")

    class Provider:
        async def step(self):
            return SimpleNamespace(
                parsed=SimpleNamespace(
                    answer="PRIVATE_ANSWER",
                    search_query=None,
                    source_ids=[],
                    personal_requests=[],
                )
            )

    class Coordinator:
        async def respond(self, *, fail=False):
            await Provider().step()
            if fail:
                raise failure
            return result

    with probe["trace_calls"](Provider, Coordinator, emit=broken_output):
        assert asyncio.run(Coordinator().respond()) is result
        with pytest.raises(ValueError) as caught:
            asyncio.run(Coordinator().respond(fail=True))
        assert caught.value is failure
