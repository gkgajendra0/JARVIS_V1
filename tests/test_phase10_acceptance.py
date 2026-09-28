from __future__ import annotations

import os
from pathlib import Path

import pytest

from jarvis.engineering_learning.evaluation import PHASE10_REPLAY_CASE_IDS
from jarvis.engineering_learning.phase10_acceptance import (
    Phase10AcceptanceError,
    _repo_snapshot,
    _require_output_outside_repo,
    _require_windows,
    _tested_commit,
    validate_acceptance_evidence,
)
from jarvis.engineering_substrate.canonical import canonical_digest


def _payload(commit: str) -> dict[str, object]:
    body: dict[str, object] = {
        "schema_version": 1,
        "status": "PASS",
        "tested_commit": commit,
        "repo_status_sha256": "a" * 64,
        "recorded_at": "2026-09-28T06:00:00+00:00",
        "suite_status": "PASS",
        "suite_digest": "b" * 64,
        "case_count": len(PHASE10_REPLAY_CASE_IDS),
        "case_ids": list(PHASE10_REPLAY_CASE_IDS),
        "authority_granted": False,
        "production_mutated": False,
        "repo_unchanged": True,
    }
    return {**body, "evidence_digest": canonical_digest(body)}


def test_phase10_acceptance_records_exact_git_revision() -> None:
    repo = Path(__file__).resolve().parents[1]

    commit = _tested_commit(repo)

    assert len(commit) == 40
    assert all(char in "0123456789abcdef" for char in commit)


def test_phase10_acceptance_snapshot_is_digest_bound() -> None:
    repo = Path(__file__).resolve().parents[1]

    snapshot = _repo_snapshot(repo)

    assert snapshot["head"] == _tested_commit(repo)
    assert len(snapshot["status_sha256"]) == 64


@pytest.mark.skipif(os.name == "nt", reason="negative control is for non-Windows CI")
def test_phase10_owner_machine_acceptance_requires_windows() -> None:
    with pytest.raises(Phase10AcceptanceError, match="must run on Windows"):
        _require_windows()


def test_phase10_acceptance_output_must_be_outside_repo(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    with pytest.raises(Phase10AcceptanceError, match="outside the tested repository"):
        _require_output_outside_repo(repo / "acceptance.json", repo=repo)

    outside = tmp_path / "acceptance.json"
    assert _require_output_outside_repo(outside, repo=repo) == outside.resolve()


def test_phase10_acceptance_evidence_validates_exact_commit() -> None:
    commit = "c" * 40
    payload = _payload(commit)

    validated = validate_acceptance_evidence(payload, tested_commit=commit)

    assert validated == payload


def test_phase10_acceptance_evidence_rejects_tampering() -> None:
    commit = "c" * 40
    payload = _payload(commit)
    payload["suite_status"] = "FAIL"

    with pytest.raises(Phase10AcceptanceError, match="digest mismatch"):
        validate_acceptance_evidence(payload, tested_commit=commit)


def test_phase10_acceptance_evidence_rejects_wrong_commit() -> None:
    payload = _payload("c" * 40)

    with pytest.raises(Phase10AcceptanceError, match="tested commit mismatch"):
        validate_acceptance_evidence(payload, tested_commit="d" * 40)


def test_phase10_acceptance_evidence_rejects_incomplete_matrix() -> None:
    commit = "c" * 40
    payload = _payload(commit)
    body = {key: value for key, value in payload.items() if key != "evidence_digest"}
    body["case_ids"] = list(PHASE10_REPLAY_CASE_IDS[:-1])
    body["case_count"] = len(PHASE10_REPLAY_CASE_IDS) - 1
    payload = {**body, "evidence_digest": canonical_digest(body)}

    with pytest.raises(Phase10AcceptanceError, match="exact Phase-10 replay matrix"):
        validate_acceptance_evidence(payload, tested_commit=commit)


def test_phase10_acceptance_evidence_requires_checkout_immutability() -> None:
    commit = "c" * 40
    payload = _payload(commit)
    body = {key: value for key, value in payload.items() if key != "evidence_digest"}
    body["repo_unchanged"] = False
    payload = {**body, "evidence_digest": canonical_digest(body)}

    with pytest.raises(Phase10AcceptanceError, match="checkout immutability"):
        validate_acceptance_evidence(payload, tested_commit=commit)


def test_phase10_acceptance_evidence_rejects_authority_claim() -> None:
    commit = "c" * 40
    payload = _payload(commit)
    body = {key: value for key, value in payload.items() if key != "evidence_digest"}
    body["authority_granted"] = True
    payload = {**body, "evidence_digest": canonical_digest(body)}

    with pytest.raises(Phase10AcceptanceError, match="Authority"):
        validate_acceptance_evidence(payload, tested_commit=commit)
