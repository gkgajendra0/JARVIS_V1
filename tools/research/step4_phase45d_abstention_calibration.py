"""Phase 4.5D research-only semantic retrieval abstention calibration.

This harness uses the actual production first-stage retrieval service and selected
Qwen adapters against a temporary migrated SQLite database populated only with
synthetic/project-style fixtures. It does not read the owner's production memory
store and it does not write a production abstention policy.
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import math
import sqlite3
import statistics
import tempfile
import time
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from jarvis.memory.assertions import SemanticAssertionDraft, SemanticAssertionRecord
from jarvis.memory.embeddings import SemanticEmbeddingStore
from jarvis.memory.lifecycle import MemoryLifecycleService
from jarvis.memory.migration_runner import MemoryMigrationRunner
from jarvis.memory.provenance import MemorySource
from jarvis.memory.retrieval import RetrievalEligibility, SemanticRetrievalService
from jarvis.memory.retrieval_models import Qwen3EmbeddingEncoder, Qwen3RetrievalReranker
from jarvis.memory.types import (
    AuthorityClass,
    FreshnessClass,
    MemorySourceClass,
    Sensitivity,
    ValueType,
)
from jarvis.memory.worker import SerialConnectionWorker

NOW = datetime(2026, 9, 5, 20, 0, tzinfo=UTC)
ALLOWED_SPLITS = frozenset({"calibration", "validation"})
ALLOWED_LABELS = frozenset({"release", "abstain"})
ALLOWED_LANGUAGES = frozenset({"en", "hi", "hinglish"})
POLICY_COMPLEXITY = {
    "score": 1,
    "score_margin": 2,
    "score_dense": 2,
    "score_margin_dense": 3,
}


@dataclass(frozen=True, slots=True)
class CalibrationCaseResult:
    case_id: str
    split: str
    label: str
    expected_memory_id: str | None
    language: str
    category: str
    top_memory_id: str | None
    positive_top1_correct: bool
    positive_hit_at_3: bool
    rerank_score: float
    rerank_margin: float
    dense_score: float
    lexical_rank: int | None
    dense_rank: int | None
    fused_score: float
    query_embedding_ms: float
    retrieval_ms: float
    rerank_ms: float

    @property
    def should_release(self) -> bool:
        return self.label == "release" and self.positive_top1_correct


@dataclass(frozen=True, slots=True)
class ReleasePolicy:
    family: str
    score_threshold: float
    margin_threshold: float | None = None
    dense_threshold: float | None = None

    def releases(self, case: CalibrationCaseResult) -> bool:
        if case.rerank_score < self.score_threshold:
            return False
        if (
            self.margin_threshold is not None
            and case.rerank_margin < self.margin_threshold
        ):
            return False
        return not (
            self.dense_threshold is not None and case.dense_score < self.dense_threshold
        )


def _load_fixture(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported Phase 4.5D corpus schema_version")
    documents = payload.get("documents")
    queries = payload.get("queries")
    if not isinstance(documents, list) or not documents:
        raise ValueError("documents must be a non-empty list")
    if not isinstance(queries, list) or not queries:
        raise ValueError("queries must be a non-empty list")

    doc_ids = [str(item.get("memory_id", "")).strip() for item in documents]
    if any(not value for value in doc_ids) or len(doc_ids) != len(set(doc_ids)):
        raise ValueError("document memory_id values must be non-empty and unique")
    replacement_ids = [
        str(item["replacement_memory_id"]).strip()
        for item in documents
        if item.get("mode") == "historical_transition"
    ]
    all_memory_ids = set(doc_ids) | set(replacement_ids)
    if len(all_memory_ids) != len(doc_ids) + len(replacement_ids):
        raise ValueError("replacement memory IDs must be unique")

    query_ids: set[str] = set()
    counts: Counter[tuple[str, str]] = Counter()
    for item in queries:
        case_id = str(item.get("case_id", "")).strip()
        split = str(item.get("split", "")).strip()
        label = str(item.get("label", "")).strip()
        language = str(item.get("language", "")).strip()
        query = str(item.get("query", "")).strip()
        expected = item.get("expected_memory_id")
        if not case_id or case_id in query_ids:
            raise ValueError("query case_id values must be non-empty and unique")
        query_ids.add(case_id)
        if split not in ALLOWED_SPLITS:
            raise ValueError(f"invalid split for {case_id}: {split}")
        if label not in ALLOWED_LABELS:
            raise ValueError(f"invalid label for {case_id}: {label}")
        if language not in ALLOWED_LANGUAGES:
            raise ValueError(f"invalid language for {case_id}: {language}")
        if not query:
            raise ValueError(f"query must not be empty for {case_id}")
        if label == "release":
            if not isinstance(expected, str) or expected not in all_memory_ids:
                raise ValueError(
                    f"release case {case_id} needs a known expected memory"
                )
        elif expected is not None:
            raise ValueError(
                f"abstain case {case_id} must have expected_memory_id=null"
            )
        counts[(split, label)] += 1

    for split in sorted(ALLOWED_SPLITS):
        for label in sorted(ALLOWED_LABELS):
            if counts[(split, label)] < 8:
                raise ValueError(
                    f"{split}/{label} needs at least 8 cases; got {counts[(split, label)]}"
                )
    return payload


def _id_factory(prefix: str):
    values = itertools.count(1)
    return lambda: f"{prefix}-{next(values):04d}"


def _connection_worker(path: Path) -> SerialConnectionWorker:
    def connection_factory() -> sqlite3.Connection:
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA secure_delete = ON")
        MemoryMigrationRunner(clock=lambda: NOW).apply(connection)
        return connection

    return SerialConnectionWorker(
        connection_factory,
        thread_name="jarvis-phase45d-calibration",
    )


def _sensitivity(mode: str) -> Sensitivity:
    if mode == "local_only":
        return Sensitivity.LOCAL_ONLY
    if mode == "secret":
        return Sensitivity.SECRET_PROHIBITED
    return Sensitivity.STANDARD


def _authority(mode: str) -> AuthorityClass:
    if mode == "untrusted":
        return AuthorityClass.UNTRUSTED
    return AuthorityClass.OWNER_EXPLICIT


def _source(memory_id: str, mode: str, suffix: str = "source") -> MemorySource:
    authority = _authority(mode)
    sensitivity = _sensitivity(mode)
    source_class = (
        MemorySourceClass.EXTERNAL_WEB
        if authority is AuthorityClass.UNTRUSTED
        else MemorySourceClass.OWNER_EXPLICIT
    )
    return MemorySource(
        source_id=f"phase45d:{memory_id}:{suffix}",
        source_class=source_class,
        canonical_ref=f"phase45d:{memory_id}",
        observed_at=NOW,
        authority_class=authority,
        sensitivity=sensitivity,
        created_at=NOW,
    )


def _draft(predicate: str, text: str, mode: str) -> SemanticAssertionDraft:
    sensitivity = _sensitivity(mode)
    return SemanticAssertionDraft(
        subject_scope="owner",
        subject="owner",
        predicate=predicate,
        value_type=ValueType.TEXT,
        value=text,
        normalized_text=text,
        freshness_class=FreshnessClass.STABLE,
        sensitivity=sensitivity,
    )


async def _populate_database(
    payload: dict[str, Any],
    lifecycle: MemoryLifecycleService,
    embeddings: SemanticEmbeddingStore,
    embedder: Qwen3EmbeddingEncoder,
) -> tuple[dict[str, str], dict[str, str]]:
    memory_to_assertion: dict[str, str] = {}
    assertion_to_memory: dict[str, str] = {}
    records_to_embed: list[SemanticAssertionRecord] = []
    forgotten: list[tuple[SemanticAssertionRecord, str]] = []

    for item in payload["documents"]:
        memory_id = str(item["memory_id"])
        predicate = str(item["predicate"])
        mode = str(item["mode"])
        text = str(item["text"])
        source = _source(memory_id, mode)
        record = await lifecycle.create(_draft(predicate, text, mode), source)
        memory_to_assertion[memory_id] = record.assertion_id
        assertion_to_memory[record.assertion_id] = memory_id
        records_to_embed.append(record)

        if mode == "historical_transition":
            replacement_memory_id = str(item["replacement_memory_id"])
            replacement_text = str(item["replacement_text"])
            replacement = await lifecycle.historical_change(
                record.assertion_id,
                _draft(predicate, replacement_text, "current"),
                _source(replacement_memory_id, "current", "transition"),
                effective_at=NOW,
                reason_code="phase45d_fixture_transition",
            )
            memory_to_assertion[replacement_memory_id] = replacement.assertion_id
            assertion_to_memory[replacement.assertion_id] = replacement_memory_id
            records_to_embed.append(replacement)
        elif mode == "forgotten":
            forgotten.append((record, memory_id))

    document_vectors = embedder.encode_documents(
        [record.normalized_text for record in records_to_embed]
    )
    if len(document_vectors) != len(records_to_embed):
        raise RuntimeError(
            "embedding row count does not match Phase 4.5D fixture records"
        )
    for record, vector in zip(records_to_embed, document_vectors, strict=True):
        await embeddings.upsert(
            record.assertion_id,
            normalized_text=record.normalized_text,
            vector=vector,
        )

    for record, memory_id in forgotten:
        forgotten_ok = await lifecycle.forget(
            record.assertion_id,
            _source(memory_id, "current", "forget"),
            reason_code="phase45d_fixture_forget",
        )
        if not forgotten_ok:
            raise RuntimeError(f"failed to forget Phase 4.5D fixture {memory_id}")

    return memory_to_assertion, assertion_to_memory


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(len(ordered) * fraction))
    return round(ordered[index], 4)


def _thresholds(values: Iterable[float]) -> tuple[float, ...]:
    ordered = sorted(set(float(value) for value in values if math.isfinite(value)))
    if not ordered:
        raise ValueError("cannot derive thresholds from an empty score set")
    scale = max(1.0, max(abs(value) for value in ordered))
    epsilon = scale * 1e-6
    candidates = [ordered[0] - epsilon]
    candidates.extend((left + right) / 2.0 for left, right in zip(ordered, ordered[1:]))
    candidates.append(ordered[-1] + epsilon)
    return tuple(candidates)


def _evaluate_policy(
    policy: ReleasePolicy,
    cases: list[CalibrationCaseResult],
) -> dict[str, Any]:
    tp = fp = fn = tn = 0
    released_ids: list[str] = []
    false_release_ids: list[str] = []
    missed_release_ids: list[str] = []
    positive_total = sum(case.label == "release" for case in cases)

    for case in cases:
        released = policy.releases(case)
        target = case.should_release
        if released and target:
            tp += 1
            released_ids.append(case.case_id)
        elif released and not target:
            fp += 1
            false_release_ids.append(case.case_id)
        elif not released and target:
            fn += 1
            missed_release_ids.append(case.case_id)
        else:
            tn += 1

    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / positive_total if positive_total else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": round(precision, 6),
        "positive_release_recall": round(recall, 6),
        "released_case_ids": released_ids,
        "false_release_case_ids": false_release_ids,
        "missed_correct_release_case_ids": missed_release_ids,
    }


def _policy_dict(policy: ReleasePolicy) -> dict[str, Any]:
    return {
        "family": policy.family,
        "score_threshold": round(policy.score_threshold, 8),
        "margin_threshold": (
            round(policy.margin_threshold, 8)
            if policy.margin_threshold is not None
            else None
        ),
        "dense_threshold": (
            round(policy.dense_threshold, 8)
            if policy.dense_threshold is not None
            else None
        ),
    }


def _policy_candidates(
    cases: list[CalibrationCaseResult],
) -> Iterable[ReleasePolicy]:
    score_thresholds = _thresholds(case.rerank_score for case in cases)
    margin_thresholds = _thresholds(case.rerank_margin for case in cases)
    dense_thresholds = _thresholds(case.dense_score for case in cases)

    for score in score_thresholds:
        yield ReleasePolicy("score", score)
    for score in score_thresholds:
        for margin in margin_thresholds:
            yield ReleasePolicy("score_margin", score, margin_threshold=margin)
    for score in score_thresholds:
        for dense in dense_thresholds:
            yield ReleasePolicy("score_dense", score, dense_threshold=dense)
    for score in score_thresholds:
        for margin in margin_thresholds:
            for dense in dense_thresholds:
                yield ReleasePolicy(
                    "score_margin_dense",
                    score,
                    margin_threshold=margin,
                    dense_threshold=dense,
                )


def _select_policy(
    calibration_cases: list[CalibrationCaseResult],
) -> tuple[ReleasePolicy, dict[str, Any], list[dict[str, Any]]]:
    best: tuple[tuple[Any, ...], ReleasePolicy, dict[str, Any]] | None = None
    best_by_metric: dict[
        tuple[str, int, int], tuple[ReleasePolicy, dict[str, Any]]
    ] = {}

    for policy in _policy_candidates(calibration_cases):
        metrics = _evaluate_policy(policy, calibration_cases)
        key = (
            metrics["fp"],
            -metrics["tp"],
            POLICY_COMPLEXITY[policy.family],
            -policy.score_threshold,
            -(
                policy.margin_threshold
                if policy.margin_threshold is not None
                else -math.inf
            ),
            -(
                policy.dense_threshold
                if policy.dense_threshold is not None
                else -math.inf
            ),
            policy.family,
        )
        if best is None or key < best[0]:
            best = (key, policy, metrics)

        metric_key = (policy.family, metrics["fp"], metrics["tp"])
        incumbent = best_by_metric.get(metric_key)
        if incumbent is None:
            best_by_metric[metric_key] = (policy, metrics)
            continue
        incumbent_policy, _ = incumbent
        conservative_key = (
            policy.score_threshold,
            policy.margin_threshold
            if policy.margin_threshold is not None
            else -math.inf,
            policy.dense_threshold if policy.dense_threshold is not None else -math.inf,
        )
        incumbent_key = (
            incumbent_policy.score_threshold,
            incumbent_policy.margin_threshold
            if incumbent_policy.margin_threshold is not None
            else -math.inf,
            incumbent_policy.dense_threshold
            if incumbent_policy.dense_threshold is not None
            else -math.inf,
        )
        if conservative_key > incumbent_key:
            best_by_metric[metric_key] = (policy, metrics)

    if best is None:
        raise RuntimeError("no Phase 4.5D policy candidates were generated")

    _, selected, selected_metrics = best
    frontier_rows = sorted(
        best_by_metric.values(),
        key=lambda item: (
            item[1]["fp"],
            -item[1]["tp"],
            POLICY_COMPLEXITY[item[0].family],
            item[0].family,
        ),
    )[:24]
    frontier = [
        {"policy": _policy_dict(policy), "metrics": metrics}
        for policy, metrics in frontier_rows
    ]
    return selected, selected_metrics, frontier


def _breakdown(
    cases: list[CalibrationCaseResult],
    policy: ReleasePolicy,
    field: str,
) -> dict[str, Any]:
    grouped: dict[str, list[CalibrationCaseResult]] = defaultdict(list)
    for case in cases:
        grouped[str(getattr(case, field))].append(case)
    output: dict[str, Any] = {}
    for key, values in sorted(grouped.items()):
        metrics = _evaluate_policy(policy, values)
        output[key] = {
            "cases": len(values),
            "release_labels": sum(case.label == "release" for case in values),
            "abstain_labels": sum(case.label == "abstain" for case in values),
            "tp": metrics["tp"],
            "fp": metrics["fp"],
            "positive_release_recall": metrics["positive_release_recall"],
        }
    return output


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    import torch

    fixture_path = Path(args.cases).resolve()
    payload = _load_fixture(fixture_path)
    device = None if args.device == "auto" else args.device
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but torch.cuda.is_available() is false")

    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()

    with tempfile.TemporaryDirectory(prefix="jarvis-phase45d-") as temp_dir:
        worker = _connection_worker(Path(temp_dir) / "calibration.db")
        lifecycle = MemoryLifecycleService(
            worker,
            clock=lambda: NOW,
            assertion_id_factory=_id_factory("phase45d-assertion"),
            operation_id_factory=_id_factory("phase45d-operation"),
        )
        embeddings = SemanticEmbeddingStore(worker, clock=lambda: NOW)
        retrieval = SemanticRetrievalService(worker)
        embedder = Qwen3EmbeddingEncoder(device=device)
        reranker = Qwen3RetrievalReranker(device=device)

        try:
            populate_started = time.perf_counter()
            _, assertion_to_memory = await _populate_database(
                payload,
                lifecycle,
                embeddings,
                embedder,
            )
            populate_seconds = time.perf_counter() - populate_started

            results: list[CalibrationCaseResult] = []
            for item in payload["queries"]:
                query = str(item["query"])

                started = time.perf_counter_ns()
                query_vector = embedder.encode_query(query)
                query_embedding_ms = (time.perf_counter_ns() - started) / 1_000_000

                started = time.perf_counter_ns()
                first_stage = await retrieval.retrieve_first_stage(
                    query,
                    query_vector,
                    eligibility=RetrievalEligibility.cloud_context(),
                    limit=3,
                )
                retrieval_ms = (time.perf_counter_ns() - started) / 1_000_000
                if not first_stage:
                    raise RuntimeError(
                        f"first-stage retrieval returned no candidates for {item['case_id']}"
                    )

                started = time.perf_counter_ns()
                reranked = reranker.rerank(query, first_stage)
                rerank_ms = (time.perf_counter_ns() - started) / 1_000_000
                if not reranked:
                    raise RuntimeError(
                        f"reranker returned no candidates for {item['case_id']}"
                    )

                top = reranked[0]
                second_score = (
                    reranked[1].rerank_score
                    if len(reranked) > 1
                    else top.rerank_score
                )
                top_assertion_id = top.candidate.assertion.assertion_id
                top_memory_id = assertion_to_memory.get(top_assertion_id)
                if top_memory_id is None:
                    raise RuntimeError(
                        f"unknown assertion returned by retrieval: {top_assertion_id}"
                    )
                top3_memory_ids = [
                    assertion_to_memory[item_.candidate.assertion.assertion_id]
                    for item_ in reranked
                ]
                expected = item.get("expected_memory_id")
                label = str(item["label"])
                positive_top1_correct = label == "release" and top_memory_id == expected
                positive_hit_at_3 = label == "release" and expected in top3_memory_ids
                dense_score = top.candidate.dense_score
                if dense_score is None or not math.isfinite(dense_score):
                    raise RuntimeError(
                        f"top candidate lacks finite dense score for {item['case_id']}"
                    )

                results.append(
                    CalibrationCaseResult(
                        case_id=str(item["case_id"]),
                        split=str(item["split"]),
                        label=label,
                        expected_memory_id=str(expected)
                        if expected is not None
                        else None,
                        language=str(item["language"]),
                        category=str(item["category"]),
                        top_memory_id=top_memory_id,
                        positive_top1_correct=positive_top1_correct,
                        positive_hit_at_3=positive_hit_at_3,
                        rerank_score=float(top.rerank_score),
                        rerank_margin=float(top.rerank_score - second_score),
                        dense_score=float(dense_score),
                        lexical_rank=top.candidate.lexical_rank,
                        dense_rank=top.candidate.dense_rank,
                        fused_score=float(top.candidate.fused_score),
                        query_embedding_ms=query_embedding_ms,
                        retrieval_ms=retrieval_ms,
                        rerank_ms=rerank_ms,
                    )
                )
        finally:
            await worker.close()

    calibration = [case for case in results if case.split == "calibration"]
    validation = [case for case in results if case.split == "validation"]
    selected, calibration_metrics, frontier = _select_policy(calibration)
    validation_metrics = _evaluate_policy(selected, validation)

    def split_summary(cases: list[CalibrationCaseResult]) -> dict[str, Any]:
        positives = [case for case in cases if case.label == "release"]
        abstains = [case for case in cases if case.label == "abstain"]
        return {
            "cases": len(cases),
            "release_labels": len(positives),
            "abstain_labels": len(abstains),
            "positive_top1_correct": sum(
                case.positive_top1_correct for case in positives
            ),
            "positive_hit_at_3": sum(case.positive_hit_at_3 for case in positives),
            "positive_top1_accuracy": round(
                sum(case.positive_top1_correct for case in positives) / len(positives),
                6,
            ),
            "positive_recall_at_3": round(
                sum(case.positive_hit_at_3 for case in positives) / len(positives), 6
            ),
            "languages": dict(Counter(case.language for case in cases)),
            "categories": dict(Counter(case.category for case in cases)),
        }

    query_times = [case.query_embedding_ms for case in results]
    retrieval_times = [case.retrieval_ms for case in results]
    rerank_times = [case.rerank_ms for case in results]
    peak_cuda = (
        int(torch.cuda.max_memory_allocated()) if torch.cuda.is_available() else None
    )

    validation_pass = validation_metrics["fp"] == 0
    status = "PASS" if validation_pass else "FAIL_VALIDATION_FALSE_RELEASE"

    return {
        "status": status,
        "purpose": "Phase 4.5D research-only abstention calibration; no production threshold auto-write",
        "fixture": fixture_path.name,
        "environment": {
            "device_requested": args.device,
            "torch_version": str(torch.__version__),
            "cuda_runtime": str(torch.version.cuda),
            "cuda_available": bool(torch.cuda.is_available()),
            "device_name": torch.cuda.get_device_name(0)
            if torch.cuda.is_available()
            else None,
        },
        "corpus": {
            "documents": len(payload["documents"]),
            "queries": len(payload["queries"]),
            "calibration": split_summary(calibration),
            "validation": split_summary(validation),
        },
        "timing": {
            "fixture_population_and_document_embedding_seconds": round(
                populate_seconds, 4
            ),
            "query_embedding_ms": {
                "p50": _percentile(query_times, 0.50),
                "p95": _percentile(query_times, 0.95),
                "max": round(max(query_times), 4),
            },
            "first_stage_retrieval_ms": {
                "p50": _percentile(retrieval_times, 0.50),
                "p95": _percentile(retrieval_times, 0.95),
                "max": round(max(retrieval_times), 4),
            },
            "rerank_ms": {
                "p50": _percentile(rerank_times, 0.50),
                "p95": _percentile(rerank_times, 0.95),
                "max": round(max(rerank_times), 4),
            },
            "peak_cuda_bytes": peak_cuda,
        },
        "calibration": {
            "selected_policy": _policy_dict(selected),
            "selected_policy_metrics": calibration_metrics,
            "frontier": frontier,
        },
        "validation": {
            "policy_frozen_from_calibration": _policy_dict(selected),
            "metrics": validation_metrics,
            "pass_no_false_release": validation_pass,
            "language_breakdown": _breakdown(validation, selected, "language"),
            "category_breakdown": _breakdown(validation, selected, "category"),
        },
        "cases": [
            {
                "case_id": case.case_id,
                "split": case.split,
                "label": case.label,
                "expected_memory_id": case.expected_memory_id,
                "language": case.language,
                "category": case.category,
                "top_memory_id": case.top_memory_id,
                "positive_top1_correct": case.positive_top1_correct,
                "positive_hit_at_3": case.positive_hit_at_3,
                "rerank_score": round(case.rerank_score, 6),
                "rerank_margin": round(case.rerank_margin, 6),
                "dense_score": round(case.dense_score, 6),
                "lexical_rank": case.lexical_rank,
                "dense_rank": case.dense_rank,
                "fused_score": round(case.fused_score, 8),
                "would_release_selected_policy": selected.releases(case),
            }
            for case in results
        ],
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cases",
        default="tools/research/step4_phase45d_abstention_cases.json",
        help="Path to the fixed Phase 4.5D corpus JSON",
    )
    parser.add_argument(
        "--device",
        default="cuda",
        help="Local Qwen device: cuda, cpu, or auto",
    )
    parser.add_argument(
        "--output",
        default=".step4-phase45d-abstention-calibration.json",
        help="UTF-8 JSON output path",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    output = asyncio.run(_run(args))
    output_path = Path(args.output)
    output_path.write_text(
        json.dumps(output, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote UTF-8 result: {output_path}")
    print(f"STATUS: {output['status']}")
    print(
        "Selected policy:",
        json.dumps(output["calibration"]["selected_policy"], ensure_ascii=False),
    )
    print(
        "Validation metrics:",
        json.dumps(output["validation"]["metrics"], ensure_ascii=False),
    )
    if output["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
