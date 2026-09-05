"""Research-only Phase 4.5 local embedding + hybrid retrieval bake-off.

This harness deliberately reuses the fixed multilingual retrieval corpus, FTS5
ranking, metrics, and RRF implementation from the existing Step-4 research tools.
It compares only the measured Qwen incumbent with the one new efficiency challenger
identified by the 2026 research refresh.

Nothing in this file writes production memory, changes canonical SQLCipher state,
or approves a production retrieval dependency.
"""

from __future__ import annotations

import argparse
import gc
import json
import statistics
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Self

import numpy as np
import psutil
import step4_hybrid_rrf_bakeoff as hybrid
import step4_memory_retrieval_bakeoff as base
import torch
from sentence_transformers import SentenceTransformer
from step4_qwen_memory_optimization_bakeoff import JARVIS_MEMORY_PROMPT

TRUNCATE_DIM = 256
RRF_K = hybrid.RRF_K
FTS_WINDOW = hybrid.FTS_WINDOW


@dataclass(frozen=True, slots=True)
class ModelProfile:
    alias: str
    model_id: str
    query_mode: str
    description: str


PROFILES = {
    "qwen": ModelProfile(
        alias="qwen",
        model_id="Qwen/Qwen3-Embedding-0.6B",
        query_mode="jarvis_instruction",
        description="measured incumbent; JARVIS-specific retrieval instruction",
    ),
    "embeddinggemma": ModelProfile(
        alias="embeddinggemma",
        model_id="google/embeddinggemma-300m",
        query_mode="model_native_retrieval_prompts",
        description=(
            "2026 efficiency challenger; Sentence Transformers encode_query/"
            "encode_document use the model's published retrieval prompts"
        ),
    ),
}


class ProcessMemorySampler:
    """Sample this process RSS while one model benchmark is active."""

    def __init__(self, *, interval_seconds: float = 0.01) -> None:
        self._process = psutil.Process()
        self._interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.baseline_rss_bytes = int(self._process.memory_info().rss)
        self.peak_rss_bytes = self.baseline_rss_bytes

    def __enter__(self) -> Self:
        self._thread = threading.Thread(
            target=self._sample,
            name="phase45-rss-sampler",
            daemon=True,
        )
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        del exc_type, exc, traceback
        self._stop.set()
        assert self._thread is not None
        self._thread.join(timeout=2.0)
        self.peak_rss_bytes = max(
            self.peak_rss_bytes,
            int(self._process.memory_info().rss),
        )

    def _sample(self) -> None:
        while not self._stop.wait(self._interval_seconds):
            self.peak_rss_bytes = max(
                self.peak_rss_bytes,
                int(self._process.memory_info().rss),
            )


def _percentile(samples: list[float], fraction: float) -> float:
    ordered = sorted(samples)
    index = min(len(ordered) - 1, int(len(ordered) * fraction))
    return ordered[index]


def _rank(
    query_embedding: np.ndarray,
    doc_embeddings: np.ndarray,
    docs: tuple[base.MemoryDoc, ...],
) -> list[tuple[str, float]]:
    scores = np.asarray(doc_embeddings @ query_embedding, dtype=np.float64)
    order = np.argsort(-scores)
    return [(docs[index].memory_id, float(scores[index])) for index in order]


def _metrics_for_cases(
    rankings: dict[str, list[str]],
    cases: list[base.QueryCase],
) -> dict[str, float | int | None]:
    positives = [case for case in cases if case.expected_memory_id is not None]
    if not positives:
        return {
            "positive_cases": 0,
            "recall_at_1": None,
            "recall_at_3": None,
            "mrr": None,
        }

    ranks: list[int | None] = []
    for case in positives:
        ranked = rankings[case.case_id]
        try:
            rank = ranked.index(case.expected_memory_id) + 1
        except ValueError:
            rank = None
        ranks.append(rank)

    return {
        "positive_cases": len(positives),
        "recall_at_1": round(sum(rank == 1 for rank in ranks) / len(ranks), 4),
        "recall_at_3": round(
            sum(rank is not None and rank <= 3 for rank in ranks) / len(ranks),
            4,
        ),
        "mrr": round(
            sum(0.0 if rank is None else 1.0 / rank for rank in ranks) / len(ranks),
            4,
        ),
    }


