from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from jarvis.capability_acquisition.acceptance import (
    Phase9AcceptanceError,
    build_parser,
    run_acceptance,
)


def _git(repo, *args: str) -> None:
    subprocess.run(
        [shutil.which("git") or "git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _clean_repo(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("Git is required for Phase-9 acceptance harness tests")
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "jarvis-tests@example.invalid")
    _git(repo, "config", "user.name", "JARVIS Tests")
    (repo / "README.md").write_text("phase9\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "phase9 acceptance fixture")
    return repo


def _external_payload() -> dict[str, object]:
    return {
        "schema": "phase9_external_acceptance.v1",
        "capability_id": "tv.control",
        "package_id": "tv.control.package",
        "package_version": "1.0.0",
        "package_digest": "a" * 64,
        "target_kind": "device",
        "target_identity": "living-room-tv",
        "operations": [
            {
                "operation": "power",
                "verified": True,
                "external_effect_observed": True,
                "observation": "TV visibly powered on.",
                "evidence_refs": ["owner-machine:tv-power-observation"],
            }
        ],
        "effective_enabled_verified": True,
        "disable_rollback_verified": True,
        "owner_confirmed": True,
        "recorded_at": "2026-09-27T20:00:00+05:30",
        "source": "jarvis-owner-machine",
    }


def test_phase9_acceptance_requires_windows_by_default(tmp_path) -> None:
    repo = _clean_repo(tmp_path)
    evidence = tmp_path / "external.json"
    evidence.write_text(json.dumps(_external_payload()), encoding="utf-8")

    if __import__("sys").platform == "win32":
        pytest.skip("non-Windows guard is exercised on non-Windows CI")

    with pytest.raises(Phase9AcceptanceError, match="requires Windows"):
        run_acceptance(
            repo_root=repo,
            external_evidence=evidence,
            change_id="change_phase9_test",
        )


def test_phase9_acceptance_refuses_missing_real_external_evidence(tmp_path) -> None:
    repo = _clean_repo(tmp_path)

    with pytest.raises(Exception, match="external acceptance evidence file"):
        run_acceptance(
            repo_root=repo,
            external_evidence=tmp_path / "missing.json",
            change_id="change_phase9_test",
            require_windows=False,
        )


def test_phase9_acceptance_refuses_dirty_protected_repository(tmp_path) -> None:
    repo = _clean_repo(tmp_path)
    evidence = tmp_path / "external.json"
    evidence.write_text(json.dumps(_external_payload()), encoding="utf-8")
    (repo / "README.md").write_text("dirty\n", encoding="utf-8")

    with pytest.raises(Phase9AcceptanceError, match="clean tracked working tree"):
        run_acceptance(
            repo_root=repo,
            external_evidence=evidence,
            change_id="change_phase9_test",
            require_windows=False,
        )


def test_phase9_acceptance_cli_requires_live_identity_inputs() -> None:
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args([])
