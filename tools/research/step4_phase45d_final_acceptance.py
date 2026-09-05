"""Final Phase 4.5D research-only retrieval release-policy acceptance harness.

The harness uses a fresh fixed synthetic corpus, the production retrieval path and
the frozen JARVIS-specific Qwen reranker instruction. MAPIE Learn-Then-Test chooses
only from a pre-registered score/margin grid using calibration cases. Held-out
validation is evaluated exactly once and cannot tune the policy.

The synthetic benchmark is not claimed to be exchangeable with future owner
traffic, so MAPIE's distributional guarantee is not promoted as a real-world JARVIS
guarantee. Operational monitoring remains required after deployment.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import tempfile
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import step4_phase45d_abstention_calibration as baseline
import step4_phase45d_final_cases as final_cases

from jarvis.memory.embeddings import SemanticEmbeddingStore
from jarvis.memory.lifecycle import MemoryLifecycleService
from jarvis.memory.retrieval import RetrievalEligibility, SemanticRetrievalService
from jarvis.memory.retrieval_models import (
    JARVIS_MEMORY_RERANK_INSTRUCTION,
    Qwen3EmbeddingEncoder,
    Qwen3RetrievalReranker,
)

MAPIE_REQUIRED_VERSION = "1.5.0"
TARGET_PRECISION = 0.95
CONFIDENCE_LEVEL = 0.95
MIN_VALIDATION_POSITIVE_TOP1_ACCURACY = 0.85
MIN_VALIDATION_POSITIVE_RECALL_AT_3 = 0.90
MIN_VALIDATION_RELEASE_RECALL = 0.40
MIN_VALIDATION_LANGUAGE_RELEASE_RECALL = 0.25
REQUIRE_ZERO_VALIDATION_FALSE_RELEASES = True

# Pre-registered using only retired V1 development evidence. The fresh final corpus
# cannot alter this grid. Keeping 30 candidates avoids an unnecessarily severe
# multiple-testing penalty while still covering score-only rules (margin=0).
SCORE_THRESHOLDS = (-2.0, 0.0, 2.0, 4.0, 6.0, 8.0)
MARGIN_THRESHOLDS = (0.0, 4.0, 8.0, 12.0, 16.0)
PREDICT_PARAMS = np.asarray(
    [(score, margin) for score in SCORE_THRESHOLDS for margin in MARGIN_THRESHOLDS],
    dtype=np.float64,
)


@dataclass(frozen=True, slots=True)
class FinalCaseResult:
    case_id: str
    split: str
    label: str
    expected_memory_id: str | None
    language: str
    category: str
    top_memory_id: str
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
    def safe_to_release(self) -> bool:
        return self.label == "release" and self.positive_top1_correct


def _mapie_controller() -> type[Any]:
    try:
        import mapie
        from mapie.risk_control import BinaryClassificationController
    except ImportError as exc:
        raise RuntimeError(
            "Phase 4.5D final acceptance requires research dependency "
            f"MAPIE=={MAPIE_REQUIRED_VERSION}"
        ) from exc

    installed = str(getattr(mapie, "__version__", "unknown"))
    if installed != MAPIE_REQUIRED_VERSION:
        raise RuntimeError(
            f"expected MAPIE {MAPIE_REQUIRED_VERSION}, found {installed}"
        )
    return BinaryClassificationController


def _release_predict(
    values: Any,
    score_threshold: float,
    margin_threshold: float,
) -> np.ndarray:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 2 or array.shape[1] != 2:
        raise ValueError("release features must have shape (n_cases, 2)")
    return (
        (array[:, 0] >= float(score_threshold))
        & (array[:, 1] >= float(margin_threshold))
    ).astype(np.int64)


def _features(cases: list[FinalCaseResult]) -> np.ndarray:
    return np.asarray(
        [(case.rerank_score, case.rerank_margin) for case in cases],
        dtype=np.float64,
    )


def _safe_labels(cases: list[FinalCaseResult]) -> np.ndarray:
    return np.asarray([case.safe_to_release for case in cases], dtype=np.int64)


def _param_tuple(value: Any) -> tuple[float, float] | None:
    if value is None:
        return None
    array = np.asarray(value, dtype=np.float64).reshape(-1)
    if array.shape != (2,) or not np.all(np.isfinite(array)):
        raise RuntimeError(f"invalid MAPIE prediction parameter: {value!r}")
    return float(array[0]), float(array[1])


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(len(ordered) * fraction))
    return round(ordered[index], 4)


def _ranking_summary(cases: list[FinalCaseResult]) -> dict[str, Any]:
    positives = [case for case in cases if case.label == "release"]
    if not positives:
        raise ValueError("ranking summary requires positive cases")
    return {
        "release_labels": len(positives),
        "positive_top1_correct": sum(case.positive_top1_correct for case in positives),
        "positive_hit_at_3": sum(case.positive_hit_at_3 for case in positives),
        "positive_top1_accuracy": round(
            sum(case.positive_top1_correct for case in positives) / len(positives), 6
        ),
        "positive_recall_at_3": round(
            sum(case.positive_hit_at_3 for case in positives) / len(positives), 6
        ),
    }


def _policy_metrics(
    cases: list[FinalCaseResult],
    params: tuple[float, float] | None,
) -> dict[str, Any]:
    if params is None:
        released = np.zeros(len(cases), dtype=bool)
    else:
        released = _release_predict(_features(cases), *params).astype(bool)

    safe = _safe_labels(cases).astype(bool)
    release_labels = np.asarray([case.label == "release" for case in cases], dtype=bool)
    tp = int(np.sum(released & safe))
    fp = int(np.sum(released & ~safe))
    safe_fn = int(np.sum(~released & safe))
    safe_tn = int(np.sum(~released & ~safe))
    precision = tp / (tp + fp) if tp + fp else 1.0
    positive_release_recall = (
        tp / int(np.sum(release_labels)) if np.any(release_labels) else 0.0
    )
    return {
        "tp": tp,
        "fp": fp,
        "safe_fn": safe_fn,
        "safe_tn": safe_tn,
        "precision": round(precision, 6),
        "positive_release_recall": round(positive_release_recall, 6),
        "released_cases": int(np.sum(released)),
        "released_case_ids": [
            case.case_id
            for case, decision in zip(cases, released, strict=True)
            if decision
        ],
        "false_release_case_ids": [
            case.case_id
            for case, decision, is_safe in zip(cases, released, safe, strict=True)
            if decision and not is_safe
        ],
        "missed_positive_case_ids": [
            case.case_id
            for case, decision in zip(cases, released, strict=True)
            if case.label == "release" and not decision
        ],
    }


def _language_breakdown(
    cases: list[FinalCaseResult],
    params: tuple[float, float] | None,
) -> dict[str, Any]:
    grouped: dict[str, list[FinalCaseResult]] = defaultdict(list)
    for case in cases:
        grouped[case.language].append(case)
    output: dict[str, Any] = {}
    for language, values in sorted(grouped.items()):
        output[language] = {
            "cases": len(values),
            "ranking": _ranking_summary(values),
            "policy": _policy_metrics(values, params),
        }
    return output


def _category_breakdown(
    cases: list[FinalCaseResult],
    params: tuple[float, float] | None,
) -> dict[str, Any]:
    grouped: dict[str, list[FinalCaseResult]] = defaultdict(list)
    for case in cases:
        grouped[case.category].append(case)
    output: dict[str, Any] = {}
    for category, values in sorted(grouped.items()):
        release_values = [case for case in values if case.label == "release"]
        output[category] = {
            "cases": len(values),
            "release_labels": len(release_values),
            "policy": _policy_metrics(values, params),
        }
        if release_values:
            output[category]["ranking"] = _ranking_summary(values)
    return output


def _calibrate_policy(
    calibration: list[FinalCaseResult],
) -> tuple[tuple[float, float] | None, dict[str, Any]]:
    controller_cls = _mapie_controller()
    controller = controller_cls(
        predict_function=_release_predict,
        risk="precision",
        target_level=TARGET_PRECISION,
        confidence_level=CONFIDENCE_LEVEL,
        best_predict_param_choice="recall",
        list_predict_params=PREDICT_PARAMS,
        fwer_method="bonferroni_holm",
    )
    controller.calibrate(_features(calibration), _safe_labels(calibration))
    best = _param_tuple(controller.best_predict_param)
    valid_raw = np.asarray(controller.valid_predict_params, dtype=np.float64)
    if valid_raw.size == 0:
        valid: list[list[float]] = []
    else:
        valid = valid_raw.reshape(-1, 2).tolist()
    return best, {
        "target_precision": TARGET_PRECISION,
        "confidence_level": CONFIDENCE_LEVEL,
        "fwer_method": "bonferroni_holm",
        "best_predict_param_choice": "recall",
        "tested_predict_params": PREDICT_PARAMS.tolist(),
        "tested_predict_param_count": int(len(PREDICT_PARAMS)),
        "valid_predict_params": valid,
        "valid_predict_param_count": len(valid),
        "best_predict_param": list(best) if best is not None else None,
    }


async def _score_cases(
    args: argparse.Namespace,
) -> tuple[list[FinalCaseResult], dict[str, Any]]:
    import torch

    device = None if args.device == "auto" else args.device
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but torch.cuda.is_available() is false")
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()

    payload = final_cases.build_payload()
    with tempfile.TemporaryDirectory(prefix="jarvis-phase45d-final-") as temp_dir:
        worker = baseline._connection_worker(Path(temp_dir) / "final-acceptance.db")
        lifecycle = MemoryLifecycleService(
            worker,
            clock=lambda: baseline.NOW,
            assertion_id_factory=baseline._id_factory("phase45d-final-assertion"),
            operation_id_factory=baseline._id_factory("phase45d-final-operation"),
        )
        embeddings = SemanticEmbeddingStore(worker, clock=lambda: baseline.NOW)
        retrieval = SemanticRetrievalService(worker)
        embedder = Qwen3EmbeddingEncoder(device=device)
        reranker = Qwen3RetrievalReranker(device=device)
        if reranker.instruction != JARVIS_MEMORY_RERANK_INSTRUCTION:
            raise RuntimeError(
                "final acceptance must use the frozen JARVIS reranker instruction"
            )

        try:
            populate_started = time.perf_counter()
            _, assertion_to_memory = await baseline._populate_database(
                payload,
                lifecycle,
                embeddings,
                embedder,
            )
            populate_seconds = time.perf_counter() - populate_started

            results: list[FinalCaseResult] = []
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
                        f"no first-stage candidates for {item['case_id']}"
                    )

                started = time.perf_counter_ns()
                reranked = reranker.rerank(query, first_stage)
                rerank_ms = (time.perf_counter_ns() - started) / 1_000_000
                if not reranked:
                    raise RuntimeError(f"no reranked candidates for {item['case_id']}")

                top = reranked[0]
                second_score = (
                    reranked[1].rerank_score if len(reranked) > 1 else top.rerank_score
                )
                top_memory_id = assertion_to_memory.get(
                    top.candidate.assertion.assertion_id
                )
                if top_memory_id is None:
                    raise RuntimeError(
                        f"unknown assertion returned for {item['case_id']}: "
                        f"{top.candidate.assertion.assertion_id}"
                    )
                top3_memory_ids = [
                    assertion_to_memory[candidate.candidate.assertion.assertion_id]
                    for candidate in reranked
                ]
                expected = item.get("expected_memory_id")
                label = str(item["label"])
                dense_score = top.candidate.dense_score
                if dense_score is None or not math.isfinite(dense_score):
                    raise RuntimeError(f"missing dense score for {item['case_id']}")

                results.append(
                    FinalCaseResult(
                        case_id=str(item["case_id"]),
                        split=str(item["split"]),
                        label=label,
                        expected_memory_id=str(expected)
                        if expected is not None
                        else None,
                        language=str(item["language"]),
                        category=str(item["category"]),
                        top_memory_id=top_memory_id,
                        positive_top1_correct=label == "release"
                        and top_memory_id == expected,
                        positive_hit_at_3=label == "release"
                        and expected in top3_memory_ids,
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

    timing = {
        "fixture_population_and_document_embedding_seconds": round(populate_seconds, 4),
        "query_embedding_ms": {
            "p50": _percentile([case.query_embedding_ms for case in results], 0.50),
            "p95": _percentile([case.query_embedding_ms for case in results], 0.95),
            "max": round(max(case.query_embedding_ms for case in results), 4),
        },
        "first_stage_retrieval_ms": {
            "p50": _percentile([case.retrieval_ms for case in results], 0.50),
            "p95": _percentile([case.retrieval_ms for case in results], 0.95),
            "max": round(max(case.retrieval_ms for case in results), 4),
        },
        "rerank_ms": {
            "p50": _percentile([case.rerank_ms for case in results], 0.50),
            "p95": _percentile([case.rerank_ms for case in results], 0.95),
            "max": round(max(case.rerank_ms for case in results), 4),
        },
        "peak_cuda_bytes": int(torch.cuda.max_memory_allocated())
        if torch.cuda.is_available()
        else None,
    }
    environment = {
        "device_requested": args.device,
        "torch_version": str(torch.__version__),
        "cuda_runtime": str(torch.version.cuda),
        "cuda_available": bool(torch.cuda.is_available()),
        "device_name": torch.cuda.get_device_name(0)
        if torch.cuda.is_available()
        else None,
    }
    return results, {"timing": timing, "environment": environment}


def _acceptance_checks(
    validation: list[FinalCaseResult],
    params: tuple[float, float] | None,
) -> dict[str, Any]:
    ranking = _ranking_summary(validation)
    policy = _policy_metrics(validation, params)
    languages = _language_breakdown(validation, params)
    language_recall = {
        language: details["policy"]["positive_release_recall"]
        for language, details in languages.items()
    }
    checks = {
        "mapie_found_valid_policy": params is not None,
        "validation_positive_top1_accuracy": (
            ranking["positive_top1_accuracy"] >= MIN_VALIDATION_POSITIVE_TOP1_ACCURACY
        ),
        "validation_positive_recall_at_3": (
            ranking["positive_recall_at_3"] >= MIN_VALIDATION_POSITIVE_RECALL_AT_3
        ),
        "validation_zero_false_releases": (
            policy["fp"] == 0 if REQUIRE_ZERO_VALIDATION_FALSE_RELEASES else True
        ),
        "validation_release_recall": (
            policy["positive_release_recall"] >= MIN_VALIDATION_RELEASE_RECALL
        ),
        "validation_language_release_recall": all(
            value >= MIN_VALIDATION_LANGUAGE_RELEASE_RECALL
            for value in language_recall.values()
        ),
    }
    return {
        "thresholds": {
            "min_validation_positive_top1_accuracy": MIN_VALIDATION_POSITIVE_TOP1_ACCURACY,
            "min_validation_positive_recall_at_3": MIN_VALIDATION_POSITIVE_RECALL_AT_3,
            "require_zero_validation_false_releases": REQUIRE_ZERO_VALIDATION_FALSE_RELEASES,
            "min_validation_release_recall": MIN_VALIDATION_RELEASE_RECALL,
            "min_validation_language_release_recall": MIN_VALIDATION_LANGUAGE_RELEASE_RECALL,
        },
        "checks": checks,
        "pass": all(checks.values()),
    }


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    results, runtime = await _score_cases(args)
    calibration = [case for case in results if case.split == "calibration"]
    validation = [case for case in results if case.split == "validation"]
    if len(calibration) != 192 or len(validation) != 128:
        raise RuntimeError("fresh final corpus split size changed unexpectedly")

    best, mapie_summary = _calibrate_policy(calibration)
    calibration_policy = _policy_metrics(calibration, best)
    validation_policy = _policy_metrics(validation, best)
    acceptance = _acceptance_checks(validation, best)
    status = "PASS" if acceptance["pass"] else "FAIL_ACCEPTANCE"

    payload = final_cases.build_payload()
    return {
        "status": status,
        "purpose": "Phase 4.5D final fresh-corpus retrieval release-policy acceptance",
        "final_acceptance_eligible": True,
        "corpus": {
            "schema_version": final_cases.FINAL_CORPUS_SCHEMA_VERSION,
            "sha256": final_cases.payload_sha256(payload),
            "documents": len(payload["documents"]),
            "queries": len(payload["queries"]),
            "calibration": {
                "cases": len(calibration),
                "labels": dict(Counter(case.label for case in calibration)),
                "languages": dict(Counter(case.language for case in calibration)),
                "ranking": _ranking_summary(calibration),
            },
            "validation": {
                "cases": len(validation),
                "labels": dict(Counter(case.label for case in validation)),
                "languages": dict(Counter(case.language for case in validation)),
                "ranking": _ranking_summary(validation),
            },
            "retired_v1_queries_reused": False,
            "exchangeability_claim": False,
            "exchangeability_note": (
                "Synthetic acceptance data are not evidence that future owner traffic is "
                "exchangeable; MAPIE is used for disciplined acceptance calibration only."
            ),
        },
        "reranker": {
            "instruction": JARVIS_MEMORY_RERANK_INSTRUCTION,
        },
        "mapie": mapie_summary,
        "calibration": {
            "policy_metrics": calibration_policy,
            "language_breakdown": _language_breakdown(calibration, best),
            "category_breakdown": _category_breakdown(calibration, best),
        },
        "validation": {
            "policy_metrics": validation_policy,
            "language_breakdown": _language_breakdown(validation, best),
            "category_breakdown": _category_breakdown(validation, best),
        },
        "acceptance": acceptance,
        **runtime,
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
                "safe_to_release": case.safe_to_release,
                "rerank_score": round(case.rerank_score, 6),
                "rerank_margin": round(case.rerank_margin, 6),
                "dense_score": round(case.dense_score, 6),
                "lexical_rank": case.lexical_rank,
                "dense_rank": case.dense_rank,
                "fused_score": round(case.fused_score, 8),
                "would_release": bool(
                    best is not None
                    and _release_predict(
                        np.asarray([[case.rerank_score, case.rerank_margin]]),
                        *best,
                    )[0]
                ),
            }
            for case in results
        ],
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", default="cuda", help="cuda, cpu or auto")
    parser.add_argument(
        "--output",
        default=".step4-phase45d-final-acceptance.json",
        help="UTF-8 result JSON",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    output = asyncio.run(_run(args))
    path = Path(args.output)
    path.write_text(
        json.dumps(output, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote UTF-8 result: {path}")
    print(f"STATUS: {output['status']}")
    print("Corpus SHA256:", output["corpus"]["sha256"])
    print("MAPIE best params:", output["mapie"]["best_predict_param"])
    print("Validation metrics:", json.dumps(output["validation"]["policy_metrics"]))
    print("Acceptance:", json.dumps(output["acceptance"]["checks"]))
    if output["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
