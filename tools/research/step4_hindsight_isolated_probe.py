"""Opt-in Hindsight *local-only* retrieval probe with temporary synthetic bank.

This is a retrieval feasibility/latency diagnostic, NOT a 4.5E influence
quality comparison and NOT a replacement for JARVIS's canonical memory.
Requires a separately running Hindsight server with its own configured LLM.
No private SQLCipher data or production memory is read.

Run in a disposable research environment:
  python tools/research/step4_hindsight_isolated_probe.py \
      --allow-local-server-writes --max-queries 3

The script creates a random prefixed bank, seeds synthetic memory hints,
queries it, reports only aggregate counts, and deletes only its own bank.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.research.step4_memory_model_comparators import (
    require_pinned_synthetic_corpus,
)
from tools.research.step4_memory_shadow_benchmark import load_cases

CASES = ROOT / "tools/research/step4_memory_shadow_development_cases_v1.json"
SAFE_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def require_loopback(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "http" or parsed.hostname not in SAFE_HOSTS:
        raise ValueError("Hindsight probe accepts only local HTTP loopback servers")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Hindsight URL must not contain credentials or parameters")
    if parsed.path not in {"", "/"}:
        raise ValueError("Hindsight URL must identify server root")
    return url.rstrip("/")


def run_local_retrieval_probe(
    *,
    client: object,
    case_data: list[dict],
    bank_id: str,
    max_queries: int | None = None,
) -> dict:
    """Seed distractors, query a bounded subset, and always delete the bank.

    Development-only source-document ranking statistics do not measure
    downstream answer safety or prove an independent utility classifier.
    """

    if not bank_id.startswith("jarvis-dev-only-"):
        raise ValueError("bank must be a newly created research-only bank")
    for case in case_data:
        if case.get("kind") != "context" or not all(
            isinstance(case.get(k), str) for k in ("request", "memory_hint", "id")
        ):
            raise ValueError("expected synthetic context cases")
    if len({case["id"] for case in case_data}) != len(case_data):
        raise ValueError("duplicate synthetic case id")
    if max_queries is not None and not 1 <= max_queries <= len(case_data):
        raise ValueError("max_queries outside synthetic corpus size")
    queried_cases = case_data[:max_queries] if max_queries else case_data
    known_docs = {f"dev_{case['id']}" for case in case_data}
    created = False
    observed: list[float] = []
    results_count = 0
    positive_queries = 0
    positive_top1_correct_doc = 0
    positive_top3_correct_doc = 0
    negative_queries = 0
    negative_self_doc_top3 = 0
    missing_document_id = 0
    unknown_document_id = 0
    cleanup_verified = False
    try:
        client.create_bank(bank_id=bank_id)
        created = True
        client.retain_batch(
            bank_id=bank_id,
            items=[
                {
                    "content": case["memory_hint"],
                    "document_id": f"dev_{case['id']}",
                    "context": "synthetic Jarvis development fixture",
                }
                for case in case_data
            ],
        )
        for case in queried_cases:
            start = time.monotonic()
            response = client.recall(bank_id=bank_id, query=case["request"])
            observed.append((time.monotonic() - start) * 1000.0)
            results = list(getattr(response, "results", ()) or ())
            results_count += len(results)
            document_ids = [getattr(result, "document_id", None) for result in results]
            missing_document_id += sum(
                not isinstance(doc, str) or not doc for doc in document_ids
            )
            unknown_document_id += sum(
                isinstance(doc, str) and bool(doc) and doc not in known_docs
                for doc in document_ids
            )
            own_doc = f"dev_{case['id']}"
            if case.get("expected") in {"essential", "helpful"}:
                positive_queries += 1
                positive_top1_correct_doc += int(
                    bool(document_ids) and document_ids[0] == own_doc
                )
                positive_top3_correct_doc += int(own_doc in document_ids[:3])
            else:
                # Hard negatives can retrieve a topically related document.
                # That is exposure, NOT proof of unsafe context injection.
                negative_queries += 1
                negative_self_doc_top3 += int(own_doc in document_ids[:3])
    finally:
        if created:
            # Failure to delete cannot be hidden: this function raises.
            client.delete_bank(bank_id=bank_id)
            cleanup_verified = True
    ordered = sorted(observed)
    p95_index = max(0, math.ceil(len(ordered) * 0.95) - 1)
    return {
        "result_kind": "LOCAL_RETRIEVAL_DIAGNOSTIC_NOT_UTILITY_ACCEPTANCE",
        "seeded_documents_including_distractors": len(case_data),
        "queried": len(observed),
        "retrieved_entries_total": results_count,
        "positive_queries": positive_queries,
        "positive_top1_correct_document": positive_top1_correct_doc,
        "positive_top3_correct_document": positive_top3_correct_doc,
        "negative_queries": negative_queries,
        "negative_own_document_in_top3": negative_self_doc_top3,
        "results_missing_document_id": missing_document_id,
        "results_outside_synthetic_bank_ids": unknown_document_id,
        "query_latency_p50_ms": (
            round(statistics.median(observed), 2) if observed else None
        ),
        "query_latency_p95_ms": round(ordered[p95_index], 2) if ordered else None,
        "synthetic_bank_cleanup_verified": cleanup_verified,
        "no_canonical_memory_access": True,
        "not_an_answer_quality_or_safety_score": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8888")
    parser.add_argument("--max-queries", type=int, default=3)
    parser.add_argument("--allow-local-server-writes", action="store_true")
    args = parser.parse_args()
    if not args.allow_local_server_writes:
        parser.error("explicit --allow-local-server-writes approval required")
    if not 1 <= args.max_queries <= 24:
        parser.error("--max-queries must be 1..24")
    url = require_loopback(args.url)
    from hindsight_client import Hindsight

    corpus, digest = load_cases(CASES)
    require_pinned_synthetic_corpus(digest)
    cases = [c for c in corpus["cases"] if c["kind"] == "context"]
    bank = f"jarvis-dev-only-{uuid.uuid4().hex}"
    client = Hindsight(base_url=url)
    try:
        report = run_local_retrieval_probe(
            client=client,
            case_data=cases,
            bank_id=bank,
            max_queries=args.max_queries,
        )
    finally:
        client.close()
    print(json.dumps(report, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
