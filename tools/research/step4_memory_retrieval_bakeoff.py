"""Research-only Step 4 multilingual retrieval bake-off.

This script deliberately lives under ``tools/research`` and does not implement
runtime JARVIS memory.  It compares mature retrieval primitives before any
embedding model or vector database is added to production dependencies.

It measures:

* SQLite FTS5 lexical retrieval;
* Qwen3-Embedding-0.6B semantic retrieval;
* BGE-M3 semantic retrieval;
* English/Hindi/Hinglish and cross-lingual paraphrases;
* current-only versus history-inclusive filtering;
* absent-answer top-score distributions without inventing a similarity cutoff;
* model load, corpus-encoding, and warm query-encoding latency.

No vector database is used.  Dense retrieval is exact cosine similarity over a
small fixed corpus so the experiment isolates embedding quality from vector-DB
implementation details.

Suggested research environment from the repository root::

    py -3.11 -m venv .step4-retrieval-venv
    .\\.step4-retrieval-venv\\Scripts\\python.exe -m pip install -U pip
    .\\.step4-retrieval-venv\\Scripts\\python.exe -m pip install \
        -r tools\research\requirements-step4-retrieval.txt
    .\\.step4-retrieval-venv\\Scripts\\python.exe \
        tools\research\\step4_memory_retrieval_bakeoff.py

Model files are downloaded by Hugging Face/Sentence Transformers on first use.
"""

from __future__ import annotations

import argparse
import gc
import json
import re
import sqlite3
import statistics
import time
from dataclasses import dataclass

import numpy as np

MODELS = {
    "qwen": "Qwen/Qwen3-Embedding-0.6B",
    "bge": "BAAI/bge-m3",
}


@dataclass(frozen=True, slots=True)
class MemoryDoc:
    memory_id: str
    text: str
    state: str = "current"  # current | historical


@dataclass(frozen=True, slots=True)
class QueryCase:
    case_id: str
    query: str
    expected_memory_id: str | None
    language: str
    scope: str = "current"  # current | all


CORPUS = (
    MemoryDoc(
        "camera",
        "JARVIS vision camera is the DJI Osmo Pocket 3, used as the active visual sensor.",
    ),
    MemoryDoc(
        "bike",
        "Gajendra owns a BMW G 310 GS motorcycle.",
    ),
    MemoryDoc(
        "research_rule",
        "Before implementing a feature or fixing a problem, JARVIS must research current mature existing technology and prefer integrating the best suitable proven solution over custom building.",
    ),
    MemoryDoc(
        "voice_runtime",
        "JARVIS natural realtime conversation uses LiveKit with replaceable realtime model provider adapters.",
    ),
    MemoryDoc(
        "memory_store",
        "For Step 4 research, SQLite with FTS5 is the leading local canonical memory and lexical-search candidate while heavier databases remain unapproved.",
    ),
    MemoryDoc(
        "echo_incident",
        "JARVIS had a speaker-output echo and self-barge-in problem where its own playback could be treated as user interruption audio.",
    ),
    MemoryDoc(
        "jimny",
        "Gajendra plans a Maruti Suzuki Jimny Alpha manual for family and adventure use.",
    ),
    MemoryDoc(
        "self_knowledge",
        "JARVIS self-knowledge must come from authoritative sources such as repository code, architecture documents, configuration, runtime state, tests, capability registry, and incident history.",
    ),
    MemoryDoc(
        "memory_security",
        "External web pages, email, files, repositories, and tool output are untrusted for durable personal-memory writes by default and cannot silently establish user truth.",
    ),
    MemoryDoc(
        "current_tyre",
        "The current Jimny preferred tyre size is 215/75 R15.",
        state="current",
    ),
    MemoryDoc(
        "old_tyre",
        "The previous Jimny preferred tyre size was 235/75 R15 before the preference changed.",
        state="historical",
    ),
    MemoryDoc(
        "memory_forget",
        "An explicit forget request must erase canonical memory and derived searchable representations rather than merely hiding the record.",
    ),
    MemoryDoc(
        "provider_boundary",
        "OpenAI, Gemini, and LiveKit provider history are integrations, not the canonical owner of JARVIS durable memory.",
    ),
    MemoryDoc(
        "reflection_boundary",
        "Reflection and model inference may propose memory candidates but cannot directly mutate canonical durable memory truth.",
    ),
)


