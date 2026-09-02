from __future__ import annotations

from pathlib import Path

import numpy as np

from jarvis.identity import overlap_shadow
from jarvis.identity.overlap import OverlapState
from jarvis.identity.sortformer_native import SortformerRun
from jarvis.identity.speaker_turn import SpeakerTurnAudio


class _FakeDiarizer:
    def __init__(self, model_path: Path, **kwargs: object) -> None:
        del kwargs
        self.model_path = model_path
        self.runtime_version = "fake-0.1"
        self.model_load_seconds = 0.012
        self.closed = False

    def run_streaming(
        self,
        samples: np.ndarray,
        *,
        sample_rate: int,
        push_seconds: float,
    ) -> SortformerRun:
        del samples, sample_rate, push_seconds
        probabilities = np.asarray(
            [
                [0.9, 0.1, 0.0, 0.0],
                [0.9, 0.8, 0.0, 0.0],
                [0.9, 0.8, 0.0, 0.0],
                [0.9, 0.1, 0.0, 0.0],
            ],
            dtype=np.float32,
        )
        return SortformerRun(
            probabilities=probabilities,
            frame_count=4,
            num_speakers=4,
            seconds_per_frame=0.08,
            audio_seconds=1.0,
            inference_seconds=0.01,
            realtime_factor=0.01,
            push_latencies_ms=(1.0,),
        )

    def close(self) -> None:
        self.closed = True


def test_overlap_shadow_scores_full_turn(monkeypatch, tmp_path: Path) -> None:
    model = tmp_path / "sortformer.gguf"
    model.write_bytes(b"model")
    fake = _FakeDiarizer(model)
    monkeypatch.setattr(
        overlap_shadow,
        "NativeSortformerDiarizer",
        lambda *args, **kwargs: fake,
    )
    observer = overlap_shadow.NativeOverlapShadowObserver(model)
    turn = SpeakerTurnAudio(
        samples=np.ones(16_000, dtype=np.int16),
        sample_rate=16_000,
    )

    result = observer.score(turn)

    assert result.evidence.state is OverlapState.OVERLAP_DETECTED
    assert result.evidence.overlap_frames == 2
    assert result.realtime_factor >= 0.0
    assert observer.runtime_version == "fake-0.1"
    assert observer.model_load_ms == 12.0

    observer.close()
    assert fake.closed is True
