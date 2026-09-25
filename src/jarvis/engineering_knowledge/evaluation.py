"""Deterministic Phase-2 EngineeringKnowledge evaluation harness and metrics."""

from __future__ import annotations

import json
import math
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class EngineeringKnowledgeEvaluationError(ValueError):
    """The evaluation corpus or observation violates the benchmark contract."""


@dataclass(frozen=True, slots=True)
class EvaluationContextFact:
    target_namespace: str
    target_identity: str
    attributes: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        namespace = _required_text(self.target_namespace, "target_namespace").casefold()
        identity = _required_text(self.target_identity, "target_identity")
        normalized_attributes: list[tuple[str, str]] = []
        seen: set[str] = set()
        for key, value in self.attributes:
            normalized_key = _required_text(key, "context attribute key").casefold()
            normalized_value = _required_text(value, f"context attribute {normalized_key}")
            if normalized_key in seen:
                raise EngineeringKnowledgeEvaluationError(
                    f"duplicate context attribute: {normalized_key}"
                )
            seen.add(normalized_key)
            normalized_attributes.append((normalized_key, normalized_value))
        object.__setattr__(self, "target_namespace", namespace)
        object.__setattr__(self, "target_identity", identity)
        object.__setattr__(
            self,
            "attributes",
            tuple(sorted(normalized_attributes)),
        )

    def attributes_dict(self) -> dict[str, str]:
        return dict(self.attributes)


@dataclass(frozen=True, slots=True)
class GradedRelevance:
    document_key: str
    grade: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "document_key",
            _required_text(self.document_key, "document_key"),
        )
        if isinstance(self.grade, bool) or not isinstance(self.grade, int):
            raise TypeError("grade must be an integer")
        if self.grade <= 0:
            raise EngineeringKnowledgeEvaluationError("grade must be positive")


@dataclass(frozen=True, slots=True)
class EngineeringKnowledgeEvaluationCase:
    query_id: str
    query_text: str
    context: tuple[EvaluationContextFact, ...]
    relevant: tuple[GradedRelevance, ...]
    forbidden_document_keys: tuple[str, ...] = ()
    stale_document_keys: tuple[str, ...] = ()
    leakage_document_keys: tuple[str, ...] = ()
    expect_no_answer: bool = False
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "query_id", _required_text(self.query_id, "query_id"))
        object.__setattr__(
            self,
            "query_text",
            _required_text(self.query_text, "query_text"),
        )
        if not isinstance(self.expect_no_answer, bool):
            raise TypeError("expect_no_answer must be a bool")

        relevant_keys = tuple(item.document_key for item in self.relevant)
        if len(set(relevant_keys)) != len(relevant_keys):
            raise EngineeringKnowledgeEvaluationError(
                f"{self.query_id}: duplicate relevant document key"
            )
        if self.expect_no_answer and relevant_keys:
            raise EngineeringKnowledgeEvaluationError(
                f"{self.query_id}: no-answer case cannot contain relevant documents"
            )

        forbidden = _unique_text_tuple(
            self.forbidden_document_keys,
            "forbidden_document_keys",
        )
        stale = _unique_text_tuple(self.stale_document_keys, "stale_document_keys")
        leakage = _unique_text_tuple(
            self.leakage_document_keys,
            "leakage_document_keys",
        )
        tags = tuple(tag.casefold() for tag in _unique_text_tuple(self.tags, "tags"))
        object.__setattr__(self, "forbidden_document_keys", forbidden)
        object.__setattr__(self, "stale_document_keys", stale)
        object.__setattr__(self, "leakage_document_keys", leakage)
        object.__setattr__(self, "tags", tags)

        prohibited = set(forbidden) | set(stale) | set(leakage)
        overlap = set(relevant_keys) & prohibited
        if overlap:
            raise EngineeringKnowledgeEvaluationError(
                f"{self.query_id}: relevant documents cannot also be prohibited: "
                + ",".join(sorted(overlap))
            )


@dataclass(frozen=True, slots=True)
class EngineeringKnowledgeEvaluationCorpus:
    corpus_id: str
    version: int
    cases: tuple[EngineeringKnowledgeEvaluationCase, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "corpus_id",
            _required_text(self.corpus_id, "corpus_id"),
        )
        if isinstance(self.version, bool) or not isinstance(self.version, int):
            raise TypeError("version must be an integer")
        if self.version <= 0:
            raise EngineeringKnowledgeEvaluationError("version must be positive")
        if not self.cases:
            raise EngineeringKnowledgeEvaluationError("corpus must contain cases")
        query_ids = tuple(case.query_id for case in self.cases)
        if len(set(query_ids)) != len(query_ids):
            raise EngineeringKnowledgeEvaluationError(
                "corpus query_id values must be unique"
            )


