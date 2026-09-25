from __future__ import annotations

import pytest

from jarvis.engineering_knowledge.benchmarking import (
    BASELINE_RETRIEVAL_VARIANT,
    PHASE2I_RETRIEVAL_VARIANTS,
    RetrievalBenchmarkAdoptionPolicy,
    RetrievalBenchmarkDecision,
    RetrievalExperimentReadiness,
    build_qwen3_experiment_contract,
    compare_retrieval_benchmark,
)
from jarvis.engineering_knowledge.evaluation import (
    EngineeringKnowledgeEvaluationMetrics,
    EngineeringKnowledgeEvaluationReport,
)
from jarvis.engineering_knowledge.retrieval import build_engineering_qwen_encoder


def _report(
    *,
    recall: float = 0.8,
    mrr: float = 0.8,
    ndcg: float = 0.8,
    latency_p95: float = 20.0,
    cpu_p95: float = 10.0,
    rss: float | None = 100.0,
    vram: float | None = 200.0,
    disk: int | None = 1000,
    applicability_violations: int = 0,
    stale_results: int = 0,
    leakage: int = 0,
    no_answer_false_positives: int = 0,
) -> EngineeringKnowledgeEvaluationReport:
    returned = 10
    metrics = EngineeringKnowledgeEvaluationMetrics(
        k=5,
        answerable_case_count=10,
        no_answer_case_count=5,
        recall_at_k=recall,
        precision_at_k=0.4,
        mrr=mrr,
        ndcg_at_k=ndcg,
        no_answer_false_positive_rate=no_answer_false_positives / 5,
        applicability_violation_rate=applicability_violations / returned,
        stale_result_rate=stale_results / returned,
        leakage_rate=leakage / returned,
        returned_hit_count=returned,
        applicability_violation_count=applicability_violations,
        stale_result_count=stale_results,
        leakage_count=leakage,
        no_answer_false_positive_count=no_answer_false_positives,
        latency_p50_ms=latency_p95 / 2,
        latency_p95_ms=latency_p95,
        cpu_p50_ms=cpu_p95 / 2,
        cpu_p95_ms=cpu_p95,
        peak_rss_mb=rss,
        peak_vram_mb=vram,
        max_disk_bytes=disk,
        rebuild_p95_ms=30.0,
    )
    return EngineeringKnowledgeEvaluationReport(
        corpus_id="jarvis.engineering_knowledge.qrels",
        corpus_version=1,
        observations=(),
        metrics=metrics,
    )


def _policy(**overrides: float | None) -> RetrievalBenchmarkAdoptionPolicy:
    values: dict[str, float | None] = {
        "minimum_ndcg_gain": 0.02,
        "minimum_mrr_gain": 0.02,
        "maximum_recall_regression": 0.01,
        "maximum_latency_ratio": 1.25,
        "maximum_cpu_ratio": 1.25,
        "maximum_rss_ratio": 1.25,
        "maximum_vram_ratio": 1.25,
        "maximum_disk_ratio": 1.25,
    }
    values.update(overrides)
    return RetrievalBenchmarkAdoptionPolicy(**values)  # type: ignore[arg-type]


def _variant(variant_id: str):
    return next(
        item for item in PHASE2I_RETRIEVAL_VARIANTS if item.variant_id == variant_id
    )


def test_phase2i_matrix_covers_planned_experiments() -> None:
    dimensions = {item.embedding_dimension for item in PHASE2I_RETRIEVAL_VARIANTS}
    backends = {item.vector_backend for item in PHASE2I_RETRIEVAL_VARIANTS}
    tokenizers = {item.fts_tokenizer for item in PHASE2I_RETRIEVAL_VARIANTS}

    assert dimensions == {256, 512, 1024}
    assert {"numpy_exact", "sqlite-vec", "lancedb", "qdrant"}.issubset(backends)
    assert "trigram" in tokenizers
    assert any(item.reranker_model_id for item in PHASE2I_RETRIEVAL_VARIANTS)
    assert BASELINE_RETRIEVAL_VARIANT.readiness is (
        RetrievalExperimentReadiness.CURRENT_BASELINE
    )


@pytest.mark.parametrize("dimension", [256, 512, 1024])
def test_qwen_experiment_contract_uses_same_pinned_model(dimension: int) -> None:
    contract = build_qwen3_experiment_contract(dimension)

    assert contract.dimension == dimension
    assert contract.model_id == BASELINE_RETRIEVAL_VARIANT.variant_id.split("-")[2].replace(
        "qwen256", contract.model_id
    )


def test_qwen_experiment_contract_rejects_unreviewed_dimension() -> None:
    with pytest.raises(ValueError, match="256, 512, or 1024"):
        build_qwen3_experiment_contract(768)