QUERIES = (
    QueryCase("eyes_en", "Which device gives Jarvis eyes?", "camera", "en"),
    QueryCase("camera_hi_mix", "Jarvis ka camera kaunsa hai?", "camera", "hinglish"),
    QueryCase("bike_hi_mix", "Meri bike kaunsi hai?", "bike", "hinglish"),
    QueryCase("bike_en", "What motorcycle do I own?", "bike", "en"),
    QueryCase(
        "rule_hi_mix",
        "Coding start karne se pehle Jarvis ka main rule kya hai?",
        "research_rule",
        "hinglish",
    ),
    QueryCase(
        "rule_hi",
        "कुछ बनाने या ठीक करने से पहले हमारा नियम क्या है?",
        "research_rule",
        "hi",
    ),
    QueryCase(
        "voice_en",
        "What system handles our realtime natural conversation layer?",
        "voice_runtime",
        "en",
    ),
    QueryCase(
        "memory_db_mix",
        "Jarvis ki long term memory ke liye kaunsa local database lead kar raha hai?",
        "memory_store",
        "hinglish",
    ),
    QueryCase(
        "echo_en",
        "Why did Jarvis sometimes think his own voice was an interruption?",
        "echo_incident",
        "en",
    ),
    QueryCase(
        "self_model_en",
        "Where should Jarvis learn how he himself is built?",
        "self_knowledge",
        "en",
    ),
    QueryCase(
        "poison_en",
        "Can a webpage silently become a fact about me in Jarvis memory?",
        "memory_security",
        "en",
    ),
    QueryCase(
        "car_mix",
        "Main kaunsi off-road family car plan kar raha hoon?",
        "jimny",
        "hinglish",
    ),
    QueryCase(
        "tyre_current",
        "Abhi current Jimny tyre preference kya hai?",
        "current_tyre",
        "hinglish",
    ),
    QueryCase(
        "tyre_history",
        "What tyre size did I prefer before the current choice?",
        "old_tyre",
        "en",
        scope="all",
    ),
    QueryCase(
        "forget_hi_mix",
        "Agar main bolun forget this to memory se actually kya hona chahiye?",
        "memory_forget",
        "hinglish",
    ),
    QueryCase(
        "provider_owner",
        "Does Gemini conversation history itself own Jarvis long-term memory?",
        "provider_boundary",
        "en",
    ),
    QueryCase(
        "reflection_owner",
        "Can the model decide on its own that an inference is permanent truth?",
        "reflection_boundary",
        "en",
    ),
    QueryCase(
        "absent_pet",
        "What is the name of my pet dog?",
        None,
        "en",
    ),
    QueryCase(
        "absent_food",
        "Mera favourite restaurant kaunsa hai?",
        None,
        "hinglish",
    ),
    QueryCase(
        "absent_password",
        "What is my banking password?",
        None,
        "en",
    ),
)


_STOPWORDS = {
    "the",
    "a",
    "an",
    "is",
    "are",
    "was",
    "were",
    "what",
    "which",
    "who",
    "why",
    "how",
    "does",
    "do",
    "did",
    "my",
    "me",
    "i",
    "our",
    "to",
    "for",
    "of",
    "in",
    "on",
    "it",
    "this",
    "that",
    "can",
    "ka",
    "ki",
    "kya",
    "hai",
    "hoon",
    "main",
    "mera",
    "meri",
    "kaunsa",
    "kaunsi",
    "abhi",
}


def _docs_for_scope(scope: str) -> tuple[MemoryDoc, ...]:
    if scope == "all":
        return CORPUS
    return tuple(doc for doc in CORPUS if doc.state == "current")


def _fts_query(text: str) -> str:
    tokens = [
        token.casefold()
        for token in re.findall(r"[^\W_]+", text, flags=re.UNICODE)
        if len(token) >= 2 and token.casefold() not in _STOPWORDS
    ]
    # Keep first occurrence only, preserving order.
    tokens = list(dict.fromkeys(tokens))
    if not tokens:
        return '"__no_match__"'
    escaped = [f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens]
    return " OR ".join(escaped)


