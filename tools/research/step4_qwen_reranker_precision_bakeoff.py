"""Research-only Qwen reranker precision/stability bake-off.

This harness keeps the already-measured first-stage retrieval fixed and asks one
narrow question: are the top-3 Qwen3-Reranker-0.6B ordering results stable, or are
BF16 score ties / batch-order effects materially affecting the observed ranking?

It compares:
* model-default BF16 inference;
* explicit FP32 inference;
* repeated scoring;
* original and reversed candidate order;
* exact score ties, score spread, ranking stability, latency and CUDA usage.

It remains under tools/research and does not implement production JARVIS memory.
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
CANDIDATE_WINDOW = 3


def _percentile(samples: list[float], fraction: float) -> float:
    ordered = sorted(samples)
    index = min(len(ordered) - 1, int(len(ordered) * fraction))
    return ordered[index]


def _dense_rank(query_embedding: np.ndarray, doc_embeddings: np.ndarray, docs):
    scores = np.asarray(doc_embeddings @ query_embedding, dtype=np.float64)
    order = np.argsort(-scores)
    return [docs[index].memory_id for index in order]


def _stable_rank(candidate_ids: list[str], score_by_id: dict[str, float]) -> list[str]:
    """Rank by score; exact ties retain first-stage candidate order explicitly."""
    first_stage_rank = {memory_id: rank for rank, memory_id in enumerate(candidate_ids)}
    return sorted(candidate_ids, key=lambda mid: (-score_by_id[mid], first_stage_rank[mid]))


def _build_first_stage(embedder: SentenceTransformer):
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
    current_embeddings = np.asarray(
        embedder.encode_document([doc.text for doc in current_docs], **encode_kwargs)
    )
    all_embeddings = np.asarray(
        embedder.encode_document([doc.text for doc in all_docs], **encode_kwargs)
    )
    _ = embedder.encode_query([base.QUERIES[0].query], **query_kwargs)

    rankings: dict[str, list[str]] = {}
    for case in base.QUERIES:
        fts_ids = [memory_id for memory_id, _ in base._fts_rank(case)[:FTS_WINDOW]]
        query_embedding = np.asarray(embedder.encode_query([case.query], **query_kwargs)[0])
        if case.scope == "all":
            docs, doc_embeddings = all_docs, all_embeddings
        else:
            docs, doc_embeddings = current_docs, current_embeddings
        dense_ids = _dense_rank(query_embedding, doc_embeddings, docs)
        fused_ids, _, _ = hybrid._rrf_fuse(fts_ids, dense_ids)
        rankings[case.case_id] = fused_ids[:CANDIDATE_WINDOW]
    return rankings


def _run_precision(
    *,
    label: str,
    model_kwargs: dict | None,
    device: str,
    repeats: int,
    first_stage_rankings: dict[str, list[str]],
    doc_by_id: dict[str, base.MemoryDoc],
) -> dict[str, object]:
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()

    load_started = time.perf_counter()
    reranker = CrossEncoder(
        RERANK_MODEL,
        device=device,
        model_kwargs=model_kwargs,
    )
    load_seconds = time.perf_counter() - load_started
    effective_dtype = str(next(reranker.model.parameters()).dtype)

    warm_case = base.QUERIES[0]
    warm_id = first_stage_rankings[warm_case.case_id][0]
    _ = reranker.predict(
        [(warm_case.query, doc_by_id[warm_id].text)],
        show_progress_bar=False,
    )

    rankings: dict[str, list[str]] = {}
    latencies: list[float] = []
    cases: dict[str, object] = {}
    exact_tie_cases: list[str] = []
    unstable_cases: list[str] = []

    for case in base.QUERIES:
        candidate_ids = first_stage_rankings[case.case_id]
        score_samples: dict[str, list[float]] = {mid: [] for mid in candidate_ids}
        observed_rankings: list[list[str]] = []

        orderings = [candidate_ids, list(reversed(candidate_ids))]
        for order_ids in orderings:
            for _ in range(repeats):
                pairs = [(case.query, doc_by_id[mid].text) for mid in order_ids]
                started = time.perf_counter_ns()
                raw_scores = reranker.predict(pairs, show_progress_bar=False)
                latencies.append((time.perf_counter_ns() - started) / 1_000_000)
                scores = np.asarray(raw_scores, dtype=np.float64).reshape(-1)
                score_by_id = {
                    memory_id: float(score)
                    for memory_id, score in zip(order_ids, scores)
                }
                for memory_id, score in score_by_id.items():
                    score_samples[memory_id].append(score)
                observed_rankings.append(_stable_rank(candidate_ids, score_by_id))

        median_scores = {
            mid: float(statistics.median(values)) for mid, values in score_samples.items()
        }
        final_ranking = _stable_rank(candidate_ids, median_scores)
        rankings[case.case_id] = final_ranking

        top_score = max(median_scores.values())
        top_ties = [
            mid for mid in candidate_ids if abs(median_scores[mid] - top_score) < 1e-12
        ]
        if len(top_ties) > 1:
            exact_tie_cases.append(case.case_id)

        unique_rankings = {tuple(ranking) for ranking in observed_rankings}
        if len(unique_rankings) > 1:
            unstable_cases.append(case.case_id)

        cases[case.case_id] = {
            "expected": case.expected_memory_id,
            "candidate_ids": candidate_ids,
            "median_scores": {mid: round(score, 8) for mid, score in median_scores.items()},
            "score_ranges": {
                mid: {
                    "min": round(min(values), 8),
                    "max": round(max(values), 8),
                    "span": round(max(values) - min(values), 8),
                }
                for mid, values in score_samples.items()
            },
            "top_ties": top_ties,
            "observed_unique_rankings": [list(item) for item in sorted(unique_rankings)],
            "final_ranking": final_ranking,
            "hit_at_1": case.expected_memory_id is not None
            and final_ranking[0] == case.expected_memory_id,
        }

    peak_cuda_bytes = (
        int(torch.cuda.max_memory_allocated()) if torch.cuda.is_available() else None
    )

    result = {
        "label": label,
        "effective_dtype": effective_dtype,
        "load_seconds": round(load_seconds, 4),
        "metrics": base._positive_metrics(rankings),
        "latency_ms": {
            "p50": round(statistics.median(latencies), 4),
            "p95": round(_percentile(latencies, 0.95), 4),
            "max": round(max(latencies), 4),
        },
        "peak_cuda_bytes": peak_cuda_bytes,
        "exact_top_tie_cases": exact_tie_cases,
        "order_or_repeat_unstable_cases": unstable_cases,
        "cases": cases,
    }

    del reranker
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if args.repeats < 1:
        raise SystemExit("--repeats must be >= 1")

    embedder = SentenceTransformer(EMBED_MODEL, device=args.device)
    first_stage_rankings = _build_first_stage(embedder)
    doc_by_id = {doc.memory_id: doc for doc in base.CORPUS}

    output: dict[str, object] = {
        "status": "PASS",
        "purpose": "research-only; no production precision/reranker approval",
        "candidate_window": CANDIDATE_WINDOW,
        "repeats_per_order": args.repeats,
        "orderings": ["first-stage", "reversed"],
        "embedding_model": EMBED_MODEL,
        "reranker_model": RERANK_MODEL,
        "configurations": {},
    }

    configs = [
        ("default", None),
        ("float32", {"torch_dtype": torch.float32}),
    ]
    for label, kwargs in configs:
        try:
            output["configurations"][label] = _run_precision(  # type: ignore[index]
                label=label,
                model_kwargs=kwargs,
                device=args.device,
                repeats=args.repeats,
                first_stage_rankings=first_stage_rankings,
                doc_by_id=doc_by_id,
            )
        except Exception as exc:
            output["status"] = "PARTIAL"
            output["configurations"][label] = {  # type: ignore[index]
                "error_type": type(exc).__name__,
                "error": str(exc),
            }

    del embedder
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
