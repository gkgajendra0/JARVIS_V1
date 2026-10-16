"""Comparator adapter tests use fakes: no cloud, bank writes, or actual LLM."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from tools.research.step4_hindsight_isolated_probe import (
    require_loopback,
    run_local_retrieval_probe,
)
from tools.research.step4_memory_model_comparators import (
    JarvisModelAdapter,
    eligible_raw_turn,
    project_triples,
    require_pinned_synthetic_corpus,
    score_raw_candidate_predictions,
)
from tools.research.step4_memory_shadow_benchmark import (
    DEFAULT_CASES,
    load_cases,
)

ROOT = Path(__file__).resolve().parents[1]


def _candidate_cases() -> list[dict]:
    data, _ = load_cases(DEFAULT_CASES)
    return [c for c in data["cases"] if c["kind"] == "candidate"]


def _context_cases() -> list[dict]:
    data, _ = load_cases(DEFAULT_CASES)
    return [c for c in data["cases"] if c["kind"] == "context"]


def test_excluded_external_source_never_reaches_model() -> None:
    case = next(c for c in _candidate_cases() if c["id"] == "c08")
    assert not eligible_raw_turn(case)
    called: list[str] = []

    def fake_model(text: str, case: dict) -> str:
        called.append(text)
        return "review"

    report = score_raw_candidate_predictions([case], fake_model)
    assert called == []
    assert report["candidate_predictions"] == {"c08": "skip"}
    assert report["attempted_model_calls"] == 0
    assert report["skipped_pre_provider"] == 1


def test_model_receives_raw_utterance_not_gold_or_seeded_proposal() -> None:
    case = _candidate_cases()[0]
    seen: list[str] = []
    seen_metadata: list[dict] = []

    def fake_model(text: str, case: dict) -> str:
        seen.append(text)
        seen_metadata.append(dict(case))
        return "review"

    result = score_raw_candidate_predictions([case], fake_model)
    assert seen == [case["utterance"]]
    assert seen_metadata == [{"id": "c01", "current_exact_value": None}]
    assert "expected" not in seen_metadata[0]
    assert "proposal" not in seen_metadata[0]
    assert result["candidate_predictions"] == {"c01": "review"}
    assert result["completed_model_calls"] == 1


def test_model_failures_are_counted_without_logging_provider_exception() -> None:
    case = _candidate_cases()[0]

    def failing_model(text: str, case: dict) -> str:
        raise RuntimeError("secret-error-detail")

    result = score_raw_candidate_predictions([case], failing_model)
    assert result["provider_failures"] == 1
    assert result["failed_case_ids"] == ["c01"]
    assert result["failure_types"] == {"c01": "RuntimeError"}
    assert "secret-error-detail" not in json.dumps(result)
    assert result["candidate_predictions"] == {}


def test_stateless_langmem_projection_is_only_review_or_conflict() -> None:
    case = _candidate_cases()[0]
    assert project_triples([], case) == "skip"
    assert project_triples([("owner", "likes", "examples")], case) == "review"
    updated = dict(case, current_exact_value="examples")
    assert project_triples([("owner", "likes", "examples")], updated) == "duplicate"
    assert project_triples([("owner", "likes", "detailed")], updated) == (
        "conflict_review"
    )


def test_provider_experiments_reject_modified_or_non_synthetic_corpus() -> None:
    _, digest = load_cases(DEFAULT_CASES)
    require_pinned_synthetic_corpus(digest)
    with pytest.raises(ValueError, match="non-pinned"):
        require_pinned_synthetic_corpus("0" * 64)


def test_cloud_model_cli_requires_explicit_opt_in() -> None:
    script = ROOT / "tools/research/step4_memory_model_comparators.py"
    result = subprocess.run(
        [sys.executable, str(script), "--backend", "langmem", "--model", "test"],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "--allow-model-calls" in result.stderr


@pytest.mark.parametrize(
    "url",
    [
        "https://localhost:8888",
        "http://api.hindsight.vectorize.io",
        "http://192.168.0.11:8888",
        "http://localhost:8888/other",
        "http://user:password@localhost:8888",
    ],
)
def test_hindsight_refuses_nonlocal_or_credential_urls(url: str) -> None:
    with pytest.raises(ValueError):
        require_loopback(url)


def test_hindsight_accepts_only_local_http() -> None:
    assert require_loopback("http://127.0.0.1:8888/") == ("http://127.0.0.1:8888")


class FakeHindsight:
    def __init__(self, *, fail: bool = False) -> None:
        self.created: list[str] = []
        self.deleted: list[str] = []
        self.retained = []
        self.queries = []
        self.fail = fail

    def create_bank(self, *, bank_id: str) -> None:
        self.created.append(bank_id)

    def retain_batch(self, *, bank_id: str, items: list) -> None:
        self.retained.extend(items)
        if self.fail:
            raise RuntimeError("test failure")

    def recall(self, *, bank_id: str, query: str) -> SimpleNamespace:
        self.queries.append(query)
        return SimpleNamespace(results=[SimpleNamespace(text="not logged")])

    def delete_bank(self, *, bank_id: str) -> None:
        self.deleted.append(bank_id)


def test_hindsight_retrieval_isolated_and_bank_deleted() -> None:
    client = FakeHindsight()
    result = run_local_retrieval_probe(
        client=client,
        case_data=_context_cases()[:2],
        bank_id="jarvis-dev-only-synthetic1",
    )
    assert result["queried"] == 2
    assert result["retrieved_entries_total"] == 2
    assert result["synthetic_bank_cleanup_verified"]
    assert result["result_kind"] == (
        "LOCAL_RETRIEVAL_DIAGNOSTIC_NOT_UTILITY_ACCEPTANCE"
    )
    assert client.created == client.deleted == ["jarvis-dev-only-synthetic1"]
    assert len(client.retained) == 2
    assert len(client.queries) == 2


def test_hindsight_cleanup_even_if_retain_fails() -> None:
    client = FakeHindsight(fail=True)
    with pytest.raises(RuntimeError, match="test failure"):
        run_local_retrieval_probe(
            client=client,
            case_data=_context_cases()[:1],
            bank_id="jarvis-dev-only-synthetic2",
        )
    assert client.created == client.deleted == ["jarvis-dev-only-synthetic2"]


def test_hindsight_cannot_write_into_arbitrary_named_bank() -> None:
    with pytest.raises(ValueError, match="research-only"):
        run_local_retrieval_probe(
            client=FakeHindsight(),
            case_data=_context_cases()[:1],
            bank_id="production-owner",
        )


def test_jarvis_adapter_reuses_event_loop_and_closes_transports() -> None:
    """Emulates loop-affine async HTTP clients; no provider calls."""

    from jarvis.memory.candidates import MemoryExtractionProposal

    class FakeAio:
        def __init__(self) -> None:
            self.closed_loop = None

        async def aclose(self) -> None:
            self.closed_loop = asyncio.get_running_loop()

    class FakeClient:
        def __init__(self) -> None:
            self.aio = FakeAio()
            self.sync_closed = False

        def close(self) -> None:
            self.sync_closed = True

    class FakeExtractor:
        def __init__(self) -> None:
            self._client = FakeClient()
            self.first_loop = None
            self.calls = 0

        async def extract(self, *, text: str) -> MemoryExtractionProposal:
            loop = asyncio.get_running_loop()
            if self.first_loop is None:
                self.first_loop = loop
            assert loop is self.first_loop, "provider reused on a different loop"
            self.calls += 1
            return MemoryExtractionProposal.model_validate(
                _candidate_cases()[0]["proposal"]
            )

    extractor = FakeExtractor()
    with JarvisModelAdapter(extractor) as adapter:
        results = score_raw_candidate_predictions(_candidate_cases()[:3], adapter)
        assert results["completed_model_calls"] == 3
        assert results["provider_failures"] == 0
        assert results["candidate_predictions"] == {
            "c01": "review",
            "c02": "review",
            "c03": "review",
        }

    assert extractor.calls == 3
    assert extractor._client.aio.closed_loop is extractor.first_loop
    assert extractor._client.sync_closed
    assert extractor.first_loop.is_closed()
    with pytest.raises(RuntimeError, match="closed"):
        adapter("No new calls", {"id": "c01"})


def test_jarvis_shared_loop_recovers_after_one_failed_case() -> None:
    """A single error is recorded and does not poison the shared loop."""

    from jarvis.memory.candidates import MemoryExtractionProposal

    class FlakyExtractor:
        def __init__(self) -> None:
            self.calls = 0
            self.first_loop = None

        async def extract(self, *, text: str) -> MemoryExtractionProposal:
            loop = asyncio.get_running_loop()
            if self.first_loop is None:
                self.first_loop = loop
            assert loop is self.first_loop
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("provider-secret-do-not-emit")
            return MemoryExtractionProposal.model_validate(
                _candidate_cases()[0]["proposal"]
            )

    with JarvisModelAdapter(FlakyExtractor()) as adapter:
        report = score_raw_candidate_predictions(_candidate_cases()[:3], adapter)

    assert report["completed_model_calls"] == 2
    assert report["provider_failures"] == 1
    assert report["failed_case_ids"] == ["c02"]
    assert report["failure_types"] == {"c02": "RuntimeError"}
    assert "provider-secret-do-not-emit" not in json.dumps(report)


def test_hindsight_seeds_all_distractors_before_querying_subset() -> None:
    """Source IDs make retrieval quality measurable without memory text logs."""

    contexts = _context_cases()
    by_request = {case["request"]: case["id"] for case in contexts}

    class RankedFake(FakeHindsight):
        def recall(self, *, bank_id: str, query: str) -> SimpleNamespace:
            self.queries.append(query)
            source_id = by_request[query]
            return SimpleNamespace(
                results=[SimpleNamespace(document_id=f"dev_{source_id}")]
            )

    client = RankedFake()
    report = run_local_retrieval_probe(
        client=client,
        case_data=contexts,
        bank_id="jarvis-dev-only-ranked-fake",
        max_queries=3,
    )
    assert report["seeded_documents_including_distractors"] == 24
    assert report["queried"] == 3
    assert report["positive_queries"] == 2
    assert report["positive_top1_correct_document"] == 2
    assert report["positive_top3_correct_document"] == 2
    assert report["negative_queries"] == 1
    assert report["negative_own_document_in_top3"] == 1
    assert report["results_missing_document_id"] == 0
    assert report["results_outside_synthetic_bank_ids"] == 0
    assert report["not_an_answer_quality_or_safety_score"]
    assert len(client.retained) == 24
    assert len(client.queries) == 3
    assert client.created == client.deleted == ["jarvis-dev-only-ranked-fake"]


def test_hindsight_missing_provenance_cannot_count_as_retrieval_hit() -> None:
    class UnattributedFake(FakeHindsight):
        def recall(self, *, bank_id: str, query: str) -> SimpleNamespace:
            return SimpleNamespace(
                results=[
                    SimpleNamespace(document_id=None),
                    SimpleNamespace(document_id="foreign-document"),
                ]
            )

    result = run_local_retrieval_probe(
        client=UnattributedFake(),
        case_data=_context_cases()[:1],
        bank_id="jarvis-dev-only-no-provenance",
    )
    assert result["retrieved_entries_total"] == 2
    assert result["positive_top1_correct_document"] == 0
    assert result["positive_top3_correct_document"] == 0
    assert result["results_missing_document_id"] == 1
    assert result["results_outside_synthetic_bank_ids"] == 1


def test_jarvis_adapter_awaits_async_provider_client_close() -> None:
    """OpenAI's AsyncOpenAI close is awaited before the event loop closes."""

    from jarvis.memory.candidates import MemoryExtractionProposal

    class FakeAsyncClient:
        def __init__(self) -> None:
            self.closed = False
            self.closed_loop = None

        async def close(self) -> None:
            self.closed = True
            self.closed_loop = asyncio.get_running_loop()

    class FakeAsyncExtractor:
        def __init__(self) -> None:
            self._client = FakeAsyncClient()
            self.extract_loop = None

        async def extract(self, *, text: str) -> MemoryExtractionProposal:
            self.extract_loop = asyncio.get_running_loop()
            return MemoryExtractionProposal.model_validate(
                _candidate_cases()[0]["proposal"]
            )

    extractor = FakeAsyncExtractor()
    with JarvisModelAdapter(extractor) as adapter:
        assert adapter("Synthetic", {"id": "c01"}) == "review"

    assert extractor._client.closed
    assert extractor._client.closed_loop is extractor.extract_loop
    assert extractor.extract_loop.is_closed()


