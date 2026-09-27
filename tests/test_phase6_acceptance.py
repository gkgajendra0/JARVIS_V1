from __future__ import annotations

import os
from pathlib import Path

import pytest

from jarvis.incident_repair.phase6_acceptance import (
    Phase6AcceptanceError,
    _repo_snapshot,
    _require_windows_docker,
    _tested_commit,
)


def test_phase6_acceptance_records_exact_git_revision() -> None:
    repo = Path(__file__).resolve().parents[1]

    commit = _tested_commit(repo)

    assert len(commit) == 40
    assert all(char in "0123456789abcdef" for char in commit)


def test_phase6_acceptance_protected_checkout_snapshot_is_digest_bound() -> None:
    repo = Path(__file__).resolve().parents[1]

    snapshot = _repo_snapshot(repo)

    assert snapshot["head"] == _tested_commit(repo)
    assert len(snapshot["status_sha256"]) == 64


@pytest.mark.skipif(os.name == "nt", reason="negative control is for non-Windows CI")
def test_owner_machine_acceptance_cannot_pass_on_non_windows() -> None:
    with pytest.raises(Phase6AcceptanceError, match="must run on Windows"):
        _require_windows_docker("jarvis-dev-tests:local")
