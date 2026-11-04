import json
from types import SimpleNamespace

import pytest

from jarvis.voice.project_stage_observation import observe_stages, tool_outcomes


@pytest.mark.asyncio
async def test_nested_observation_preserves_results_errors_privacy_and_restoration():
    ticks = iter([0, 1, 2, 3, 5, 6, 7])
    failure = ValueError("PRIVATE_ERROR")
    returned = object()

    class Operations:
        def inner(self):
            return returned

        async def outer(self, *, fail=False):
            assert self.inner() is returned
            if fail:
                raise failure
            return returned

    originals = (Operations.inner, Operations.outer)
    with observe_stages(
        [(Operations, "outer", "prepare", True), (Operations, "inner", "hello", False)],
        clock=lambda: next(ticks),
    ) as rows:
        assert await Operations().outer() is returned
    assert (Operations.inner, Operations.outer) == originals
    assert rows[1] == {
        "stage": "hello",
        "start_ms": 2000,
        "duration_ms": 1000,
        "outcome": "returned",
    }
    assert rows[0]["stage"] == "prepare" and rows[0]["duration_ms"] == 4000
    with (
        observe_stages([(Operations, "outer", "prepare", True)]) as failed,
        pytest.raises(ValueError) as caught,
    ):
        await Operations().outer(fail=True)
    assert caught.value is failure and failed[0]["outcome"] == "raised"
    assert "PRIVATE" not in json.dumps(rows + failed)
    assert (Operations.inner, Operations.outer) == originals


def test_actual_tool_statuses_are_distinct_and_source_values_are_never_exposed():
    context = json.dumps(
        {
            "personal": {"status": "denied", "facts": ["PRIVATE_FACT"]},
            "retrieval": [
                {"tool": "personal", "status": "denied", "source_ids": []},
                {"tool": "search", "status": "no_match", "source_ids": []},
                {
                    "tool": "PRIVATE_TOOL",
                    "status": "PRIVATE_STATUS",
                    "source_ids": ["PRIVATE_ID"],
                },
            ],
        }
    )
    result = tool_outcomes(context)
    assert result["personal_status"] == "denied"
    assert result["tools"][:2] == [
        {"tool": "personal", "status": "denied", "source_count": 0},
        {"tool": "search", "status": "no_match", "source_count": 0},
    ]
    assert "PRIVATE" not in json.dumps(result)
    assert tool_outcomes(None) == {"personal_status": "unobserved", "tools": []}


def test_hello_return_is_not_equated_with_verified_and_private_errors_are_hidden():
    class Approval:
        def verify(self):
            return SimpleNamespace(status=SimpleNamespace(value="canceled"))

        def authorize(self, text):
            raise RuntimeError(text)

    with observe_stages(
        [
            (Approval, "verify", "hello_verification", False),
            (Approval, "authorize", "fresh_owner_authorization", False),
        ]
    ) as rows:
        Approval().verify()
        with pytest.raises(RuntimeError):
            Approval().authorize(
                "strong owner verification was not granted: user_canceled"
            )
        with pytest.raises(RuntimeError):
            Approval().authorize("PRIVATE_ERROR")
    assert rows[0]["verification_status"] == "canceled"
    assert rows[1]["authorization_reason"] == "user_canceled"
    assert rows[2]["authorization_reason"] == "unclassified"
    assert "PRIVATE" not in json.dumps(rows)


def test_inflight_worker_is_explicit_and_failed_report_is_a_frozen_snapshot():
    from concurrent.futures import ThreadPoolExecutor
    from contextvars import copy_context
    from threading import Event

    from jarvis.voice.project_contract_diagnostics import DevelopmentCaseFailure

    entered, release = Event(), Event()

    class Worker:
        def run(self):
            entered.set()
            assert release.wait(2)

    with (
        ThreadPoolExecutor(1) as executor,
        observe_stages([(Worker, "run", "hello_verification", False)]) as rows,
    ):
        future = executor.submit(copy_context().run, Worker().run)
        try:
            assert entered.wait(2)
            co = SimpleNamespace(
                _lab_stage_spans=rows, diagnostics=lambda: {"stage": "generating"}
            )
            report = DevelopmentCaseFailure(RuntimeError("PRIVATE"), co, []).report
            assert report["stage_spans"][0]["outcome"] == "running"
            assert report["stage_spans"][0]["duration_ms"] is None
            assert report["stage_spans_incomplete"] is True
        finally:
            release.set()
        future.result(2)
    assert rows[0]["outcome"] == "returned"
    assert report["stage_spans"][0]["outcome"] == "running"


def test_unrelated_execution_context_is_not_attributed_to_this_case():
    from contextvars import Context

    class Work:
        def run(self):
            return "ok"

    with observe_stages([(Work, "run", "hello", False)]) as rows:
        assert Context().run(Work().run) == "ok"
        assert rows == []
        assert Work().run() == "ok"
    assert len(rows) == 1
