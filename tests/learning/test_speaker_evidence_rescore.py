"""Rescoring recorded lab utterances (numbers only), offline."""

import io
import json
import wave

import numpy as np
import pytest

from jarvis.identity.speaker_shadow import SpeakerShadowScore
from jarvis.identity.speaker_turn import SpeakerTurnAudio
from jarvis.identity.speech_region import SpeechRegionResult
from jarvis.voice.speaker_evidence_rescore import live_evidence, rescore


def wav(seconds, rate=24000, channels=1, amplitude=3000):
    t = np.arange(int(seconds * rate)) / rate
    mono = (amplitude * np.sin(2 * np.pi * 200 * t)).astype(np.int16)
    data = np.repeat(mono, channels) if channels > 1 else mono
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(data.tobytes())
    return buffer.getvalue()


class LengthScorer:
    """Score grows with duration: lets tests tell clip from region."""

    def score(self, samples, *, sample_rate):
        return SpeakerShadowScore(
            "scored", round(len(samples) / sample_rate / 10, 4), 1.0, ()
        )


class LastSecond:
    async def extract(self, turn):
        tail = turn.samples[-turn.sample_rate :]
        return SpeechRegionResult(
            SpeakerTurnAudio(tail, turn.sample_rate, 0.0, 1.0),
            1,
            "speech_region_selected",
        )


def test_live_evidence_is_read_from_the_lab_log(tmp_path):
    log = tmp_path / "voice-lab.jsonl"
    log.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "event": "Speaker evidence | turn_id=7f9f9d4b-2fac | status=non_owner | score=0.4330 | threshold=0.45 | opening=False | reason=scored | enforcement=on | effect=x"
                    }
                ),
                json.dumps(
                    {
                        "event": "Speaker evidence | turn_id=c79cc557-3aba | status=unknown | score=n/a | threshold=0.45 | opening=True | reason=speaker_quality_rejected | enforcement=on | effect=none"
                    }
                ),
                "not json",
            ]
        ),
        encoding="utf-8",
    )
    live = live_evidence(log)
    assert live["7f9f9d4b-2fac"] == {
        "status": "non_owner",
        "score": 0.433,
        "opening": False,
        "reason": "scored",
    }
    assert live["c79cc557-3aba"]["score"] is None
    assert live_evidence(tmp_path / "missing.jsonl") == {}


@pytest.mark.asyncio
async def test_each_utterance_gets_clip_and_region_scores_and_its_live_result():
    run = {
        "sessions": [
            {
                "utterances": [
                    {
                        "id": "r/s1/u1",
                        "session": 1,
                        "speech_seconds": 1.95,
                        "overlapped_reply": False,
                        "asr": [{"text": "What should I pack?"}],
                        "accepted": [{"turn_id": "t1", "text": "What should I pack?"}],
                    },
                    {  # video-only: no transcript accepted
                        "id": "r/s1/u2",
                        "session": 1,
                        "speech_seconds": 4.0,
                        "overlapped_reply": False,
                        "asr": [],
                        "accepted": [],
                    },
                    {"id": "r/s1/u3", "session": 1, "accepted": []},  # no audio kept
                ]
            }
        ],
        "audio": {"r/s1/u1": wav(2.5), "r/s1/u2": wav(4.5, rate=48000, channels=2)},
    }
    live = {
        "t1": {
            "status": "non_owner",
            "score": 0.433,
            "opening": False,
            "reason": "scored",
        }
    }
    entries = await rescore(run, LengthScorer(), LastSecond(), live)
    assert [e["id"] for e in entries] == ["r/s1/u1", "r/s1/u2"]
    first, video = entries
    assert first["clip"]["score"] == 0.25 and first["region"]["score"] == 0.1
    assert first["live"] == [live["t1"]] and first["accepted"][0]["turn_id"] == "t1"
    assert video["accepted"] == [] and video["live"] == []
    assert video["clip"]["seconds"] == 4.5  # stereo 48 kHz folded to mono
    # Numbers and text only: the output never carries audio.
    text = json.dumps(entries)
    assert "samples" not in text and len(text) < 4000
