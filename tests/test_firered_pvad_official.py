from __future__ import annotations

import numpy as np

from jarvis.identity.firered_pvad_official import (
    FIRERED_PVAD_FILTER_ALPHA,
    FIRERED_PVAD_MIN_SILENCE_SECONDS,
    FIRERED_PVAD_MIN_SPEECH_SECONDS,
    FireRedOfficialParityVad,
)


def test_official_parity_pcm16_preserves_int16() -> None:
    samples = np.asarray([-32768, -1, 0, 1, 32767], dtype=np.int16)

    converted = FireRedOfficialParityVad._to_pcm16(samples)

    assert converted.dtype == np.int16
    assert np.array_equal(converted, samples)


def test_official_parity_pcm16_clips_float_input() -> None:
    samples = np.asarray([-2.0, -1.0, 0.0, 1.0, 2.0], dtype=np.float32)

    converted = FireRedOfficialParityVad._to_pcm16(samples)

    assert converted.tolist() == [-32767, -32767, 0, 32767, 32767]


def test_official_parity_uses_published_plugin_defaults() -> None:
    assert FIRERED_PVAD_FILTER_ALPHA == 0.8
    assert FIRERED_PVAD_MIN_SPEECH_SECONDS == 0.16
    assert FIRERED_PVAD_MIN_SILENCE_SECONDS == 0.40
