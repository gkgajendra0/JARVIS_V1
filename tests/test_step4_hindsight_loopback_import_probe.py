"""Zero-network fake-HTTP tests for opt-in Hindsight import acceptance."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from tools.research.step4_hindsight_local_recall_probe import capture_recall
from tools.research.step4_hindsight_local_recall_probe import main as recall_main
from tools.research.step4_hindsight_loopback_import_probe import (
    DOCKER_CONTAINER,
    IMAGE,
    LocalHTTPError,
    ProbeFailure,
    _http_stage,
    _multipart,
    check_isolated_docker_inspect,
    main,
    run_local_import,
)
from tools.research.step4_hindsight_semantic_eval import CASES

from jarvis.memory.hindsight_transfer_shadow import PINNED_FACTS

BANK = "jarvis-dev-only-0123456789abcdef0123456789abcdef"
ROOT = f"/v1/default/banks/{BANK}"


def _docker_inspect() -> dict[str, Any]:
    return {
        "Name": f"/{DOCKER_CONTAINER}",
        "Config": {
            "Image": IMAGE,
            "Env": [
                "HINDSIGHT_API_LLM_PROVIDER=none",
                "HINDSIGHT_API_ENABLE_AUTO_CONSOLIDATION=false",
                "HINDSIGHT_API_ENABLE_OBSERVATIONS=false",
                "HINDSIGHT_API_DATABASE_URL=pg0",
            ],
        },
        "State": {"Running": True},
        "HostConfig": {
            "PortBindings": {
                "8888/tcp": [{"HostIp": "127.0.0.1", "HostPort": "18888"}],
            },
            "RestartPolicy": {"Name": "no"},
        },
        "Mounts": [
            {
                "Type": "volume",
                "Name": "jarvis-hindsight-lab-fresh",
                "Destination": "/home/hindsight/.pg0",
            }
        ],
    }


class FakeTransport:
    def __init__(
        self,
        *,
        auto: bool = False,
        operation: str = "completed",
        missing_document: bool = False,
        missing_fact_metadata: bool = False,
    ) -> None:
        self.auto = auto
        self.operation = operation
        self.missing_document = missing_document
        self.missing_fact_metadata = missing_fact_metadata
        self.created = False
        self.deleted = False
        self.events: list[tuple[str, str]] = []

    def request(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        content_type: str | None = None,
    ) -> dict[str, Any]:
        self.events.append((method, path))
        if method == "GET" and path == "/version":
            return {"api_version": "test"}
        if method == "PUT" and path == ROOT:
            self.created = True
            return {"bank_id": BANK}
        if method == "GET" and path == f"{ROOT}/config":
            if self.deleted:
                raise LocalHTTPError(404)
            return {
                "config": {
                    "enable_auto_consolidation": self.auto,
                    "enable_observations": False,
                }
            }
        if method == "POST" and path.startswith(f"{ROOT}/transfer/import"):
            assert not self.auto
            assert "mode=merge&document_conflict=skip" in path
            assert content_type and content_type.startswith("multipart/form-data;")
            assert body and body.count(b"manifest.json") >= 1
            return {"operation_id": "mock-op-001"}
        if method == "GET" and path == f"{ROOT}/operations/mock-op-001":
            return {"status": self.operation}
        if method == "GET" and path == f"{ROOT}/documents?limit=100":
            return {
                "total": len(PINNED_FACTS),
                "items": [
                    {
                        "id": f"jarvis-dev-only-{fact.assertion_id}",
                        "memory_unit_count": 1,
                    }
                    for fact in PINNED_FACTS
                ],
            }
        if method == "GET" and path.startswith(f"{ROOT}/documents/"):
            doc_id = path.split("/")[-1]
            target = next(
                fact
                for fact in PINNED_FACTS
                if f"jarvis-dev-only-{fact.assertion_id}" == doc_id
            )
            return {
                "id": doc_id,
                "original_text": "BAD" if self.missing_document else target.text,
                "memory_unit_count": 1,
            }
        if method == "GET" and path.startswith(f"{ROOT}/memories/list?document_id="):
            doc_id = path.split("document_id=", 1)[1].split("&", 1)[0]
            target = next(
                fact
                for fact in PINNED_FACTS
                if f"jarvis-dev-only-{fact.assertion_id}" == doc_id
            )
            metadata = {
                "assertion_id": target.assertion_id,
                "assertion_version": str(target.version),
                "source_turn_id": target.source_turn_id,
                "canonical_source_ref": (
                    f"conversation:synthetic:{target.source_turn_id}"
                ),
                "predicate": target.predicate,
                "revision_kind": target.revision_kind,
                "source_class": "synthetic_owner_direct",
                "admission_policy": "shadow_only_no_write",
            }
            if target.supersedes_id is not None:
                metadata["supersedes_id"] = target.supersedes_id
            if self.missing_fact_metadata:
                metadata.pop("canonical_source_ref")
            return {
                "total": 1,
                "items": [
                    {
                        "document_id": doc_id,
                        "text": target.text,
                        "fact_type": "world",
                        "metadata": metadata,
                    }
                ],
            }
        if method == "DELETE" and path == ROOT:
            self.deleted = True
            return {"success": True}
        raise AssertionError(f"unexpected fake call: {method} {path}")


def test_docker_verified_local_identity_is_required():
    assert check_isolated_docker_inspect(_docker_inspect())
    for key, val in {
        "HINDSIGHT_API_LLM_PROVIDER": "openai",
        "HINDSIGHT_API_ENABLE_AUTO_CONSOLIDATION": "true",
        "HINDSIGHT_API_ENABLE_OBSERVATIONS": "true",
    }.items():
        inspected = _docker_inspect()
        inspected["Config"]["Env"].append(f"{key}={val}")
        with pytest.raises(ProbeFailure):
            check_isolated_docker_inspect(inspected)


def test_docker_refuses_cloud_key_public_port_and_bind_mount():
    inspected = _docker_inspect()
    inspected["Config"]["Env"].append("GOOGLE_API_KEY=private-value")
    with pytest.raises(ProbeFailure, match="credentials"):
        check_isolated_docker_inspect(inspected)
    inspected = _docker_inspect()
    inspected["HostConfig"]["PortBindings"]["8888/tcp"][0]["HostIp"] = "0.0.0.0"
    with pytest.raises(ProbeFailure, match="loopback"):
        check_isolated_docker_inspect(inspected)
    inspected = _docker_inspect()
    inspected["Mounts"][0]["Type"] = "bind"
    with pytest.raises(ProbeFailure, match="volume"):
        check_isolated_docker_inspect(inspected)


def test_approved_one_import_reads_five_and_confirms_cleanup():
    fake = FakeTransport()
    result = run_local_import(
        fake, inspected=True, bank_id=BANK, pause=lambda _seconds: None
    )
    assert result["import_completed"] is True
    assert result["documents_read_back"] == 5
    assert result["facts_read_back"] == 5
    assert result["fact_provenance_verified"] is True
    assert result["disposable_bank_cleanup_verified"] is True
    assert fake.deleted
    assert [method for method, _ in fake.events].count("POST") == 1
    assert fake.events.index(("GET", f"{ROOT}/config")) < next(
        i for i, event in enumerate(fake.events) if event[0] == "POST"
    )
    assert all(method != "PATCH" for method, _ in fake.events)
    assert fake.events[-1] == ("GET", f"{ROOT}/config")


def test_unsafe_bank_config_blocks_import_and_cleans_up():
    fake = FakeTransport(auto=True)
    with pytest.raises(ProbeFailure, match="auto_consolidation"):
        run_local_import(fake, inspected=True, bank_id=BANK)
    assert fake.deleted
    assert all(method not in {"PATCH", "POST"} for method, _ in fake.events)


def test_provider_failure_stops_without_retry_and_cleans_up():
    fake = FakeTransport(operation="failed")
    with pytest.raises(ProbeFailure, match="not_completed"):
        run_local_import(fake, inspected=True, bank_id=BANK)
    assert fake.deleted
    assert [method for method, _ in fake.events].count("POST") == 1


def test_missing_fictional_document_detected_and_cleaned_up():
    fake = FakeTransport(missing_document=True)
    with pytest.raises(ProbeFailure, match="readback_mismatch"):
        run_local_import(fake, inspected=True, bank_id=BANK)
    assert fake.deleted


def test_missing_fact_provenance_detected_and_cleaned_up():
    fake = FakeTransport(missing_fact_metadata=True)
    with pytest.raises(ProbeFailure, match="imported_fact_provenance_mismatch"):
        run_local_import(fake, inspected=True, bank_id=BANK)
    assert fake.deleted
    assert [method for method, _ in fake.events].count("POST") == 1


def test_no_docker_proof_or_bad_bank_id_means_no_requests():
    fake = FakeTransport()
    with pytest.raises(ProbeFailure, match="provenance"):
        run_local_import(fake, inspected=False, bank_id=BANK)
    with pytest.raises(ProbeFailure, match="invalid_disposable_bank_id"):
        run_local_import(fake, inspected=True, bank_id="owner-bank")
    assert fake.events == []


def test_exactly_one_file_is_uploaded_in_multipart():
    body, content_type = _multipart(b"PK-synthetic-only")
    assert b"PK-synthetic-only" in body
    assert body.count(b'filename="synthetic.zip"') == 1
    assert content_type.startswith("multipart/form-data; boundary=")


def test_default_cli_does_not_inspect_docker_or_contact_localhost(
    capsys: Any,
    monkeypatch: pytest.MonkeyPatch,
):
    def explode() -> bool:
        raise AssertionError("dry run inspected Docker")

    monkeypatch.setattr(
        "tools.research.step4_hindsight_loopback_import_probe.verify_local_container",
        explode,
    )
    main([])
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "dry_run_zero_network_calls"
    assert report["expected_documents"] == 5


def test_sanitized_http_stage_exposes_no_bank_id_or_url():
    path = f"{ROOT}/transfer/import?mode=merge&document_conflict=skip"
    assert _http_stage("POST", path) == "archive_upload"
    assert _http_stage("PATCH", f"{ROOT}/config") == "bank_config_update"
    assert _http_stage("GET", f"{ROOT}/config") == "bank_config_read"
    assert (
        _http_stage("GET", f"{ROOT}/memories/list?document_id=synthetic-doc&limit=2")
        == "memory_list"
    )
    assert _http_stage("DELETE", ROOT) == "bank_cleanup"
    assert _http_stage("PUT", ROOT) == "bank_creation"
    err = LocalHTTPError(400, stage=_http_stage("POST", path))
    assert str(err) == "archive_upload_http_400"
    assert BANK not in str(err)
    assert "transfer" not in str(err)
    assert str(LocalHTTPError(404)) == "unknown_http_404"


def test_rejected_bank_creation_preserves_http_400_when_cleanup_is_404():
    class RejectedBank(FakeTransport):
        def request(
            self,
            method: str,
            path: str,
            body: bytes | None = None,
            content_type: str | None = None,
        ) -> dict[str, Any]:
            if method == "PUT" and path == ROOT:
                raise LocalHTTPError(400, stage="bank_creation")
            if method == "DELETE" and path == ROOT:
                raise LocalHTTPError(404, stage="bank_cleanup")
            return super().request(method, path, body, content_type)

    with pytest.raises(LocalHTTPError, match="bank_creation_http_400"):
        run_local_import(RejectedBank(), inspected=True, bank_id=BANK)


def test_cleanup_failure_preserves_primary_stage_and_cleanup_stage():
    class RejectedAndUncleaned(FakeTransport):
        def request(
            self,
            method: str,
            path: str,
            body: bytes | None = None,
            content_type: str | None = None,
        ) -> dict[str, Any]:
            if method == "PUT" and path == ROOT:
                raise LocalHTTPError(400, stage="bank_creation")
            if method == "DELETE" and path == ROOT:
                raise LocalHTTPError(400, stage="bank_cleanup")
            return super().request(method, path, body, content_type)

    with pytest.raises(
        ProbeFailure,
        match="primary_bank_creation_http_400__cleanup_bank_cleanup_http_400",
    ):
        run_local_import(RejectedAndUncleaned(), inspected=True, bank_id=BANK)


class RecallFakeTransport(FakeTransport):
    """Nine read-only recall responses from the five pinned fictional facts."""

    def __init__(
        self,
        *,
        missing_evidence: bool = False,
        corrupt_provenance: bool = False,
        crash_recall: bool = False,
    ) -> None:
        super().__init__()
        self.missing_evidence = missing_evidence
        self.corrupt_provenance = corrupt_provenance
        self.crash_recall = crash_recall

    def request(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        content_type: str | None = None,
    ) -> dict[str, Any]:
        if method == "POST" and path == f"{ROOT}/memories/recall":
            self.events.append((method, path))
            if self.crash_recall:
                raise LocalHTTPError(503, stage="semantic_recall")
            assert body and content_type == "application/json"
            query = json.loads(body)
            assert query["types"] == ["world"]
            assert query["prefer_observations"] is False
            assert query["tags_match"] == "all_strict"
            assert query["trace"] is False
            case = next(case for case in CASES if case.query == query["query"])
            ordered = list(case.required_ids)
            ordered.extend(
                fact.assertion_id
                for fact in PINNED_FACTS
                if fact.assertion_id not in ordered
            )
            if self.missing_evidence and case.case_id == "atlas_current_day":
                ordered.remove("synthetic-workshop-day-v2")
            out = []
            for ident in ordered:
                fact = next(f for f in PINNED_FACTS if f.assertion_id == ident)
                metadata = {
                    "assertion_id": fact.assertion_id,
                    "assertion_version": str(fact.version),
                    "source_turn_id": fact.source_turn_id,
                    "canonical_source_ref": (
                        f"conversation:synthetic:{fact.source_turn_id}"
                    ),
                    "predicate": fact.predicate,
                    "revision_kind": fact.revision_kind,
                    "source_class": "synthetic_owner_direct",
                    "admission_policy": "shadow_only_no_write",
                }
                if fact.supersedes_id:
                    metadata["supersedes_id"] = fact.supersedes_id
                out.append(
                    {
                        "id": f"mock-{ident}",
                        "type": "world",
                        "text": fact.text,
                        "document_id": f"jarvis-dev-only-{ident}",
                        "metadata": metadata,
                    }
                )
            if self.corrupt_provenance:
                out[0]["metadata"].pop("canonical_source_ref")
            return {"results": out}
        return super().request(method, path, body, content_type)


def test_opt_in_local_recall_runs_after_readback_and_cleans_bank():
    fake = RecallFakeTransport()
    result = run_local_import(
        fake,
        inspected=True,
        bank_id=BANK,
        pause=lambda _seconds: None,
        after_readback=capture_recall,
    )
    capture = result["research_recall"]
    assert capture["kind"] == "LOCAL_HINDSIGHT_RECALL_EVIDENCE_ONLY"
    assert capture["queries_executed"] == 9
    assert capture["retrieval_required_cases"] == 7
    assert capture["retrieval_pass_cases"] == 7
    assert capture["retrieval_gate"] == "pass"
    assert capture["decision_gate"] == "not_evaluated"
    assert capture["answer_accuracy_measured"] is False
    assert result["disposable_bank_cleanup_verified"] is True
    assert fake.deleted
    recall_events = [
        pos
        for pos, item in enumerate(fake.events)
        if item == ("POST", f"{ROOT}/memories/recall")
    ]
    assert len(recall_events) == 9
    assert (
        fake.events.index(
            (
                "GET",
                f"{ROOT}/memories/list?document_id=jarvis-dev-only-synthetic-workshop-venue-v1&limit=2",
            )
        )
        < recall_events[0]
    )
    assert fake.events[-1] == ("GET", f"{ROOT}/config")


def test_low_recall_rank_is_measured_failure_not_false_pass():
    fake = RecallFakeTransport(missing_evidence=True)
    result = run_local_import(
        fake,
        inspected=True,
        bank_id=BANK,
        pause=lambda _seconds: None,
        after_readback=capture_recall,
    )
    assert result["research_recall"]["retrieval_gate"] == "fail"
    assert result["research_recall"]["retrieval_pass_cases"] == 6
    assert fake.deleted
    assert result["disposable_bank_cleanup_verified"] is True


def test_corrupt_recall_provenance_fails_closed_and_still_cleans_bank():
    fake = RecallFakeTransport(corrupt_provenance=True)
    with pytest.raises(
        ProbeFailure, match="semantic_recall_provenance_or_schema_failed"
    ):
        run_local_import(
            fake,
            inspected=True,
            bank_id=BANK,
            pause=lambda _seconds: None,
            after_readback=capture_recall,
        )
    assert fake.deleted


def test_recall_http_failure_does_not_retry_and_cleans_bank():
    fake = RecallFakeTransport(crash_recall=True)
    with pytest.raises(LocalHTTPError, match="semantic_recall_http_503"):
        run_local_import(
            fake,
            inspected=True,
            bank_id=BANK,
            pause=lambda _seconds: None,
            after_readback=capture_recall,
        )
    assert fake.deleted
    assert fake.events.count(("POST", f"{ROOT}/memories/recall")) == 1


def test_recall_http_errors_have_sanitized_stage():
    # Regression for Hindsight 1.0 route; the old path returned HTTP 404.
    assert _http_stage("POST", f"{ROOT}/memories/recall") == "semantic_recall"
    assert _http_stage("POST", f"{ROOT}/recall") == "unknown"


def test_new_probe_default_never_contacts_docker_or_localhost(
    capsys: Any,
    monkeypatch: pytest.MonkeyPatch,
):
    def fail_container() -> bool:
        raise AssertionError("default preview unexpectedly inspected Docker")

    monkeypatch.setattr(
        "tools.research.step4_hindsight_local_recall_probe.verify_local_container",
        fail_container,
    )
    recall_main([])
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "dry_run_zero_network_calls"
    assert result["queries_planned"] == 9
    assert result["live_retrieval_not_yet_measured"] is True


def test_isolated_recall_cli_bootstraps_checkout_path():
    """The new user-facing command must launch under Python -I."""
    root = Path(__file__).resolve().parents[1]
    script = root / "tools" / "research" / "step4_hindsight_local_recall_probe.py"
    output = subprocess.run(
        [sys.executable, "-I", str(script)],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert output.returncode == 0, output.stderr
    preview = json.loads(output.stdout)
    assert preview["status"] == "dry_run_zero_network_calls"
    assert preview["queries_planned"] == 9