def test_engineering_qwen_encoder_accepts_experiment_contract() -> None:
    contract = build_qwen3_experiment_contract(512)
    encoder = build_engineering_qwen_encoder(device="cpu", contract=contract)

    assert encoder.contract == contract
    assert encoder.contract.dimension == 512


def test_candidate_failing_safety_gate_is_rejected_before_quality_gain() -> None:
    candidate = _variant("fts5-unicode61-qwen512-numpy-rrf")
    comparison = compare_retrieval_benchmark(
        baseline_variant=BASELINE_RETRIEVAL_VARIANT,
        baseline_report=_report(),
        candidate_variant=candidate,
        candidate_report=_report(
            recall=0.95,
            mrr=0.95,
            ndcg=0.95,
            applicability_violations=1,
        ),
        policy=_policy(),
    )

    assert comparison.decision is RetrievalBenchmarkDecision.REJECT_SAFETY


def test_relevance_regression_rejects_candidate() -> None:
    candidate = _variant("fts5-unicode61-qwen512-numpy-rrf")
    comparison = compare_retrieval_benchmark(
        baseline_variant=BASELINE_RETRIEVAL_VARIANT,
        baseline_report=_report(recall=0.9),
        candidate_variant=candidate,
        candidate_report=_report(recall=0.8, ndcg=0.9, mrr=0.9),
        policy=_policy(maximum_recall_regression=0.02),
    )

    assert comparison.decision is (
        RetrievalBenchmarkDecision.REJECT_RELEVANCE_REGRESSION
    )


def test_missing_requested_resource_evidence_blocks_adoption() -> None:
    candidate = _variant("fts5-unicode61-qwen512-numpy-rrf")
    comparison = compare_retrieval_benchmark(
        baseline_variant=BASELINE_RETRIEVAL_VARIANT,
        baseline_report=_report(),
        candidate_variant=candidate,
        candidate_report=_report(ndcg=0.85, mrr=0.85, vram=None),
        policy=_policy(),
    )

    assert comparison.decision is (
        RetrievalBenchmarkDecision.INSUFFICIENT_RESOURCE_EVIDENCE
    )
    assert "missing_vram_measurement" in comparison.reason_codes


def test_resource_regression_rejects_candidate() -> None:
    candidate = _variant("fts5-unicode61-qwen1024-numpy-rrf")
    comparison = compare_retrieval_benchmark(
        baseline_variant=BASELINE_RETRIEVAL_VARIANT,
        baseline_report=_report(),
        candidate_variant=candidate,
        candidate_report=_report(
            ndcg=0.9,
            mrr=0.9,
            latency_p95=40.0,
        ),
        policy=_policy(maximum_latency_ratio=1.5),
    )

    assert comparison.decision is (
        RetrievalBenchmarkDecision.REJECT_RESOURCE_REGRESSION
    )
    assert "latency_ratio_exceeds_policy" in comparison.reason_codes


def test_no_meaningful_gain_keeps_baseline() -> None:
    candidate = _variant("fts5-trigram-qwen256-numpy-rrf")
    comparison = compare_retrieval_benchmark(
        baseline_variant=BASELINE_RETRIEVAL_VARIANT,
        baseline_report=_report(),
        candidate_variant=candidate,
        candidate_report=_report(ndcg=0.805, mrr=0.805),
        policy=_policy(),
    )

    assert comparison.decision is RetrievalBenchmarkDecision.NO_MEANINGFUL_BENEFIT


def test_candidate_is_adoptable_only_with_quality_gain_and_bounded_resources() -> None:
    candidate = _variant("fts5-unicode61-qwen512-numpy-rrf")
    comparison = compare_retrieval_benchmark(
        baseline_variant=BASELINE_RETRIEVAL_VARIANT,
        baseline_report=_report(),
        candidate_variant=candidate,
        candidate_report=_report(
            recall=0.81,
            ndcg=0.85,
            mrr=0.83,
            latency_p95=22.0,
            cpu_p95=11.0,
            rss=110.0,
            vram=220.0,
            disk=1050,
        ),
        policy=_policy(),
    )

    assert comparison.decision is RetrievalBenchmarkDecision.ADOPTABLE
    assert comparison.ndcg_gain == pytest.approx(0.05)
    assert comparison.mrr_gain == pytest.approx(0.03)
    assert comparison.latency_ratio == pytest.approx(1.1)


def test_baseline_must_itself_pass_safety_gate() -> None:
    candidate = _variant("fts5-unicode61-qwen512-numpy-rrf")
    with pytest.raises(ValueError, match="baseline benchmark must pass"):
        compare_retrieval_benchmark(
            baseline_variant=BASELINE_RETRIEVAL_VARIANT,
            baseline_report=_report(stale_results=1),
            candidate_variant=candidate,
            candidate_report=_report(ndcg=0.9, mrr=0.9),
            policy=_policy(),
        )