def test_hindsight_bounded_retention_paces_and_limits_cloud_work() -> None:
    """Three fake retain batches, two queries, no calls to the cloud."""

    class BoundedFake(FakeHindsight):
        def __init__(self) -> None:
            super().__init__()
            self.batch_sizes: list[int] = []

        def retain_batch(self, *, bank_id: str, items: list) -> None:
            self.batch_sizes.append(len(items))
            super().retain_batch(bank_id=bank_id, items=items)

    now = [0.0]
    pauses: list[float] = []

    def advance(seconds: float) -> None:
        pauses.append(seconds)
        now[0] += seconds

    client = BoundedFake()
    report = run_local_retrieval_probe(
        client=client,
        case_data=_context_cases(),
        bank_id="jarvis-dev-only-capped-pacing",
        max_seed_items=3,
        max_queries=2,
        retain_batch_size=1,
        min_seconds_between_retain_batches=65,
        clock=lambda: now[0],
        sleep=advance,
    )
    assert client.batch_sizes == [1, 1, 1]
    assert len(client.retained) == 3
    assert len(client.queries) == 2
    assert pauses == [65, 65]
    assert report["seeded_documents_including_distractors"] == 3
    assert report["retain_batches"] == 3
    assert report["queried"] == 2
    assert report["synthetic_bank_cleanup_verified"]
    assert client.created == client.deleted


