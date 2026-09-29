from __future__ import annotations

import json

import pytest

from jarvis.promotion import runtime_dependencies
from jarvis.promotion.runtime_dependencies import ReleaseDependencyError


def _write_overlay(root, release_sha: str, *, filename: str = "demo_module.py"):
    target = root / release_sha
    overlay = target / "site-packages"
    overlay.mkdir(parents=True)
    (overlay / filename).write_text("VALUE = 1\n", encoding="utf-8")
    payload = {
        "schema": "release_dependency_overlay.v1",
        "release_sha": release_sha,
        "change_id": "change-demo",
        "manifest_artifact_id": "artifact-demo",
        "manifest_artifact_digest": "a" * 64,
        "binding_digest": "b" * 64,
        "runtime_bindings": [],
        "overlay_digest": runtime_dependencies._tree_digest(overlay),
    }
    (target / "runtime-dependencies.json").write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    return overlay


def test_runtime_dependency_overlay_is_verified_on_read(tmp_path, monkeypatch) -> None:
    release_sha = "1" * 40
    monkeypatch.setattr(
        runtime_dependencies,
        "default_runtime_dependency_root",
        lambda: tmp_path,
    )
    overlay = _write_overlay(tmp_path, release_sha)

    assert runtime_dependencies.runtime_dependency_overlay(release_sha) == overlay

    (overlay / "demo_module.py").write_text("VALUE = 2\n", encoding="utf-8")
    with pytest.raises(ReleaseDependencyError, match="integrity mismatch"):
        runtime_dependencies.runtime_dependency_overlay(release_sha)


def test_runtime_dependency_overlay_rejects_pth_startup_logic(
    tmp_path,
    monkeypatch,
) -> None:
    release_sha = "2" * 40
    monkeypatch.setattr(
        runtime_dependencies,
        "default_runtime_dependency_root",
        lambda: tmp_path,
    )
    _write_overlay(tmp_path, release_sha, filename="unsafe.pth")

    with pytest.raises(ReleaseDependencyError, match=r"\.pth startup logic"):
        runtime_dependencies.runtime_dependency_overlay(release_sha)
