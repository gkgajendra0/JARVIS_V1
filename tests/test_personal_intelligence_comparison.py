"""Behavioral contracts for the fictional, offline comparison harness."""

from __future__ import annotations

import asyncio
import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "benchmarks/personal_intelligence_v1.json"


def _api():
    path = ROOT / "tools/research/personal_intelligence_comparison.py"
    if not path.is_file():
        pytest.fail("The fictional comparison harness has not been implemented")
    spec = importlib.util.spec_from_file_location("pi_comparison", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _document():
    return json.loads(CORPUS.read_text(encoding="utf-8"))


def _case(case_id="PI001"):
    return next(case for case in _document()["cases"] if case["id"] == case_id)


def test_public_cases_load_without_losing_hindi_or_lifecycle_operations():
    cases = _api().load_cases(CORPUS)
    assert len(cases) == 20
    assert {case["language"] for case in cases} == {"en", "hi", "hi-Latn"}
    assert cases[11]["events"][1]["target_source_ids"] == ["PI012-e1"]


def test_candidate_projection_never_copies_gold_or_case_classification():
    case = _case()
    case["evaluation_only"]["nested"] = {"answer": "GOLD_CANARY"}
    result = _api().candidate_input(case, destination="cloud")
    assert set(result) == {"id", "language", "events", "query"}
    assert "GOLD_CANARY" not in json.dumps(result)
    assert "evaluation_only" not in json.dumps(result)
    assert "domain" not in result
    result["events"][0]["text"] = "modified by candidate"
    assert case["events"][0]["text"].startswith("For this fictional trial")


@pytest.mark.parametrize("case_id", ["PI010", "PI011"])
def test_restricted_history_is_removed_before_cloud_adapter_access(case_id):
    result = _api().candidate_input(_case(case_id), destination="cloud")
    assert result["events"] == []


def test_local_destination_can_read_local_only_owner_history():
    result = _api().candidate_input(_case("PI011"), destination="local")
    assert result["events"][0]["id"] == "PI011-e1"


@pytest.mark.parametrize("permission", [None, "false", 0])
def test_missing_or_non_boolean_permissions_fail_closed(permission):
    case = _case()
    if permission is None:
        del case["events"][0]["cloud_release_allowed"]
    else:
        case["events"][0]["cloud_release_allowed"] = permission
    with pytest.raises(ValueError):
        _api().candidate_input(case, destination="cloud")


@pytest.mark.parametrize(
    "mutation",
    [
        "naive",
        "future",
        "reversed",
        "duplicate_case",
        "duplicate_event",
        "foreign_forget",
    ],
)
def test_invalid_chronology_and_source_identity_are_rejected(tmp_path, mutation):
    document = _document()
    if mutation == "naive":
        document["cases"][0]["events"][0]["at"] = "2026-10-01T09:00:00"
    elif mutation == "future":
        document["cases"][0]["events"][0]["at"] = "2027-10-01T09:00:00Z"
    elif mutation == "reversed":
        document["cases"][0]["events"].reverse()
    elif mutation == "duplicate_case":
        document["cases"].append(copy.deepcopy(document["cases"][0]))
    elif mutation == "duplicate_event":
        document["cases"][0]["events"][1]["id"] = "PI001-e1"
    else:
        document["cases"][11]["events"][1]["target_source_ids"] = ["PI001-e1"]
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError):
        _api().load_cases(path)


@pytest.mark.parametrize("location", ["event", "query"])
def test_unknown_provider_fields_are_rejected(location):
    case = _case()
    target = case["events"][0] if location == "event" else case["query"]
    target["answer_hint"] = "do not copy this"
    with pytest.raises(ValueError):
        _api().candidate_input(case, destination="cloud")


@pytest.mark.parametrize("location", ["language", "requester", "kind"])
def test_container_in_scalar_policy_field_is_a_validation_error(location):
    case = _case()
    if location == "language":
        case["language"] = []
    elif location == "requester":
        case["query"]["requester"] = []
    else:
        case["events"][0]["kind"] = []
    with pytest.raises(ValueError):
        _api().candidate_input(case, destination="cloud")


class _HistoryAdapter:
    """An explicit in-memory protocol fixture; never a measured service arm."""

    def __init__(self, *, ready=True, evidence=None, fail_ingestion=False):
        self.events = {}
        self.calls = []
        self.ready = ready
        self.evidence = evidence
        self.fail_ingestion = fail_ingestion
        self.closed = False

    async def reset(self, identity):
        self.calls.append(("reset", identity))
        self.events.clear()

    async def ingest(self, event):
        if self.fail_ingestion:
            raise RuntimeError("private-provider-error-canary")
        self.events[event["id"]] = copy.deepcopy(event)
        self.calls.append(("ingest", event["id"]))

    async def wait_ready(self, timeout_s):
        self.calls.append(("ready",))
        return self.ready

    async def invalidate(self, source_ids):
        self.calls.append(("invalidate", source_ids))
        for source_id in source_ids:
            self.events.pop(source_id, None)

    async def select(self, query, token_budget):
        return {
            "status": "ready",
            "evidence": self.evidence
            if self.evidence is not None
            else [
                {"source_ids": [key], "text": value["text"]}
                for key, value in self.events.items()
            ],
            "elapsed_ms": 0,
        }

    async def close(self):
        self.closed = True


async def _record_answer(payload):
    return {"text": "fictional protocol answer", "received": copy.deepcopy(payload)}