@dataclass(frozen=True, slots=True)
class EngineeringKnowledgeEvaluationHit:
    document_key: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "document_key",
            _required_text(self.document_key, "document_key"),
        )


@dataclass(frozen=True, slots=True)
class EvaluationResourceSample:
    wall_latency_ms: float
    cpu_time_ms: float
    rss_mb: float | None = None
    vram_mb: float | None = None
    disk_bytes: int | None = None
    rebuild_ms: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "wall_latency_ms",
            _non_negative_finite(self.wall_latency_ms, "wall_latency_ms"),
        )
        object.__setattr__(
            self,
            "cpu_time_ms",
            _non_negative_finite(self.cpu_time_ms, "cpu_time_ms"),
        )
        for field in ("rss_mb", "vram_mb", "rebuild_ms"):
            value = getattr(self, field)
            if value is not None:
                object.__setattr__(
                    self,
                    field,
                    _non_negative_finite(value, field),
                )
        if self.disk_bytes is not None:
            if isinstance(self.disk_bytes, bool) or not isinstance(self.disk_bytes, int):
                raise TypeError("disk_bytes must be an integer")
            if self.disk_bytes < 0:
                raise EngineeringKnowledgeEvaluationError(
                    "disk_bytes must be non-negative"
                )


@dataclass(frozen=True, slots=True)
class EngineeringKnowledgeEvaluationObservation:
    query_id: str
    ranked_hits: tuple[EngineeringKnowledgeEvaluationHit, ...]
    resources: EvaluationResourceSample

    def __post_init__(self) -> None:
        object.__setattr__(self, "query_id", _required_text(self.query_id, "query_id"))
        keys = tuple(hit.document_key for hit in self.ranked_hits)
        if len(set(keys)) != len(keys):
            raise EngineeringKnowledgeEvaluationError(
                f"{self.query_id}: ranked hits must be unique"
            )


@dataclass(frozen=True, slots=True)
class EngineeringKnowledgeEvaluationMetrics:
    k: int
    answerable_case_count: int
    no_answer_case_count: int
    recall_at_k: float
    precision_at_k: float
    mrr: float
    ndcg_at_k: float
    no_answer_false_positive_rate: float
    applicability_violation_rate: float
    stale_result_rate: float
    leakage_rate: float
    returned_hit_count: int
    applicability_violation_count: int
    stale_result_count: int
    leakage_count: int
    no_answer_false_positive_count: int
    latency_p50_ms: float
    latency_p95_ms: float
    cpu_p50_ms: float
    cpu_p95_ms: float
    peak_rss_mb: float | None
    peak_vram_mb: float | None
    max_disk_bytes: int | None
    rebuild_p95_ms: float | None

    @property
    def safety_gate_passed(self) -> bool:
        return (
            self.applicability_violation_count == 0
            and self.stale_result_count == 0
            and self.leakage_count == 0
            and self.no_answer_false_positive_count == 0
        )


@dataclass(frozen=True, slots=True)
class EngineeringKnowledgeEvaluationReport:
    corpus_id: str
    corpus_version: int
    observations: tuple[EngineeringKnowledgeEvaluationObservation, ...]
    metrics: EngineeringKnowledgeEvaluationMetrics


class EngineeringKnowledgeEvaluationRetriever(Protocol):
    def retrieve(
        self,
        case: EngineeringKnowledgeEvaluationCase,
        *,
        limit: int,
    ) -> tuple[EngineeringKnowledgeEvaluationHit, ...]: ...


class EvaluationResourceProbe(Protocol):
    def snapshot(
        self,
    ) -> tuple[float | None, float | None, int | None, float | None]: ...


class NullEvaluationResourceProbe:
    def snapshot(
        self,
    ) -> tuple[float | None, float | None, int | None, float | None]:
        return None, None, None, None


