"""Offline fake-server regression tests for Step 10's 240-fact opt-in trial."""

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
from tools.research.step10_local_240fact_semantic_trial import (
    CASE_COUNT,
    DOCUMENT_COUNT,
    EXPECTED_ARCHIVE_HASH,
    PAGE_SIZE,
    capture_real_hindsight_comparison,
    main,
    run_single_live_trial,
    verified_fixture,
    verify_paginated_source_readback,
)

from jarvis.memory.research_semantic_pressure import (
    BY_ID,
    CASES,
    FACTS,
    metadata,
)

BANK = "jarvis-dev-only-0123456789abcdef0123456789abcdef"
ROOT = f"/v1/default/banks/{BANK}"


class Fake240Transport:
    """One deterministic mock protocol, never contacts Docker or a provider."""

    def __init__(
        self,
        *,
        prior_bank: bool = False,
        missing_page: bool = False,
        duplicate_page: bool = False,
        bad_source: bool = False,
        forged_recall: bool = False,
        fail_recall: bool = False,
        fail_cleanup: bool = False,
        bad_config: bool = False,
        import_failed: bool = False,
    ) -> None:
        self.prior_bank = prior_bank
        self.missing_page = missing_page
        self.duplicate_page = duplicate_page
        self.bad_source = bad_source
        self.forged_recall = forged_recall
        self.fail_recall = fail_recall
        self.fail_cleanup = fail_cleanup
        self.bad_config = bad_config
        self.import_failed = import_failed
        self.created = False
        self.deleted = False
        self.calls: list[tuple[str, str]] = []

    def request(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        content_type: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append((method, path))
        if method == "GET" and path == "/v1/default/banks?query=jarvis-dev-only-&limit=100":
            return {"total": 1 if self.prior_bank else 0}
        if method == "GET" and path == "/version":
            return {"version": "1.0.0"}
        if method == "PUT" and path == ROOT:
            assert body == b"{}"
            self.created = True
            return {}
        if method == "GET" and path == f"{ROOT}/config":
            if self.deleted:
                raise LocalHTTPError(404, stage="bank_config_read")
            return {
                "config": {
                    "enable_auto_consolidation": self.bad_config,
                    "enable_observations": False,
                }
            }
        if method == "POST" and "/transfer/import?" in path:
            assert self.created and not self.deleted
            assert body is not None and body.count(b"manifest.json") == 1
            assert content_type and content_type.startswith("multipart/form-data;")
            return {"operation_id": "fake-fictitious-240-operation"}
        if method == "GET" and "/operations/" in path:
            return {"status": "failed" if self.import_failed else "completed"}
        if method == "GET" and path.startswith(f"{ROOT}/documents?limit="):
            size = int(path.split("limit=")[1].split("&")[0])
            offset = int(path.split("offset=")[1])
            assert size == PAGE_SIZE
            entries = FACTS[offset : offset + size]
            if self.missing_page and offset == 80:
                entries = entries[:-1]
            if self.duplicate_page and offset == 160:
                entries = FACTS[80:160]
            return {
                "total": DOCUMENT_COUNT,
                "limit": size,
                "offset": offset,
                "items": [
                    {
                        "id": f"jarvis-dev-only-{f.assertion.assertion_id}",
                        "memory_unit_count": 1,
                    }
                    for f in entries
                ],
            }
        if method == "GET" and path.startswith(f"{ROOT}/documents/"):
            doc_id = path.rsplit("/", 1)[-1]
            ident = doc_id.removeprefix("jarvis-dev-only-")
            fact = BY_ID[ident]
            return {
                "id": doc_id,
                "original_text": fact.text,
                "memory_unit_count": 1,
            }
        if method == "GET" and path.startswith(f"{ROOT}/memories/list?document_id="):
            doc_id = path.split("document_id=")[1].split("&")[0]
            ident = doc_id.removeprefix("jarvis-dev-only-")
            fact = BY_ID[ident]
            meta = metadata(fact)
            if self.bad_source and ident == FACTS[0].assertion.assertion_id:
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
            request = json.loads(body)
            assert request["types"] == ["world"]
            assert request["prefer_observations"] is False
            assert request["tags_match"] == "all_strict"
            case = next(c for c in CASES if c.query == request["query"])
            wanted = list(case.required_ids)
            wanted.extend(ident for ident in BY_ID if ident not in wanted)
            rows = []
            for ident in wanted[:16]:
                fact = BY_ID[ident]
                rows.append(
                    {
                        "document_id": f"jarvis-dev-only-{ident}",
                        "text": fact.text,
                        "type": "world",
                        "metadata": metadata(fact),
                    }
                )
            if self.forged_recall:
                rows[0]["metadata"]["canonical_source_ref"] = "forged"
            return {"results": rows}
        if method == "DELETE" and path == ROOT:
            if self.fail_cleanup:
                raise LocalHTTPError(503, stage="bank_cleanup")
            self.deleted = True
            return {"success": True}
        raise AssertionError("unexpected fake server request")


def test_frozen_240_fact_archive_matches_owner_offline_sha():
    data, evidence = verified_fixture()
    assert evidence["sha256"] == EXPECTED_ARCHIVE_HASH
    assert evidence["documents"] == DOCUMENT_COUNT == 240
    assert len(data) < 1_048_576
    assert len(CASES) == CASE_COUNT == 68


def test_paginated_source_readback_covers_exactly_all_240_facts():
    fake = Fake240Transport()
    verify_paginated_source_readback(fake, ROOT)
    pages = [
        (method, path)
        for method, path in fake.calls
        if path.startswith(f"{ROOT}/documents?limit=")
    ]
    assert len(pages) == 3
    assert [path.split("offset=")[1] for _, path in pages] == [
        "0", "80", "160"
    ]
    assert len(fake.calls) == 3 + 240 * 2


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        ({"missing_page": True}, "incomplete_240_document_page"),
        ({"duplicate_page": True}, "untrusted_240_document_index"),
        ({"bad_source": True}, "240_fact_source_provenance_mismatch"),
    ],
)
def test_bad_pages_or_fact_sources_rejected(options, expected):
    fake = Fake240Transport(**options)
    with pytest.raises(ProbeFailure, match=expected):
        verify_paginated_source_readback(fake, ROOT)


