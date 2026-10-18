"""No-network fake server and objective comparison tests for Step 7."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from tools.research.step4_hindsight_loopback_import_probe import (
    LocalHTTPError,
    ProbeFailure,
)
from tools.research.step7_local_engine_comparison import (
    main,
    run_one_local_comparison,
)

from jarvis.memory.research_compare_fixture import (
    BY_ID,
    CASES,
    DOCUMENT_COUNT,
    FACTS,
    TOP_K,
    ComparisonFailure,
    bm25,
    build_archive,
    fuse,
    metadata,
    score_rankings,
    validate_archive,
    validate_recall,
)

BANK = "jarvis-dev-only-0123456789abcdef0123456789abcdef"
ROOT = f"/v1/default/banks/{BANK}"


class FakeScaleTransport:
    """Fake real-server protocol. Does not open any network connection."""

    def __init__(
        self,
        *,
        existing: bool = False,
        invalid_config: bool = False,
        corrupt_fact: bool = False,
        corrupt_recall: bool = False,
        fail_recall: bool = False,
        fail_cleanup: bool = False,
    ) -> None:
        self.events: list[tuple[str, str]] = []
        self.created = False
        self.deleted = False
        self.existing = existing
        self.invalid_config = invalid_config
        self.corrupt_fact = corrupt_fact
        self.corrupt_recall = corrupt_recall
        self.fail_recall = fail_recall
        self.fail_cleanup = fail_cleanup

    def request(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        content_type: str | None = None,
    ) -> dict[str, Any]:
        self.events.append((method, path))
        if method == "GET" and path == "/v1/default/banks?query=jarvis-dev-only-&limit=100":
            return {"total": 1 if self.existing else 0}
        if method == "GET" and path == "/version":
            return {"version": "1.0.0"}
        if method == "PUT" and path == ROOT:
            self.created = True
            assert body == b"{}"
            return {}
        if method == "GET" and path == f"{ROOT}/config":
            if self.deleted:
                raise LocalHTTPError(404, stage="bank_config_read")
            return {
                "config": {
                    "enable_auto_consolidation": self.invalid_config,
                    "enable_observations": False,
                }
            }
        if method == "POST" and "/transfer/import?" in path:
            assert self.created
            assert body is not None and b"manifest.json" in body
            assert content_type and content_type.startswith("multipart/form-data;")
            return {"operation_id": "synthetic-operation-007"}
        if method == "GET" and "/operations/" in path:
            return {"status": "completed"}
        if method == "GET" and path == f"{ROOT}/documents?limit=100":
            return {
                "total": DOCUMENT_COUNT,
                "items": [
                    {
                        "id": f"jarvis-dev-only-{fact.assertion.assertion_id}",
                        "memory_unit_count": 1,
                    }
                    for fact in FACTS
                ],
            }
        if method == "GET" and path.startswith(f"{ROOT}/documents/"):
            doc_id = path.rsplit("/", 1)[-1]
            fact = BY_ID[doc_id.removeprefix("jarvis-dev-only-")]
            return {
                "id": doc_id,
                "original_text": fact.text,
                "memory_unit_count": 1,
            }
        if method == "GET" and path.startswith(f"{ROOT}/memories/list?document_id="):
            doc_id = path.split("document_id=", 1)[1].split("&", 1)[0]
            fact = BY_ID[doc_id.removeprefix("jarvis-dev-only-")]
            meta = metadata(fact)
            if self.corrupt_fact and fact is FACTS[0]:
                meta.pop("canonical_source_ref")
            return {
                "total": 1,
                "items": [
                    {
                        "document_id": doc_id,
                        "text": fact.text,
                        "fact_type": "world",
                        "metadata": meta,
                    }
                ],
            }
        if method == "POST" and path == f"{ROOT}/memories/recall":
            if self.fail_recall:
                raise LocalHTTPError(503, stage="semantic_recall")
            assert body is not None and content_type == "application/json"
            payload = json.loads(body)
            assert payload["types"] == ["world"]
            assert payload["tags_match"] == "all_strict"
            assert payload["tags"] == ["jarvis-dev-only", "synthetic"]
            assert payload["prefer_observations"] is False
            case = next(row for row in CASES if row.query == payload["query"])
            ranked = list(case.required_ids)
            ranked.extend(
                fact.assertion.assertion_id
                for fact in FACTS
                if fact.assertion.assertion_id not in ranked
            )
            rows = []
            for ident in ranked[:TOP_K]:
                fact = BY_ID[ident]
                meta = metadata(fact)
                rows.append(
                    {
                        "text": fact.text,
                        "type": "world",
                        "metadata": meta,
                        "document_id": f"jarvis-dev-only-{ident}",
                    }
                )
            if self.corrupt_recall:
                rows[0]["metadata"].pop("source_turn_id")
            return {"results": rows}
        if method == "DELETE" and path == ROOT:
            if self.fail_cleanup:
                raise LocalHTTPError(503, stage="bank_cleanup")
            self.deleted = True
            return {"success": True}
        raise AssertionError("Unexpected fake protocol request")


def test_corpus_is_only_60_fictional_fact_texts():
    assert len(FACTS) == DOCUMENT_COUNT == 60
    assert len(BY_ID) == 60
    assert len({f.source_turn_id for f in FACTS}) == 60
    assert all("fictional Meridian project" in f.text for f in FACTS)
    assert len(CASES) == 18
    assert len({c.case_id for c in CASES}) == 18
    assert sum(bool(c.required_ids) for c in CASES) == 16
    assert sum(not c.required_ids for c in CASES) == 2


def test_archive_is_deterministic_pinned_to_reviewed_generator():
    archive = build_archive()
    assert archive == build_archive()
    report = validate_archive(archive)
    assert report["documents"] == 60
    assert report["synthetic_only"] is True
    assert len(report["sha256"]) == 64
    with pytest.raises(ComparisonFailure, match="unrecognized_archive"):
        validate_archive(archive + b"malicious-trailing-bytes")


def test_lexical_and_fusion_are_deterministic():
    query = CASES[0].query
    assert bm25(query) == bm25(query)
    assert bm25(query)
    a = tuple(f.assertion.assertion_id for f in FACTS[:8])
    b = tuple(f.assertion.assertion_id for f in FACTS[8:16])
    assert fuse(a, b) == fuse(a, b)
    assert len(fuse(a, b)) == 16
    with pytest.raises(ComparisonFailure):
        fuse((a[0], a[0]), b)
    with pytest.raises(ComparisonFailure):
        fuse(("synthetic-owner-private",), b)


def test_metadata_exactness_rejects_forged_recall():
    fact = FACTS[0]
    item = {
        "type": "world",
        "text": fact.text,
        "document_id": f"jarvis-dev-only-{fact.assertion.assertion_id}",
        "metadata": metadata(fact),
    }
    assert validate_recall({"results": [item]}) == (fact.assertion.assertion_id,)
    forged = {**item, "metadata": {**item["metadata"], "source_turn_id": "owner"}}
    with pytest.raises(ComparisonFailure, match="recalled_fact_identity_mismatch"):
        validate_recall({"results": [forged]})
    with pytest.raises(ComparisonFailure, match="duplicate_recalled_assertion"):
        validate_recall({"results": [item, item]})
    with pytest.raises(ComparisonFailure, match="invalid_recall_schema"):
        validate_recall({"results": "not-a-list"})


def test_score_requires_same_18_cases_for_all_three_engines():
    rankings = {
        engine: {case.case_id: () for case in CASES}
        for engine in ("hindsight", "lexical", "hybrid")
    }
    report = score_rankings(rankings)
    for score in report["engines"].values():
        assert score["retrieval_hits"] == 0
        assert score["structured_decisions_correct"] == 2
        assert score["unknown_abstentions"] == 2
    del rankings["lexical"]
    with pytest.raises(ComparisonFailure, match="invalid_comparison_engines"):
        score_rankings(rankings)


def test_fake_live_run_measures_three_engines_and_verifies_cleanup():
    fake = FakeScaleTransport()
    report = run_one_local_comparison(
        fake, inspected=True, bank_id=BANK, pause=lambda _: None
    )
    assert report["status"] == "measured"
    assert report["documents_imported_and_verified"] == 60
    assert report["disposable_bank_cleanup_verified"] is True
    assert len(report["archive_sha256"]) == 64
    comparison = report["comparison"]
    assert comparison["real_hindsight_recall_measured"] is True
    assert comparison["hindsight_recall_requests"] == 18
    assert comparison["engines"]["hindsight"]["retrieval_hits"] == 16
    assert comparison["engines"]["hindsight"]["structured_decisions_correct"] == 18
    assert comparison["engines"]["lexical"]["retrieval_required"] == 16
    assert comparison["engines"]["hybrid"]["retrieval_required"] == 16
    assert fake.deleted
    assert sum(method == "POST" and path.endswith("/memories/recall")
               for method, path in fake.events) == 18
    assert sum(method == "POST" and "/transfer/import?" in path
               for method, path in fake.events) == 1


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"invalid_config": True}, "auto_consolidation_not_disabled"),
        ({"corrupt_fact": True}, "scale_fact_provenance_mismatch"),
        ({"corrupt_recall": True}, "untrusted_scale_recall_evidence"),
        ({"fail_recall": True}, "semantic_recall_http_503"),
    ],
)
def test_every_failure_cleans_disposable_bank(kwargs, expected):
    fake = FakeScaleTransport(**kwargs)
    with pytest.raises(ProbeFailure, match=expected):
        run_one_local_comparison(
            fake, inspected=True, bank_id=BANK, pause=lambda _: None
        )
    assert fake.deleted


def test_cleanup_failure_never_reports_success():
    fake = FakeScaleTransport(fail_cleanup=True)
    with pytest.raises(ProbeFailure, match="scale_bank_cleanup_unverified"):
        run_one_local_comparison(
            fake, inspected=True, bank_id=BANK, pause=lambda _: None
        )
    assert not fake.deleted


def test_existing_bank_preflight_blocks_all_writes():
    fake = FakeScaleTransport(existing=True)
    with pytest.raises(ProbeFailure, match="existing_research_banks_detected"):
        run_one_local_comparison(
            fake, inspected=True, bank_id=BANK, pause=lambda _: None
        )
    assert fake.events == [
        ("GET", "/v1/default/banks?query=jarvis-dev-only-&limit=100")
    ]


def test_cannot_run_without_docker_inspection_or_valid_bank_id():
    fake = FakeScaleTransport()
    with pytest.raises(ProbeFailure, match="docker_provenance_not_verified"):
        run_one_local_comparison(fake, inspected=False, bank_id=BANK)
    with pytest.raises(ProbeFailure, match="invalid_disposable_bank_id"):
        run_one_local_comparison(fake, inspected=True, bank_id="owner-personal-bank")
    assert fake.events == []


def test_default_main_does_not_check_docker_or_issue_network_calls(
    capsys, monkeypatch
):
    def forbidden():
        raise AssertionError("dry-run must never inspect Docker")
    monkeypatch.setattr(
        "tools.research.step7_local_engine_comparison.verify_local_container",
        forbidden,
    )
    main([])
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "dry_run_zero_network_calls"
    assert out["documents_planned"] == 60
    assert out["queries_planned"] == 18
    assert out["local_import_approved"] is False


def test_isolated_python_cli_dry_run():
    root = Path(__file__).resolve().parents[1]
    path = root / "tools" / "research" / "step7_local_engine_comparison.py"
    result = subprocess.run(
        [sys.executable, "-I", str(path)],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "dry_run_zero_network_calls"