class EngineeringKnowledgeEvaluationHarness:
    """Run a corpus and score relevance, safety and bounded resource observations."""

    def __init__(
        self,
        retriever: EngineeringKnowledgeEvaluationRetriever,
        *,
        resource_probe: EvaluationResourceProbe | None = None,
    ) -> None:
        self._retriever = retriever
        self._resource_probe = resource_probe or NullEvaluationResourceProbe()

    def run(
        self,
        corpus: EngineeringKnowledgeEvaluationCorpus,
        *,
        k: int = 5,
    ) -> EngineeringKnowledgeEvaluationReport:
        _positive_int(k, "k")
        observations: list[EngineeringKnowledgeEvaluationObservation] = []
        for case in corpus.cases:
            wall_start = time.perf_counter()
            cpu_start = time.process_time()
            hits = self._retriever.retrieve(case, limit=k)
            cpu_ms = (time.process_time() - cpu_start) * 1000.0
            wall_ms = (time.perf_counter() - wall_start) * 1000.0
            rss_mb, vram_mb, disk_bytes, rebuild_ms = self._resource_probe.snapshot()
            observations.append(
                EngineeringKnowledgeEvaluationObservation(
                    query_id=case.query_id,
                    ranked_hits=hits,
                    resources=EvaluationResourceSample(
                        wall_latency_ms=wall_ms,
                        cpu_time_ms=cpu_ms,
                        rss_mb=rss_mb,
                        vram_mb=vram_mb,
                        disk_bytes=disk_bytes,
                        rebuild_ms=rebuild_ms,
                    ),
                )
            )
        return score_engineering_knowledge_evaluation(
            corpus,
            tuple(observations),
            k=k,
        )


def load_engineering_knowledge_qrels(
    path: str | Path,
) -> EngineeringKnowledgeEvaluationCorpus:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise EngineeringKnowledgeEvaluationError("qrel corpus root must be an object")
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list):
        raise EngineeringKnowledgeEvaluationError("qrel corpus cases must be a list")

    cases: list[EngineeringKnowledgeEvaluationCase] = []
    for raw_case in raw_cases:
        if not isinstance(raw_case, dict):
            raise EngineeringKnowledgeEvaluationError("qrel case must be an object")
        context = tuple(
            EvaluationContextFact(
                target_namespace=str(item["target_namespace"]),
                target_identity=str(item["target_identity"]),
                attributes=tuple(
                    (str(key), str(value))
                    for key, value in _dict(item.get("attributes", {}), "attributes").items()
                ),
            )
            for item in _list(raw_case.get("context", []), "context")
        )
        relevant = tuple(
            GradedRelevance(
                document_key=str(item["document_key"]),
                grade=int(item["grade"]),
            )
            for item in _list(raw_case.get("relevant", []), "relevant")
        )
        cases.append(
            EngineeringKnowledgeEvaluationCase(
                query_id=str(raw_case["query_id"]),
                query_text=str(raw_case["query_text"]),
                context=context,
                relevant=relevant,
                forbidden_document_keys=tuple(
                    str(item)
                    for item in _list(
                        raw_case.get("forbidden_document_keys", []),
                        "forbidden_document_keys",
                    )
                ),
                stale_document_keys=tuple(
                    str(item)
                    for item in _list(
                        raw_case.get("stale_document_keys", []),
                        "stale_document_keys",
                    )
                ),
                leakage_document_keys=tuple(
                    str(item)
                    for item in _list(
                        raw_case.get("leakage_document_keys", []),
                        "leakage_document_keys",
                    )
                ),
                expect_no_answer=bool(raw_case.get("expect_no_answer", False)),
                tags=tuple(
                    str(item) for item in _list(raw_case.get("tags", []), "tags")
                ),
            )
        )
    return EngineeringKnowledgeEvaluationCorpus(
        corpus_id=str(payload.get("corpus_id", "")),
        version=int(payload.get("version", 0)),
        cases=tuple(cases),
    )