def test_fake_owner_live_harness_exercises_68_queries_and_cleans_up():
    fake = Fake240Transport()
    report = run_single_live_trial(fake, inspected=True, bank_id=BANK, pause=lambda _: None)
    assert report["status"] == "measured"
    assert report["archive_sha256"] == EXPECTED_ARCHIVE_HASH
    assert report["documents_read_back"] == 240
    assert report["disposable_bank_cleanup_verified"] is True
    result = report["comparison"]
    assert result["real_hindsight_retrieval_measured"] is True
    assert result["actual_hindsight_requests"] == 68
    assert set(result["measured_by_k"]) == {"4", "8", "16"}
    for entry in result["measured_by_k"].values():
        assert entry["engines"]["hindsight"]["supported_retrieval"] == 64
        assert entry["engines"]["hindsight"]["decisions_correct"] == 68
        assert entry["engines"]["lexical"]["supported_required"] == 64
        assert entry["engines"]["hybrid"]["decisions_required"] == 68
    recall_calls = sum(
        method == "POST" and path == f"{ROOT}/memories/recall"
        for method, path in fake.calls
    )
    import_calls = sum(
        method == "POST" and "/transfer/import?" in path
        for method, path in fake.calls
    )
    assert recall_calls == 68
    assert import_calls == 1
    assert fake.deleted


@pytest.mark.parametrize(
    ("options", "reason"),
    [
        ({"bad_config": True}, "auto_consolidation_not_disabled"),
        ({"import_failed": True}, "240_import_operation_failed"),
        ({"bad_source": True}, "240_fact_source_provenance_mismatch"),
        ({"forged_recall": True}, "240_recall_untrusted_provenance"),
        ({"fail_recall": True}, "semantic_recall_http_503"),
    ],
)
def test_trial_failure_always_deletes_temporary_bank(options, reason):
    fake = Fake240Transport(**options)
    with pytest.raises(ProbeFailure, match=reason):
        run_single_live_trial(fake, inspected=True, bank_id=BANK, pause=lambda _: None)
    assert fake.deleted


def test_cleanup_failure_blocks_claiming_success():
    fake = Fake240Transport(fail_cleanup=True)
    with pytest.raises(ProbeFailure, match="cleanup_bank_cleanup_http_503"):
        run_single_live_trial(fake, inspected=True, bank_id=BANK, pause=lambda _: None)
    assert not fake.deleted


def test_prior_bank_or_invalid_provenance_refuses_any_creation():
    fake = Fake240Transport(prior_bank=True)
    with pytest.raises(ProbeFailure, match="existing_or_unverifiable_research_banks"):
        run_single_live_trial(fake, inspected=True, bank_id=BANK)
    assert all(method != "PUT" for method, _ in fake.calls)
    fake = Fake240Transport()
    with pytest.raises(ProbeFailure, match="docker_provenance_not_verified"):
        run_single_live_trial(fake, inspected=False, bank_id=BANK)
    with pytest.raises(ProbeFailure, match="invalid_disposable_bank_id"):
        run_single_live_trial(fake, inspected=True, bank_id="production-bank")
    assert fake.calls == []


def test_invalid_capture_result_also_triggers_cleanup():
    fake = Fake240Transport()
    with pytest.raises(ProbeFailure, match="invalid_240_comparison_output"):
        run_single_live_trial(
            fake, inspected=True, bank_id=BANK, pause=lambda _: None,
            capture=lambda _transport, _root: None,
        )
    assert fake.deleted


def test_default_cli_does_not_inspect_docker_or_contact_localhost(capsys, monkeypatch):
    def forbidden():
        raise AssertionError("no Docker in dry run")

    monkeypatch.setattr(
        "tools.research.step10_local_240fact_semantic_trial.verify_local_container",
        forbidden,
    )
    main([])
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "dry_run_zero_network_calls"
    assert payload["fictional_documents"] == 240
    assert payload["hindsight_requests_if_authorized"] == 68
    assert payload["local_import_approved"] is False
    assert payload["actual_hindsight_measured"] is False


def test_isolated_cli_preview_not_networked():
    root = Path(__file__).resolve().parents[1]
    file_path = root / "tools" / "research" / "step10_local_240fact_semantic_trial.py"
    result = subprocess.run(
        [sys.executable, "-I", str(file_path)],
        cwd=root, capture_output=True, text=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "dry_run_zero_network_calls"
    assert payload["archive_sha256"] == EXPECTED_ARCHIVE_HASH
