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
import statistics
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

from tools.research.step4_memory_shadow_benchmark import load_cases

ROOT = Path(__file__).resolve().parents[2]
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
) -> dict:
    """Exercise the actual Hindsight client; always clean up our random bank."""

    if not bank_id.startswith("jarvis-dev-only-"):
        raise ValueError("bank must be a newly created research-only bank")
    for case in case_data:
        if case.get("kind") != "context" or not all(
            isinstance(case.get(k), str) for k in ("request", "memory_hint", "id")
        ):
            raise ValueError("expected synthetic context cases")
    created = False
    observed: list[float] = []
    results_count = 0
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
        for case in case_data:
            start = time.monotonic()
            response = client.recall(bank_id=bank_id, query=case["request"])
            observed.append((time.monotonic() - start) * 1000.0)
            results_count += len(getattr(response, "results", ()))
    finally:
        if created:
            # Failure to delete cannot be hidden: this function raises.
            client.delete_bank(bank_id=bank_id)
            cleanup_verified = True
    return {
        "result_kind": "LOCAL_RETRIEVAL_DIAGNOSTIC_NOT_UTILITY_ACCEPTANCE",
        "queried": len(observed),
        "retrieved_entries_total": results_count,
        "query_latency_p50_ms": (
            round(statistics.median(observed), 2) if observed else None
        ),
        "synthetic_bank_cleanup_verified": cleanup_verified,
        "no_canonical_memory_access": True,
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

    corpus, _digest = load_cases(CASES)
    cases = [c for c in corpus["cases"] if c["kind"] == "context"]
    bank = f"jarvis-dev-only-{uuid.uuid4().hex}"
    client = Hindsight(base_url=url)
    try:
        report = run_local_retrieval_probe(
            client=client, case_data=cases[: args.max_queries], bank_id=bank
        )
    finally:
        client.close()
    print(json.dumps(report, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