def score_engineering_knowledge_evaluation(
    corpus: EngineeringKnowledgeEvaluationCorpus,
    observations: tuple[EngineeringKnowledgeEvaluationObservation, ...],
    *,
    k: int = 5,
) -> EngineeringKnowledgeEvaluationReport:
    _positive_int(k, "k")
    observed = {item.query_id: item for item in observations}
    expected_ids = {case.query_id for case in corpus.cases}
    if set(observed) != expected_ids:
        missing = sorted(expected_ids - set(observed))
        extra = sorted(set(observed) - expected_ids)
        raise EngineeringKnowledgeEvaluationError(
            f"observation query IDs mismatch: missing={missing}, extra={extra}"
        )

    recalls: list[float] = []
    precisions: list[float] = []
    reciprocal_ranks: list[float] = []
    ndcgs: list[float] = []
    no_answer_false_positive_count = 0
    applicability_violation_count = 0
    stale_result_count = 0
    leakage_count = 0
    returned_hit_count = 0
    no_answer_case_count = 0
    answerable_case_count = 0

    resources: list[EvaluationResourceSample] = []

    for case in corpus.cases:
        observation = observed[case.query_id]
        resources.append(observation.resources)
        ranked = tuple(hit.document_key for hit in observation.ranked_hits[:k])
        returned_hit_count += len(ranked)

        forbidden = set(case.forbidden_document_keys)
        stale = set(case.stale_document_keys)
        leakage = set(case.leakage_document_keys)
        applicability_violation_count += sum(key in forbidden for key in ranked)
        stale_result_count += sum(key in stale for key in ranked)
        leakage_count += sum(key in leakage for key in ranked)

        if case.expect_no_answer:
            no_answer_case_count += 1
            if ranked:
                no_answer_false_positive_count += 1
            continue

        answerable_case_count += 1
        grades = {item.document_key: item.grade for item in case.relevant}
        relevant_keys = set(grades)
        retrieved_relevant = sum(key in relevant_keys for key in ranked)
        recalls.append(
            retrieved_relevant / len(relevant_keys) if relevant_keys else 0.0
        )
        precisions.append(retrieved_relevant / k)

        first_rank = next(
            (rank for rank, key in enumerate(ranked, start=1) if key in relevant_keys),
            None,
        )
        reciprocal_ranks.append(0.0 if first_rank is None else 1.0 / first_rank)
        ndcgs.append(_ndcg_at_k(ranked, grades, k))

    wall = [item.wall_latency_ms for item in resources]
    cpu = [item.cpu_time_ms for item in resources]
    rss = [item.rss_mb for item in resources if item.rss_mb is not None]
    vram = [item.vram_mb for item in resources if item.vram_mb is not None]
    disk = [item.disk_bytes for item in resources if item.disk_bytes is not None]
    rebuild = [item.rebuild_ms for item in resources if item.rebuild_ms is not None]

    metrics = EngineeringKnowledgeEvaluationMetrics(
        k=k,
        answerable_case_count=answerable_case_count,
        no_answer_case_count=no_answer_case_count,
        recall_at_k=_mean(recalls),
        precision_at_k=_mean(precisions),
        mrr=_mean(reciprocal_ranks),
        ndcg_at_k=_mean(ndcgs),
        no_answer_false_positive_rate=(
            no_answer_false_positive_count / no_answer_case_count
            if no_answer_case_count
            else 0.0
        ),
        applicability_violation_rate=(
            applicability_violation_count / returned_hit_count
            if returned_hit_count
            else 0.0
        ),
        stale_result_rate=(
            stale_result_count / returned_hit_count if returned_hit_count else 0.0
        ),
        leakage_rate=leakage_count / returned_hit_count if returned_hit_count else 0.0,
        returned_hit_count=returned_hit_count,
        applicability_violation_count=applicability_violation_count,
        stale_result_count=stale_result_count,
        leakage_count=leakage_count,
        no_answer_false_positive_count=no_answer_false_positive_count,
        latency_p50_ms=_percentile(wall, 50.0),
        latency_p95_ms=_percentile(wall, 95.0),
        cpu_p50_ms=_percentile(cpu, 50.0),
        cpu_p95_ms=_percentile(cpu, 95.0),
        peak_rss_mb=max(rss) if rss else None,
        peak_vram_mb=max(vram) if vram else None,
        max_disk_bytes=max(disk) if disk else None,
        rebuild_p95_ms=_percentile(rebuild, 95.0) if rebuild else None,
    )
    return EngineeringKnowledgeEvaluationReport(
        corpus_id=corpus.corpus_id,
        corpus_version=corpus.version,
        observations=observations,
        metrics=metrics,
    )


def _ndcg_at_k(
    ranked: tuple[str, ...],
    grades: dict[str, int],
    k: int,
) -> float:
    gains = [grades.get(key, 0) for key in ranked[:k]]
    dcg = sum(
        ((2**grade) - 1) / math.log2(rank + 1)
        for rank, grade in enumerate(gains, start=1)
    )
    ideal_grades = sorted(grades.values(), reverse=True)[:k]
    idcg = sum(
        ((2**grade) - 1) / math.log2(rank + 1)
        for rank, grade in enumerate(ideal_grades, start=1)
    )
    return 0.0 if idcg == 0.0 else dcg / idcg


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile / 100.0
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    normalized = value.strip()
    if not normalized:
        raise EngineeringKnowledgeEvaluationError(f"{field} must not be empty")
    return normalized


def _unique_text_tuple(values: tuple[str, ...], field: str) -> tuple[str, ...]:
    normalized = tuple(_required_text(value, field) for value in values)
    if len(set(normalized)) != len(normalized):
        raise EngineeringKnowledgeEvaluationError(f"{field} must be unique")
    return normalized


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be an integer")
    if value <= 0:
        raise EngineeringKnowledgeEvaluationError(f"{field} must be positive")
    return value


def _non_negative_finite(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{field} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0.0:
        raise EngineeringKnowledgeEvaluationError(
            f"{field} must be finite and non-negative"
        )
    return normalized


def _list(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise EngineeringKnowledgeEvaluationError(f"{field} must be a list")
    return value


def _dict(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise EngineeringKnowledgeEvaluationError(f"{field} must be an object")
    return value
