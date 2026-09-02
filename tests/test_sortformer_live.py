from __future__ import annotations

import ctypes

import numpy as np
import pytest

from jarvis.identity.sortformer_live import NativeSortformerLiveStream
from jarvis.identity.sortformer_native import SortformerNativeError


class _FakeLib:
    def __init__(self) -> None:
        self.samples = 0
        self.sample_rate = 16_000
        self.closed = False
        self.finished = False

    def nemo_speech_diar_stream_open(self, model, out) -> int:
        del model
        out._obj.value = 123
        return 0

    def nemo_speech_diar_stream_push_f32(
        self,
        stream,
        samples,
        n_samples,
        sample_rate,
    ) -> int:
        del stream, samples
        self.samples += int(n_samples)
        self.sample_rate = int(sample_rate)
        return 0

    def nemo_speech_diar_stream_finish(self, stream) -> int:
        del stream
        self.finished = True
        return 0

    def nemo_speech_diar_stream_close(self, stream) -> None:
        del stream
        self.closed = True

    def nemo_speech_diar_frame_count(self, stream) -> int:
        del stream
        return self.samples // 1600

    def nemo_speech_diar_frame_probs_start(self, stream) -> int:
        del stream
        return 0

    def nemo_speech_diar_frame_probs(self, stream, out, capacity) -> int:
        del stream
        frames = self.samples // 1600
        values = []
        for index in range(frames):
            values.extend((0.9 if index % 2 == 0 else 0.1, 0.1 if index % 2 == 0 else 0.9))
        assert int(capacity) >= len(values)
        for index, value in enumerate(values):
            out[index] = value
        return 0


class _FakeDiarizer:
    def __init__(self) -> None:
        self._model = ctypes.c_void_p(1)
        self._lib = _FakeLib()
        self.num_speakers = 2
        self.seconds_per_frame = 0.1

    def _check(self, status: int, operation: str) -> None:
        if status != 0:
            raise SortformerNativeError(operation)


def test_live_stream_exposes_probabilities_before_finish() -> None:
    diarizer = _FakeDiarizer()
    stream = NativeSortformerLiveStream(diarizer)  # type: ignore[arg-type]

    first = stream.push(np.ones(1600, dtype=np.int16), sample_rate=16_000)
    second = stream.push(np.ones(1600, dtype=np.int16), sample_rate=16_000)

    assert first.snapshot.frame_count == 1
    assert first.snapshot.probabilities.shape == (1, 2)
    assert second.snapshot.frame_count == 2
    assert second.audio_seconds_total == pytest.approx(0.2)
    np.testing.assert_allclose(second.snapshot.probabilities[1], [0.1, 0.9])

    final = stream.finish()
    assert final.frame_count == 2
    assert diarizer._lib.finished is True

    with pytest.raises(SortformerNativeError, match="already finished"):
        stream.push(np.ones(1600, dtype=np.int16), sample_rate=16_000)

    stream.close()
    assert diarizer._lib.closed is True


def test_live_stream_rejects_sample_rate_change() -> None:
    diarizer = _FakeDiarizer()
    with NativeSortformerLiveStream(diarizer) as stream:  # type: ignore[arg-type]
        stream.push(np.ones(800, dtype=np.int16), sample_rate=16_000)
        with pytest.raises(ValueError, match="cannot change"):
            stream.push(np.ones(800, dtype=np.int16), sample_rate=48_000)
