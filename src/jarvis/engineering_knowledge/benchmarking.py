"""Phase-2I retrieval experiment matrix and evidence-based adoption gates."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from jarvis.engineering_knowledge.evaluation import (
    EngineeringKnowledgeEvaluationReport,
)
from jarvis.memory.embeddings import (
    QWEN3_EMBEDDING_MODEL_ID,
    QWEN3_EMBEDDING_REVISION,
    EmbeddingContract,
)
from jarvis.memory.retrieval_models import (
    QWEN3_RERANKER_MODEL_ID,
    QWEN3_RERANKER_REVISION,
)

def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


def _non_negative_float(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{field} must be numeric")
    normalized = float(value)
    if normalized < 0.0:
        raise ValueError(f"{field} must be non-negative")
    return normalized


def _positive_float(value: object, field: str) -> float:
    normalized = _non_negative_float(value, field)
    if normalized <= 0.0:
        raise ValueError(f"{field} must be positive")
    return normalized



class RetrievalExperimentReadiness(StrEnum):
    CURRENT_BASELINE = "current_baseline"
    BUILTIN_EXPERIMENT = "builtin_experiment"
    OPTIONAL_DEPENDENCY = "optional_dependency"


@dataclass(frozen=True, slots=True)
class RetrievalExperimentVariant:
    variant_id: str
    embedding_dimension: int
    fts_tokenizer: str
    vector_backend: str
    reranker_model_id: str | None
    reranker_model_revision: str | None
    reranker_top_k: int | None
    readiness: RetrievalExperimentReadiness
    required_capabilities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "variant_id",
            _required_text(self.variant_id, "variant_id"),
        )
        if isinstance(self.embedding_dimension, bool) or not isinstance(
            self.embedding_dimension, int
        ):
            raise TypeError("embedding_dimension must be an integer")
        if self.embedding_dimension <= 0:
            raise ValueError("embedding_dimension must be positive")
        object.__setattr__(
            self,
            "fts_tokenizer",
            _required_text(self.fts_tokenizer, "fts_tokenizer"),
        )
        object.__setattr__(
            self,
            "vector_backend",
            _required_text(self.vector_backend, "vector_backend"),
        )
        if self.reranker_model_id is None:
            if (
                self.reranker_model_revision is not None
                or self.reranker_top_k is not None
            ):
                raise ValueError("reranker revision/top-k require a reranker model")
        else:
            object.__setattr__(
                self,
                "reranker_model_id",
                _required_text(self.reranker_model_id, "reranker_model_id"),
            )
            object.__setattr__(
                self,
                "reranker_model_revision",
                _required_text(
                    self.reranker_model_revision,
                    "reranker_model_revision",
                ),
            )
            if isinstance(self.reranker_top_k, bool) or not isinstance(
                self.reranker_top_k, int
            ):
                raise TypeError("reranker_top_k must be an integer")
            if self.reranker_top_k <= 0:
                raise ValueError("reranker_top_k must be positive")
        if not isinstance(self.readiness, RetrievalExperimentReadiness):
            raise TypeError("readiness must be a RetrievalExperimentReadiness")
        normalized_capabilities = tuple(
            _required_text(item, "required_capability")
            for item in self.required_capabilities
        )
        if len(set(normalized_capabilities)) != len(normalized_capabilities):
            raise ValueError("required_capabilities must be unique")
        object.__setattr__(
            self,
            "required_capabilities",
            normalized_capabilities,
        )


BASELINE_RETRIEVAL_VARIANT = RetrievalExperimentVariant(
    variant_id="fts5-unicode61-qwen256-numpy-rrf",
    embedding_dimension=256,
    fts_tokenizer="unicode61 remove_diacritics 2",
    vector_backend="numpy_exact",
    reranker_model_id=None,
    reranker_model_revision=None,
    reranker_top_k=None,
    readiness=RetrievalExperimentReadiness.CURRENT_BASELINE,
)

PHASE2I_RETRIEVAL_VARIANTS: tuple[RetrievalExperimentVariant, ...] = (
    BASELINE_RETRIEVAL_VARIANT,
    RetrievalExperimentVariant(
        variant_id="fts5-unicode61-qwen512-numpy-rrf",
        embedding_dimension=512,
        fts_tokenizer="unicode61 remove_diacritics 2",
        vector_backend="numpy_exact",
        reranker_model_id=None,
        reranker_model_revision=None,
        reranker_top_k=None,
        readiness=RetrievalExperimentReadiness.BUILTIN_EXPERIMENT,
    ),
    RetrievalExperimentVariant(
        variant_id="fts5-unicode61-qwen1024-numpy-rrf",
        embedding_dimension=1024,
        fts_tokenizer="unicode61 remove_diacritics 2",
        vector_backend="numpy_exact",
        reranker_model_id=None,
        reranker_model_revision=None,
        reranker_top_k=None,
        readiness=RetrievalExperimentReadiness.BUILTIN_EXPERIMENT,
    ),
    RetrievalExperimentVariant(
        variant_id="fts5-trigram-qwen256-numpy-rrf",
        embedding_dimension=256,
        fts_tokenizer="trigram",
        vector_backend="numpy_exact",
        reranker_model_id=None,
        reranker_model_revision=None,
        reranker_top_k=None,
        readiness=RetrievalExperimentReadiness.BUILTIN_EXPERIMENT,
        required_capabilities=("sqlite_fts5_trigram",),
    ),
    RetrievalExperimentVariant(
        variant_id="fts5-unicode61-qwen256-numpy-rrf-rerank3",
        embedding_dimension=256,
        fts_tokenizer="unicode61 remove_diacritics 2",
        vector_backend="numpy_exact",
        reranker_model_id=QWEN3_RERANKER_MODEL_ID,
        reranker_model_revision=QWEN3_RERANKER_REVISION,
        reranker_top_k=3,
        readiness=RetrievalExperimentReadiness.BUILTIN_EXPERIMENT,
        required_capabilities=("local_qwen_reranker",),
    ),
    RetrievalExperimentVariant(
        variant_id="fts5-unicode61-qwen256-sqlite-vec-rrf",
        embedding_dimension=256,
        fts_tokenizer="unicode61 remove_diacritics 2",
        vector_backend="sqlite-vec",
        reranker_model_id=None,
        reranker_model_revision=None,
        reranker_top_k=None,
        readiness=RetrievalExperimentReadiness.OPTIONAL_DEPENDENCY,
        required_capabilities=("sqlite_vec_extension",),
    ),
    RetrievalExperimentVariant(
        variant_id="fts5-unicode61-qwen256-lancedb-rrf",
        embedding_dimension=256,
        fts_tokenizer="unicode61 remove_diacritics 2",
        vector_backend="lancedb",
        reranker_model_id=None,
        reranker_model_revision=None,
        reranker_top_k=None,
        readiness=RetrievalExperimentReadiness.OPTIONAL_DEPENDENCY,
        required_capabilities=("lancedb",),
    ),
    RetrievalExperimentVariant(
        variant_id="fts5-unicode61-qwen256-qdrant-rrf",
        embedding_dimension=256,
        fts_tokenizer="unicode61 remove_diacritics 2",
        vector_backend="qdrant",
        reranker_model_id=None,
        reranker_model_revision=None,
        reranker_top_k=None,
        readiness=RetrievalExperimentReadiness.OPTIONAL_DEPENDENCY,
        required_capabilities=("qdrant",),
    ),
)


def build_qwen3_experiment_contract(dimension: int) -> EmbeddingContract:
    if dimension not in {256, 512, 1024}:
        raise ValueError("Phase-2I Qwen experiment dimension must be 256, 512, or 1024")
    return EmbeddingContract(
        model_id=QWEN3_EMBEDDING_MODEL_ID,
        model_revision=QWEN3_EMBEDDING_REVISION,
        dimension=dimension,
    )


@dataclass(frozen=True, slots=True)
class RetrievalBenchmarkAdoptionPolicy:
    minimum_ndcg_gain: float
    minimum_mrr_gain: float
    maximum_recall_regression: float
    maximum_latency_ratio: float
    maximum_cpu_ratio: float
    maximum_rss_ratio: float | None = None
    maximum_vram_ratio: float | None = None
    maximum_disk_ratio: float | None = None

    def __post_init__(self) -> None:
        for field in (
            "minimum_ndcg_gain",
            "minimum_mrr_gain",
            "maximum_recall_regression",
        ):
            value = _non_negative_float(getattr(self, field), field)
            object.__setattr__(self, field, value)
        for field in ("maximum_latency_ratio", "maximum_cpu_ratio"):
            value = _positive_float(getattr(self, field), field)
            object.__setattr__(self, field, value)
        for field in (
            "maximum_rss_ratio",
            "maximum_vram_ratio",
            "maximum_disk_ratio",
        ):
            value = getattr(self, field)
            if value is not None:
                object.__setattr__(
                    self,
                    field,
                    _positive_float(value, field),
                )


class RetrievalBenchmarkDecision(StrEnum):
    ADOPTABLE = "adoptable"
    REJECT_SAFETY = "reject_safety"
    REJECT_RELEVANCE_REGRESSION = "reject_relevance_regression"
    REJECT_RESOURCE_REGRESSION = "reject_resource_regression"
    NO_MEANINGFUL_BENEFIT = "no_meaningful_benefit"
    INSUFFICIENT_RESOURCE_EVIDENCE = "insufficient_resource_evidence"


@dataclass(frozen=True, slots=True)
class RetrievalBenchmarkComparison:
    baseline_variant_id: str
    candidate_variant_id: str
    decision: RetrievalBenchmarkDecision
    reason_codes: tuple[str, ...]
    ndcg_gain: float
    mrr_gain: float
    recall_delta: float
    latency_ratio: float | None
    cpu_ratio: float | None
    rss_ratio: float | None
    vram_ratio: float | None
    disk_ratio: float | None


def compare_retrieval_benchmark(
    *,
    baseline_variant: RetrievalExperimentVariant,
    baseline_report: EngineeringKnowledgeEvaluationReport,
    candidate_variant: RetrievalExperimentVariant,
    candidate_report: EngineeringKnowledgeEvaluationReport,
    policy: RetrievalBenchmarkAdoptionPolicy,
) -> RetrievalBenchmarkComparison:
    if baseline_variant.variant_id == candidate_variant.variant_id:
        raise ValueError("baseline and candidate variants must be different")
    if not baseline_report.metrics.safety_gate_passed:
        raise ValueError("baseline benchmark must pass the zero-tolerance safety gate")
    if baseline_report.corpus_id != candidate_report.corpus_id:
        raise ValueError("benchmark reports must use the same corpus_id")
    if baseline_report.corpus_version != candidate_report.corpus_version:
        raise ValueError("benchmark reports must use the same corpus version")
    if baseline_report.metrics.k != candidate_report.metrics.k:
        raise ValueError("benchmark reports must use the same K")

    baseline = baseline_report.metrics
    candidate = candidate_report.metrics
    ndcg_gain = candidate.ndcg_at_k - baseline.ndcg_at_k
    mrr_gain = candidate.mrr - baseline.mrr
    recall_delta = candidate.recall_at_k - baseline.recall_at_k

    ratios = {
        "latency": _ratio(candidate.latency_p95_ms, baseline.latency_p95_ms),
        "cpu": _ratio(candidate.cpu_p95_ms, baseline.cpu_p95_ms),
        "rss": _optional_ratio(candidate.peak_rss_mb, baseline.peak_rss_mb),
        "vram": _optional_ratio(candidate.peak_vram_mb, baseline.peak_vram_mb),
        "disk": _optional_ratio(
            _float_or_none(candidate.max_disk_bytes),
            _float_or_none(baseline.max_disk_bytes),
        ),
    }

    reasons: list[str] = []
    if not candidate.safety_gate_passed:
        reasons.append("candidate_failed_zero_tolerance_safety_gate")
        return _comparison(
            baseline_variant,
            candidate_variant,
            RetrievalBenchmarkDecision.REJECT_SAFETY,
            reasons,
            ndcg_gain,
            mrr_gain,
            recall_delta,
            ratios,
        )

    if recall_delta < -policy.maximum_recall_regression:
        reasons.append("recall_regression_exceeds_policy")
        return _comparison(
            baseline_variant,
            candidate_variant,
            RetrievalBenchmarkDecision.REJECT_RELEVANCE_REGRESSION,
            reasons,
            ndcg_gain,
            mrr_gain,
            recall_delta,
            ratios,
        )

    missing_resources = _missing_required_resources(ratios, policy)
    if missing_resources:
        reasons.extend(f"missing_{name}_measurement" for name in missing_resources)
        return _comparison(
            baseline_variant,
            candidate_variant,
            RetrievalBenchmarkDecision.INSUFFICIENT_RESOURCE_EVIDENCE,
            reasons,
            ndcg_gain,
            mrr_gain,
            recall_delta,
            ratios,
        )

    resource_regressions = _resource_regressions(ratios, policy)
    if resource_regressions:
        reasons.extend(f"{name}_ratio_exceeds_policy" for name in resource_regressions)
        return _comparison(
            baseline_variant,
            candidate_variant,
            RetrievalBenchmarkDecision.REJECT_RESOURCE_REGRESSION,
            reasons,
            ndcg_gain,
            mrr_gain,
            recall_delta,
            ratios,
        )

    meaningful = (
        ndcg_gain >= policy.minimum_ndcg_gain or mrr_gain >= policy.minimum_mrr_gain
    )
    if not meaningful:
        reasons.append("relevance_gain_below_measured_policy_threshold")
        return _comparison(
            baseline_variant,
            candidate_variant,
            RetrievalBenchmarkDecision.NO_MEANINGFUL_BENEFIT,
            reasons,
            ndcg_gain,
            mrr_gain,
            recall_delta,
            ratios,
        )

    reasons.append("candidate_improves_relevance_within_resource_and_safety_policy")
    return _comparison(
        baseline_variant,
        candidate_variant,
        RetrievalBenchmarkDecision.ADOPTABLE,
        reasons,
        ndcg_gain,
        mrr_gain,
        recall_delta,
        ratios,
    )


def _comparison(
    baseline_variant: RetrievalExperimentVariant,
    candidate_variant: RetrievalExperimentVariant,
    decision: RetrievalBenchmarkDecision,
    reasons: list[str],
    ndcg_gain: float,
    mrr_gain: float,
    recall_delta: float,
    ratios: dict[str, float | None],
) -> RetrievalBenchmarkComparison:
    return RetrievalBenchmarkComparison(
        baseline_variant_id=baseline_variant.variant_id,
        candidate_variant_id=candidate_variant.variant_id,
        decision=decision,
        reason_codes=tuple(reasons),
        ndcg_gain=ndcg_gain,
        mrr_gain=mrr_gain,
        recall_delta=recall_delta,
        latency_ratio=ratios["latency"],
        cpu_ratio=ratios["cpu"],
        rss_ratio=ratios["rss"],
        vram_ratio=ratios["vram"],
        disk_ratio=ratios["disk"],
    )


def _missing_required_resources(
    ratios: dict[str, float | None],
    policy: RetrievalBenchmarkAdoptionPolicy,
) -> tuple[str, ...]:
    missing: list[str] = [name for name in ("latency", "cpu") if ratios[name] is None]
    for name, limit in (
        ("rss", policy.maximum_rss_ratio),
        ("vram", policy.maximum_vram_ratio),
        ("disk", policy.maximum_disk_ratio),
    ):
        if limit is not None and ratios[name] is None:
            missing.append(name)
    return tuple(missing)


def _resource_regressions(
    ratios: dict[str, float | None],
    policy: RetrievalBenchmarkAdoptionPolicy,
) -> tuple[str, ...]:
    checks = (
        ("latency", policy.maximum_latency_ratio),
        ("cpu", policy.maximum_cpu_ratio),
        ("rss", policy.maximum_rss_ratio),
        ("vram", policy.maximum_vram_ratio),
        ("disk", policy.maximum_disk_ratio),
    )
    return tuple(
        name
        for name, limit in checks
        if limit is not None and ratios[name] is not None and ratios[name] > limit
    )


def _ratio(candidate: float, baseline: float) -> float | None:
    if baseline <= 0.0:
        return None if candidate > 0.0 else 1.0
    return candidate / baseline


def _optional_ratio(
    candidate: float | None,
    baseline: float | None,
) -> float | None:
    if candidate is None or baseline is None:
        return None
    return _ratio(candidate, baseline)


def _float_or_none(value: int | None) -> float | None:
    return None if value is None else float(value)


