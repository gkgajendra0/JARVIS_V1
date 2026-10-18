"""Owner-opt-in Step 8 harder-language Hindsight/BM25/hybrid study.

Dry-run: zero network calls and no Docker inspection.
Live flag: one new 60-fact *fictional-only* bank, exactly 24 local recalls,
then deletion via the proven Step 7 provenance/cleanup harness. No LLM.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from tools.research.step4_hindsight_loopback_import_probe import (
    DOCKER_CONTAINER,
    LocalHindsightHTTP,
    ProbeFailure,
    verify_local_container,
)
from tools.research.step7_local_engine_comparison import (
    run_one_local_comparison,
)

from jarvis.memory.research_challenge_suite import (
    CHALLENGE_CASES,
    score_challenge_rankings,
)
from jarvis.memory.research_compare_fixture import (
    TOP_K,
    bm25,
    build_archive,
    fuse,
    validate_archive,
    validate_recall,
)

CHALLENGE_COUNT = 24


def _json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def lexical_offline_score() -> dict[str, Any]:
    """Actual local deterministic BM25 baseline, no Hindsight or AI models."""
    lexical = {case.case_id: bm25(case.query) for case in CHALLENGE_CASES}
    empty = {case.case_id: () for case in CHALLENGE_CASES}
    report = score_challenge_rankings(
        {"hindsight": empty, "lexical": lexical, "hybrid": empty}
    )
    return report["engines"]["lexical"]


def capture_harder_retrieval(transport: Any, root: str) -> dict[str, Any]:
    """Runs exactly 24 fixed queries, returns only aggregate safe metrics."""
    if len(CHALLENGE_CASES) != CHALLENGE_COUNT:
        raise ProbeFailure("changed_challenge_count")
    rankings: dict[str, dict[str, tuple[str, ...]]] = {
        "hindsight": {},
        "lexical": {},
        "hybrid": {},
    }
    hindsight_ns = 0
    lexical_ns = 0
    for case in CHALLENGE_CASES:
        request = {
            "query": case.query,
            "query_timestamp": "2026-02-02T00:00:00Z",
            "types": ["world"],
            "budget": "mid",
            "max_tokens": 1024,
            "prefer_observations": False,
            "tags": ["jarvis-dev-only", "synthetic"],
            "tags_match": "all_strict",
            "trace": False,
        }
        started = time.perf_counter_ns()
        recalled = transport.request(
            "POST", f"{root}/memories/recall", _json(request), "application/json"
        )
        hindsight_ns += time.perf_counter_ns() - started
        try:
            hindsight = validate_recall(recalled)
        except (ValueError, TypeError):
            raise ProbeFailure("invalid_challenge_provenance") from None

        started = time.perf_counter_ns()
        lexical = bm25(case.query)
        lexical_ns += time.perf_counter_ns() - started
        rankings["hindsight"][case.case_id] = hindsight
        rankings["lexical"][case.case_id] = lexical
        rankings["hybrid"][case.case_id] = fuse(hindsight[:TOP_K], lexical[:TOP_K])

    try:
        report = score_challenge_rankings(rankings)
    except (ValueError, TypeError):
        raise ProbeFailure("invalid_challenge_scoring") from None
    report.update(
        {
            "kind": "STEP8_REAL_LOCAL_HARDER_LANGUAGE_COMPARISON",
            "hindsight_recall_requests": CHALLENGE_COUNT,
            "hindsight_http_total_ms": round(hindsight_ns / 1_000_000, 2),
            "lexical_inprocess_total_ms": round(lexical_ns / 1_000_000, 2),
            "latencies_not_directly_comparable": True,
            "actual_hindsight_retrieval_measured": True,
            "synthetic_corpus_provenance_verified": True,
            "no_provider_calls_configured": True,
            "owner_data_accessed": False,
        }
    )
    return report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-one-local-60-fact-hard-challenge",
        action="store_true",
        help="Explicit approval for one fictional bank and 24 actual local recalls.",
    )
    args = parser.parse_args(argv)
    if not args.allow_one_local_60_fact_hard_challenge:
        archive = validate_archive(build_archive())
        print(
            json.dumps(
                {
                    "kind": "STEP8_HARD_LANGUAGE_PROTOCOL_PREVIEW",
                    "status": "dry_run_zero_network_calls",
                    "archive_sha256": archive["sha256"],
                    "documents_planned": archive["documents"],
                    "queries_planned": CHALLENGE_COUNT,
                    "supported_questions": 20,
                    "unknown_questions": 2,
                    "prelabeled_unresolved_questions": 2,
                    "top_k": TOP_K,
                    "required_container": DOCKER_CONTAINER,
                    "local_import_approved": False,
                    "lexical_offline_only": lexical_offline_score(),
                    "hindsight_real_measured": False,
                    "production_promotion_allowed": False,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return
    try:
        verify_local_container()
        report = run_one_local_comparison(
            LocalHindsightHTTP(),
            inspected=True,
            bank_id=f"jarvis-dev-only-{uuid.uuid4().hex}",
            capture=capture_harder_retrieval,
        )
        comparison = report["comparison"]
        report["kind"] = "STEP8_OWNER_LOCAL_HARD_LANGUAGE_BENCHMARK"
    except Exception as exc:  # noqa: BLE001 - sanitized no owner data
        code = str(exc) if isinstance(exc, ProbeFailure) else "hard_probe_failed"
        print(
            json.dumps(
                {
                    "kind": "STEP8_OWNER_LOCAL_HARD_LANGUAGE_BENCHMARK",
                    "status": "fail_closed",
                    "reason_code": code,
                },
                indent=2,
                sort_keys=True,
            )
        )
        raise SystemExit(1) from None
    print(json.dumps(report, indent=2, sort_keys=True))
    if not comparison["hybrid_noninferior_on_challenge"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
