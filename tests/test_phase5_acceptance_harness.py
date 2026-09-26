from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.engineering_substrate.dependency import UV_WINDOWS_X64_0_12_19
from jarvis.engineering_substrate.phase5_acceptance import (
    Phase5AcceptanceError,
    _restart_lineage_acceptance,
    _tested_commit,
    _validate_uv_release_asset,
)


def test_acceptance_records_full_git_revision() -> None:
    repo = Path(__file__).resolve().parents[1]

    commit = _tested_commit(repo)

    assert len(commit) == 40
    assert all(char in "0123456789abcdef" for char in commit)


def test_uv_acceptance_rejects_tampered_release_asset_before_execution(
    tmp_path: Path,
) -> None:
    asset = tmp_path / UV_WINDOWS_X64_0_12_19.release_asset_name
    executable = tmp_path / "uv.exe"
    asset.write_bytes(b"tampered-release-asset")
    executable.write_bytes(b"not-executed")

    with pytest.raises(Phase5AcceptanceError, match="SHA-256 mismatch"):
        _validate_uv_release_asset(asset, executable)


def test_uv_acceptance_rejects_unreviewed_asset_name(tmp_path: Path) -> None:
    asset = tmp_path / "renamed-uv.zip"
    executable = tmp_path / "uv.exe"
    asset.write_bytes(b"not-the-reviewed-release")
    executable.write_bytes(b"not-executed")

    with pytest.raises(Phase5AcceptanceError, match="file name"):
        _validate_uv_release_asset(asset, executable)


def test_restart_lineage_acceptance_reopens_same_waiting_workitem(
    tmp_path: Path,
) -> None:
    result = _restart_lineage_acceptance(tmp_path)

    assert result["state"] == "waiting_resource"
    assert str(result["work_id"]).startswith("work_")
    assert int(result["version"]) == 2
    assert len(str(result["lineage_digest"])) == 64


def test_restart_lineage_acceptance_is_isolated_per_store(tmp_path: Path) -> None:
    first = _restart_lineage_acceptance(tmp_path / "one")
    second = _restart_lineage_acceptance(tmp_path / "two")

    assert first["work_id"] != second["work_id"]
    assert first["lineage_digest"] != second["lineage_digest"]
