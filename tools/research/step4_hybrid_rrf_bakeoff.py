"""Research-only Step 4 hybrid retrieval bake-off.

Combines the already-selected research candidates:

* SQLite FTS5 lexical ranking;
* Qwen3-Embedding-0.6B semantic ranking;
* JARVIS-specific query instruction;
* 256-dimensional Matryoshka output;
* standard Reciprocal Rank Fusion (RRF) with rank constant 60.

The goal is to test whether mature rank fusion preserves semantic paraphrase recall
while correcting lexical/semantic rank-1 disagreements.  This file lives under
``tools/research`` and does not implement production memory.
"""

from __future__ import annotations

import argparse
import gc
import json
import statistics
import time

import numpy as np
import torch
from sentence_transformers import SentenceTransformer

import step4_memory_retrieval_bakeoff as base
from step4_qwen_memory_optimization_bakeoff import JARVIS_MEMORY_PROMPT

MODEL_NAME = "Qwen/Qwen3-Embedding-0.6B"
TRUNCATE_DIM = 256
RRF_K = 60
FTS_WINDOW = 10


def _dense_rank(
    query_embedding: np.ndarray,
    doc_embeddings: np.ndarray,
    docs: tuple[base.MemoryDoc, ...],
) -> list[tuple[str, float]]:
    scores = np.asarray(doc_embeddings @ query_embedding, dtype=np.float64)
    order = np.argsort(-scores)
    return [(docs[index].memory_id, float(scores[index])) for index in order]


def _rrf_fuse(
    fts_ids: list[str],
    dense_ids: list[str],
) -> tuple[list[str], dict[str, float], list[str]]:
    """Fuse equal-weight lexical + semantic ranks using standard RRF.

    Exact RRF score ties are broken by the semantic rank, then lexical rank, then
    stable memory id.  The tie group is also returned explicitly so the research
    output does not hide that the base RRF formula itself tied candidates.
    """

    fts_rank = {memory_id: rank for rank, memory_id in enumerate(fts_ids, start=1)}
    dense_rank = {memory_id: rank for rank, memory_id in enumerate(dense_ids, start=1)}
    candidates = set(fts_rank) | set(dense_rank)

    scores: dict[str, float] = {}
    for memory_id in candidates:
        score = 0.0
        if memory_id in fts_rank:
            score += 1.0 / (RRF_K + fts_rank[memory_id])
        if memory_id in dense_rank:
            score += 1.0 / (RRF_K + dense_rank[memory_id])
        scores[memory_id] = score

    ranked = sorted(
        candidates,
        key=lambda memory_id: (
            -scores[memory_id],
            dense_rank.get(memory_id, 10**9),
            fts_rank.get(memory_id, 10**9),
            memory_id,
        ),
    )

    top_score = scores[ranked[0]]
    raw_top_ties = sorted(
        memory_id for memory_id in ranked if abs(scores[memory_id] - top_score) < 1e-15
    )
    return ranked, scores, raw_top_ties


