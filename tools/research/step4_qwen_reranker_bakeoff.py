"""Research-only Step 4 retrieve/fuse/rerank bake-off.

This harness evaluates the mature two-stage retrieval pattern after the fixed-weight
RRF sweep showed that first-stage candidate recall is already strong but ordering
still has edge cases.

Stage 1:
* SQLite FTS5 lexical retrieval
* Qwen3-Embedding-0.6B semantic retrieval
* JARVIS-specific query instruction
* 256-dimensional Matryoshka embeddings
* equal-weight RRF candidate fusion, k=60

Stage 2:
* Qwen3-Reranker-0.6B CrossEncoder over only the top fused candidates

The harness tests small candidate windows (default 3 and 5), records quality,
latency and CUDA usage, and remains entirely under tools/research. It does not
implement production JARVIS memory.
"""

from __future__ import annotations

import argparse
import gc
import json
import statistics
import time

import numpy as np
import torch
from sentence_transformers import CrossEncoder, SentenceTransformer

import step4_memory_retrieval_bakeoff as base
import step4_hybrid_rrf_bakeoff as hybrid
from step4_qwen_memory_optimization_bakeoff import JARVIS_MEMORY_PROMPT

EMBED_MODEL = "Qwen/Qwen3-Embedding-0.6B"
RERANK_MODEL = "Qwen/Qwen3-Reranker-0.6B"
TRUNCATE_DIM = 256
FTS_WINDOW = 10
RRF_K = 60


def _percentile(samples: list[float], fraction: float) -> float:
    ordered = sorted(samples)
    index = min(len(ordered) - 1, int(len(ordered) * fraction))
    return ordered[index]


