"""Lab-only Paid lane: durable shared USD 1 budget (owner approval 2026-11-23).

Offline only: every provider here is a fake; no request leaves the process.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
import types

import pytest
from pydantic import BaseModel

from jarvis.voice import paid_acceptance_budget as paid
from jarvis.voice.paid_acceptance_budget import (
    BudgetedGeminiClient,
    PaidBudgetExhausted,
    PaidBudgetHalted,
    PaidBudgetLedger,
    learning_call_path,
)

# -- fakes ---------------------------------------------------------------------


class ServerError(Exception):
    def __init__(self, code):
        super().__init__(f"HTTP {code}")
        self.code = code
        self.status_code = code


class Usage:
    def __init__(self, inp=3000, out=200, thoughts=0, total=None):
        self.total_input_tokens = inp
        self.total_output_tokens = out
        self.total_thought_tokens = thoughts
        self.total_tokens = inp + out + thoughts if total is None else total
        self.total_cached_tokens = 0
        self.total_tool_use_tokens = 0


class Response:
    def __init__(self, text, usage=None):
        self.output_text = text
        self.usage = usage


class FakeInteractions:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.sdk_configuration = types.SimpleNamespace(retry_config=object())

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        if item == "stall":
            await asyncio.sleep(3600)
        return item


class FakeGenai:
    def __init__(self, script, api_key="paid-test"):
        self.api_key = api_key
        self.aio = types.SimpleNamespace(interactions=FakeInteractions(script))


def _ledger(tmp_path):
    return PaidBudgetLedger(tmp_path / "shared" / "paid-ledger.sqlite3")


def _budgeted(ledger, script, classify=paid.answer_call_path):
    inner = FakeGenai(script)
    return inner, BudgetedGeminiClient(inner, ledger, lab="lab-9", classify=classify)


def _request(client, max_output_tokens=2048):
    return client.aio.interactions.create(
        model="gemini-3.5-flash-lite",
        input='{"q": 1}',
        system_instruction="fictional",
        response_format={"type": "text"},
        generation_config={"max_output_tokens": max_output_tokens},
    )


def _rows(ledger):
    db = sqlite3.connect(ledger.path)
    try:
        return db.execute(
            "SELECT call_path, status, reserved_micro_usd, charged_micro_usd"
            " FROM request ORDER BY seq"
        ).fetchall()
    finally:
        db.close()


# -- pricing and bounds -----------------------------------------------------------


def test_worst_case_reservation_bounds_input_bytes_and_output_with_thinking():
    # Google: max_output_tokens is the combined total of thinking and output.
    input_bound, output_bound, cost = paid.worst_case(10_000, 2048)
    assert input_bound == 10_000 + paid.INPUT_OVERHEAD_TOKENS
    assert output_bound == 2048
    expected = input_bound * 0.30 + output_bound * 2.50  # micro-USD
    assert cost >= expected and cost - expected < 2


def test_usage_cost_never_undercounts_thinking_and_unknown_is_none():
    assert paid.usage_cost({"input_tokens": 1000, "output_tokens": 100}) == 550
    with_thoughts = {
        "input_tokens": 1000,
        "output_tokens": 100,
        "reasoning_tokens": 400,
    }
    assert paid.usage_cost(with_thoughts) == 300 + 500 * 2.5
    by_total = {"input_tokens": 1000, "output_tokens": 100, "total_tokens": 2000}
    assert paid.usage_cost(by_total) == 300 + 1000 * 2.5
    assert paid.usage_cost(None) is None
    assert paid.usage_cost({}) is None
    assert paid.usage_cost({"output_tokens": 5}) is None
    assert paid.usage_cost({"input_tokens": 5}) is None
    tools = {"input_tokens": 1000, "output_tokens": 0, "tool_use_tokens": 500}
    assert paid.usage_cost(tools) == 1500 * 0.30  # tool-use tokens bill as input


# -- reservation and settlement ---------------------------------------------------


def test_a_successful_request_is_reserved_first_then_settled_to_its_usage(tmp_path):
    ledger = _ledger(tmp_path)
    _inner, client = _budgeted(ledger, [Response("{}", Usage(3000, 200))])
    asyncio.run(_request(client))
    ((path, status, reserved, charged),) = _rows(ledger)
    assert (path, status) == ("answer", "settled")
    assert charged == 3000 * 0.30 + 200 * 2.50 and reserved > charged
    assert ledger.snapshot()["committed_usd"] == charged / 1e6


@pytest.mark.parametrize(
    "item,outcome",
    [
        (ServerError(503), "provider error"),
        (ServerError(429), "rate limit"),
        (Response("{}", None), "usage missing"),
        (Response("{}", types.SimpleNamespace()), "usage without token counts"),
    ],
)
def test_unknown_usage_keeps_its_whole_reservation(tmp_path, item, outcome):
    ledger = _ledger(tmp_path)
    _inner, client = _budgeted(ledger, [item])
    try:
        asyncio.run(_request(client))
    except ServerError:
        pass
    ((_path, status, reserved, charged),) = _rows(ledger)
    assert status == "unknown_retained", outcome
    assert charged == reserved > 0


def test_a_timeout_or_cancellation_keeps_its_reservation(tmp_path):
    ledger = _ledger(tmp_path)
    _inner, client = _budgeted(ledger, ["stall"])

    async def run():
        await asyncio.wait_for(_request(client), 0.05)

    with pytest.raises(TimeoutError):
        asyncio.run(run())
    ((_path, status, reserved, charged),) = _rows(ledger)
    assert status == "unknown_retained" and charged == reserved


def test_a_crash_mid_request_leaves_the_reservation_held_after_restart(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.reserve(
        lab="lab-9",
        call_path="extraction",
        model="m",
        input_bytes=11_000,
        max_output_tokens=4096,
    )
    ledger.close()  # process dies before settling
    reopened = _ledger(tmp_path)
    ((_path, status, reserved, charged),) = _rows(reopened)
    assert status == "reserved" and charged is None
    assert reopened.snapshot()["committed_usd"] == reserved / 1e6


GOOD = {
    "model": "gemini-3.5-flash-lite",
    "input": "{}",
    "system_instruction": "fictional",
    "response_format": {"type": "text", "mime_type": "application/json", "schema": {}},
    "store": False,
    "generation_config": {"max_output_tokens": 2048},
}


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"model": "gemini-3.8-flash"}, "unpriced model"),
        ({"model": None}, "missing model"),
        ({"generation_config": None}, "no output bound"),
        ({"generation_config": {}}, "no output bound"),
        ({"generation_config": {"max_output_tokens": 0}}, "zero bound"),
        ({"generation_config": {"max_output_tokens": 65536}}, "bound too large"),
        (
            {
                "generation_config": {
                    "max_output_tokens": 2048,
                    "thinking_level": "high",
                }
            },
            "thinking option",
        ),
        ({"tools": [{"type": "google_search"}]}, "tool (billed separately)"),
        ({"store": True}, "stored interaction"),
        ({"response_format": {"type": "image"}}, "media output"),
        ({"input": [{"type": "image", "data": "x"}]}, "media input"),
        ({"previous_interaction_id": "x"}, "unpriced option"),
    ],
)
def test_unpriced_models_and_options_are_refused_before_anything_is_reserved(
    tmp_path, change, reason
):
    ledger = _ledger(tmp_path)
    inner, client = _budgeted(ledger, [Response("{}", Usage())])
    kwargs = {**GOOD, **change}
    if change.get("model", "") is None:
        kwargs.pop("model")
    with pytest.raises(paid.PaidRequestRefused):
        asyncio.run(client.aio.interactions.create(**kwargs))
    assert inner.aio.interactions.calls == [] and _rows(ledger) == [], reason


def test_the_clients_own_requests_pass_the_check():
    assert paid.check_request(dict(GOOD)) == 2048


# -- exhaustion, resume, no reset ---------------------------------------------------


def _fill(ledger, micro_usd):
    db = sqlite3.connect(ledger.path)
    db.execute(
        "INSERT INTO request (request_id, budget_id, lab, call_path, model, status,"
        " input_bound, output_bound, reserved_micro_usd, charged_micro_usd,"
        " reserved_at) VALUES ('earlier', ?, 'lab-9', 'answer', 'm', 'settled',"
        " 1, 1, ?, ?, 'then')",
        (paid.BUDGET_ID, micro_usd, micro_usd),
    )
    db.commit()
    db.close()


def test_a_request_that_cannot_fit_is_refused_before_it_is_sent(tmp_path):
    ledger = _ledger(tmp_path)
    sent = json.dumps(["fictional", '{"q": 1}', {"type": "text"}]).encode()
    _, _, need = paid.worst_case(len(sent), 2048)
    _fill(ledger, paid.CEILING_MICRO_USD - need + 1)
    inner, client = _budgeted(ledger, [Response("{}", Usage())])
    with pytest.raises(PaidBudgetExhausted, match="remains uncommitted"):
        asyncio.run(_request(client))
    assert inner.aio.interactions.calls == []
    assert len(_rows(ledger)) == 1  # only the earlier spend


def test_resume_and_a_new_lab_share_one_budget(tmp_path):
    first = _ledger(tmp_path)
    _inner, client = _budgeted(first, [Response("{}", Usage(3000, 200))])
    asyncio.run(_request(client))
    spent = first.snapshot()["committed_usd"]
    first.close()
    second = PaidBudgetLedger(tmp_path / "shared" / "paid-ledger.sqlite3")
    assert second.snapshot()["committed_usd"] == spent  # carried, never reset
    assert second.snapshot()["ceiling_usd"] == 1.0


def test_the_ceiling_can_never_be_reset_or_raised(tmp_path, monkeypatch):
    ledger = _ledger(tmp_path)
    ledger.close()
    monkeypatch.setattr(paid, "CEILING_MICRO_USD", 2_000_000)
    with pytest.raises(ValueError, match="approved USD 1"):
        _ledger(tmp_path)
    assert not hasattr(PaidBudgetLedger, "reset")
    assert not hasattr(PaidBudgetLedger, "increase")


def test_a_cost_above_its_reservation_halts_the_budget(tmp_path):
    ledger = _ledger(tmp_path)
    huge = Response("{}", Usage(inp=10, out=10, thoughts=1_000_000))
    _inner, client = _budgeted(ledger, [huge, Response("{}", Usage())])
    asyncio.run(_request(client))
    assert ledger.snapshot()["halted_reason"]
    with pytest.raises(PaidBudgetHalted):
        asyncio.run(_request(client))


# -- retries are reserved; tools never repeat ------------------------------------


class _Log:
    def __init__(self):
        self.rows = []

    def event(self, row):
        self.rows.append(row)


class _Out(BaseModel):
    response: dict


def test_answer_retries_are_each_reserved_and_exhaustion_is_not_retried(tmp_path):
    from jarvis.hands.provider_adapters import GeminiStructuredOutputClient
    from jarvis.voice.personal_memory_acceptance import (
        AcceptanceInterrupted,
        Say,
        TextDriver,
        told,
    )

    ledger = _ledger(tmp_path)
    inner, budgeted = _budgeted(
        ledger, [ServerError(503), Response('{"response": {}}', Usage(2000, 50))]
    )
    client = paid.PaidLaneDriverClient(
        GeminiStructuredOutputClient(
            client=budgeted, model="gemini-3.5-flash-lite", max_output_tokens=2048
        )
    )
    log = _Log()
    driver = TextDriver(client, log, model="m", sleep=lambda _s: asyncio.sleep(0))
    step = Say("s-1", "D0", "fictional", told(17))

    def request():
        return client.parse_with_telemetry(
            system_prompt="p", input_payload={"x": 1}, response_model=_Out
        )

    _telemetry, attempt, _ = asyncio.run(
        driver._model_step(group="g", step=step, index=0, request=request)
    )
    assert attempt == 2 and len(inner.aio.interactions.calls) == 2
    assert [r[1] for r in _rows(ledger)] == ["unknown_retained", "settled"]

    # Exhaustion: interrupted, never retried, nothing sent.
    _fill(ledger, paid.CEILING_MICRO_USD)
    inner.aio.interactions.script = [Response('{"response": {}}', Usage())]
    with pytest.raises(AcceptanceInterrupted, match="PaidBudgetExhausted"):
        asyncio.run(driver._model_step(group="g", step=step, index=1, request=request))
    assert len(inner.aio.interactions.calls) == 2
    assert log.rows[-1]["decision"] != "transient_retry"


# -- all three call paths are covered and use the Paid key only -----------------


def test_extraction_resolution_and_answers_all_use_the_paid_key_and_the_ledger(
    tmp_path, monkeypatch
):
    from jarvis.memory.learning_extractors import EXTRACTION_PROMPT, RESOLUTION_PROMPT

    built = []

    class Client:
        def __init__(self, api_key, http_options=None):
            self.api_key = api_key
            self.http_options = http_options
            self.aio = types.SimpleNamespace(
                interactions=FakeInteractions(
                    [Response('{"candidates": []}', Usage(3000, 20))] * 3
                ),
                aclose=None,
            )
            built.append(self)

    fake = types.ModuleType("google.genai")
    fake.Client = Client
    google = sys.modules.get("google") or types.ModuleType("google")
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setattr(google, "genai", fake, raising=False)
    monkeypatch.setitem(sys.modules, "google.genai", fake)
    monkeypatch.setenv("JARVIS_GEMINI_PAID_API_KEY", "paid-test")
    monkeypatch.setenv("GOOGLE_API_KEY", "free-must-not-be-used")
    ledger = _ledger(tmp_path)
    adapter, answer = paid.build_paid_clients("gemini-3.5-flash-lite", ledger, lab="L")
    assert [c.api_key for c in built] == ["paid-test", "paid-test"]
    assert all(c.aio.interactions.sdk_configuration.retry_config is None for c in built)

    asyncio.run(adapter._request(EXTRACTION_PROMPT, {"t": 1}, {"type": "object"}))
    asyncio.run(adapter._request(RESOLUTION_PROMPT, {"t": 1}, {"type": "object"}))

    class Out(BaseModel):
        candidates: list

    asyncio.run(
        paid.PaidLaneDriverClient(answer).parse_with_telemetry(
            system_prompt="answer",
            input_payload={"q": 1},
            response_model=Out,
            scope_id="x",
            operation_id="y",
        )
    )
    assert [r[:2] for r in _rows(ledger)] == [
        ("extraction", "settled"),
        ("resolution", "settled"),
        ("answer", "settled"),
    ]
    # Every request the clients sent went through the ledger.
    assert sum(len(c.aio.interactions.calls) for c in built) == 3


def test_learning_call_paths_are_told_apart_by_prompt():
    from jarvis.memory.learning_extractors import EXTRACTION_PROMPT, RESOLUTION_PROMPT

    assert learning_call_path({"system_instruction": EXTRACTION_PROMPT}) == "extraction"
    assert learning_call_path({"system_instruction": RESOLUTION_PROMPT}) == "resolution"
    assert learning_call_path({"system_instruction": "x"}) == "learning_other"


# -- one lane per lab -------------------------------------------------------------


def test_a_lab_never_changes_lane_on_resume(tmp_path):
    from jarvis.voice.project_memory_lab import check_lane

    ledger = tmp_path / "ledger.sqlite3"
    check_lane(tmp_path, "paid", ledger)  # fresh lab
    (tmp_path / "acceptance-steps.jsonl").write_text(
        json.dumps({"lane": "paid", "step_id": "story-01"}) + "\n", encoding="utf-8"
    )
    check_lane(tmp_path, "paid", ledger)
    with pytest.raises(ValueError, match="cannot continue on free"):
        check_lane(tmp_path, "free", None)
    with pytest.raises(ValueError, match="requires its ledger"):
        check_lane(tmp_path, "paid", None)
    with pytest.raises(ValueError, match="requires its ledger"):
        check_lane(tmp_path, "free", ledger)


def test_events_carry_the_lane(tmp_path):
    from jarvis.voice.personal_memory_acceptance import ResultLog

    log = ResultLog(tmp_path, commit="c", hashes={}, models={"lane": "paid"})
    log.event({"kind": "x"})
    row = json.loads((tmp_path / "acceptance-events.jsonl").read_text())
    assert row["lane"] == "paid"


def test_the_paid_clients_refuse_an_unpriced_model(tmp_path, monkeypatch):
    fake = types.ModuleType("google.genai")
    fake.Client = lambda **_k: (_ for _ in ()).throw(AssertionError("built a client"))
    google = sys.modules.get("google") or types.ModuleType("google")
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setattr(google, "genai", fake, raising=False)
    monkeypatch.setitem(sys.modules, "google.genai", fake)
    monkeypatch.setenv("JARVIS_GEMINI_PAID_API_KEY", "paid-test")
    with pytest.raises(paid.PaidRequestRefused, match="answer model"):
        paid.build_paid_clients("gemini-3.8-flash", _ledger(tmp_path), lab="L")


# -- the checkpoint allowance ------------------------------------------------------

CHECKPOINT = ("checkpoint-test", 100_000)  # USD 0.10


def test_an_allowance_caps_its_slice_and_refuses_unsent(tmp_path):
    ledger = _ledger(tmp_path)
    inner = FakeGenai([Response("{}", Usage(100, 2000))] * 40)  # ~USD 0.005 each
    client = BudgetedGeminiClient(
        inner, ledger, lab="L", classify=paid.answer_call_path, allowance=CHECKPOINT
    )
    sent = 0
    with pytest.raises(paid.PaidAllowanceExhausted, match="checkpoint-test"):
        for _ in range(40):
            asyncio.run(_request(client))
            sent += 1
    used = ledger.snapshot()["allowances"][0]
    assert used["cap_usd"] == 0.10 and used["used_usd"] <= 0.10
    assert len(inner.aio.interactions.calls) == sent  # the refused one was not sent
    # Spending outside the allowance still draws on the shared budget.
    free = BudgetedGeminiClient(
        FakeGenai([Response("{}", Usage(3000, 200))]),
        ledger,
        lab="L",
        classify=paid.answer_call_path,
    )
    asyncio.run(_request(free))
    assert ledger.snapshot()["committed_usd"] > used["used_usd"]


def test_an_allowance_is_durable_and_its_cap_is_fixed(tmp_path):
    ledger = _ledger(tmp_path)
    _inner, client = _budgeted(ledger, [ServerError(503)])
    client._allowance = CHECKPOINT
    with pytest.raises(ServerError):
        asyncio.run(_request(client))
    held = ledger.snapshot()["allowances"][0]["used_usd"]
    ledger.close()
    reopened = _ledger(tmp_path)
    assert reopened.snapshot()["allowances"][0]["used_usd"] == held > 0
    with pytest.raises(ValueError, match="was fixed"):
        reopened.reserve(
            lab="L",
            call_path="answer",
            model="m",
            input_bytes=10,
            max_output_tokens=10,
            allowance=("checkpoint-test", 200_000),
        )


def test_a_ledger_created_before_allowances_keeps_its_rows(tmp_path):
    path = tmp_path / "old" / "ledger.sqlite3"
    path.parent.mkdir()
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE budget (budget_id TEXT PRIMARY KEY, ceiling_micro_usd INTEGER
            NOT NULL, pricing TEXT NOT NULL, created_at TEXT NOT NULL,
            halted_reason TEXT);
        CREATE TABLE request (seq INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id TEXT NOT NULL UNIQUE, budget_id TEXT NOT NULL,
            lab TEXT NOT NULL, call_path TEXT NOT NULL, model TEXT NOT NULL,
            status TEXT NOT NULL, input_bound INTEGER NOT NULL,
            output_bound INTEGER NOT NULL, reserved_micro_usd INTEGER NOT NULL,
            charged_micro_usd INTEGER, usage TEXT, outcome TEXT,
            reserved_at TEXT NOT NULL, finished_at TEXT);
        """
    )
    db.execute(
        "INSERT INTO budget VALUES (?, 1000000, '{}', 'then', NULL)", (paid.BUDGET_ID,)
    )
    db.execute(
        "INSERT INTO request (request_id, budget_id, lab, call_path, model, status,"
        " input_bound, output_bound, reserved_micro_usd, charged_micro_usd,"
        " reserved_at) VALUES ('r1', ?, 'L', 'answer', 'm', 'settled', 1, 1, 50, 40,"
        " 'then')",
        (paid.BUDGET_ID,),
    )
    db.commit()
    db.close()
    ledger = PaidBudgetLedger(path)
    snap = ledger.snapshot()
    assert snap["committed_usd"] == 40 / 1e6 and snap["ceiling_usd"] == 1.0


def test_resume_marker_rule_allows_only_the_recorded_recovery_build(tmp_path):
    from jarvis.voice.project_memory_lab import MARKER, RECOVERY_SOURCE, _resume_allowed

    marker = tmp_path / "project-memory.marker"
    original, recovery, other = "0" * 40, "7" * 40, "9" * 40
    marker.write_text(json.dumps({"kind": MARKER, "commit": original}, sort_keys=True))
    assert _resume_allowed(tmp_path, marker, original, False)  # same build
    assert not _resume_allowed(tmp_path, marker, recovery, False)  # ordinary resume
    assert _resume_allowed(tmp_path, marker, recovery, True)  # explicit recovery entry
    (tmp_path / RECOVERY_SOURCE).write_text(
        json.dumps({"original_commit": original, "recovery_commit": recovery})
    )
    assert _resume_allowed(tmp_path, marker, recovery, False)  # its continuation
    assert not _resume_allowed(tmp_path, marker, other, False)
    assert not _resume_allowed(tmp_path, marker, other, True)  # one recovery only
    marker.write_text("not json")
    assert not _resume_allowed(tmp_path, marker, recovery, True)
    marker.unlink()
    assert not _resume_allowed(tmp_path, marker, recovery, True)
