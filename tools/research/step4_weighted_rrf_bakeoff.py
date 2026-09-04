"""Research-only weighted RRF sweep for Step 4 memory retrieval.

Equal-weight RRF improved overall retrieval quality but regressed one case that
Qwen semantic retrieval alone ranked correctly.  Weighted RRF is a mature hybrid
search mechanism, so this spike measures whether modestly favoring the empirically
stronger semantic signal fixes that regression while preserving lexical rescues.

This file is research-only and does not implement production JARVIS memory.
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
SEMANTIC_WEIGHTS = (1.0, 1.25, 1.5, 1.75, 2.0)


def _dense_rank(query_embedding, doc_embeddings, docs):
    scores = np.asarray(doc_embeddings @ query_embedding, dtype=np.float64)
    order = np.argsort(-scores)
    return [(docs[index].memory_id, float(scores[index])) for index in order]


def _weighted_rrf(fts_ids, dense_ids, semantic_weight):
    fts_rank = {mid: rank for rank, mid in enumerate(fts_ids, start=1)}
    dense_rank = {mid: rank for rank, mid in enumerate(dense_ids, start=1)}
    candidates = set(fts_rank) | set(dense_rank)
    scores = {}
    for mid in candidates:
        score = 0.0
        if mid in fts_rank:
            score += 1.0 / (RRF_K + fts_rank[mid])
        if mid in dense_rank:
            score += semantic_weight / (RRF_K + dense_rank[mid])
        scores[mid] = score
    ranked = sorted(
        candidates,
        key=lambda mid: (
            -scores[mid],
            dense_rank.get(mid, 10**9),
            fts_rank.get(mid, 10**9),
            mid,
        ),
    )
    return ranked, scores


def _percentile(samples, fraction):
    ordered = sorted(samples)
    return ordered[min(len(ordered) - 1, int(len(ordered) * fraction))]


def main():
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

    _ = model.encode_query([base.QUERIES[0].query], **query_kwargs)

    prepared = {}
    query_latencies = []
    fts_latencies = []
    for case in base.QUERIES:
        fts_started = time.perf_counter_ns()
        fts_ids = [mid for mid, _ in base._fts_rank(case)[:FTS_WINDOW]]
        fts_latencies.append((time.perf_counter_ns() - fts_started) / 1_000_000)

        dense_started = time.perf_counter_ns()
        query_embedding = np.asarray(model.encode_query([case.query], **query_kwargs)[0])
        query_latencies.append((time.perf_counter_ns() - dense_started) / 1_000_000)

        if case.scope == "all":
            docs, doc_embeddings = all_docs, all_embeddings
        else:
            docs, doc_embeddings = current_docs, current_embeddings
        dense_ids = [mid for mid, _ in _dense_rank(query_embedding, doc_embeddings, docs)]
        prepared[case.case_id] = (case, fts_ids, dense_ids)

    dense_rankings = {case_id: dense_ids for case_id, (_, _, dense_ids) in prepared.items()}
    fts_rankings = {case_id: fts_ids for case_id, (_, fts_ids, _) in prepared.items()}

    sweeps = {}
    for weight in SEMANTIC_WEIGHTS:
        rankings = {}
        case_results = {}
        for case_id, (case, fts_ids, dense_ids) in prepared.items():
            fused, scores = _weighted_rrf(fts_ids, dense_ids, weight)
            rankings[case_id] = fused
            expected = case.expected_memory_id
            case_results[case_id] = {
                "expected": expected,
                "fts_top3": fts_ids[:3],
                "dense_top3": dense_ids[:3],
                "fused_top3": [
                    {"memory_id": mid, "score": round(scores[mid], 8)}
                    for mid in fused[:3]
                ],
                "hit_at_1": expected is not None and fused[0] == expected,
            }
        positive_misses = [
            case_id
            for case_id, result in case_results.items()
            if result["expected"] is not None and not result["hit_at_1"]
        ]
        sweeps[str(weight)] = {
            "metrics": base._positive_metrics(rankings),
            "positive_rank1_misses": positive_misses,
            "cases": case_results,
        }

    output = {
        "status": "PASS",
        "purpose": "research-only; no production retrieval-stack approval",
        "model": MODEL_NAME,
        "device": str(next(model.parameters()).device),
        "truncate_dim": TRUNCATE_DIM,
        "rank_constant": RRF_K,
        "fts_window": FTS_WINDOW,
        "lexical_weight": 1.0,
        "semantic_weights_tested": list(SEMANTIC_WEIGHTS),
        "load_seconds": round(load_seconds, 4),
        "corpus_encode_seconds": round(corpus_encode_seconds, 4),
        "peak_cuda_bytes": int(torch.cuda.max_memory_allocated()) if torch.cuda.is_available() else None,
        "baselines": {
            "fts5": base._positive_metrics(fts_rankings),
            "qwen_jarvis_256": base._positive_metrics(dense_rankings),
        },
        "latency_ms": {
            "fts_p50": round(statistics.median(fts_latencies), 4),
            "fts_p95": round(_percentile(fts_latencies, 0.95), 4),
            "qwen_encode_p50": round(statistics.median(query_latencies), 4),
            "qwen_encode_p95": round(_percentile(query_latencies, 0.95), 4),
        },
        "sweeps": sweeps,
    }

    del model
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