def _dense_rank(
    query_embedding: np.ndarray,
    doc_embeddings: np.ndarray,
    docs: tuple[base.MemoryDoc, ...],
) -> list[str]:
    scores = np.asarray(doc_embeddings @ query_embedding, dtype=np.float64)
    order = np.argsort(-scores)
    return [docs[index].memory_id for index in order]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", default="cuda")
    parser.add_argument(
        "--candidate-windows",
        default="3,5",
        help="Comma-separated fused candidate counts to rerank (default: 3,5)",
    )
    args = parser.parse_args()

    candidate_windows = sorted(
        {int(value.strip()) for value in args.candidate_windows.split(",") if value.strip()}
    )
    if not candidate_windows or any(value < 1 for value in candidate_windows):
        raise SystemExit("candidate windows must be positive integers")

    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()

    embed_load_started = time.perf_counter()
    embedder = SentenceTransformer(EMBED_MODEL, device=args.device)
    embed_load_seconds = time.perf_counter() - embed_load_started

    encode_kwargs = {
        "normalize_embeddings": True,
        "convert_to_numpy": True,
        "show_progress_bar": False,
        "truncate_dim": TRUNCATE_DIM,
    }
    query_kwargs = dict(encode_kwargs)
    query_kwargs["prompt"] = JARVIS_MEMORY_PROMPT

    current_docs = base._docs_for_scope("current")
    all_docs = base._docs_for_scope("all")
    doc_by_id = {doc.memory_id: doc for doc in base.CORPUS}

    corpus_started = time.perf_counter()
    current_embeddings = np.asarray(
        embedder.encode_document([doc.text for doc in current_docs], **encode_kwargs)
    )
    all_embeddings = np.asarray(
        embedder.encode_document([doc.text for doc in all_docs], **encode_kwargs)
    )
    corpus_encode_seconds = time.perf_counter() - corpus_started

    # Warm first-stage semantic query path.
    _ = embedder.encode_query([base.QUERIES[0].query], **query_kwargs)

    first_stage_rankings: dict[str, list[str]] = {}
    first_stage_latency_ms: list[float] = []
    first_stage_cases: dict[str, object] = {}

    for case in base.QUERIES:
        started = time.perf_counter_ns()
        fts_ids = [memory_id for memory_id, _ in base._fts_rank(case)[:FTS_WINDOW]]
        query_embedding = np.asarray(
            embedder.encode_query([case.query], **query_kwargs)[0]
        )
        if case.scope == "all":
            docs, doc_embeddings = all_docs, all_embeddings
        else:
            docs, doc_embeddings = current_docs, current_embeddings
        dense_ids = _dense_rank(query_embedding, doc_embeddings, docs)
        fused_ids, _, _ = hybrid._rrf_fuse(fts_ids, dense_ids)
        first_stage_latency_ms.append((time.perf_counter_ns() - started) / 1_000_000)
        first_stage_rankings[case.case_id] = fused_ids
        first_stage_cases[case.case_id] = {
            "expected": case.expected_memory_id,
            "fts_top3": fts_ids[:3],
            "dense_top3": dense_ids[:3],
            "rrf_top5": fused_ids[:5],
        }

    reranker_load_started = time.perf_counter()
    reranker = CrossEncoder(RERANK_MODEL, device=args.device)
    reranker_load_seconds = time.perf_counter() - reranker_load_started

    # Warm reranker path before measurements.
    warm_doc = doc_by_id[first_stage_rankings[base.QUERIES[0].case_id][0]].text
    _ = reranker.predict([(base.QUERIES[0].query, warm_doc)], show_progress_bar=False)

    configurations: dict[str, object] = {}

    for window in candidate_windows:
        rankings: dict[str, list[str]] = {}
        rerank_latency_ms: list[float] = []
        total_latency_ms: list[float] = []
        absent_top_scores: list[float] = []
        cases: dict[str, object] = {}
        candidate_recall_hits = 0
        positive_count = 0

        for case, first_stage_ms in zip(base.QUERIES, first_stage_latency_ms):
            candidate_ids = first_stage_rankings[case.case_id][:window]
            if case.expected_memory_id is not None:
                positive_count += 1
                if case.expected_memory_id in candidate_ids:
                    candidate_recall_hits += 1

            pairs = [(case.query, doc_by_id[memory_id].text) for memory_id in candidate_ids]
            rerank_started = time.perf_counter_ns()
            raw_scores = reranker.predict(pairs, show_progress_bar=False)
            rerank_elapsed = (time.perf_counter_ns() - rerank_started) / 1_000_000
            scores = np.asarray(raw_scores, dtype=np.float64).reshape(-1)

            order = np.argsort(-scores)
            reranked_ids = [candidate_ids[index] for index in order]
            reranked_scores = [float(scores[index]) for index in order]
            rankings[case.case_id] = reranked_ids
            rerank_latency_ms.append(rerank_elapsed)
            total_latency_ms.append(first_stage_ms + rerank_elapsed)

            if case.expected_memory_id is None and reranked_scores:
                absent_top_scores.append(reranked_scores[0])

            cases[case.case_id] = {
                "language": case.language,
                "scope": case.scope,
                "expected": case.expected_memory_id,
                "candidate_ids": candidate_ids,
                "reranked_top": [
                    {"memory_id": memory_id, "score": round(score, 6)}
                    for memory_id, score in zip(reranked_ids[:3], reranked_scores[:3])
                ],
                "hit_at_1": case.expected_memory_id is not None
                and bool(reranked_ids)
                and reranked_ids[0] == case.expected_memory_id,
            }

        configurations[str(window)] = {
            "candidate_window": window,
            "candidate_recall": round(candidate_recall_hits / positive_count, 4),
            "metrics": base._positive_metrics(rankings),
            "rerank_latency_ms": {
                "p50": round(statistics.median(rerank_latency_ms), 4),
                "p95": round(_percentile(rerank_latency_ms, 0.95), 4),
                "max": round(max(rerank_latency_ms), 4),
            },
            "end_to_end_latency_ms": {
                "p50": round(statistics.median(total_latency_ms), 4),
                "p95": round(_percentile(total_latency_ms, 0.95), 4),
                "max": round(max(total_latency_ms), 4),
            },
            "absent_top_score_distribution": {
                "count": len(absent_top_scores),
                "min": round(min(absent_top_scores), 6) if absent_top_scores else None,
                "median": round(statistics.median(absent_top_scores), 6)
                if absent_top_scores
                else None,
                "max": round(max(absent_top_scores), 6) if absent_top_scores else None,
            },
            "cases": cases,
        }

    output = {
        "status": "PASS",
        "purpose": "research-only; no production reranker approval",
        "embedding_model": EMBED_MODEL,
        "reranker_model": RERANK_MODEL,
        "device": args.device,
        "truncate_dim": TRUNCATE_DIM,
        "first_stage": {
            "fts_window": FTS_WINDOW,
            "rrf_rank_constant": RRF_K,
            "weights": "equal",
            "metrics": base._positive_metrics(first_stage_rankings),
            "latency_ms": {
                "p50": round(statistics.median(first_stage_latency_ms), 4),
                "p95": round(_percentile(first_stage_latency_ms, 0.95), 4),
                "max": round(max(first_stage_latency_ms), 4),
            },
        },
        "load_seconds": {
            "embedder": round(embed_load_seconds, 4),
            "reranker": round(reranker_load_seconds, 4),
        },
        "corpus_encode_seconds": round(corpus_encode_seconds, 4),
        "peak_cuda_bytes_combined": (
            int(torch.cuda.max_memory_allocated()) if torch.cuda.is_available() else None
        ),
        "configurations": configurations,
        "first_stage_cases": first_stage_cases,
    }

    del reranker
    del embedder
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