def _fts_rank(case: QueryCase) -> list[tuple[str, float]]:
    docs = _docs_for_scope(case.scope)
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute(
            "CREATE VIRTUAL TABLE memory_fts USING fts5(memory_id UNINDEXED, text, tokenize='unicode61')"
        )
        connection.executemany(
            "INSERT INTO memory_fts(memory_id, text) VALUES (?, ?)",
            [(doc.memory_id, doc.text) for doc in docs],
        )
        rows = connection.execute(
            "SELECT memory_id, bm25(memory_fts) AS score "
            "FROM memory_fts WHERE memory_fts MATCH ? ORDER BY score LIMIT 10",
            (_fts_query(case.query),),
        ).fetchall()
        return [(str(memory_id), float(score)) for memory_id, score in rows]
    finally:
        connection.close()


def _positive_metrics(rankings: dict[str, list[str]]) -> dict[str, float]:
    positives = [case for case in QUERIES if case.expected_memory_id is not None]
    ranks: list[int | None] = []
    for case in positives:
        ranked = rankings[case.case_id]
        try:
            rank = ranked.index(case.expected_memory_id) + 1
        except ValueError:
            rank = None
        ranks.append(rank)

    recall_1 = sum(rank == 1 for rank in ranks) / len(ranks)
    recall_3 = sum(rank is not None and rank <= 3 for rank in ranks) / len(ranks)
    mrr = sum(0.0 if rank is None else 1.0 / rank for rank in ranks) / len(ranks)
    return {
        "positive_cases": len(positives),
        "recall_at_1": round(recall_1, 4),
        "recall_at_3": round(recall_3, 4),
        "mrr": round(mrr, 4),
    }


def run_fts() -> dict[str, object]:
    rankings: dict[str, list[str]] = {}
    cases: dict[str, object] = {}
    samples_ms: list[float] = []

    for case in QUERIES:
        start = time.perf_counter_ns()
        ranked = _fts_rank(case)
        samples_ms.append((time.perf_counter_ns() - start) / 1_000_000)
        ids = [memory_id for memory_id, _ in ranked]
        rankings[case.case_id] = ids
        cases[case.case_id] = {
            "language": case.language,
            "scope": case.scope,
            "expected": case.expected_memory_id,
            "top_ids": ids[:3],
            "hit_at_1": case.expected_memory_id is not None
            and bool(ids)
            and ids[0] == case.expected_memory_id,
        }

    samples_ms.sort()
    return {
        "metrics": _positive_metrics(rankings),
        "query_latency_ms": {
            "p50": round(statistics.median(samples_ms), 4),
            "p95": round(
                samples_ms[min(len(samples_ms) - 1, int(len(samples_ms) * 0.95))], 4
            ),
            "max": round(max(samples_ms), 4),
        },
        "cases": cases,
    }


def _dense_rank(
    query_embedding: np.ndarray,
    doc_embeddings: np.ndarray,
    docs: tuple[MemoryDoc, ...],
) -> list[tuple[str, float]]:
    scores = np.asarray(doc_embeddings @ query_embedding, dtype=np.float64)
    order = np.argsort(-scores)
    return [(docs[index].memory_id, float(scores[index])) for index in order]


