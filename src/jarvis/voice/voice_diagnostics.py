"""Lab-only end-to-end voice diagnostics: audio -> ASR -> transcript -> memory.

Explicitly enabled only by ``project_voice_lab --record-diagnostics``. Normal
Jarvis never constructs it. Per owner utterance (local VAD speech start/end)
it correlates, under one ID:

* the exact post-wake microphone audio forwarded to Gemini (replayable WAV)
* Gemini's raw input transcription events (partial/final)
* the canonical accepted USER transcript (bridge), matched by activity epoch
* routing / project selection, the saved event text read back from the
  encrypted store, and its receipt
* response decisions (played / withheld), repairs, fallbacks, spoken replies
  (complete / interrupted), tool calls, latency and errors

Utterances that never produce a transcript are kept and flagged. Recognised
text is labelled as recognition, never as what was said: the audio is the
reference. Everything is DPAPI-sealed at rest (current Windows user,
purpose-bound) inside the isolated lab; nothing is sent anywhere. Retention:
runs older than ``retention_days`` and beyond ``keep_runs`` are deleted on
start; ``cleanup`` deletes all diagnostics and reports.
"""

from __future__ import annotations

import asyncio
import base64
import html
import io
import json
import logging
import shutil
import time
import wave
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

LOGGER = logging.getLogger(__name__)

PURPOSE = "jarvis-voice-diagnostics-v1"
_DIRECTORY = "voice-diagnostics"
_REPORT = "report.html"
_NO_TRANSCRIPT_GRACE_SECONDS = 4.0


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _wav(chunks, sample_rate, channels) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(2)
        out.setframerate(sample_rate)
        for chunk in chunks:
            out.writeframes(chunk)
    return buffer.getvalue()


