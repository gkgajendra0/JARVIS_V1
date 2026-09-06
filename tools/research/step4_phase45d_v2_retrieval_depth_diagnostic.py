"""Development-only retrieval-depth diagnosis after Phase 4.5D V2 rejection.

V2 is fully exposed and retired from acceptance. This harness may therefore reuse the
V2 corpus to diagnose whether the accepted Qwen retriever is starving the reranker by
passing only three candidates. It does not calibrate a release policy and its output
must never be cited as final acceptance evidence.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import tempfile
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import step4_phase45d_abstention_calibration as baseline
import step4_phase45d_final_v2_cases as v2_cases

from jarvis.memory.embeddings import (
    QWEN3_EMBEDDING_CONTRACT,
    QWEN3_EMBEDDING_MODEL_ID,
    QWEN3_EMBEDDING_REVISION,
    SemanticEmbeddingStore,
)
from jarvis.memory.lifecycle import MemoryLifecycleService
from jarvis.memory.retrieval import RetrievalEligibility, SemanticRetrievalService
from jarvis.memory.retrieval_models import (
    JARVIS_MEMORY_RERANK_INSTRUCTION,
    QWEN3_RERANKER_MODEL_ID,
    QWEN3_RERANKER_REVISION,
    Qwen3EmbeddingEncoder,
    Qwen3RetrievalReranker,
    RerankedCandidate,
)

RETRIEVAL_DEPTHS = (3, 5, 10, 20, 50, 100)
RERANK_DEPTHS = (3, 5, 10, 20)
OUTPUT_DEFAULT = Path(".step4-phase45d-v2-retrieval-depth-diagnostic-v1.json")


@dataclass(frozen=True, slots=True)
class PositiveDiagnostic:
    case_id: str
    split: str
    language: str
    category: str
    relation: str
    expected_memory_id: str
    expected_first_stage_rank: int | None
    reranked_top_memory_by_depth: dict[int, str]
    query_embedding_ms: float
    retrieval_ms: float
    rerank_top20_ms: float


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(len(ordered) * fraction))
    return round(ordered[index], 4)


def _relation(memory_id: str) -> str:
    return memory_id.rsplit("_", 1)[-1]


def _top_for_depth(
    reranked: tuple[RerankedCandidate, ...], depth: int
) -> RerankedCandidate | None:
    for item in reranked:
        if item.candidate.fused_rank <= depth:
            return item
    return None


def _depth_metrics(
    rows: list[PositiveDiagnostic],
    *,
    retrieval_depths: tuple[int, ...] = RETRIEVAL_DEPTHS,
    rerank_depths: tuple[int, ...] = RERANK_DEPTHS,
) -> dict[str, Any]:
    total = len(rows)
    retrieval: dict[str, Any] = {}
    for depth in retrieval_depths:
        hits = sum(
            row.expected_first_stage_rank is not None
            and row.expected_first_stage_rank <= depth
            for row in rows
        )
        retrieval[str(depth)] = {
            "hits": hits,
            "total": total,
            "recall": round(hits / total, 6) if total else 0.0,
        }

    rerank: dict[str, Any] = {}
    for depth in rerank_depths:
        correct = sum(
            row.reranked_top_memory_by_depth.get(depth) == row.expected_memory_id
            for row in rows
        )
        rerank[str(depth)] = {
            "top1_correct": correct,
            "total": total,
            "top1_accuracy": round(correct / total, 6) if total else 0.0,
        }

    missing_at_max = [
        row.case_id
        for row in rows
        if row.expected_first_stage_rank is None
        or row.expected_first_stage_rank > max(retrieval_depths)
    ]
    return {
        "cases": total,
        "first_stage": retrieval,
        "reranked": rerank,
        "missing_expected_at_max_retrieval_depth": missing_at_max,
    }


def _grouped(rows: list[PositiveDiagnostic], attribute: str) -> dict[str, Any]:
    grouped: dict[str, list[PositiveDiagnostic]] = defaultdict(list)
    for row in rows:
        grouped[str(getattr(row, attribute))].append(row)
    return {
        key: _depth_metrics(values)
        for key, values in sorted(grouped.items(), key=lambda item: item[0])
    }


def _public_case(row: PositiveDiagnostic) -> dict[str, Any]:
    return {
        "case_id": row.case_id,
        "split": row.split,
        "language": row.language,
        "category": row.category,
        "relation": row.relation,
        "expected_memory_id": row.expected_memory_id,
        "expected_first_stage_rank": row.expected_first_stage_rank,
        "reranked_top_memory_by_depth": {
            str(depth): memory_id
            for depth, memory_id in sorted(row.reranked_top_memory_by_depth.items())
        },
    }


async def _run(device: str) -> dict[str, Any]:
    try:
        import torch
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Torch is required") from exc
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but torch.cuda.is_available() is false")
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()

    payload = v2_cases.build_payload()
    positive_queries = [
        item for item in payload["queries"] if item["label"] == "release"
    ]
    if len(positive_queries) != 900:
        raise RuntimeError("V2 positive-query count changed unexpectedly")

    with tempfile.TemporaryDirectory(prefix="jarvis-phase45d-v2-depth-") as temp_dir:
        worker = baseline._connection_worker(Path(temp_dir) / "diagnostic.db")
        lifecycle = MemoryLifecycleService(
            worker,
            clock=lambda: baseline.NOW,
            assertion_id_factory=baseline._id_factory("phase45d-v2-depth-assertion"),
            operation_id_factory=baseline._id_factory("phase45d-v2-depth-operation"),
        )
        embeddings = SemanticEmbeddingStore(worker, clock=lambda: baseline.NOW)
        retrieval = SemanticRetrievalService(worker)
        embedder = Qwen3EmbeddingEncoder(device=device)
        reranker = Qwen3RetrievalReranker(
            device=device,
            candidate_window=max(RERANK_DEPTHS),
        )
        if reranker.instruction != JARVIS_MEMORY_RERANK_INSTRUCTION:
            raise RuntimeError(
                "diagnostic must use the frozen JARVIS reranker instruction"
            )

        rows: list[PositiveDiagnostic] = []
        try:
            populate_started = time.perf_counter()
            _, assertion_to_memory = await baseline._populate_database(
                payload,
                lifecycle,
                embeddings,
                embedder,
            )
            populate_seconds = time.perf_counter() - populate_started

            for item in positive_queries:
                query = str(item["query"])
                expected = str(item["expected_memory_id"])

                tick = time.perf_counter_ns()
                query_vector = embedder.encode_query(query)
                query_embedding_ms = (time.perf_counter_ns() - tick) / 1_000_000

                tick = time.perf_counter_ns()
                first_stage = await retrieval.retrieve_first_stage(
                    query,
                    query_vector,
                    eligibility=RetrievalEligibility.cloud_context(),
                    limit=max(RETRIEVAL_DEPTHS),
                )
                retrieval_ms = (time.perf_counter_ns() - tick) / 1_000_000
                if not first_stage:
                    raise RuntimeError(f"no candidates for {item['case_id']}")

                expected_rank: int | None = None
                for candidate in first_stage:
                    memory_id = assertion_to_memory.get(
                        candidate.assertion.assertion_id
                    )
                    if memory_id == expected:
                        expected_rank = candidate.fused_rank
                        break

                tick = time.perf_counter_ns()
                reranked = reranker.rerank(query, first_stage)
                rerank_top20_ms = (time.perf_counter_ns() - tick) / 1_000_000
                if not reranked:
                    raise RuntimeError(
                        f"reranker returned nothing for {item['case_id']}"
                    )

                top_by_depth: dict[int, str] = {}
                for depth in RERANK_DEPTHS:
                    top = _top_for_depth(reranked, depth)
                    if top is None:
                        raise RuntimeError(
                            f"no reranked top candidate at depth {depth} for "
                            f"{item['case_id']}"
                        )
                    memory_id = assertion_to_memory.get(
                        top.candidate.assertion.assertion_id
                    )
                    if memory_id is None:
                        raise RuntimeError(
                            f"unknown reranked assertion for {item['case_id']}"
                        )
                    top_by_depth[depth] = memory_id

                rows.append(
                    PositiveDiagnostic(
                        case_id=str(item["case_id"]),
                        split=str(item["split"]),
                        language=str(item["language"]),
                        category=str(item["category"]),
                        relation=_relation(expected),
                        expected_memory_id=expected,
                        expected_first_stage_rank=expected_rank,
                        reranked_top_memory_by_depth=top_by_depth,
                        query_embedding_ms=query_embedding_ms,
                        retrieval_ms=retrieval_ms,
                        rerank_top20_ms=rerank_top20_ms,
                    )
                )
        finally:
            await worker.close()

    rank_values = [
        row.expected_first_stage_rank
        for row in rows
        if row.expected_first_stage_rank is not None
    ]
    timing = {
        "fixture_population_and_document_embedding_seconds": round(populate_seconds, 4),
        "query_embedding_p50_ms": _percentile(
            [row.query_embedding_ms for row in rows], 0.50
        ),
        "query_embedding_p95_ms": _percentile(
            [row.query_embedding_ms for row in rows], 0.95
        ),
        "retrieval_top100_p50_ms": _percentile(
            [row.retrieval_ms for row in rows], 0.50
        ),
        "retrieval_top100_p95_ms": _percentile(
            [row.retrieval_ms for row in rows], 0.95
        ),
        "rerank_top20_p50_ms": _percentile([row.rerank_top20_ms for row in rows], 0.50),
        "rerank_top20_p95_ms": _percentile([row.rerank_top20_ms for row in rows], 0.95),
        "qwen_peak_cuda_bytes": (
            int(torch.cuda.max_memory_allocated())
            if torch.cuda.is_available()
            else None
        ),
    }

    expected_rank_summary = {
        "found_within_top100": len(rank_values),
        "missing_within_top100": len(rows) - len(rank_values),
        "min": min(rank_values) if rank_values else None,
        "median": float(np.median(rank_values)) if rank_values else None,
        "p95": float(np.percentile(rank_values, 95)) if rank_values else None,
        "max": max(rank_values) if rank_values else None,
    }

    by_split: dict[str, Any] = {}
    for split in ("calibration", "validation"):
        subset = [row for row in rows if row.split == split]
        by_split[split] = {
            "overall": _depth_metrics(subset),
            "languages": {
                language: _depth_metrics(
                    [row for row in subset if row.language == language]
                )
                for language in v2_cases.LANGUAGES
            },
            "relations": _grouped(subset, "relation"),
        }

    return {
        "status": "DEVELOPMENT_DIAGNOSTIC_COMPLETE",
        "purpose": "Phase 4.5D post-V2 retrieval-depth development diagnosis",
        "development_only": True,
        "acceptance_evidence": False,
        "v2_is_exposed_and_retired": True,
        "models": {
            "embedding": {
                "model_id": QWEN3_EMBEDDING_MODEL_ID,
                "revision": QWEN3_EMBEDDING_REVISION,
                "dimension": QWEN3_EMBEDDING_CONTRACT.dimension,
            },
            "reranker": {
                "model_id": QWEN3_RERANKER_MODEL_ID,
                "revision": QWEN3_RERANKER_REVISION,
                "instruction": JARVIS_MEMORY_RERANK_INSTRUCTION,
            },
        },
        "retrieval_depths": list(RETRIEVAL_DEPTHS),
        "rerank_depths": list(RERANK_DEPTHS),
        "positive_cases": len(rows),
        "expected_first_stage_rank": expected_rank_summary,
        "overall": _depth_metrics(rows),
        "splits": by_split,
        "timing": timing,
        "cases": [_public_case(row) for row in rows],
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    parser.add_argument("--output", default=str(OUTPUT_DEFAULT))
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    output_path = Path(args.output)
    if output_path.exists():
        raise RuntimeError(
            f"refusing to overwrite existing retrieval-depth evidence: {output_path}"
        )
    if max(RERANK_DEPTHS) > max(RETRIEVAL_DEPTHS):
        raise RuntimeError("rerank depth cannot exceed retrieval depth")
    output = asyncio.run(_run(args.device))
    output_path.write_text(
        json.dumps(output, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote UTF-8 result: {output_path}")
    print("STATUS:", output["status"])
    print(
        "OVERALL:",
        json.dumps(
            {
                "first_stage": output["overall"]["first_stage"],
                "reranked": output["overall"]["reranked"],
            }
        ),
    )


if __name__ == "__main__":
    main()
