"""Zero-network fake-HTTP tests for opt-in Hindsight import acceptance."""

from __future__ import annotations

import json
from typing import Any

import pytest
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
    ) -> None:
        self.auto = auto
        self.operation = operation
        self.missing_document = missing_document
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
        if method == "PATCH" and path == f"{ROOT}/config":
            assert self.created
            assert json.loads(body or b"{}")["updates"] == {
                "enable_auto_consolidation": False,
                "enable_observations": False,
            }
            return {"success": True}
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
    assert result["disposable_bank_cleanup_verified"] is True
    assert fake.deleted
    assert [method for method, _ in fake.events].count("POST") == 1
    assert fake.events.index(("GET", f"{ROOT}/config")) < next(
        i for i, event in enumerate(fake.events) if event[0] == "POST"
    )
    assert fake.events[-1] == ("GET", f"{ROOT}/config")


def test_unsafe_bank_config_blocks_import_and_cleans_up():
    fake = FakeTransport(auto=True)
    with pytest.raises(ProbeFailure, match="auto_consolidation"):
        run_local_import(fake, inspected=True, bank_id=BANK)
    assert fake.deleted
    assert all(method != "POST" for method, _ in fake.events)


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
        ProbeFailure, match="primary_bank_creation_http_400__cleanup_bank_cleanup_http_400"
    ):
        run_local_import(RejectedAndUncleaned(), inspected=True, bank_id=BANK)
