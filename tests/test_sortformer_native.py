from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from jarvis.identity.sortformer_native import (
    NVIDIA_SORTFORMER_LOW_LATENCY,
    NVIDIA_SORTFORMER_ULTRA_LOW_LATENCY,
    SortformerGeometry,
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


def test_published_low_latency_geometry_matches_model_card() -> None:
    geometry = NVIDIA_SORTFORMER_LOW_LATENCY

    assert geometry.chunk_frames == 6
    assert geometry.right_context_frames == 7
    assert geometry.input_buffer_frames == 13
    assert geometry.fifo_frames == 188
    assert geometry.spkcache_frames == 188
    assert geometry.update_period_frames == 144


def test_published_ultra_low_latency_geometry_matches_model_card() -> None:
    geometry = NVIDIA_SORTFORMER_ULTRA_LOW_LATENCY

    assert geometry.chunk_frames == 3
    assert geometry.right_context_frames == 1
    assert geometry.input_buffer_frames == 4
    assert geometry.fifo_frames == 188
    assert geometry.spkcache_frames == 188
    assert geometry.update_period_frames == 144


def test_invalid_geometry_is_rejected_before_native_runtime() -> None:
    with pytest.raises(ValueError, match="chunk_frames"):
        SortformerGeometry(
            name="bad",
            chunk_frames=0,
            right_context_frames=0,
            left_context_frames=0,
            fifo_frames=1,
            spkcache_frames=1,
            update_period_frames=1,
        )


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
