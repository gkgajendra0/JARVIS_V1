"""Lab-only: rescore recorded utterances against the enrolled owner voice.

Reads one ``--record-diagnostics`` run of the isolated voice lab (DPAPI-sealed,
current Windows user), decrypts each utterance's audio in memory, and scores
two variants with the same CAM++ template and speech-region detector the live
shadow uses:

- ``clip``: the whole recorded utterance (local VAD speech plus 0.5 s pre-roll);
- ``region``: the most recent consolidated speech region inside the clip, as
  the live shadow selects it.

Each entry also carries the live ``Speaker evidence`` result for its accepted
transcript turn(s), from the lab's ``voice-lab.jsonl``. The output file holds
numbers, recognized text and ids only: no audio is written or sent anywhere.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import re
import wave
from pathlib import Path

import numpy as np

_LIVE = re.compile(
    r"Speaker evidence \| turn_id=(?P<turn>[0-9a-f-]+) \| status=(?P<status>\w+) \| "
    r"score=(?P<score>[0-9.]+|n/a) \| threshold=[0-9.]+ \| opening=(?P<opening>\w+) \| "
    r"reason=(?P<reason>\w+)"
)


def live_evidence(log_path: Path) -> dict[str, dict]:
    """turn_id -> live status/score from the lab log (plaintext JSON lines)."""
    found: dict[str, dict] = {}
    if not Path(log_path).is_file():
        return found
    for line in (
        Path(log_path).read_text(encoding="utf-8", errors="replace").splitlines()
    ):
        try:
            event = str(json.loads(line).get("event", ""))
        except (ValueError, AttributeError):
            continue
        match = _LIVE.search(event)
        if match is None:
            continue
        score = match["score"]
        found[match["turn"]] = {
            "status": match["status"],
            "score": None if score == "n/a" else float(score),
            "opening": match["opening"] == "True",
            "reason": match["reason"],
        }
    return found


def _pcm(wav_bytes: bytes) -> tuple[np.ndarray, int]:
    with wave.open(io.BytesIO(wav_bytes), "rb") as reader:
        rate = reader.getframerate()
        channels = reader.getnchannels()
        frames = reader.readframes(reader.getnframes())
    samples = np.frombuffer(frames, dtype=np.int16)
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1).astype(np.int16)
    return samples, rate


async def _score_variant(samples, rate, observer) -> dict:
    from jarvis.identity.speaker_identity import assess_speaker_segment

    quality = assess_speaker_segment(samples, sample_rate=rate)
    result = observer.score(samples, sample_rate=rate)
    return {
        "seconds": round(len(samples) / rate, 2),
        "rms_dbfs": round(float(quality.rms_dbfs), 1),
        "quality_accepted": bool(quality.accepted),
        "quality_reasons": list(quality.reason_codes),
        "score": (
            None
            if result.max_reference_cosine is None
            else round(float(result.max_reference_cosine), 4)
        ),
    }


async def rescore(run: dict, observer, region_detector, live: dict) -> list[dict]:
    """One entry per recorded utterance with audio (numbers only)."""
    from jarvis.identity.speaker_turn import SpeakerTurnAudio

    entries = []
    for session in run["sessions"]:
        for utterance in session["utterances"]:
            wav_bytes = run["audio"].get(utterance["id"])
            if wav_bytes is None:
                continue
            samples, rate = _pcm(wav_bytes)
            turns = [
                {"turn_id": a["turn_id"], "text": a["text"]}
                for a in utterance.get("accepted", [])
                if not a.get("duplicate_event")
            ]
            entry = {
                "id": utterance["id"],
                "session": utterance["session"],
                "speech_seconds": utterance.get("speech_seconds"),
                "overlapped_reply": utterance.get("overlapped_reply"),
                "recognized": [a.get("text") for a in utterance.get("asr", [])][-1:],
                "accepted": turns,
                "live": [live.get(t["turn_id"]) for t in turns],
                "clip": await _score_variant(samples, rate, observer),
                "region": None,
            }
            if region_detector is not None:
                turn = SpeakerTurnAudio(
                    samples=samples,
                    sample_rate=rate,
                    start_monotonic=0.0,
                    end_monotonic=len(samples) / rate,
                )
                region = await region_detector.extract(turn)
                if region.turn is not None:
                    entry["region"] = await _score_variant(
                        region.turn.samples, region.turn.sample_rate, observer
                    )
                    entry["region"]["reason"] = region.reason
                else:
                    entry["region"] = {"score": None, "reason": region.reason}
            entries.append(entry)
    return entries


def main() -> None:
    from jarvis.machine_config import default_machine_config_path

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", type=Path, required=True)
    parser.add_argument("--profile", type=Path, default=default_machine_config_path())
    args = parser.parse_args()

    from jarvis.identity.speaker_shadow import build_default_enrolled_speaker_observer
    from jarvis.identity.speech_region import LiveKitSileroSpeechRegionDetector
    from jarvis.security.dpapi import WindowsDpapiKeyProtector
    from jarvis.voice.project_voice_lab import prepare_speaker_evidence
    from jarvis.voice.voice_diagnostics import load_run

    lab = args.lab_root.resolve()
    runs = sorted((lab / "voice-diagnostics" / "runs").glob("*"))
    if not runs:
        parser.error("no diagnostics run in this lab")
    prepare_speaker_evidence(args.profile, lab)
    observer = build_default_enrolled_speaker_observer()
    run = load_run(runs[-1], WindowsDpapiKeyProtector())
    entries = asyncio.run(
        rescore(
            run,
            observer,
            LiveKitSileroSpeechRegionDetector(),
            live_evidence(lab / "voice-lab.jsonl"),
        )
    )
    out = lab / "speaker-rescore.json"
    out.write_text(
        json.dumps({"run_id": runs[-1].name, "utterances": entries}, indent=2),
        encoding="utf-8",
    )
    print(out)


if __name__ == "__main__":
    main()
