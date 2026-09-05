"""Development-only Qwen reranker instruction bake-off for Phase 4.5D.

The V1 64-case corpus has been retired from final acceptance. This harness reuses
that corpus only to compare the current generic Qwen reranker instruction against
one pre-registered JARVIS-memory-specific instruction. It never writes a
production release policy.
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import json
import math
import tempfile
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import step4_phase45d_abstention_calibration as baseline

from jarvis.memory.embeddings import SemanticEmbeddingStore
from jarvis.memory.lifecycle import MemoryLifecycleService
from jarvis.memory.retrieval import RetrievalEligibility, RetrievalCandidate, SemanticRetrievalService
from jarvis.memory.retrieval_models import (
    JARVIS_MEMORY_RERANK_INSTRUCTION,
    Qwen3EmbeddingEncoder,
    Qwen3RetrievalReranker,
)


@dataclass(frozen=True, slots=True)
class DevCase:
    case_id: str
    label: str
    language: str
    category: str
    expected_memory_id: str | None
    top_memory_id: str
    positive_top1_correct: bool
    positive_hit_at_3: bool
    rerank_score: float
    rerank_margin: float
    rerank_ms: float

    @property
    def safe_to_release(self) -> bool:
        return self.label == "release" and self.positive_top1_correct


@dataclass(frozen=True, slots=True)
class CachedFirstStage:
    item: dict[str, Any]
    query: str
    candidates: tuple[RetrievalCandidate, ...]


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(len(ordered) * fraction))
    return round(ordered[index], 4)


def _binary_auc(cases: list[DevCase], value_name: str) -> float | None:
    positives = [case for case in cases if case.safe_to_release]
    negatives = [case for case in cases if not case.safe_to_release]
    if not positives or not negatives:
        return None
    wins = 0.0
    for positive in positives:
        positive_value = float(getattr(positive, value_name))
        for negative in negatives:
            negative_value = float(getattr(negative, value_name))
            if positive_value > negative_value:
                wins += 1.0
            elif positive_value == negative_value:
                wins += 0.5
    return round(wins / (len(positives) * len(negatives)), 6)


def _risk_coverage(cases: list[DevCase]) -> dict[str, Any]:
    ordered = sorted(
        cases,
        key=lambda case: (-case.rerank_score, -case.rerank_margin, case.case_id),
    )
    if not ordered:
        raise ValueError("risk-coverage requires at least one case")

    cumulative_errors = 0
    risk_values: list[float] = []
    zero_error_prefix = 0
    for index, case in enumerate(ordered, start=1):
        if not case.safe_to_release:
            cumulative_errors += 1
        elif cumulative_errors == 0:
            zero_error_prefix = index
        risk_values.append(cumulative_errors / index)

    release_total = sum(case.label == "release" for case in cases)
    zero_error_safe = sum(case.safe_to_release for case in ordered[:zero_error_prefix])
    return {
        "aurc": round(sum(risk_values) / len(risk_values), 6),
        "zero_error_prefix_cases": zero_error_prefix,
        "zero_error_coverage": round(zero_error_prefix / len(ordered), 6),
        "zero_error_positive_release_recall": round(
            zero_error_safe / release_total if release_total else 0.0,
            6,
        ),
    }


def _score_distribution(cases: list[DevCase]) -> dict[str, Any]:
    safe_scores = sorted(case.rerank_score for case in cases if case.safe_to_release)
    unsafe_scores = sorted(case.rerank_score for case in cases if not case.safe_to_release)
    if not safe_scores or not unsafe_scores:
        return {}

    def median(values: list[float]) -> float:
        midpoint = len(values) // 2
        if len(values) % 2:
            return float(values[midpoint])
        return float((values[midpoint - 1] + values[midpoint]) / 2.0)

    return {
        "safe_min": round(min(safe_scores), 6),
        "safe_median": round(median(safe_scores), 6),
        "safe_max": round(max(safe_scores), 6),
        "unsafe_min": round(min(unsafe_scores), 6),
        "unsafe_median": round(median(unsafe_scores), 6),
        "unsafe_max": round(max(unsafe_scores), 6),
        "min_safe_minus_max_unsafe": round(min(safe_scores) - max(unsafe_scores), 6),
    }


def _language_breakdown(cases: list[DevCase]) -> dict[str, Any]:
    grouped: dict[str, list[DevCase]] = defaultdict(list)
    for case in cases:
        grouped[case.language].append(case)

    output: dict[str, Any] = {}
    for language, values in sorted(grouped.items()):
        positives = [case for case in values if case.label == "release"]
        output[language] = {
            "cases": len(values),
            "release_labels": len(positives),
            "positive_top1_correct": sum(case.positive_top1_correct for case in positives),
            "positive_top1_accuracy": round(
                sum(case.positive_top1_correct for case in positives) / len(positives)
                if positives
                else 0.0,
                6,
            ),
        }
    return output


def _summary(cases: list[DevCase]) -> dict[str, Any]:
    positives = [case for case in cases if case.label == "release"]
    rerank_times = [case.rerank_ms for case in cases]
    return {
        "cases": len(cases),
        "release_labels": len(positives),
        "positive_top1_correct": sum(case.positive_top1_correct for case in positives),
        "positive_hit_at_3": sum(case.positive_hit_at_3 for case in positives),
        "positive_top1_accuracy": round(
            sum(case.positive_top1_correct for case in positives) / len(positives),
            6,
        ),
        "positive_recall_at_3": round(
            sum(case.positive_hit_at_3 for case in positives) / len(positives),
            6,
        ),
        "score_auroc_safe_vs_unsafe": _binary_auc(cases, "rerank_score"),
        "margin_auroc_safe_vs_unsafe": _binary_auc(cases, "rerank_margin"),
        "risk_coverage": _risk_coverage(cases),
        "score_distribution": _score_distribution(cases),
        "language_breakdown": _language_breakdown(cases),
        "rerank_ms": {
            "p50": _percentile(rerank_times, 0.50),
            "p95": _percentile(rerank_times, 0.95),
            "max": round(max(rerank_times), 4),
        },
    }


def _custom_has_language_regression(default: dict[str, Any], custom: dict[str, Any]) -> bool:
    default_languages = default["language_breakdown"]
    custom_languages = custom["language_breakdown"]
    for language in ("en", "hi", "hinglish"):
        if custom_languages[language]["positive_top1_accuracy"] < default_languages[language][
            "positive_top1_accuracy"
        ]:
            return True
    return False


def _recommend(default: dict[str, Any], custom: dict[str, Any]) -> dict[str, Any]:
    if _custom_has_language_regression(default, custom):
        return {
            "mode": "default",
            "reason": "custom_instruction_regressed_at_least_one_language_top1_accuracy",
        }

    default_key = (
        -default["positive_top1_accuracy"],
        default["risk_coverage"]["aurc"],
        -(default["score_auroc_safe_vs_unsafe"] or -math.inf),
        -default["risk_coverage"]["zero_error_positive_release_recall"],
        0,
    )
    custom_key = (
        -custom["positive_top1_accuracy"],
        custom["risk_coverage"]["aurc"],
        -(custom["score_auroc_safe_vs_unsafe"] or -math.inf),
        -custom["risk_coverage"]["zero_error_positive_release_recall"],
        1,
    )
    if custom_key < default_key:
        return {
            "mode": "jarvis_memory",
            "reason": "better_pre_registered_development_metric_order_without_language_regression",
        }
    return {
        "mode": "default",
        "reason": "custom_instruction_did_not_beat_default_pre_registered_metric_order",
    }


async def _cache_first_stage(
    payload: dict[str, Any],
    retrieval: SemanticRetrievalService,
    embedder: Qwen3EmbeddingEncoder,
) -> tuple[CachedFirstStage, ...]:
    cached: list[CachedFirstStage] = []
    for item in payload["queries"]:
        query = str(item["query"])
        query_vector = embedder.encode_query(query)
        candidates = await retrieval.retrieve_first_stage(
            query,
            query_vector,
            eligibility=RetrievalEligibility.cloud_context(),
            limit=3,
        )
        if not candidates:
            raise RuntimeError(f"no first-stage candidates for {item['case_id']}")
        cached.append(CachedFirstStage(item=item, query=query, candidates=candidates))
    return tuple(cached)


def _score_mode(
    cached: tuple[CachedFirstStage, ...],
    assertion_to_memory: dict[str, str],
    *,
    device: str | None,
    instruction: str | None,
) -> list[DevCase]:
    reranker = Qwen3RetrievalReranker(device=device, instruction=instruction)
    results: list[DevCase] = []
    for row in cached:
        started = time.perf_counter_ns()
        reranked = reranker.rerank(row.query, row.candidates)
        rerank_ms = (time.perf_counter_ns() - started) / 1_000_000
        if not reranked:
            raise RuntimeError(f"reranker returned no candidates for {row.item['case_id']}")

        top = reranked[0]
        second_score = reranked[1].rerank_score if len(reranked) > 1 else top.rerank_score
        top_memory_id = assertion_to_memory[top.candidate.assertion.assertion_id]
        top3_memory_ids = [
            assertion_to_memory[item.candidate.assertion.assertion_id] for item in reranked
        ]
        expected = row.item.get("expected_memory_id")
        label = str(row.item["label"])
        results.append(
            DevCase(
                case_id=str(row.item["case_id"]),
                label=label,
                language=str(row.item["language"]),
                category=str(row.item["category"]),
                expected_memory_id=str(expected) if expected is not None else None,
                top_memory_id=top_memory_id,
                positive_top1_correct=label == "release" and top_memory_id == expected,
                positive_hit_at_3=label == "release" and expected in top3_memory_ids,
                rerank_score=float(top.rerank_score),
                rerank_margin=float(top.rerank_score - second_score),
                rerank_ms=rerank_ms,
            )
        )
    return results


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    import torch

    fixture_path = Path(args.cases).resolve()
    payload = baseline._load_fixture(fixture_path)
    device = None if args.device == "auto" else args.device
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but torch.cuda.is_available() is false")
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()

    with tempfile.TemporaryDirectory(prefix="jarvis-phase45d-instruction-") as temp_dir:
        worker = baseline._connection_worker(Path(temp_dir) / "instruction-bakeoff.db")
        lifecycle = MemoryLifecycleService(
            worker,
            clock=lambda: baseline.NOW,
            assertion_id_factory=baseline._id_factory("phase45d-instruction-assertion"),
            operation_id_factory=baseline._id_factory("phase45d-instruction-operation"),
        )
        embeddings = SemanticEmbeddingStore(worker, clock=lambda: baseline.NOW)
        retrieval = SemanticRetrievalService(worker)
        embedder = Qwen3EmbeddingEncoder(device=device)

        try:
            _, assertion_to_memory = await baseline._populate_database(
                payload,
                lifecycle,
                embeddings,
                embedder,
            )
            cached = await _cache_first_stage(payload, retrieval, embedder)

            default_cases = _score_mode(
                cached,
                assertion_to_memory,
                device=device,
                instruction=None,
            )
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

            custom_cases = _score_mode(
                cached,
                assertion_to_memory,
                device=device,
                instruction=JARVIS_MEMORY_RERANK_INSTRUCTION,
            )
        finally:
            await worker.close()

    default_summary = _summary(default_cases)
    custom_summary = _summary(custom_cases)
    recommendation = _recommend(default_summary, custom_summary)
    peak_cuda = int(torch.cuda.max_memory_allocated()) if torch.cuda.is_available() else None

    return {
        "status": "PASS",
        "purpose": "development-only reranker instruction comparison on retired Phase 4.5D V1 corpus",
        "final_acceptance_eligible": False,
        "fixture": fixture_path.name,
        "environment": {
            "device_requested": args.device,
            "torch_version": str(torch.__version__),
            "cuda_runtime": str(torch.version.cuda),
            "cuda_available": bool(torch.cuda.is_available()),
            "device_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
            "peak_cuda_bytes": peak_cuda,
        },
        "instructions": {
            "default": None,
            "jarvis_memory": JARVIS_MEMORY_RERANK_INSTRUCTION,
        },
        "modes": {
            "default": default_summary,
            "jarvis_memory": custom_summary,
        },
        "development_recommendation": recommendation,
        "cases": {
            "default": [
                {
                    "case_id": case.case_id,
                    "label": case.label,
                    "language": case.language,
                    "category": case.category,
                    "expected_memory_id": case.expected_memory_id,
                    "top_memory_id": case.top_memory_id,
                    "positive_top1_correct": case.positive_top1_correct,
                    "positive_hit_at_3": case.positive_hit_at_3,
                    "rerank_score": round(case.rerank_score, 6),
                    "rerank_margin": round(case.rerank_margin, 6),
                }
                for case in default_cases
            ],
            "jarvis_memory": [
                {
                    "case_id": case.case_id,
                    "label": case.label,
                    "language": case.language,
                    "category": case.category,
                    "expected_memory_id": case.expected_memory_id,
                    "top_memory_id": case.top_memory_id,
                    "positive_top1_correct": case.positive_top1_correct,
                    "positive_hit_at_3": case.positive_hit_at_3,
                    "rerank_score": round(case.rerank_score, 6),
                    "rerank_margin": round(case.rerank_margin, 6),
                }
                for case in custom_cases
            ],
        },
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cases",
        default="tools/research/step4_phase45d_abstention_cases.json",
        help="Retired V1 Phase 4.5D corpus",
    )
    parser.add_argument("--device", default="cuda", help="cuda, cpu, or auto")
    parser.add_argument(
        "--output",
        default=".step4-phase45d-reranker-instruction-bakeoff.json",
        help="UTF-8 result JSON",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    result = asyncio.run(_run(args))
    output_path = Path(args.output)
    output_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote UTF-8 result: {output_path}")
    print("STATUS:", result["status"])
    print(
        "Development recommendation:",
        json.dumps(result["development_recommendation"], ensure_ascii=False),
    )
    for mode in ("default", "jarvis_memory"):
        summary = result["modes"][mode]
        print(
            mode,
            json.dumps(
                {
                    "positive_top1_accuracy": summary["positive_top1_accuracy"],
                    "score_auroc": summary["score_auroc_safe_vs_unsafe"],
                    "aurc": summary["risk_coverage"]["aurc"],
                    "zero_error_positive_release_recall": summary["risk_coverage"][
                        "zero_error_positive_release_recall"
                    ],
                    "language_breakdown": summary["language_breakdown"],
                },
                ensure_ascii=False,
            ),
        )


if __name__ == "__main__":
    main()