async def _run(case, adapter, **kwargs):
    return await _api().run_case(
        case,
        adapter,
        _record_answer,
        destination="cloud",
        token_budget=4096,
        timeout_s=0.2,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_verified_forget_is_an_operation_and_cannot_reach_answer_context():
    adapter = _HistoryAdapter()
    result = await _run(_case("PI012"), adapter)
    assert result["status"] == "answered"
    assert result["answer"]["received"]["context"] == []
    assert ("invalidate", ("PI012-e1",)) in adapter.calls
    assert ("ingest", "PI012-e2") not in adapter.calls
    invalidation = adapter.calls.index(("invalidate", ("PI012-e1",)))
    assert adapter.calls[invalidation - 1] == ("ready",)
    assert adapter.calls[invalidation + 1] == ("ready",)
    assert adapter.closed


@pytest.mark.asyncio
async def test_private_forget_text_still_invalidates_previously_released_source():
    case = _case("PI012")
    case["events"][1]["cloud_release_allowed"] = False
    adapter = _HistoryAdapter()
    result = await _run(case, adapter)
    assert result["status"] == "answered"
    assert result["answer"]["received"]["context"] == []
    assert ("invalidate", ("PI012-e1",)) in adapter.calls
    assert ("ingest", "PI012-e2") not in adapter.calls


def test_unknown_actor_and_null_retention_fail_before_projection():
    case = _case()
    case["events"][0]["actor"] = "unknown"
    case["events"][0]["retention"] = None
    with pytest.raises(ValueError):
        _api().candidate_input(case, destination="cloud")


@pytest.mark.asyncio
async def test_empty_history_still_requires_reset_readiness():
    adapter = _HistoryAdapter(ready=False)
    result = await _run(_case("PI010"), adapter)
    assert result["status"] == "unavailable"
    assert "answer" not in result
    assert adapter.closed


@pytest.mark.asyncio
async def test_answerer_receives_sources_and_no_mutation_tools_or_gold():
    result = await _run(_case(), _HistoryAdapter())
    payload = result["answer"]["received"]
    assert result["status"] == "answered"
    assert payload["tools"] == []
    assert payload["query"]["actions_authorized"] is False
    assert "evaluation_only" not in json.dumps(payload)
    assert payload["context"][0]["source_ids"] == ["PI001-e1"]


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["foreign-source", "PI011-e1", "PI012-e1"])
async def test_unadmitted_or_forgotten_source_cannot_be_released(source):
    case = _case("PI012") if source == "PI012-e1" else _case()
    adapter = _HistoryAdapter(evidence=[{"source_ids": [source], "text": "fake"}])
    result = await _run(case, adapter)
    assert result["status"] == "failed"
    assert "answer" not in result
    assert adapter.closed


@pytest.mark.asyncio
async def test_service_text_cannot_replace_a_cited_original_source():
    adapter = _HistoryAdapter(
        evidence=[{"source_ids": ["PI001-e1"], "text": "The owner eats meat."}]
    )
    result = await _run(_case(), adapter)
    context = result["answer"]["received"]["context"]
    assert (
        context[0]["text"]
        == "For this fictional trial, you may remember that I eat vegetarian food."
    )
    assert "eats meat" not in json.dumps(context)


@pytest.mark.asyncio
async def test_readiness_failure_is_unavailable_and_closes_adapter():
    adapter = _HistoryAdapter(ready=False)
    result = await _run(_case(), adapter)
    assert result["status"] == "unavailable"
    assert "answer" not in result
    assert adapter.closed


@pytest.mark.asyncio
async def test_provider_failure_is_sanitized_and_still_cleans_up():
    adapter = _HistoryAdapter(fail_ingestion=True)
    result = await _run(_case(), adapter)
    assert result["status"] == "failed"
    assert "private-provider-error-canary" not in json.dumps(result)
    assert adapter.closed


@pytest.mark.asyncio
async def test_cancellation_propagates_and_closes_the_adapter():
    class CancelledAdapter(_HistoryAdapter):
        async def select(self, query, token_budget):
            raise asyncio.CancelledError

    adapter = CancelledAdapter()
    with pytest.raises(asyncio.CancelledError):
        await _run(_case(), adapter)
    assert adapter.closed


@pytest.mark.asyncio
async def test_oversized_context_is_rejected_before_answerer_release():
    result = await _api().run_case(
        _case(),
        _HistoryAdapter(),
        _record_answer,
        destination="cloud",
        token_budget=1,
        timeout_s=0.2,
    )
    assert result["status"] == "failed"
    assert "answer" not in result


@pytest.mark.asyncio
async def test_hanging_ingestion_times_out_and_closes_adapter():
    class HangingAdapter(_HistoryAdapter):
        async def ingest(self, event):
            await asyncio.Event().wait()

    adapter = HangingAdapter()
    result = await _run(_case(), adapter)
    assert result["status"] == "unavailable"
    assert "answer" not in result
    assert adapter.closed


@pytest.mark.asyncio
async def test_cleanup_failure_cannot_be_reported_as_an_answered_trial():
    class BrokenCleanupAdapter(_HistoryAdapter):
        async def close(self):
            raise RuntimeError("sensitive cleanup detail")

    result = await _run(_case(), BrokenCleanupAdapter())
    assert result["status"] == "cleanup_failed"
    assert "answer" not in result
    assert "sensitive cleanup detail" not in json.dumps(result)


def test_default_cli_validates_without_model_or_engine_calls():
    _api()
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            str(ROOT / "tools/research/personal_intelligence_comparison.py"),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "status": "validated_only",
        "cases": 20,
        "events": 34,
        "model_calls": 0,
        "engine_trials": 0,
    }
