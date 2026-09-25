from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass

import pytest

from jarvis.engineering_knowledge import evaluation


CORPUS_PATH = (
    Path(__file__).resolve().parents[1]
    / "benchmarks"
    / "engineering_knowledge_qrels_v1.json"
)


def _case(
    query_id: str,
    *,
    relevant: tuple[evaluation.GradedRelevance, ...] = (),
    forbidden: tuple[str, ...] = (),
    stale: tuple[str, ...] = (),
    leakage: tuple[str, ...] = (),
    no_answer: bool = False,
) -> evaluation.EngineeringKnowledgeEvaluationCase:
    return evaluation.EngineeringKnowledgeEvaluationCase(
        query_id=query_id,
        query_text=f"query {query_id}",
        context=(
            evaluation.EvaluationContextFact(
                target_namespace="jarvis.component",
                target_identity="runtime.voice",
            ),
        ),
        relevant=relevant,
        forbidden_document_keys=forbidden,
        stale_document_keys=stale,
        leakage_document_keys=leakage,
        expect_no_answer=no_answer,
        tags=("test",),
    )


def _observation(
    query_id: str,
    ranked: tuple[str, ...],
    *,
    latency_ms: float = 10.0,
    cpu_ms: float = 5.0,
    rss_mb: float | None = None,
    vram_mb: float | None = None,
    disk_bytes: int | None = None,
    rebuild_ms: float | None = None,
) -> evaluation.EngineeringKnowledgeEvaluationObservation:
    return evaluation.EngineeringKnowledgeEvaluationObservation(
        query_id=query_id,
        ranked_hits=tuple(
            evaluation.EngineeringKnowledgeEvaluationHit(document_key=key)
            for key in ranked
        ),
        resources=evaluation.EvaluationResourceSample(
            wall_latency_ms=latency_ms,
            cpu_time_ms=cpu_ms,
            rss_mb=rss_mb,
            vram_mb=vram_mb,
            disk_bytes=disk_bytes,
            rebuild_ms=rebuild_ms,
        ),
    )


def test_phase2h_corpus_loads_and_covers_required_categories() -> None:
    corpus = evaluation.load_engineering_knowledge_qrels(CORPUS_PATH)

    assert corpus.corpus_id == "jarvis.engineering_knowledge.qrels"
    assert corpus.version == 1
    assert len(corpus.cases) >= 14

    tags = {tag for case in corpus.cases for tag in case.tags}
    required = {
        "exact_crash_signature",
        "code_symbol",
        "paraphrase",
        "hinglish",
        "component_constraint",
        "version_constraint",
        "device_constraint",
        "stale",
        "contradiction",
        "similar_but_inapplicable",
        "no_answer",
        "poisoned_evidence",
        "secret_like",
        "unknown_facet",
        "cross_process",
    }
    assert required.issubset(tags)


def test_metrics_are_computed_with_graded_relevance_and_safety_counts() -> None:
    corpus = evaluation.EngineeringKnowledgeEvaluationCorpus(
        corpus_id="unit",
        version=1,
        cases=(
            _case(
                "answerable",
                relevant=(
                    evaluation.GradedRelevance("best", 3),
                    evaluation.GradedRelevance("secondary", 1),
                ),
                forbidden=("wrong-component",),
                stale=("stale-old",),
                leakage=("private-secret",),
            ),
            _case("no-answer", no_answer=True),
        ),
    )
    observations = (
        _observation(
            "answerable",
            ("best", "wrong-component", "stale-old", "private-secret"),
            latency_ms=10.0,
            cpu_ms=4.0,
            rss_mb=100.0,
            vram_mb=200.0,
            disk_bytes=1000,
            rebuild_ms=30.0,
        ),
        _observation(
            "no-answer",
            ("false-positive",),
            latency_ms=30.0,
            cpu_ms=8.0,
            rss_mb=110.0,
            vram_mb=190.0,
            disk_bytes=1200,
            rebuild_ms=50.0,
        ),
    )

    report = evaluation.score_engineering_knowledge_evaluation(
        corpus,
        observations,
        k=4,
    )
    metrics = report.metrics

    assert metrics.answerable_case_count == 1
    assert metrics.no_answer_case_count == 1
    assert metrics.recall_at_k == pytest.approx(0.5)
    assert metrics.precision_at_k == pytest.approx(0.25)
    assert metrics.mrr == pytest.approx(1.0)
    assert 0.0 < metrics.ndcg_at_k <= 1.0
    assert metrics.no_answer_false_positive_rate == pytest.approx(1.0)
    assert metrics.applicability_violation_count == 1
    assert metrics.stale_result_count == 1
    assert metrics.leakage_count == 1
    assert metrics.no_answer_false_positive_count == 1
    assert metrics.safety_gate_passed is False
    assert metrics.latency_p50_ms == pytest.approx(20.0)
    assert metrics.latency_p95_ms == pytest.approx(29.0)
    assert metrics.cpu_p50_ms == pytest.approx(6.0)
    assert metrics.cpu_p95_ms == pytest.approx(7.8)
    assert metrics.peak_rss_mb == pytest.approx(110.0)
    assert metrics.peak_vram_mb == pytest.approx(200.0)
    assert metrics.max_disk_bytes == 1200
    assert metrics.rebuild_p95_ms == pytest.approx(49.0)


