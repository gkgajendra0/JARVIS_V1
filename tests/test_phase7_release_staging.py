from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from jarvis.promotion.release import GitReleaseStager, ReleaseError


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_exact_release_worktree_is_reusable_and_tracked_mutation_fails(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    _git(repository, "init")
    (repository / "payload.txt").write_text("accepted\n", encoding="utf-8")
    _git(repository, "add", "payload.txt")
    _git(
        repository,
        "-c",
        "user.name=JARVIS CI",
        "-c",
        "user.email=jarvis-ci@example.invalid",
        "commit",
        "-m",
        "accepted release",
    )
    sha = _git(repository, "rev-parse", "HEAD")

    stager = GitReleaseStager(repository, tmp_path / "releases")
    first = stager.stage(sha)
    second = stager.stage(sha)

    assert first == second
    assert _git(first, "rev-parse", "HEAD") == sha
    assert (first / "payload.txt").read_text(encoding="utf-8") == "accepted\n"

    (first / "payload.txt").write_text("mutated\n", encoding="utf-8")
    with pytest.raises(ReleaseError, match="tracked source mutations"):
        stager.stage(sha)