class VoiceDiagnostics:
    """Runtime-scoped recorder for one lab run (all wake sessions)."""

    def __init__(
        self,
        lab: Path,
        *,
        protector,
        max_utterance_seconds: float = 30.0,
        pre_roll_seconds: float = 0.5,
        max_run_audio_bytes: int = 150_000_000,
        max_utterances: int = 300,
        retention_days: float = 7.0,
        keep_runs: int = 5,
    ) -> None:
        self.root = Path(lab) / _DIRECTORY
        self._protector = protector
        self.max_utterance_seconds = max_utterance_seconds
        self.pre_roll_seconds = pre_roll_seconds
        self._max_run_audio_bytes = max_run_audio_bytes
        self._max_utterances = max_utterances
        prune(self.root, retention_days=retention_days, keep_runs=keep_runs)
        self.run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ-") + uuid4().hex[:6]
        self.run_dir = self.root / "runs" / self.run_id
        self.run_dir.mkdir(parents=True, exist_ok=False)
        self._sessions: dict[int, _SessionDiagnostics] = {}
        self._session_count = 0
        self.utterance_count = 0
        self.audio_bytes = 0
        self._tasks: set[asyncio.Task] = set()
        self._closed = False
        self._write_now("run.json", {"run_id": self.run_id, "started_at": _now()})

    # -- wiring ---------------------------------------------------------------

    def attach(self, session, bridge) -> None:
        """voice_session_observer: one Gemini wake session."""
        self._session_count += 1
        diag = _SessionDiagnostics(self, self._session_count, bridge.conversation)
        self._sessions[id(bridge.conversation)] = diag
        session.on("user_state_changed", diag.on_user_state)
        session.on("agent_state_changed", diag.on_agent_state)
        session.on("user_input_transcribed", diag.on_transcribed)
        session.on("function_tools_executed", diag.on_tools)
        session.on("error", diag.on_error)
        bridge.add_accepted_turn_observer(diag.observe_turn)
        bridge.add_close_observer(diag.close)

    def audio_tap(self, bridge):
        """session_audio_tap: frames forwarded to Gemini for this session."""
        diag = self._sessions.get(id(bridge.conversation))
        return None if diag is None else diag.observe_frame

    def project_event(self, conversation, kind: str, **fields) -> None:
        """Hook used by VoiceProjectTurns (lab only)."""
        diag = self._sessions.get(id(conversation))
        if diag is not None:
            diag.project_event(kind, fields)

    # -- storage --------------------------------------------------------------

    def allow_audio(self, size: int) -> bool:
        if self.audio_bytes + size > self._max_run_audio_bytes:
            return False
        self.audio_bytes += size
        return True

    def _sealed(self, payload) -> bytes:
        data = (
            payload
            if isinstance(payload, bytes)
            else json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
        )
        return self._protector.seal(data, purpose=PURPOSE)

    def _write_now(self, name: str, payload) -> None:
        (self.run_dir / (name + ".sealed")).write_bytes(self._sealed(payload))

    def write(self, name: str, payload) -> None:
        """Seal and write off the event loop (DPAPI and disk are blocking)."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._write_now(name, payload)
            return
        task = loop.create_task(asyncio.to_thread(self._write_now, name, payload))
        self._tasks.add(task)
        task.add_done_callback(self._done)

    def _done(self, task) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            LOGGER.warning(
                "Voice diagnostics write failed | error=%s",
                type(task.exception()).__name__,
            )

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        for diag in list(self._sessions.values()):
            diag.close()
        while self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)
        LOGGER.info(
            "Voice diagnostics saved | run=%s | utterances=%s | dir=%s",
            self.run_id,
            self.utterance_count,
            self.run_dir,
        )


class _SessionDiagnostics:
    def __init__(self, owner: VoiceDiagnostics, number: int, conversation) -> None:
        self._owner = owner
        self.number = number
        self._conversation = conversation
        self.utterances: list[dict] = []
        self.unmatched: list[dict] = []
        self.started_at = _now()
        self._current: dict | None = None
        self._chunks: list[bytes] = []
        self._chunk_seconds = 0.0
        self._format = None
        self._pre_roll: deque = deque()
        self._pre_roll_seconds = 0.0
        self._seen_asr: set = set()
        self._seen_turns: set = set()
        self._speech_ended: float | None = None
        self._closed = False

    # -- audio ----------------------------------------------------------------

    def observe_frame(self, frame, _observed_at) -> None:
        if self._closed:
            return
        data = (
            bytes(frame.data.cast("B"))
            if hasattr(frame.data, "cast")
            else bytes(frame.data)
        )
        seconds = frame.samples_per_channel / frame.sample_rate
        fmt = (frame.sample_rate, frame.num_channels)
        if self._current is not None and fmt == self._format:
            if self._chunk_seconds < self._owner.max_utterance_seconds:
                self._chunks.append(data)
                self._chunk_seconds += seconds
            else:
                self._current["audio_truncated"] = True
            return
        if self._format is not None and fmt != self._format:
            self._pre_roll.clear()
            self._pre_roll_seconds = 0.0
        self._format = fmt
        self._pre_roll.append((data, seconds))
        self._pre_roll_seconds += seconds
        while self._pre_roll and self._pre_roll_seconds > self._owner.pre_roll_seconds:
            _, old = self._pre_roll.popleft()
            self._pre_roll_seconds -= old

    # -- speech detection -----------------------------------------------------

    def on_user_state(self, event) -> None:
        if self._closed:
            return
        if event.new_state == "speaking":
            self._finish_utterance()
            if self._owner.utterance_count >= self._owner._max_utterances:
                return
            self._owner.utterance_count += 1
            index = len(self.utterances) + 1
            self._current = {
                "id": f"{self._owner.run_id}/s{self.number}/u{index}",
                "session": self.number,
                "index": index,
                "speech_started_at": _now(),
                "speech_ended_at": None,
                "epoch": None,
                "audio": None,
                "audio_truncated": False,
                "asr": [],
                "accepted": [],
                "project": [],
                "responses": [],
                "assistant": [],
                "tools": [],
                "errors": [],
                "latency_ms": None,
                "flags": [],
            }
            self.utterances.append(self._current)
            self._assign_epoch_after_runtime(self._current)
            self._chunks = [chunk for chunk, _ in self._pre_roll]
            self._chunk_seconds = self._pre_roll_seconds
        elif event.new_state == "listening" and event.old_state == "speaking":
            current = self._current
            if current is None:
                return
            current["speech_ended_at"] = _now()
            if current["epoch"] is None:
                current["epoch"] = self._conversation.user_activity_epoch
            self._speech_ended = time.monotonic()
            self._finish_utterance()

    def _assign_epoch_after_runtime(self, utterance) -> None:
        """The runtime's own speech-start handler advances the activity epoch;
        read it once that handler has run (same event-loop turn)."""

        def assign():
            if utterance["epoch"] is None:
                utterance["epoch"] = self._conversation.user_activity_epoch

        try:
            asyncio.get_running_loop().call_soon(assign)
        except RuntimeError:
            assign()

    def _finish_utterance(self) -> None:
        current = self._current
        if current is None:
            return
        self._current = None
        if self._chunks and self._format is not None:
            sample_rate, channels = self._format
            audio = _wav(self._chunks, sample_rate, channels)
            name = current["id"].replace("/", "_") + ".wav"
            if self._owner.allow_audio(len(audio)):
                self._owner.write(name, audio)
                current["audio"] = {
                    "file": name + ".sealed",
                    "seconds": round(self._chunk_seconds, 2),
                    "sample_rate": sample_rate,
                    "channels": channels,
                    "includes_pre_roll_seconds": round(self._pre_roll_seconds, 2),
                }
            else:
                current["flags"].append("audio_not_kept_run_limit")
        self._chunks = []
        self._chunk_seconds = 0.0
        self._pre_roll.clear()
        self._pre_roll_seconds = 0.0

    def _utterance_for_epoch(self, epoch):
        for utterance in reversed(self.utterances):
            if utterance["epoch"] == epoch or (
                utterance["epoch"] is None and utterance is self._current
            ):
                return utterance
        return None

    def _latest(self):
        return self.utterances[-1] if self.utterances else None

    # -- recognition and canonical turns --------------------------------------

    def on_transcribed(self, event) -> None:
        key = (
            getattr(event, "item_id", None),
            event.transcript,
            bool(event.is_final),
        )
        entry = {
            "at": _now(),
            "text": event.transcript,
            "final": bool(event.is_final),
            "item_id": getattr(event, "item_id", None),
        }
        if key in self._seen_asr:
            entry["duplicate"] = True
        self._seen_asr.add(key)
        target = self._current or self._latest()
        (target["asr"] if target is not None else self.unmatched).append(entry)

    def observe_turn(self, turn) -> None:
        role = turn.role.value
        duplicate = turn.turn_id in self._seen_turns
        self._seen_turns.add(turn.turn_id)
        if role == "user":
            entry = {
                "at": _now(),
                "turn_id": turn.turn_id,
                "text": turn.text,
                "epoch": turn.user_activity_epoch,
            }
            if duplicate:
                entry["duplicate_event"] = True
            target = self._utterance_for_epoch(turn.user_activity_epoch)
            if target is None:
                self.unmatched.append({"kind": "accepted_without_speech", **entry})
            else:
                target["accepted"].append(entry)
        elif role == "assistant":
            entry = {
                "at": _now(),
                "turn_id": turn.turn_id,
                "text": turn.text,
                "interrupted": bool(turn.interrupted),
            }
            if duplicate:
                entry["duplicate_event"] = True
            target = self._utterance_for_epoch(self._conversation.user_activity_epoch)
            (target["assistant"] if target is not None else self.unmatched).append(
                entry
            )

    # -- responses ------------------------------------------------------------

    def on_agent_state(self, event) -> None:
        if event.new_state != "speaking":
            return
        target = self._utterance_for_epoch(self._conversation.user_activity_epoch)
        if target is not None and target["latency_ms"] is None and self._speech_ended:
            target["latency_ms"] = round((time.monotonic() - self._speech_ended) * 1000)

    def on_tools(self, event) -> None:
        target = self._utterance_for_epoch(self._conversation.user_activity_epoch)
        for call in getattr(event, "function_calls", ()) or ():
            entry = {"at": _now(), "name": getattr(call, "name", "unknown")}
            (target["tools"] if target is not None else self.unmatched).append(entry)

    def on_error(self, event) -> None:
        error = getattr(event, "error", None)
        entry = {
            "at": _now(),
            "error": getattr(error, "label", type(error).__name__),
            "recoverable": bool(getattr(error, "recoverable", False)),
        }
        target = self._latest()
        (target["errors"] if target is not None else self.unmatched).append(entry)

    def project_event(self, kind: str, fields: dict) -> None:
        epoch = fields.pop("epoch", self._conversation.user_activity_epoch)
        target = self._utterance_for_epoch(epoch)
        entry = {"at": _now(), "kind": kind, **fields}
        if kind in {"response_withheld", "response_played"}:
            bucket = "responses"
        else:
            bucket = "project"
        if target is None:
            self.unmatched.append(entry)
        else:
            target[bucket].append(entry)

    # -- close ----------------------------------------------------------------

    def close(self) -> None:
        if self._closed:
            return
        self._finish_utterance()
        self._closed = True
        for utterance in self.utterances:
            if not utterance["accepted"]:
                utterance["flags"].append("no_accepted_transcript")
            if len(utterance["accepted"]) > 1:
                utterance["flags"].append("several_transcripts_for_one_utterance")
        self._owner.write(
            f"session-{self.number:03d}.json",
            {
                "run_id": self._owner.run_id,
                "session": self.number,
                "started_at": self.started_at,
                "closed_at": _now(),
                "utterances": self.utterances,
                "unmatched": self.unmatched,
            },
        )


# -- retention, cleanup and the human-readable report -------------------------


def prune(root: Path, *, retention_days: float, keep_runs: int) -> list[str]:
    """Delete expired runs, the oldest beyond ``keep_runs``, and old reports."""
    removed = []
    runs_dir = Path(root) / "runs"
    if not runs_dir.is_dir():
        return removed
    runs = sorted((p for p in runs_dir.iterdir() if p.is_dir()), key=lambda p: p.name)
    cutoff = time.time() - retention_days * 86400
    keep = set(runs[-keep_runs:]) if keep_runs > 0 else set()
    for run in runs:
        if run not in keep or run.stat().st_mtime < cutoff:
            shutil.rmtree(run, ignore_errors=True)
            removed.append(run.name)
        else:
            report = run / _REPORT
            if report.exists():
                report.unlink()  # plaintext reports never outlive one lab start
    return removed


def cleanup(lab: Path) -> bool:
    """Remove every recording, record and report for this lab."""
    target = Path(lab) / _DIRECTORY
    if not target.exists():
        return False
    shutil.rmtree(target)
    return True


def load_run(run_dir: Path, protector) -> dict:
    def read(name):
        return protector.unseal((run_dir / name).read_bytes(), purpose=PURPOSE)

    sessions = [
        json.loads(read(path.name))
        for path in sorted(run_dir.glob("session-*.json.sealed"))
    ]
    audio = {}
    for session in sessions:
        for utterance in session["utterances"]:
            entry = utterance.get("audio")
            if entry and (run_dir / entry["file"]).exists():
                audio[utterance["id"]] = read(entry["file"])
    return {
        "run": json.loads(read("run.json.sealed")),
        "sessions": sessions,
        "audio": audio,
    }


def _cell(value) -> str:
    return html.escape("" if value is None else str(value))


def render_report(data: dict) -> str:
    rows = []
    totals = {"utterances": 0, "no_transcript": 0, "saved": 0, "withheld": 0}
    for session in data["sessions"]:
        for u in session["utterances"]:
            totals["utterances"] += 1
            finals = [
                a["text"] for a in u["asr"] if a["final"] and not a.get("duplicate")
            ]
            partials = [a["text"] for a in u["asr"] if not a["final"]]
            accepted = [
                a["text"] for a in u["accepted"] if not a.get("duplicate_event")
            ]
            prepared = [p for p in u["project"] if p["kind"] == "prepared"]
            saved = [
                p.get("saved_text") for p in prepared if p.get("saved_text") is not None
            ]
            flags = list(u["flags"])
            if not accepted:
                totals["no_transcript"] += 1
            if saved:
                totals["saved"] += 1
            if accepted and finals and finals[-1].strip() != accepted[-1]:
                flags.append("final_recognition_differs_from_accepted")
            if accepted and prepared and saved and saved[-1] != accepted[-1]:
                flags.append("SAVED_TEXT_DIFFERS")
            if any(a.get("duplicate") for a in u["asr"]):
                flags.append("duplicate_recognition_event")
            if any(a.get("duplicate_event") for a in u["accepted"] + u["assistant"]):
                flags.append("duplicate_turn_event")
            for p in prepared:
                if p.get("action") in {"created", "switched"}:
                    flags.append(f"project_{p['action']}: {p.get('project')}")
            withheld = [r for r in u["responses"] if r["kind"] == "response_withheld"]
            totals["withheld"] += bool(withheld)
            audio = data["audio"].get(u["id"])
            player = (
                '<audio controls src="data:audio/wav;base64,'
                + base64.b64encode(audio).decode()
                + '"></audio>'
                if audio
                else "<em>no audio kept</em>"
            )
            routing = "<br>".join(
                _cell(
                    f"{p.get('status')} · {p.get('action') or ''} · {p.get('project') or ''}"
                    + (f" (from {p['previous']})" if p.get("previous") else "")
                    + (f" · refs {p['references']}" if p.get("references") else "")
                    + (f" · “{p['announcement']}”" if p.get("announcement") else "")
                    + (f" · question “{p['question']}”" if p.get("question") else "")
                    + (f" · {p['reason']}" if p.get("reason") else "")
                )
                for p in prepared
            )
            receipts = "<br>".join(
                _cell(
                    f"event {p['receipt']['event_id'][:8]} seq {p['receipt']['sequence']} "
                    f"rev {p['receipt']['revision']} {p['receipt']['status']}"
                )
                for p in prepared
                if p.get("receipt")
            )
            other = "<br>".join(
                _cell(
                    f"{p['kind']}: "
                    + ", ".join(
                        f"{k}={v}" for k, v in p.items() if k not in {"kind", "at"}
                    )
                )
                for p in u["project"]
                if p["kind"] != "prepared"
            )
            replies = "<br>".join(
                _cell(("[interrupted] " if a["interrupted"] else "") + a["text"])
                for a in u["assistant"]
            )
            responses = ", ".join(
                "withheld" if r["kind"] == "response_withheld" else "played"
                for r in u["responses"]
            )
            rows.append(
                "<tr>"
                f"<td>{_cell(u['id'])}<br><small>{_cell(u['speech_started_at'])}</small></td>"
                f"<td>{player}<br><small>{_cell((u.get('audio') or {}).get('seconds'))} s</small></td>"
                f"<td><small>{_cell(' … '.join(partials[-3:]))}</small><br>{_cell(finals[-1] if finals else '')}</td>"
                f"<td>{_cell(accepted[-1] if accepted else '— none —')}</td>"
                f"<td>{routing}{('<br><small>' + other + '</small>') if other else ''}</td>"
                f"<td>{_cell(saved[-1] if saved else '')}<br><small>{receipts}</small></td>"
                f"<td>{replies}<br><small>{_cell(responses)}</small></td>"
                f"<td>{_cell(', '.join(t['name'] for t in u['tools']))}<br>"
                f"<small>{_cell(u['latency_ms'])} ms</small></td>"
                f"<td>{'<br>'.join(_cell(f) for f in flags)}"
                f"{'<br>'.join(_cell(e['error']) for e in u['errors'])}</td>"
                "</tr>"
            )
    unmatched = sum(len(s["unmatched"]) for s in data["sessions"])
    run = data["run"]
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Jarvis voice diagnostics {_cell(run["run_id"])}</title>
<style>body{{font:14px system-ui;margin:16px}}table{{border-collapse:collapse;width:100%}}
td,th{{border:1px solid #ccc;padding:6px;vertical-align:top}}th{{background:#f3f3f3}}
.note{{background:#fff7d6;padding:8px;border:1px solid #e6d27a}}</style></head><body>
<h1>Voice diagnostics — run {_cell(run["run_id"])}</h1>
<p class="note"><b>Recognition is not ground truth.</b> “Recognised” and “Accepted” columns are
Gemini's speech recognition, not what you said. Play the audio to compare. The audio is
what Jarvis forwarded to Gemini after the wake word, plus a short pre-roll.
This file is a plaintext copy of encrypted lab diagnostics; it is deleted at the next lab
start, or with <code>-CleanupDiagnostics</code>.</p>
<p>Utterances detected: {totals["utterances"]} · without accepted transcript: {totals["no_transcript"]} · saved to project memory: {totals["saved"]} · with a withheld answer: {totals["withheld"]} · unmatched events: {unmatched}</p>
<table><tr><th>Utterance</th><th>Audio</th><th>Recognised (partials … final)</th>
<th>Accepted transcript</th><th>Routing / project</th><th>Saved text (read back) / receipt</th>
<th>Jarvis reply</th><th>Tools / latency</th><th>Flags</th></tr>
{"".join(rows)}</table></body></html>"""


