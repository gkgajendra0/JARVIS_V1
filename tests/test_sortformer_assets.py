from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.identity.sortformer_assets import (
    SORTFORMER_MODEL_FILENAME,
    SORTFORMER_MODEL_SIZE_BYTES,
    SortformerAssetIntegrityError,
    default_sortformer_model_path,
    verify_sortformer_model,
)


def test_configured_sortformer_path_wins(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured = tmp_path / "custom.gguf"
    monkeypatch.setenv("JARVIS_SORTFORMER_MODEL_PATH", str(configured))

    assert default_sortformer_model_path() == configured


def test_default_windows_style_sortformer_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("JARVIS_SORTFORMER_MODEL_PATH", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    assert default_sortformer_model_path() == (
        tmp_path / "JARVIS" / "models" / "diarization" / SORTFORMER_MODEL_FILENAME
    )


def test_missing_sortformer_model_fails_integrity(tmp_path: Path) -> None:
    with pytest.raises(SortformerAssetIntegrityError, match="missing"):
        verify_sortformer_model(tmp_path / "missing.gguf")


def test_wrong_size_sortformer_model_fails_before_hash(tmp_path: Path) -> None:
    model = tmp_path / SORTFORMER_MODEL_FILENAME
    model.write_bytes(b"not-the-model")

    with pytest.raises(SortformerAssetIntegrityError, match="size mismatch"):
        verify_sortformer_model(model)


def test_pinned_model_size_is_not_placeholder() -> None:
    assert SORTFORMER_MODEL_SIZE_BYTES > 100_000_000