def test_hindsight_quota_error_stops_further_retain_batches_and_deletes_bank() -> None:
    class FailSecondBatch(FakeHindsight):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        def retain_batch(self, *, bank_id: str, items: list) -> None:
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("synthetic quota 429")
            super().retain_batch(bank_id=bank_id, items=items)

    client = FailSecondBatch()
    with pytest.raises(RuntimeError, match="synthetic quota"):
        run_local_retrieval_probe(
            client=client,
            case_data=_context_cases(),
            bank_id="jarvis-dev-only-quota-stop",
            max_seed_items=3,
            retain_batch_size=1,
            min_seconds_between_retain_batches=65,
            clock=lambda: 0.0,
            sleep=lambda _: None,
        )
    assert client.calls == 2
    assert len(client.retained) == 1
    assert not client.queries
    assert client.created == client.deleted


def test_hindsight_cli_refuses_accidental_24_memory_bulk_run() -> None:
    script = ROOT / "tools/research/step4_hindsight_isolated_probe.py"
    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--allow-local-server-writes",
            "--max-seed-items",
            "24",
            "--max-queries",
            "3",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    assert "--allow-large-synthetic-run" in completed.stderr


def test_hindsight_budget_validation_happens_before_any_bank_creation() -> None:
    client = FakeHindsight()
    with pytest.raises(ValueError, match="max_queries"):
        run_local_retrieval_probe(
            client=client,
            case_data=_context_cases(),
            bank_id="jarvis-dev-only-bad-budget",
            max_seed_items=2,
            max_queries=3,
        )
    assert not client.created
