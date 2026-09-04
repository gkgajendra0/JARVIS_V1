"""Research-only Qwen3 memory-retrieval optimization bake-off.

This script imports the fixed Step-4 retrieval corpus and metrics from
``step4_memory_retrieval_bakeoff.py`` and evaluates only Qwen-specific options:

* the model's built-in generic query prompt versus a JARVIS-memory-specific prompt;
* Matryoshka output dimensions 1024, 512, and 256;
* retrieval quality, absent-answer score distribution, latency, and CUDA usage.

It does not implement runtime memory and it does not approve an embedding model.
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

MODEL_NAME = "Qwen/Qwen3-Embedding-0.6B"
JARVIS_MEMORY_PROMPT = (
    "Instruct: Given a JARVIS memory retrieval query, retrieve the most relevant "
    "trustworthy personal, episodic, project, or self-knowledge memory needed to "
    "answer the query\nQuery:"
)


def _rank(
    query_embedding: np.ndarray,
    doc_embeddings: np.ndarray,
    docs: tuple[base.MemoryDoc, ...],
) -> list[tuple[str, float]]:
    scores = np.asarray(doc_embeddings @ query_embedding, dtype=np.float64)
    order = np.argsort(-scores)
    return [(docs[index].memory_id, float(scores[index])) for index in order]


def _percentile(samples: list[float], fraction: float) -> float:
    ordered = sorted(samples)
    index = min(len(ordered) - 1, int(len(ordered) * fraction))
    return ordered[index]


def run_configuration(
    model: SentenceTransformer,
    *,
    prompt_mode: str,
    truncate_dim: int,
) -> dict[str, object]:
    current_docs = base._docs_for_scope("current")
    all_docs = base._docs_for_scope("all")

    encode_kwargs = {
        "normalize_embeddings": True,
        "convert_to_numpy": True,
        "show_progress_bar": False,
        "truncate_dim": truncate_dim,
    }

    corpus_started = time.perf_counter()
    current_embeddings = np.asarray(
        model.encode_document([doc.text for doc in current_docs], **encode_kwargs)
    )
    all_embeddings = np.asarray(
        model.encode_document([doc.text for doc in all_docs], **encode_kwargs)
    )
    corpus_seconds = time.perf_counter() - corpus_started

    query_kwargs = dict(encode_kwargs)
    if prompt_mode == "jarvis":
        query_kwargs["prompt"] = JARVIS_MEMORY_PROMPT

    _ = model.encode_query([base.QUERIES[0].query], **query_kwargs)

    rankings: dict[str, list[str]] = {}
    cases: dict[str, object] = {}
    query_latencies: list[float] = []
    absent_scores: list[float] = []
    expected_scores: list[float] = []

    for case in base.QUERIES:
        started = time.perf_counter_ns()
        query_embedding = np.asarray(
            model.encode_query([case.query], **query_kwargs)[0]
        )
        query_latencies.append((time.perf_counter_ns() - started) / 1_000_000)

        if case.scope == "all":
            docs, doc_embeddings = all_docs, all_embeddings
        else:
            docs, doc_embeddings = current_docs, current_embeddings

        ranked = _rank(query_embedding, doc_embeddings, docs)
        ids = [memory_id for memory_id, _ in ranked]
        rankings[case.case_id] = ids

        if case.expected_memory_id is None:
            absent_scores.append(ranked[0][1])
        else:
            expected_score = next(
                score
                for memory_id, score in ranked
                if memory_id == case.expected_memory_id
            )
            expected_scores.append(expected_score)

        cases[case.case_id] = {
            "language": case.language,
            "scope": case.scope,
            "expected": case.expected_memory_id,
            "top": [
                {"memory_id": memory_id, "score": round(score, 6)}
                for memory_id, score in ranked[:3]
            ],
            "hit_at_1": case.expected_memory_id is not None
            and ranked[0][0] == case.expected_memory_id,
        }

    return {
        "prompt_mode": prompt_mode,
        "truncate_dim": truncate_dim,
        "metrics": base._positive_metrics(rankings),
        "corpus_encode_seconds": round(corpus_seconds, 4),
        "query_encode_latency_ms": {
            "p50": round(statistics.median(query_latencies), 4),
            "p95": round(_percentile(query_latencies, 0.95), 4),
            "max": round(max(query_latencies), 4),
        },
        "absent_top_score_distribution": {
            "count": len(absent_scores),
            "min": round(min(absent_scores), 6),
            "median": round(statistics.median(absent_scores), 6),
            "max": round(max(absent_scores), 6),
        },
        "expected_memory_score_distribution": {
            "count": len(expected_scores),
            "min": round(min(expected_scores), 6),
            "median": round(statistics.median(expected_scores), 6),
            "max": round(max(expected_scores), 6),
        },
        "cases": cases,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", default="cuda")
    parser.add_argument(
        "--dims",
        default="1024,512,256",
        help="Comma-separated Matryoshka dimensions (default: 1024,512,256)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dims = [int(value.strip()) for value in args.dims.split(",") if value.strip()]
    invalid = [value for value in dims if value < 32 or value > 1024]
    if invalid:
        raise SystemExit(f"invalid Qwen dimensions: {invalid}")

    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()

    load_started = time.perf_counter()
    model = SentenceTransformer(MODEL_NAME, device=args.device)
    load_seconds = time.perf_counter() - load_started

    results: dict[str, object] = {}
    for prompt_mode in ("default", "jarvis"):
        for dimension in dims:
            key = f"{prompt_mode}_{dimension}"
            results[key] = run_configuration(
                model,
                prompt_mode=prompt_mode,
                truncate_dim=dimension,
            )

    output = {
        "status": "PASS",
        "purpose": "research-only; no production embedding approval",
        "model": MODEL_NAME,
        "device": str(next(model.parameters()).device),
        "load_seconds": round(load_seconds, 4),
        "peak_cuda_bytes": (
            int(torch.cuda.max_memory_allocated()) if torch.cuda.is_available() else None
        ),
        "jarvis_memory_prompt": JARVIS_MEMORY_PROMPT,
        "configurations": results,
    }

    del model
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