def test_perfect_rankings_pass_zero_tolerance_safety_gate() -> None:
    corpus = evaluation.EngineeringKnowledgeEvaluationCorpus(
        corpus_id="perfect",
        version=1,
        cases=(
            _case(
                "q1",
                relevant=(
                    evaluation.GradedRelevance("a", 3),
                    evaluation.GradedRelevance("b", 1),
                ),
                forbidden=("forbidden",),
                stale=("stale",),
                leakage=("leak",),
            ),
            _case("q2", no_answer=True),
        ),
    )
    report = evaluation.score_engineering_knowledge_evaluation(
        corpus,
        (
            _observation("q1", ("a", "b"), latency_ms=1.0, cpu_ms=1.0),
            _observation("q2", (), latency_ms=1.0, cpu_ms=1.0),
        ),
        k=2,
    )

    assert report.metrics.recall_at_k == pytest.approx(1.0)
    assert report.metrics.precision_at_k == pytest.approx(1.0)
    assert report.metrics.mrr == pytest.approx(1.0)
    assert report.metrics.ndcg_at_k == pytest.approx(1.0)
    assert report.metrics.safety_gate_passed is True


def test_observation_set_must_exactly_match_corpus() -> None:
    corpus = evaluation.EngineeringKnowledgeEvaluationCorpus(
        corpus_id="mismatch",
        version=1,
        cases=(_case("expected", no_answer=True),),
    )

    with pytest.raises(
        evaluation.EngineeringKnowledgeEvaluationError,
        match="observation query IDs mismatch",
    ):
        evaluation.score_engineering_knowledge_evaluation(
            corpus,
            (_observation("extra", ()),),
        )


def test_no_answer_case_cannot_declare_relevant_documents() -> None:
    with pytest.raises(
        evaluation.EngineeringKnowledgeEvaluationError,
        match="no-answer case cannot contain relevant",
    ):
        _case(
            "invalid",
            relevant=(evaluation.GradedRelevance("doc", 1),),
            no_answer=True,
        )


@dataclass
class _Retriever:
    hits_by_query: dict[str, tuple[str, ...]]

    def retrieve(
        self,
        case: evaluation.EngineeringKnowledgeEvaluationCase,
        *,
        limit: int,
    ) -> tuple[evaluation.EngineeringKnowledgeEvaluationHit, ...]:
        return tuple(
            evaluation.EngineeringKnowledgeEvaluationHit(document_key=key)
            for key in self.hits_by_query.get(case.query_id, ())[:limit]
        )


class _Probe:
    def snapshot(
        self,
    ) -> tuple[float | None, float | None, int | None, float | None]:
        return 123.0, 456.0, 789, 12.0


def test_harness_runs_retriever_and_resource_probe() -> None:
    corpus = evaluation.EngineeringKnowledgeEvaluationCorpus(
        corpus_id="harness",
        version=1,
        cases=(
            _case("q1", relevant=(evaluation.GradedRelevance("doc", 3),)),
            _case("q2", no_answer=True),
        ),
    )
    harness = evaluation.EngineeringKnowledgeEvaluationHarness(
        _Retriever({"q1": ("doc",), "q2": ()}),
        resource_probe=_Probe(),
    )

    report = harness.run(corpus, k=3)

    assert report.metrics.safety_gate_passed is True
    assert report.metrics.recall_at_k == pytest.approx(1.0)
    assert report.metrics.peak_rss_mb == pytest.approx(123.0)
    assert report.metrics.peak_vram_mb == pytest.approx(456.0)
    assert report.metrics.max_disk_bytes == 789
    assert report.metrics.rebuild_p95_ms == pytest.approx(12.0)
    assert all(
        observation.resources.wall_latency_ms >= 0.0
        for observation in report.observations
    )
