from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np
import pytest
from livekit import rtc

from jarvis.voice.wakeword import (
    BoundedLiveKitWakeVerifier,
    CascadedWakePredictor,
    LiveKitWakeDetector,
    OpenWakeWordStreamingPredictor,
    load_livekit_predictor,
)


class FakePredictor:
    def __init__(self, score: float) -> None:
        self.score = score
        self.windows: list[np.ndarray] = []

    def predict(self, audio_chunk: np.ndarray) -> dict[str, float]:
        self.windows.append(audio_chunk)
        return {"jarvis": self.score}


class FakeStreamingPredictor(FakePredictor):
    window_samples = 1_280

    def __init__(self, score: float) -> None:
        super().__init__(score)
        self.reset_calls = 0

    def reset(self) -> None:
        self.reset_calls += 1


def frame(samples: int = 1_280) -> rtc.AudioFrame:
    return rtc.AudioFrame(
        data=np.ones(samples, dtype=np.int16).tobytes(),
        sample_rate=16_000,
        num_channels=1,
        samples_per_channel=samples,
    )


def test_streaming_predictor_reuses_livekit_bundled_feature_models(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import openwakeword.model as openwakeword_model

    captured: dict[str, object] = {}

    class FakeModel:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        def predict(self, _samples: np.ndarray) -> dict[str, float]:
            return {"jarvis": 0.0}

        def reset(self) -> None:
            return None

    monkeypatch.setattr(openwakeword_model, "Model", FakeModel)
    classifier_path = tmp_path / "jarvis.onnx"
    classifier_path.write_bytes(b"stub")

    OpenWakeWordStreamingPredictor(classifier_path)

    mel_path = Path(str(captured["melspec_model_path"]))
    embedding_path = Path(str(captured["embedding_model_path"]))
    assert mel_path.is_file()
    assert embedding_path.is_file()
    assert mel_path.name == "melspectrogram.onnx"
    assert embedding_path.name == "embedding_model.onnx"
    assert captured["wakeword_models"] == [str(classifier_path)]
    assert captured["inference_framework"] == "onnx"
    assert captured["ncpu"] == 1


def test_bounded_verifier_uses_low_idle_cpu_session_options(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import onnxruntime as ort

    captured_options: list[ort.SessionOptions] = []

    class FakeInput:
        name = "input"

    class FakeSession:
        def __init__(
            self,
            _path: str,
            *,
            sess_options: ort.SessionOptions,
            providers: list[str],
        ) -> None:
            captured_options.append(sess_options)
            assert providers == ["CPUExecutionProvider"]

        def get_inputs(self) -> list[FakeInput]:
            return [FakeInput()]

    monkeypatch.setattr(ort, "InferenceSession", FakeSession)
    classifier_path = tmp_path / "jarvis.onnx"
    classifier_path.write_bytes(b"stub")

    BoundedLiveKitWakeVerifier(classifier_path)

    assert len(captured_options) == 3
    for options in captured_options:
        assert options.intra_op_num_threads == 1
        assert options.inter_op_num_threads == 1
        assert options.execution_mode == ort.ExecutionMode.ORT_SEQUENTIAL
        assert options.graph_optimization_level == ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        assert options.get_session_config_entry("session.intra_op.allow_spinning") == "0"
        assert options.get_session_config_entry("session.inter_op.allow_spinning") == "0"


def test_bounded_verifier_preserves_livekit_classifier_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import onnxruntime as ort

    classifier_inputs: list[np.ndarray] = []
    embedding_inputs: list[np.ndarray] = []

    class FakeInput:
        name = "input"

    class FakeSession:
        def __init__(
            self,
            path: str,
            *,
            sess_options: ort.SessionOptions,
            providers: list[str],
        ) -> None:
            del sess_options, providers
            self._name = Path(path).name

        def get_inputs(self) -> list[FakeInput]:
            return [FakeInput()]

        def run(
            self,
            _outputs: object,
            inputs: dict[str, np.ndarray],
        ) -> list[np.ndarray]:
            value = next(iter(inputs.values()))
            if self._name == "melspectrogram.onnx":
                return [np.zeros((1, 1, 196, 32), dtype=np.float32)]
            if self._name == "embedding_model.onnx":
                embedding_inputs.append(value.copy())
                return [np.zeros((1, 1, 1, 96), dtype=np.float32)]
            classifier_inputs.append(value.copy())
            return [np.array([[0.91]], dtype=np.float32)]

    monkeypatch.setattr(ort, "InferenceSession", FakeSession)
    classifier_path = tmp_path / "jarvis.onnx"
    classifier_path.write_bytes(b"stub")
    verifier = BoundedLiveKitWakeVerifier(classifier_path)

    scores = verifier.predict(np.ones(32_000, dtype=np.int16))

    assert scores["jarvis"] == pytest.approx(0.91)
    assert len(embedding_inputs) == 16
    assert embedding_inputs[0].shape == (1, 76, 32, 1)
    assert np.all(embedding_inputs[0] == pytest.approx(2.0))
    assert classifier_inputs[0].shape == (1, 16, 96)


def test_load_predictor_uses_bounded_verifier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jarvis.voice import wakeword

    captured: dict[str, Path] = {}

    def build_verifier(path: Path) -> FakePredictor:
        captured["path"] = path
        return FakePredictor(0.0)

    monkeypatch.setattr(
        wakeword,
        "OpenWakeWordStreamingPredictor",
        lambda _path: FakeStreamingPredictor(0.0),
    )
    monkeypatch.setattr(wakeword, "BoundedLiveKitWakeVerifier", build_verifier)
    classifier_path = tmp_path / "jarvis.onnx"
    classifier_path.write_bytes(b"stub")

    predictor = wakeword.load_livekit_predictor(classifier_path)

    assert isinstance(predictor, CascadedWakePredictor)
    assert captured["path"] == classifier_path


def test_wake_cascade_uses_exact_verifier_only_after_streaming_pretrigger() -> None:
    streaming = FakeStreamingPredictor(0.20)
    verifier = FakePredictor(0.91)
    cascade = CascadedWakePredictor(
        streaming,
        verifier,
        pretrigger_threshold=0.05,
    )
    chunk = np.ones(1_280, dtype=np.int16)

    for _ in range(24):
        assert cascade.predict(chunk) == {"jarvis": 0.0}

    scores = cascade.predict(chunk)

    assert scores == {"jarvis": 0.91}
    assert len(verifier.windows) == 1
    assert verifier.windows[0].shape == (32_000,)


def test_wake_cascade_suppresses_low_streaming_scores_without_exact_work() -> None:
    streaming = FakeStreamingPredictor(0.01)
    verifier = FakePredictor(0.99)
    cascade = CascadedWakePredictor(
        streaming,
        verifier,
        pretrigger_threshold=0.05,
    )
    chunk = np.ones(1_280, dtype=np.int16)

    for _ in range(30):
        assert cascade.predict(chunk) == {"jarvis": 0.0}

    assert verifier.windows == []


def test_wake_cascade_reset_clears_exact_window_history() -> None:
    streaming = FakeStreamingPredictor(0.20)
    verifier = FakePredictor(0.91)
    cascade = CascadedWakePredictor(streaming, verifier)
    chunk = np.ones(1_280, dtype=np.int16)

    for _ in range(24):
        cascade.predict(chunk)
    cascade.reset()
    assert cascade.predict(chunk) == {"jarvis": 0.0}

    assert verifier.windows == []
    assert streaming.reset_calls == 1


@pytest.mark.asyncio
async def test_detector_scores_two_second_windows_and_disables_after_wake() -> None:
    predictor = FakePredictor(0.9)
    detector = LiveKitWakeDetector(
        predictor,
        threshold=0.68,
        debounce_seconds=2,
    )
    detector.enable()

    for _ in range(25):
        detector.feed(frame())

    detection = await asyncio.wait_for(detector.wait_for_detection(), timeout=1)

    assert detection.name == "jarvis"
    assert detection.confidence == 0.9
    assert predictor.windows[0].shape == (32_000,)
    assert detector.enabled is False
    await detector.aclose()


@pytest.mark.asyncio
async def test_detector_uses_streaming_predictor_window() -> None:
    predictor = FakeStreamingPredictor(0.9)
    detector = LiveKitWakeDetector(
        predictor,
        threshold=0.68,
        debounce_seconds=2,
    )
    detector.enable()
    detector.feed(frame())

    detection = await asyncio.wait_for(detector.wait_for_detection(), timeout=1)

    assert detection.name == "jarvis"
    assert predictor.windows[0].shape == (1_280,)
    assert predictor.reset_calls == 1
    await detector.aclose()


@pytest.mark.asyncio
async def test_detector_ignores_audio_while_disabled() -> None:
    predictor = FakePredictor(0.9)
    detector = LiveKitWakeDetector(
        predictor,
        threshold=0.68,
        debounce_seconds=2,
    )

    for _ in range(30):
        detector.feed(frame())
    await asyncio.sleep(0)

    assert predictor.windows == []
    await detector.aclose()


def test_missing_wake_model_fails_truthfully(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Wake-word model not found"):
        load_livekit_predictor(tmp_path / "missing.onnx")
