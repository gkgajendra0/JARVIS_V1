from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

from jarvis.autonomy.phase10a_acceptance import (
    Phase10AAcceptanceError,
    _git_revision,
    _require_output_outside_repo,
    _require_windows,
    validate_acceptance_evidence,
)
from jarvis.autonomy.replay import (
    PHASE10A_REPLAY_CORPUS_V1,
    phase10a_pytest_node_ids,
    phase10a_replay_corpus_digest,
    validate_phase10a_replay_corpus,
)
from jarvis.engineering_substrate.canonical import canonical_digest


def _payload(commit: str) -> dict[str, object]:
    body: dict[str, object] = {
        "schema_version": 1,
        "status": "PASS",
        "tested_commit": commit,
        "protected_main_commit": "d" * 40,
        "repo_status_sha256": "a" * 64,
        "repo_unchanged": True,
        "protected_main_unchanged": True,
        "recorded_at": "2026-09-28T16:00:00+00:00",
        "replay_corpus_digest": phase10a_replay_corpus_digest(),
        "case_count": len(PHASE10A_REPLAY_CORPUS_V1),
        "case_ids": [item.case_id for item in PHASE10A_REPLAY_CORPUS_V1],
        "pytest_node_count": len(phase10a_pytest_node_ids()),
        "pytest_stdout_sha256": "b" * 64,
        "pytest_stderr_sha256": "c" * 64,
        "authority_granted": False,
        "production_mutated": False,
        "production_autonomy_mode_enabled": False,
    }
    return {**body, "evidence_digest": canonical_digest(body)}


def test_phase10a_replay_corpus_is_exactly_thirty_unique_cases() -> None:
    validate_phase10a_replay_corpus()

    assert len(PHASE10A_REPLAY_CORPUS_V1) == 30
    assert [item.case_id[:2] for item in PHASE10A_REPLAY_CORPUS_V1] == [
        f"{index:02d}" for index in range(1, 31)
    ]
    assert len(phase10a_replay_corpus_digest()) == 64


def test_phase10a_replay_pytest_nodes_reference_real_tests() -> None:
    repo = Path(__file__).resolve().parents[1]

    for node_id in phase10a_pytest_node_ids():
        relative, function_name = node_id.split("::", 1)
        path = repo / relative
        assert path.is_file(), node_id
        module = ast.parse(path.read_text(encoding="utf-8"))
        functions = {
            item.name
            for item in module.body
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert function_name in functions, node_id

    for case in PHASE10A_REPLAY_CORPUS_V1:
        for evidence in case.evidence_tests:
            if "::" not in evidence:
                assert (repo / evidence).is_file(), evidence


def test_phase10a_acceptance_records_exact_git_revision() -> None:
    repo = Path(__file__).resolve().parents[1]

    commit = _git_revision(repo, "HEAD")

    assert len(commit) == 40
    assert all(char in "0123456789abcdef" for char in commit)


@pytest.mark.skipif(os.name == "nt", reason="negative control is for non-Windows CI")
def test_phase10a_owner_machine_acceptance_requires_windows() -> None:
    with pytest.raises(Phase10AAcceptanceError, match="must run on Windows"):
        _require_windows()


def test_phase10a_acceptance_output_must_be_outside_repo(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    with pytest.raises(
        Phase10AAcceptanceError,
        match="outside the tested repository",
    ):
        _require_output_outside_repo(repo / "acceptance.json", repo=repo)

    outside = tmp_path / "acceptance.json"
    assert _require_output_outside_repo(outside, repo=repo) == outside.resolve()


def test_phase10a_acceptance_evidence_validates_exact_commit() -> None:
    commit = "c" * 40
    payload = _payload(commit)

    assert validate_acceptance_evidence(payload, tested_commit=commit) == payload


def test_phase10a_acceptance_evidence_rejects_tampering() -> None:
    commit = "c" * 40
    payload = _payload(commit)
    payload["status"] = "FAIL"

    with pytest.raises(Phase10AAcceptanceError, match="digest mismatch"):
        validate_acceptance_evidence(payload, tested_commit=commit)


def test_phase10a_acceptance_evidence_rejects_wrong_commit() -> None:
    payload = _payload("c" * 40)

    with pytest.raises(
        Phase10AAcceptanceError,
        match="tested commit mismatch",
    ):
        validate_acceptance_evidence(payload, tested_commit="d" * 40)


def test_phase10a_acceptance_evidence_rejects_incomplete_corpus() -> None:
    commit = "c" * 40
    payload = _payload(commit)
    body = {
        key: value
        for key, value in payload.items()
        if key != "evidence_digest"
    }
    body["case_ids"] = body["case_ids"][:-1]
    body["case_count"] = 29
    payload = {**body, "evidence_digest": canonical_digest(body)}

    with pytest.raises(Phase10AAcceptanceError, match="locked Phase-10A"):
        validate_acceptance_evidence(payload, tested_commit=commit)


@pytest.mark.parametrize(
    ("field", "message"),
    (
        ("repo_unchanged", "checkout immutability"),
        ("protected_main_unchanged", "protected-main immutability"),
        ("authority_granted", "Authority"),
        ("production_mutated", "production"),
        ("production_autonomy_mode_enabled", "production autonomy"),
    ),
)
def test_phase10a_acceptance_rejects_governance_boundary_failure(
    field: str,
    message: str,
) -> None:
    commit = "c" * 40
    payload = _payload(commit)
    body = {
        key: value
        for key, value in payload.items()
        if key != "evidence_digest"
    }
    body[field] = not bool(body[field])
    payload = {**body, "evidence_digest": canonical_digest(body)}

    with pytest.raises(Phase10AAcceptanceError, match=message):
        validate_acceptance_evidence(payload, tested_commit=commit)