def write_report(lab: Path, protector, run_id: str | None = None) -> Path:
    runs_dir = Path(lab) / _DIRECTORY / "runs"
    runs = (
        sorted(p for p in runs_dir.iterdir() if p.is_dir()) if runs_dir.is_dir() else []
    )
    if run_id is not None:
        runs = [p for p in runs if p.name == run_id]
    if not runs:
        raise FileNotFoundError("no voice diagnostics run in this lab")
    run_dir = runs[-1]
    path = run_dir / _REPORT
    path.write_text(render_report(load_run(run_dir, protector)), encoding="utf-8")
    return path


def main() -> None:
    import argparse
    import os

    parser = argparse.ArgumentParser(description="Voice lab diagnostics report/cleanup")
    parser.add_argument("action", choices=("report", "cleanup"))
    parser.add_argument("--lab-root", type=Path, required=True)
    parser.add_argument("--run")
    args = parser.parse_args()
    lab = args.lab_root.resolve(strict=True)
    if not (lab / "project-memory.marker").is_file():
        parser.error("not an isolated project-memory lab profile")
    if args.action == "cleanup":
        print("Removed." if cleanup(lab) else "Nothing to remove.")
        return
    if os.name != "nt":
        parser.error("reports need Windows DPAPI")
    from jarvis.security.dpapi import WindowsDpapiKeyProtector

    print(write_report(lab, WindowsDpapiKeyProtector(), args.run))


if __name__ == "__main__":
    main()
