"""Step 10: owner-OPT-IN 240-fact Hindsight/BM25/RRF alias-retrieval study.

By default the CLI makes ZERO network requests and never inspects Docker.
An explicitly approved run validates the exact fictional archive, imports
only into one UUID-scoped disposable bank, verifies all 240 source facts,
makes exactly 68 local recall requests, and verifies bank deletion.
Never connects to canonical SQLCipher, an LLM API, or a production service.
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
    LocalHindsightHTTP,
    LocalHTTPError,
    ProbeFailure,
    _multipart,
    _require_disabled_config,
    verify_local_container,
)

from jarvis.memory.research_semantic_pressure import (
    BY_ID,
    CASES,
    DOCUMENT_COUNT,
    FACTS,
    TOP_K_CHOICES,
    BM25Index,
    PressureFailure,
    build_archive,
    fuse,
    inspect_archive,
    metadata,
    offline_report,
    score_rankings,
    validate_recall,
)

EXPECTED_ARCHIVE_HASH = "d5ee8f2d9587691012d276748e3c553a6c057f33ad83e357d48f258163df0246"
CASE_COUNT = 68
PAGE_SIZE = 80
POLL_LIMIT = 180
POLL_SECONDS = 2
_BANK_ID = re.compile(r"^jarvis-dev-only-[a-f0-9]{32}$")
_OPERATION_ID = re.compile(r"^[a-zA-Z0-9_-]{4,100}$")


def _json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def verified_fixture() -> tuple[bytes, dict[str, Any]]:
    archive = build_archive()
    report = inspect_archive(archive)
    if (
        report["sha256"] != EXPECTED_ARCHIVE_HASH
        or report["documents"] != DOCUMENT_COUNT
        or DOCUMENT_COUNT != 240
        or len(CASES) != CASE_COUNT
    ):
        raise ProbeFailure("unrecognized_240_fact_fictional_fixture")
    return archive, report


def _preflight_no_existing_banks(transport: Any) -> None:
    response = transport.request(
        "GET", "/v1/default/banks?query=jarvis-dev-only-&limit=100"
    )
    if (
        type(response.get("total")) is not int
        or response["total"] != 0
    ):
        raise ProbeFailure("existing_or_unverifiable_research_banks")


def verify_paginated_source_readback(transport: Any, root: str) -> None:
    """Inspect all 240 list entries AND each individual fact and document."""
    seen: set[str] = set()
    for offset in range(0, DOCUMENT_COUNT, PAGE_SIZE):
        listing = transport.request(
            "GET", f"{root}/documents?limit={PAGE_SIZE}&offset={offset}"
        )
        items = listing.get("items")
        if (
            type(listing.get("total")) is not int
            or listing["total"] != DOCUMENT_COUNT
            or not isinstance(items, list)
            or len(items) != PAGE_SIZE
        ):
            raise ProbeFailure("incomplete_240_document_page")
        for item in items:
            if not isinstance(item, dict):
                raise ProbeFailure("malformed_240_document_page")
            doc_id = item.get("id")
            if (
                not isinstance(doc_id, str)
                or not doc_id.startswith("jarvis-dev-only-")
                or doc_id.removeprefix("jarvis-dev-only-") not in BY_ID
                or doc_id in seen
                or item.get("memory_unit_count") != 1
            ):
                raise ProbeFailure("untrusted_240_document_index")
            seen.add(doc_id)
    expected = {f"jarvis-dev-only-{ident}" for ident in BY_ID}
    if seen != expected:
        raise ProbeFailure("missing_or_extra_240_documents")

    for fact in FACTS:
        assertion_id = fact.assertion.assertion_id
        doc_id = f"jarvis-dev-only-{assertion_id}"
        doc = transport.request("GET", f"{root}/documents/{doc_id}")
        if (
            doc.get("id") != doc_id
            or doc.get("original_text") != fact.text
            or doc.get("memory_unit_count") != 1
        ):
            raise ProbeFailure("240_document_readback_mismatch")
        found = transport.request(
            "GET", f"{root}/memories/list?document_id={doc_id}&limit=2"
        )
        memories = found.get("items")
        if (
            found.get("total") != 1
            or not isinstance(memories, list)
            or len(memories) != 1
            or not isinstance(memories[0], dict)
            or memories[0].get("document_id") != doc_id
            or memories[0].get("text") != fact.text
            or memories[0].get("fact_type") != "world"
            or memories[0].get("metadata") != metadata(fact)
        ):
            raise ProbeFailure("240_fact_source_provenance_mismatch")


def capture_real_hindsight_comparison(
    transport: Any, root: str
) -> dict[str, Any]:
    """Exactly 68 calls, same raw questions for all retrieval methods."""
    if len(CASES) != CASE_COUNT:
        raise ProbeFailure("modified_pressure_questions")
    index = BM25Index()
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
        start = time.perf_counter_ns()
        response = transport.request(
            "POST",
            f"{root}/memories/recall",
            _json(request),
            "application/json",
        )
        hindsight_ns += time.perf_counter_ns() - start
        try:
            hindsight = validate_recall(response)
        except (TypeError, ValueError):
            raise ProbeFailure("240_recall_untrusted_provenance") from None

        start = time.perf_counter_ns()
        lexical = index.retrieve(case.query)
        lexical_ns += time.perf_counter_ns() - start
        rankings["hindsight"][case.case_id] = hindsight
        rankings["lexical"][case.case_id] = lexical
        rankings["hybrid"][case.case_id] = fuse(
            hindsight[:16], lexical[:16]
        )

    measured_by_k: dict[str, Any] = {}
    for k in TOP_K_CHOICES:
        result = score_rankings(rankings, k=k)
        engines = result["engines"]
        lexical = engines["lexical"]
        hindsight = engines["hindsight"]
        hybrid = engines["hybrid"]
        measured_by_k[str(k)] = {
            "engines": engines,
            "hindsight_minus_bm25_decisions": (
                hindsight["decisions_correct"] - lexical["decisions_correct"]
            ),
            "hybrid_minus_bm25_decisions": (
                hybrid["decisions_correct"] - lexical["decisions_correct"]
            ),
            "hybrid_minus_bm25_retrieval": (
                hybrid["supported_retrieval"] - lexical["supported_retrieval"]
            ),
            "hybrid_minus_hindsight_decisions": (
                hybrid["decisions_correct"] - hindsight["decisions_correct"]
            ),
        }

    return {
        "kind": "STEP10_REAL_LOCAL_240_FACT_SEMANTIC_COMPARISON",
        "fact_count": DOCUMENT_COUNT,
        "actual_hindsight_requests": CASE_COUNT,
        "measured_by_k": measured_by_k,
        "hindsight_http_total_ms": round(hindsight_ns / 1_000_000, 2),
        "lexical_inprocess_total_ms": round(lexical_ns / 1_000_000, 2),
        "latencies_not_directly_comparable": True,
        "real_hindsight_retrieval_measured": True,
        "language_scope_oracle_supplied": True,
        "llm_answer_accuracy_measured": False,
        "actual_owner_data": False,
        "production_promotion_allowed": False,
    }


def run_single_live_trial(
    transport: Any,
    *,
    inspected: bool,
    bank_id: str,
    pause: Callable[[float], None] = time.sleep,
    capture: Callable[[Any, str], dict[str, Any]] = capture_real_hindsight_comparison,
) -> dict[str, Any]:
    """Fail-closed one-off synthetic bank import, readback, recall and delete."""
    if inspected is not True:
        raise ProbeFailure("docker_provenance_not_verified")
    if not isinstance(bank_id, str) or not _BANK_ID.fullmatch(bank_id):
        raise ProbeFailure("invalid_disposable_bank_id")
    archive, evidence = verified_fixture()
    root = f"/v1/default/banks/{bank_id}"
    _preflight_no_existing_banks(transport)

    possibly_created = False
    cleaned = False
    failure: Exception | None = None
    measurements: dict[str, Any] | None = None
    try:
        transport.request("GET", "/version")
        possibly_created = True
        transport.request("PUT", root, _json({}), "application/json")
        _require_disabled_config(transport.request("GET", f"{root}/config"))
        multipart, content_type = _multipart(archive)
        imported = transport.request(
            "POST",
            f"{root}/transfer/import?mode=merge&document_conflict=skip",
            multipart,
            content_type,
        )
        operation_id = imported.get("operation_id")
        if not isinstance(operation_id, str) or not _OPERATION_ID.fullmatch(
            operation_id
        ):
            raise ProbeFailure("invalid_240_import_operation")
        last = "unknown"
        for iteration in range(POLL_LIMIT):
            status = transport.request("GET", f"{root}/operations/{operation_id}")
            last = status.get("status")
            if last in ("failed", "cancelled", "not_found"):
                raise ProbeFailure("240_import_operation_failed")
            if last == "completed":
                break
            if iteration != POLL_LIMIT - 1:
                pause(POLL_SECONDS)
        if last != "completed":
            raise ProbeFailure("240_import_operation_timeout")

        verify_paginated_source_readback(transport, root)
        measurements = capture(transport, root)
        if not isinstance(measurements, dict):
            raise ProbeFailure("invalid_240_comparison_output")
    except Exception as exc:  # noqa: BLE001 - delete even on untrusted provider failures
        failure = exc
    finally:
        if possibly_created:
            try:
                try:
                    response = transport.request("DELETE", root)
                except LocalHTTPError as exc:
                    if exc.status_code == 404:
                        cleaned = True
                    else:
                        raise
                else:
                    if response.get("success") is not True:
                        raise ProbeFailure("240_bank_delete_not_confirmed")
                    try:
                        transport.request("GET", f"{root}/config")
                    except LocalHTTPError as exc:
                        if exc.status_code == 404:
                            cleaned = True
                        else:
                            raise
                    if not cleaned:
                        raise ProbeFailure("240_bank_cleanup_unverified")
            except Exception as cleanup_exc:  # noqa: BLE001 - preserve primary failure
                previous = (
                    str(failure) if isinstance(failure, ProbeFailure) else "unknown"
                )
                cleanup_reason = (
                    str(cleanup_exc)
                    if isinstance(cleanup_exc, ProbeFailure)
                    else "unknown"
                )
                raise ProbeFailure(
                    f"primary_{previous}__cleanup_{cleanup_reason}"
                ) from None
    if failure is not None:
        raise failure
    if not cleaned or measurements is None:
        raise ProbeFailure("240_bank_cleanup_unverified")
    return {
        "kind": "STEP10_OWNER_LOCAL_240_FACT_TRIAL",
        "status": "measured",
        "archive_sha256": evidence["sha256"],
        "documents_read_back": DOCUMENT_COUNT,
        "source_metadata_exact": True,
        "disposable_bank_cleanup_verified": True,
        "no_cloud_provider_configured": True,
        "no_production_memory": True,
        "production_promotion_allowed": False,
        "comparison": measurements,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-one-local-240-fact-semantic-trial",
        action="store_true",
        help="Owner opt-in for exactly one isolated 240-fact import and 68 recalls.",
    )
    args = parser.parse_args(argv)
    if not args.allow_one_local_240_fact_semantic_trial:
        archive, manifest = verified_fixture()
        preview = offline_report()
        print(
            json.dumps(
                {
                    "kind": "STEP10_LOCAL_240_FACT_PROTOCOL",
                    "status": "dry_run_zero_network_calls",
                    "archive_sha256": manifest["sha256"],
                    "archive_bytes": len(archive),
                    "fictional_documents": manifest["documents"],
                    "hindsight_requests_if_authorized": CASE_COUNT,
                    "local_import_approved": False,
                    "required_container": DOCKER_CONTAINER,
                    "lexical_baseline_by_k": preview["results_by_k"],
                    "actual_hindsight_measured": False,
                    "production_promotion_allowed": False,
                },
                sort_keys=True,
                indent=2,
            )
        )
        return
    try:
        verified_fixture()
        verify_local_container()
        result = run_single_live_trial(
            LocalHindsightHTTP(),
            inspected=True,
            bank_id=f"jarvis-dev-only-{uuid.uuid4().hex}",
        )
    except Exception as exc:  # noqa: BLE001 - sanitized no raw content
        reason = str(exc) if isinstance(exc, ProbeFailure) else "local_trial_failed"
        print(
            json.dumps(
                {"kind": "STEP10_OWNER_LOCAL_240_FACT_TRIAL", "status": "fail_closed",
                 "reason_code": reason},
                sort_keys=True,
                indent=2,
            )
        )
        raise SystemExit(1) from None
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
