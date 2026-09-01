from __future__ import annotations

import argparse

import numpy as np
import pytest

from jarvis.identity.speaker_benchmark import (
    InMemorySegmentRecorder,
    _parse_scenario_command,
    int16_to_float32,
    max_reference_cosine,
    normalize_embedding,
    parse_model_spec,
    segment_metrics,
)


class FakeFrame:
    def __init__(self, values: list[int], *, sample_rate: int = 48_000) -> None:
        self.num_channels = 1
        self.sample_rate = sample_rate
        self.data = np.asarray(values, dtype=np.int16).tobytes()


def test_parse_model_spec_uses_explicit_name_path_contract() -> None:
    spec = parse_model_spec("campp=C:/models/campp.onnx")

    assert spec.name == "campp"
    assert str(spec.path).replace("\\", "/") == "C:/models/campp.onnx"
    with pytest.raises(argparse.ArgumentTypeError):
        parse_model_spec("C:/models/campp.onnx")
    with pytest.raises(argparse.ArgumentTypeError):
        parse_model_spec("=C:/models/campp.onnx")


def test_int16_pcm_conversion_is_normalized_float32() -> None:
    converted = int16_to_float32(np.asarray([-32768, 0, 16384, 32767], dtype=np.int16))

    assert converted.dtype == np.float32
    assert converted[0] == pytest.approx(-1.0)
    assert converted[1] == 0.0
    assert converted[2] == pytest.approx(0.5)
    assert converted[3] < 1.0


def test_segment_metrics_report_duration_energy_and_clipping() -> None:
    samples = np.full(48_000, 16384, dtype=np.int16)

    metrics = segment_metrics(samples, 48_000)

    assert metrics.duration_seconds == pytest.approx(1.0)
    assert metrics.rms_dbfs == pytest.approx(-6.0206, abs=0.001)
    assert metrics.peak_dbfs == pytest.approx(-6.0206, abs=0.001)
    assert metrics.clipping_ratio == 0.0

    clipped = segment_metrics(
        np.asarray([-32768, 32767, 0, 0], dtype=np.int16),
        4,
    )
    assert clipped.clipping_ratio == pytest.approx(0.5)


def test_reference_cosine_uses_best_prototype_without_centroid_collapse() -> None:
    references = [
        normalize_embedding(np.asarray([1.0, 0.0], dtype=np.float32)),
        normalize_embedding(np.asarray([0.0, 1.0], dtype=np.float32)),
    ]

    score = max_reference_cosine(
        references,
        np.asarray([0.1, 0.9], dtype=np.float32),
    )

    assert score == pytest.approx(0.9938837, abs=1e-6)


def test_in_memory_recorder_keeps_only_active_mono_segment() -> None:
    recorder = InMemorySegmentRecorder()
    recorder.accept_frame(FakeFrame([1, 2]))
    recorder.start()
    recorder.accept_frame(FakeFrame([3, 4]))
    recorder.accept_frame(FakeFrame([5, 6]))

    samples, sample_rate = recorder.stop()

    assert sample_rate == 48_000
    assert samples.tolist() == [3, 4, 5, 6]
    assert recorder.recording is False
    with pytest.raises(RuntimeError, match="not active"):
        recorder.stop()


def test_in_memory_recorder_rejects_sample_rate_drift() -> None:
    recorder = InMemorySegmentRecorder()
    recorder.start()
    recorder.accept_frame(FakeFrame([1, 2], sample_rate=48_000))

    with pytest.raises(ValueError, match="sample rate changed"):
        recorder.accept_frame(FakeFrame([3, 4], sample_rate=16_000))


def test_scenario_command_supports_duration_sweep_without_thresholds() -> None:
    assert _parse_scenario_command("owner-normal") == ("owner-normal", 3.0)
    assert _parse_scenario_command("owner-short 0.5") == ("owner-short", 0.5)
    assert _parse_scenario_command(" ") is None
    with pytest.raises(ValueError):
        _parse_scenario_command("owner normal 3")
    with pytest.raises(ValueError):
        _parse_scenario_command("owner 0")