def _percentile(samples: list[float], fraction: float) -> float:
    ordered = sorted(samples)
    index = min(len(ordered) - 1, int(len(ordered) * fraction))
    return ordered[index]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()

    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()

    load_started = time.perf_counter()
    model = SentenceTransformer(MODEL_NAME, device=args.device)
    load_seconds = time.perf_counter() - load_started

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
    corpus_started = time.perf_counter()
    current_embeddings = np.asarray(
        model.encode_document([doc.text for doc in current_docs], **encode_kwargs)
    )
    all_embeddings = np.asarray(
        model.encode_document([doc.text for doc in all_docs], **encode_kwargs)
    )
    corpus_encode_seconds = time.perf_counter() - corpus_started

    # Warm semantic query path before measuring.
    _ = model.encode_query([base.QUERIES[0].query], **query_kwargs)

    fts_rankings: dict[str, list[str]] = {}
    dense_rankings: dict[str, list[str]] = {}
    fused_rankings: dict[str, list[str]] = {}
    cases: dict[str, object] = {}
    total_latency_ms: list[float] = []
    dense_latency_ms: list[float] = []
    fts_latency_ms: list[float] = []
    raw_top_tie_cases: list[str] = []

    for case in base.QUERIES:
        total_started = time.perf_counter_ns()

        fts_started = time.perf_counter_ns()
        fts_ranked = base._fts_rank(case)[:FTS_WINDOW]
        fts_elapsed = (time.perf_counter_ns() - fts_started) / 1_000_000
        fts_ids = [memory_id for memory_id, _ in fts_ranked]

        dense_started = time.perf_counter_ns()
        query_embedding = np.asarray(
            model.encode_query([case.query], **query_kwargs)[0]
        )
        dense_elapsed = (time.perf_counter_ns() - dense_started) / 1_000_000

        if case.scope == "all":
            docs, doc_embeddings = all_docs, all_embeddings
        else:
            docs, doc_embeddings = current_docs, current_embeddings
        dense_ranked = _dense_rank(query_embedding, doc_embeddings, docs)
        dense_ids = [memory_id for memory_id, _ in dense_ranked]

        fused_ids, fused_scores, raw_top_ties = _rrf_fuse(fts_ids, dense_ids)
        total_elapsed = (time.perf_counter_ns() - total_started) / 1_000_000

        fts_latency_ms.append(fts_elapsed)
        dense_latency_ms.append(dense_elapsed)
        total_latency_ms.append(total_elapsed)
        fts_rankings[case.case_id] = fts_ids
        dense_rankings[case.case_id] = dense_ids
        fused_rankings[case.case_id] = fused_ids
        if len(raw_top_ties) > 1:
            raw_top_tie_cases.append(case.case_id)

        cases[case.case_id] = {
            "language": case.language,
            "scope": case.scope,
            "expected": case.expected_memory_id,
            "fts_top3": fts_ids[:3],
            "dense_top3": dense_ids[:3],
            "rrf_top3": [
                {
                    "memory_id": memory_id,
                    "rrf_score": round(fused_scores[memory_id], 8),
                }
                for memory_id in fused_ids[:3]
            ],
            "raw_rrf_top_ties": raw_top_ties,
            "rrf_hit_at_1": case.expected_memory_id is not None
            and fused_ids[0] == case.expected_memory_id,
        }

    output = {
        "status": "PASS",
        "purpose": "research-only; no production retrieval-stack approval",
        "model": MODEL_NAME,
        "device": str(next(model.parameters()).device),
        "qwen_prompt": JARVIS_MEMORY_PROMPT,
        "truncate_dim": TRUNCATE_DIM,
        "rrf": {
            "rank_constant": RRF_K,
            "fts_window": FTS_WINDOW,
            "weights": "equal",
            "exact_tie_break": "semantic rank, then lexical rank, then memory id",
        },
        "load_seconds": round(load_seconds, 4),
        "corpus_encode_seconds": round(corpus_encode_seconds, 4),
        "peak_cuda_bytes": (
            int(torch.cuda.max_memory_allocated())
            if torch.cuda.is_available()
            else None
        ),
        "metrics": {
            "fts5": base._positive_metrics(fts_rankings),
            "qwen_jarvis_256": base._positive_metrics(dense_rankings),
            "rrf_hybrid": base._positive_metrics(fused_rankings),
        },
        "latency_ms": {
            "fts_p50": round(statistics.median(fts_latency_ms), 4),
            "fts_p95": round(_percentile(fts_latency_ms, 0.95), 4),
            "qwen_encode_p50": round(statistics.median(dense_latency_ms), 4),
            "qwen_encode_p95": round(_percentile(dense_latency_ms, 0.95), 4),
            "hybrid_end_to_end_p50": round(statistics.median(total_latency_ms), 4),
            "hybrid_end_to_end_p95": round(_percentile(total_latency_ms, 0.95), 4),
        },
        "raw_rrf_top_tie_cases": raw_top_tie_cases,
        "cases": cases,
    }

    del model
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