def _language_breakdown(
    rankings: dict[str, list[str]],
) -> dict[str, dict[str, float | int | None]]:
    output: dict[str, dict[str, float | int | None]] = {}
    for language in sorted({case.language for case in base.QUERIES}):
        language_cases = [
            case
            for case in base.QUERIES
            if case.language == language and case.expected_memory_id is not None
        ]
        output[language] = _metrics_for_cases(rankings, language_cases)
    return output


def _sync_cuda() -> None:
    if torch.cuda.is_available():
        torch.cuda.synchronize()


def _encode_documents(
    model: SentenceTransformer,
    profile: ModelProfile,
    texts: list[str],
) -> np.ndarray:
    del profile
    return np.asarray(
        model.encode_document(
            texts,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
            truncate_dim=TRUNCATE_DIM,
        )
    )


def _encode_query(
    model: SentenceTransformer,
    profile: ModelProfile,
    query: str,
) -> np.ndarray:
    kwargs: dict[str, object] = {
        "normalize_embeddings": True,
        "convert_to_numpy": True,
        "show_progress_bar": False,
        "truncate_dim": TRUNCATE_DIM,
    }
    if profile.query_mode == "jarvis_instruction":
        kwargs["prompt"] = JARVIS_MEMORY_PROMPT
    return np.asarray(model.encode_query([query], **kwargs)[0])


def _prepare_device(requested: str) -> str | None:
    if requested == "auto":
        return None
    if requested == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but torch.cuda.is_available() is false")
    return requested


def _model_runtime_metadata(model: SentenceTransformer) -> dict[str, object]:
    first_parameter = next(model.parameters())
    return {
        "device": str(first_parameter.device),
        "parameter_dtype": str(first_parameter.dtype),
        "parameters": int(sum(parameter.numel() for parameter in model.parameters())),
        "native_embedding_dimension": model.get_sentence_embedding_dimension(),
        "benchmark_dimension": TRUNCATE_DIM,
    }


