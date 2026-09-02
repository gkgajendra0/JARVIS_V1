from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from jarvis.identity.sortformer_native import (
    SortformerNativeError,
    _to_float32_mono,
    resolve_sortformer_model,
)


def test_int16_pcm_is_normalized_to_float32() -> None:
    samples = np.asarray([-32768, -16384, 0, 16384, 32767], dtype=np.int16)

    result = _to_float32_mono(samples)

    assert result.dtype == np.float32
    assert result.flags.c_contiguous
    assert result[0] == pytest.approx(-1.0)
    assert result[2] == pytest.approx(0.0)
    assert result[-1] == pytest.approx(32767 / 32768)


def test_float_audio_is_clipped_to_pcm_range() -> None:
    samples = np.asarray([-1.4, -0.2, 0.0, 0.4, 1.7], dtype=np.float64)

    result = _to_float32_mono(samples)

    np.testing.assert_allclose(
        result,
        np.asarray([-1.0, -0.2, 0.0, 0.4, 1.0], dtype=np.float32),
    )


def test_nonfinite_audio_is_rejected() -> None:
    with pytest.raises(ValueError, match="non-finite"):
        _to_float32_mono(np.asarray([0.0, np.inf], dtype=np.float32))


def test_explicit_model_path_is_resolved(tmp_path: Path) -> None:
    model = tmp_path / "sortformer.gguf"
    model.write_bytes(b"model")

    assert resolve_sortformer_model(model) == model.resolve()


def test_model_path_can_come_from_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = tmp_path / "sortformer.gguf"
    model.write_bytes(b"model")
    monkeypatch.setenv("JARVIS_SORTFORMER_MODEL_PATH", str(model))

    assert resolve_sortformer_model() == model.resolve()


def test_missing_model_path_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("JARVIS_SORTFORMER_MODEL_PATH", raising=False)

    with pytest.raises(SortformerNativeError, match="model was not found"):
        resolve_sortformer_model()