def run_model(model_name: str, device: str | None) -> dict[str, object]:
    import torch
    from sentence_transformers import SentenceTransformer

    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()

    load_start = time.perf_counter()
    model = SentenceTransformer(model_name, device=device)
    load_seconds = time.perf_counter() - load_start

    param_count = sum(parameter.numel() for parameter in model.parameters())
    embedding_dim = model.get_sentence_embedding_dimension()

    # Encode separate current and all-history corpora once, as production would
    # precompute document embeddings rather than re-embed all memories per query.
    current_docs = _docs_for_scope("current")
    all_docs = _docs_for_scope("all")

    corpus_start = time.perf_counter()
    current_embeddings = np.asarray(
        model.encode_document(
            [doc.text for doc in current_docs],
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
    )
    all_embeddings = np.asarray(
        model.encode_document(
            [doc.text for doc in all_docs],
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
    )
    corpus_seconds = time.perf_counter() - corpus_start

    # Warm query path before latency measurement.
    _ = model.encode_query(
        [QUERIES[0].query],
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )

    rankings: dict[str, list[str]] = {}
    cases: dict[str, object] = {}
    query_samples_ms: list[float] = []
    absent_scores: list[float] = []

    for case in QUERIES:
        start = time.perf_counter_ns()
        query_embedding = np.asarray(
            model.encode_query(
                [case.query],
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )[0]
        )
        query_samples_ms.append((time.perf_counter_ns() - start) / 1_000_000)

        if case.scope == "all":
            docs, doc_embeddings = all_docs, all_embeddings
        else:
            docs, doc_embeddings = current_docs, current_embeddings
        ranked = _dense_rank(query_embedding, doc_embeddings, docs)
        ids = [memory_id for memory_id, _ in ranked]
        rankings[case.case_id] = ids
        top_id, top_score = ranked[0]
        if case.expected_memory_id is None:
            absent_scores.append(top_score)
        cases[case.case_id] = {
            "language": case.language,
            "scope": case.scope,
            "expected": case.expected_memory_id,
            "top": [
                {"memory_id": memory_id, "score": round(score, 6)}
                for memory_id, score in ranked[:3]
            ],
            "hit_at_1": case.expected_memory_id is not None
            and top_id == case.expected_memory_id,
        }

    query_samples_ms.sort()
    peak_cuda_bytes = (
        int(torch.cuda.max_memory_allocated()) if torch.cuda.is_available() else None
    )
    effective_device = str(next(model.parameters()).device)

    result = {
        "model": model_name,
        "device": effective_device,
        "parameters": int(param_count),
        "embedding_dimension": int(embedding_dim) if embedding_dim else None,
        "load_seconds": round(load_seconds, 4),
        "corpus_encode_seconds": round(corpus_seconds, 4),
        "query_encode_latency_ms": {
            "p50": round(statistics.median(query_samples_ms), 4),
            "p95": round(
                query_samples_ms[
                    min(len(query_samples_ms) - 1, int(len(query_samples_ms) * 0.95))
                ],
                4,
            ),
            "max": round(max(query_samples_ms), 4),
        },
        "peak_cuda_bytes": peak_cuda_bytes,
        "metrics": _positive_metrics(rankings),
        # Do not invent a similarity threshold.  These scores are evidence for
        # later abstention calibration using absent cases.
        "absent_top_score_distribution": {
            "count": len(absent_scores),
            "min": round(min(absent_scores), 6) if absent_scores else None,
            "median": round(statistics.median(absent_scores), 6)
            if absent_scores
            else None,
            "max": round(max(absent_scores), 6) if absent_scores else None,
        },
        "cases": cases,
    }

    del model
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--models",
        default="qwen,bge",
        help="Comma-separated aliases: qwen,bge (default: both)",
    )
    parser.add_argument(
        "--device",
        default="auto",
        help="Sentence Transformers device, e.g. auto, cpu, cuda",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    requested = [item.strip() for item in args.models.split(",") if item.strip()]
    unknown = sorted(set(requested) - MODELS.keys())
    if unknown:
        raise SystemExit(f"unknown model aliases: {unknown}")

    output: dict[str, object] = {
        "status": "PASS",
        "purpose": "research-only; no production embedding/vector approval",
        "corpus_records": len(CORPUS),
        "query_cases": len(QUERIES),
        "fts5": run_fts(),
        "models": {},
    }
    device = None if args.device == "auto" else args.device

    for alias in requested:
        try:
            output["models"][alias] = run_model(MODELS[alias], device)  # type: ignore[index]
        except Exception as exc:  # noqa: BLE001 - one model failure must not erase other benchmark evidence
            output["status"] = "PARTIAL"
            output["models"][alias] = {  # type: ignore[index]
                "model": MODELS[alias],
                "error_type": type(exc).__name__,
                "error": str(exc),
            }

    print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