def _benchmark_model(
    profile: ModelProfile,
    *,
    device: str | None,
) -> dict[str, object]:
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()

    current_docs = base._docs_for_scope("current")
    all_docs = base._docs_for_scope("all")

    with ProcessMemorySampler() as rss:
        load_started = time.perf_counter()
        model = SentenceTransformer(
            profile.model_id,
            device=device,
            truncate_dim=TRUNCATE_DIM,
        )
        load_seconds = time.perf_counter() - load_started
        runtime = _model_runtime_metadata(model)

        corpus_started = time.perf_counter()
        current_embeddings = _encode_documents(
            model,
            profile,
            [doc.text for doc in current_docs],
        )
        all_embeddings = _encode_documents(
            model,
            profile,
            [doc.text for doc in all_docs],
        )
        _sync_cuda()
        corpus_encode_seconds = time.perf_counter() - corpus_started

        if current_embeddings.shape[1] != TRUNCATE_DIM:
            raise RuntimeError(
                f"{profile.alias} produced {current_embeddings.shape[1]} dimensions; "
                f"expected {TRUNCATE_DIM}"
            )

        # Warm the exact query path before latency measurement.
        _ = _encode_query(model, profile, base.QUERIES[0].query)
        _sync_cuda()

        dense_rankings: dict[str, list[str]] = {}
        fused_rankings: dict[str, list[str]] = {}
        cases: dict[str, object] = {}
        dense_latency_ms: list[float] = []
        hybrid_latency_ms: list[float] = []
        fts_latency_ms: list[float] = []
        absent_dense_scores: list[float] = []
        raw_rrf_top_tie_cases: list[str] = []

        for case in base.QUERIES:
            total_started = time.perf_counter_ns()

            fts_started = time.perf_counter_ns()
            fts_ranked = base._fts_rank(case)[:FTS_WINDOW]
            fts_elapsed = (time.perf_counter_ns() - fts_started) / 1_000_000
            fts_ids = [memory_id for memory_id, _ in fts_ranked]

            _sync_cuda()
            dense_started = time.perf_counter_ns()
            query_embedding = _encode_query(model, profile, case.query)
            _sync_cuda()
            dense_elapsed = (time.perf_counter_ns() - dense_started) / 1_000_000

            if case.scope == "all":
                docs, doc_embeddings = all_docs, all_embeddings
            else:
                docs, doc_embeddings = current_docs, current_embeddings

            dense_ranked = _rank(query_embedding, doc_embeddings, docs)
            dense_ids = [memory_id for memory_id, _ in dense_ranked]
            fused_ids, fused_scores, raw_top_ties = hybrid._rrf_fuse(
                fts_ids,
                dense_ids,
            )
            total_elapsed = (time.perf_counter_ns() - total_started) / 1_000_000

            dense_rankings[case.case_id] = dense_ids
            fused_rankings[case.case_id] = fused_ids
            fts_latency_ms.append(fts_elapsed)
            dense_latency_ms.append(dense_elapsed)
            hybrid_latency_ms.append(total_elapsed)
            if len(raw_top_ties) > 1:
                raw_rrf_top_tie_cases.append(case.case_id)
            if case.expected_memory_id is None:
                absent_dense_scores.append(dense_ranked[0][1])

            cases[case.case_id] = {
                "language": case.language,
                "scope": case.scope,
                "expected": case.expected_memory_id,
                "fts_top3": fts_ids[:3],
                "dense_top3": [
                    {"memory_id": memory_id, "score": round(score, 6)}
                    for memory_id, score in dense_ranked[:3]
                ],
                "rrf_top3": [
                    {
                        "memory_id": memory_id,
                        "rrf_score": round(fused_scores[memory_id], 8),
                    }
                    for memory_id in fused_ids[:3]
                ],
                "raw_rrf_top_ties": raw_top_ties,
                "dense_hit_at_1": (
                    case.expected_memory_id is not None
                    and dense_ids[0] == case.expected_memory_id
                ),
                "rrf_hit_at_1": (
                    case.expected_memory_id is not None
                    and fused_ids[0] == case.expected_memory_id
                ),
            }

        _sync_cuda()
        peak_cuda_bytes = (
            int(torch.cuda.max_memory_allocated())
            if torch.cuda.is_available()
            else None
        )

        result = {
            "profile": profile.alias,
            "model": profile.model_id,
            "description": profile.description,
            "query_mode": profile.query_mode,
            "runtime": runtime,
            "load_seconds": round(load_seconds, 4),
            "corpus_encode_seconds": round(corpus_encode_seconds, 4),
            "derived_vectors": {
                "dtype": str(all_embeddings.dtype),
                "dimension": int(all_embeddings.shape[1]),
                "all_scope_records": int(all_embeddings.shape[0]),
                "all_scope_bytes": int(all_embeddings.nbytes),
                "bytes_per_vector": int(all_embeddings[0].nbytes),
            },
            "memory": {
                "baseline_rss_bytes": rss.baseline_rss_bytes,
                "peak_rss_bytes": rss.peak_rss_bytes,
                "peak_rss_delta_bytes": max(
                    0,
                    rss.peak_rss_bytes - rss.baseline_rss_bytes,
                ),
                "peak_cuda_allocated_bytes": peak_cuda_bytes,
            },
            "metrics": {
                "dense": base._positive_metrics(dense_rankings),
                "rrf_hybrid": base._positive_metrics(fused_rankings),
            },
            "language_breakdown": {
                "dense": _language_breakdown(dense_rankings),
                "rrf_hybrid": _language_breakdown(fused_rankings),
            },
            "latency_ms": {
                "fts_p50": round(statistics.median(fts_latency_ms), 4),
                "fts_p95": round(_percentile(fts_latency_ms, 0.95), 4),
                "dense_query_p50": round(statistics.median(dense_latency_ms), 4),
                "dense_query_p95": round(_percentile(dense_latency_ms, 0.95), 4),
                "hybrid_end_to_end_p50": round(
                    statistics.median(hybrid_latency_ms),
                    4,
                ),
                "hybrid_end_to_end_p95": round(
                    _percentile(hybrid_latency_ms, 0.95),
                    4,
                ),
            },
            "absent_dense_top_score_distribution": {
                "count": len(absent_dense_scores),
                "min": round(min(absent_dense_scores), 6)
                if absent_dense_scores
                else None,
                "median": round(statistics.median(absent_dense_scores), 6)
                if absent_dense_scores
                else None,
                "max": round(max(absent_dense_scores), 6)
                if absent_dense_scores
                else None,
            },
            "raw_rrf_top_tie_cases": raw_rrf_top_tie_cases,
            "cases": cases,
        }

    del model, current_embeddings, all_embeddings
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return result


