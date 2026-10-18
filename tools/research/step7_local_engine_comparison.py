"""Step 7: one opt-in LOCAL 60-fact Hindsight vs lexical vs RRF study.

No external model, real owner memory, SQLCipher, runtime integration, or
automatic retries. Default is OFFLINE and zero network requests. Explicit
owner approval creates ONE disposable synthetic bank, verifies all facts,
executes 18 fixed queries, and always attempts to delete the bank.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from tools.research.step4_hindsight_loopback_import_probe import (
    DOCKER_CONTAINER,
    LocalHTTPError,
    LocalHindsightHTTP,
    ProbeFailure,
    _multipart,
    _require_disabled_config,
    verify_local_container,
)

from jarvis.memory.research_compare_fixture import (
    BY_ID,
    CASES,
    DOCUMENT_COUNT,
    FACTS,
    TOP_K,
    bm25,
    build_archive,
    fuse,
    metadata,
    score_rankings,
    validate_archive,
    validate_recall,
)

POLL_LIMIT = 90
POLL_PAUSE_SECONDS = 2
_BANK = re.compile(r"^jarvis-dev-only-[0-9a-f]{32}$")
_OPERATION = re.compile(r"^[a-zA-Z0-9_-]{4,100}$")
CASE_COUNT = 18


def _json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _assert_no_prior_banks(transport: Any) -> None:
    prior = transport.request(
        "GET", "/v1/default/banks?query=jarvis-dev-only-&limit=100"
    )
    if prior.get("total") != 0:
        raise ProbeFailure("existing_research_banks_detected")


def _readback(transport: Any, root: str) -> None:
    listed = transport.request("GET", f"{root}/documents?limit=100")
    items = listed.get("items")
    expected = {f"jarvis-dev-only-{fact.assertion.assertion_id}" for fact in FACTS}
    if (
        listed.get("total") != DOCUMENT_COUNT
        or not isinstance(items, list)
        or len(items) != DOCUMENT_COUNT
        or any(not isinstance(doc, dict) for doc in items)
        or {doc.get("id") for doc in items} != expected
        or any(doc.get("memory_unit_count") != 1 for doc in items)
    ):
        raise ProbeFailure("scale_document_list_mismatch")

    for fact in FACTS:
        doc_id = f"jarvis-dev-only-{fact.assertion.assertion_id}"
        detail = transport.request("GET", f"{root}/documents/{doc_id}")
        if (
            detail.get("id") != doc_id
            or detail.get("original_text") != fact.text
            or detail.get("memory_unit_count") != 1
        ):
            raise ProbeFailure("scale_document_readback_mismatch")
        found = transport.request(
            "GET", f"{root}/memories/list?document_id={doc_id}&limit=2"
        )
        rows = found.get("items")
        if (
            found.get("total") != 1
            or not isinstance(rows, list)
            or len(rows) != 1
            or not isinstance(rows[0], dict)
            or rows[0].get("document_id") != doc_id
            or rows[0].get("text") != fact.text
            or rows[0].get("fact_type") != "world"
            or rows[0].get("metadata") != metadata(fact)
        ):
            raise ProbeFailure("scale_fact_provenance_mismatch")


def _capture_comparison(transport: Any, root: str) -> dict[str, Any]:
    if len(CASES) != CASE_COUNT:
        raise ProbeFailure("scale_case_protocol_changed")
    rankings: dict[str, dict[str, tuple[str, ...]]] = {
        "hindsight": {},
        "lexical": {},
        "hybrid": {},
    }
    hindsight_ns = 0
    lexical_ns = 0
    for case in CASES:
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
            "POST",
            f"{root}/memories/recall",
            _json(request),
            "application/json",
        )
        hindsight_ns += time.perf_counter_ns() - started
        try:
            hindsight = validate_recall(recalled)
        except (ValueError, TypeError):
            raise ProbeFailure("untrusted_scale_recall_evidence") from None

        started = time.perf_counter_ns()
        lexical = bm25(case.query)
        lexical_ns += time.perf_counter_ns() - started
        rankings["hindsight"][case.case_id] = hindsight
        rankings["lexical"][case.case_id] = lexical
        rankings["hybrid"][case.case_id] = fuse(
            hindsight[:TOP_K], lexical[:TOP_K]
        )
    report = score_rankings(rankings)
    h = report["engines"]["hindsight"]
    hybrid = report["engines"]["hybrid"]
    delta_hits = hybrid["retrieval_hits"] - h["retrieval_hits"]
    delta_answers = (
        hybrid["structured_decisions_correct"] - h["structured_decisions_correct"]
    )
    report.update(
        {
            "kind": "STEP7_REAL_LOCAL_HINDSIGHT_ENGINE_COMPARISON",
            "real_hindsight_recall_measured": True,
            "hindsight_recall_requests": CASE_COUNT,
            "synthetic_corpus_provenance_verified": True,
            "hybrid_retrieval_delta": delta_hits,
            "hybrid_structured_decision_delta": delta_answers,
            "hybrid_noninferior_on_this_fixture": delta_hits >= 0
            and delta_answers >= 0,
            "hindsight_http_total_ms": round(hindsight_ns / 1_000_000, 2),
            "lexical_inprocess_total_ms": round(lexical_ns / 1_000_000, 2),
            "latencies_not_directly_comparable": True,
            "no_provider_calls_configured": True,
            "owner_data_accessed": False,
        }
    )
    return report


def run_one_local_comparison(
    transport: Any,
    *,
    inspected: bool,
    bank_id: str,
    pause: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """One import with unconditional cleanup, including failed import/recall."""
    if inspected is not True:
        raise ProbeFailure("docker_provenance_not_verified")
    if not isinstance(bank_id, str) or not _BANK.fullmatch(bank_id):
        raise ProbeFailure("invalid_disposable_bank_id")
    archive = build_archive()
    archive_inspected = validate_archive(archive)
    root = f"/v1/default/banks/{bank_id}"
    created_or_uncertain = False
    primary: Exception | None = None
    cleaned = False
    result: dict[str, Any] = {}
    # A read-only preflight guards against accidentally overlapping prior labs.
    _assert_no_prior_banks(transport)
    try:
        transport.request("GET", "/version")
        created_or_uncertain = True
        transport.request("PUT", root, _json({}), "application/json")
        _require_disabled_config(transport.request("GET", f"{root}/config"))
        multipart, content_type = _multipart(archive)
        uploaded = transport.request(
            "POST",
            f"{root}/transfer/import?mode=merge&document_conflict=skip",
            multipart,
            content_type,
        )
        operation_id = uploaded.get("operation_id")
        if not isinstance(operation_id, str) or not _OPERATION.fullmatch(operation_id):
            raise ProbeFailure("invalid_scale_import_reference")
        last = "unknown"
        for index in range(POLL_LIMIT):
            progress = transport.request(
                "GET", f"{root}/operations/{operation_id}"
            )
            last = progress.get("status")
            if last in ("failed", "cancelled", "not_found"):
                raise ProbeFailure("scale_import_operation_failed")
            if last == "completed":
                break
            if index != POLL_LIMIT - 1:
                pause(POLL_PAUSE_SECONDS)
        if last != "completed":
            raise ProbeFailure("scale_import_operation_timeout")
        _readback(transport, root)
        result = _capture_comparison(transport, root)
    except Exception as exc:  # noqa: BLE001 - deletion must happen
        primary = exc
    finally:
        if created_or_uncertain:
            try:
                try:
                    deleted = transport.request("DELETE", root)
                except LocalHTTPError as exc:
                    if exc.status_code == 404:
                        cleaned = True
                    else:
                        raise
                else:
                    if deleted.get("success") is not True:
                        raise ProbeFailure("scale_bank_deletion_failed")
                    try:
                        transport.request("GET", f"{root}/config")
                    except LocalHTTPError as exc:
                        if exc.status_code == 404:
                            cleaned = True
                        else:
                            raise
                    if not cleaned:
                        raise ProbeFailure("scale_bank_still_exists")
            except Exception as cleanup_error:
                if primary is not None:
                    p = str(primary) if isinstance(primary, ProbeFailure) else "unknown"
                    c = (
                        str(cleanup_error)
                        if isinstance(cleanup_error, ProbeFailure)
                        else "unknown"
                    )
                    raise ProbeFailure(f"primary_{p}__cleanup_{c}") from None
                raise ProbeFailure("scale_bank_cleanup_unverified") from None
    if primary is not None:
        raise primary
    if not cleaned:
        raise ProbeFailure("scale_bank_cleanup_unverified")
    return {
        "kind": "STEP7_OWNER_LOCAL_ENGINE_BENCHMARK",
        "status": "measured",
        "archive_sha256": archive_inspected["sha256"],
        "documents_imported_and_verified": DOCUMENT_COUNT,
        "disposable_bank_cleanup_verified": True,
        "no_consolidation_triggered": True,
        "production_promotion_allowed": False,
        "comparison": result,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-one-local-60-fact-comparison",
        action="store_true",
        help="Explicit owner approval for one new synthetic bank and 18 local recalls.",
    )
    args = parser.parse_args(argv)
    if not args.allow_one_local_60_fact_comparison:
        archive_info = validate_archive(build_archive())
        print(
            json.dumps(
                {
                    "kind": "STEP7_REAL_ENGINE_COMPARISON_PROTOCOL",
                    "status": "dry_run_zero_network_calls",
                    "archive_sha256": archive_info["sha256"],
                    "documents_planned": archive_info["documents"],
                    "queries_planned": len(CASES),
                    "rank_limit": TOP_K,
                    "required_container": DOCKER_CONTAINER,
                    "local_import_approved": False,
                    "real_hindsight_large_scale_measured": False,
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
        )
    except Exception as exc:  # noqa: BLE001 - never print provider or machine secrets
        reason = str(exc) if isinstance(exc, ProbeFailure) else "scale_probe_failed"
        print(
            json.dumps(
                {
                    "kind": "STEP7_OWNER_LOCAL_ENGINE_BENCHMARK",
                    "status": "fail_closed",
                    "reason_code": reason,
                },
                indent=2,
                sort_keys=True,
            )
        )
        raise SystemExit(1) from None
    print(json.dumps(report, indent=2, sort_keys=True))
    if not report["comparison"]["hybrid_noninferior_on_this_fixture"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