def _environment() -> dict[str, object]:
    import sentence_transformers
    import transformers

    return {
        "sentence_transformers": sentence_transformers.__version__,
        "transformers": transformers.__version__,
        "torch": torch.__version__,
        "cuda_available": torch.cuda.is_available(),
        "cuda_version": torch.version.cuda,
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "psutil": psutil.__version__,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--models",
        default="qwen,embeddinggemma",
        help="Comma-separated aliases: qwen,embeddinggemma (default: both)",
    )
    parser.add_argument(
        "--device",
        default="cuda",
        help="Sentence Transformers device: cuda, cpu, or auto (default: cuda)",
    )
    parser.add_argument(
        "--output",
        default=".step4-phase45-embedding-bakeoff.json",
        help="UTF-8 JSON result path",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    requested = [item.strip() for item in args.models.split(",") if item.strip()]
    unknown = sorted(set(requested) - PROFILES.keys())
    if unknown:
        raise SystemExit(f"unknown model aliases: {unknown}")

    device = _prepare_device(args.device)
    output: dict[str, object] = {
        "status": "PASS",
        "purpose": (
            "research-only Phase 4.5 embedding comparison; no production retrieval "
            "or vector-extension approval"
        ),
        "corpus_source": "step4_memory_retrieval_bakeoff.CORPUS/QUERIES",
        "corpus_records": len(base.CORPUS),
        "query_cases": len(base.QUERIES),
        "positive_query_cases": sum(
            case.expected_memory_id is not None for case in base.QUERIES
        ),
        "absent_query_cases": sum(
            case.expected_memory_id is None for case in base.QUERIES
        ),
        "truncate_dim": TRUNCATE_DIM,
        "rrf": {
            "rank_constant": RRF_K,
            "fts_window": FTS_WINDOW,
            "weights": "equal",
            "tie_break": "semantic rank, then lexical rank, then stable memory id",
        },
        "environment": _environment(),
        "fts5": base.run_fts(),
        "models": {},
    }

    for alias in requested:
        profile = PROFILES[alias]
        try:
            output["models"][alias] = _benchmark_model(  # type: ignore[index]
                profile,
                device=device,
            )
        except Exception as exc:  # noqa: BLE001 - model failure is research evidence
            output["status"] = "PARTIAL"
            output["models"][alias] = {  # type: ignore[index]
                "profile": alias,
                "model": profile.model_id,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "note": (
                    "If this is a gated Hugging Face model, accept the model terms "
                    "and authenticate in the research environment; do not rerun any "
                    "already-passed model merely to recover the gated result."
                ),
            }

    target = Path(args.output)
    target.write_text(
        json.dumps(output, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote UTF-8 result: {target}")


if __name__ == "__main__":
    main()
