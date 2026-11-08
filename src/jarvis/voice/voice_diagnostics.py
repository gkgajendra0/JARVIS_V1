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
_ACCEPTANCE = "acceptance.json"
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
        group_gap_seconds: float = 1.2,
        max_run_audio_bytes: int = 150_000_000,
        max_utterances: int = 300,
        retention_days: float = 7.0,
        keep_runs: int = 5,
    ) -> None:
        self.root = Path(lab) / _DIRECTORY
        self._protector = protector
        self.max_utterance_seconds = max_utterance_seconds
        self.pre_roll_seconds = pre_roll_seconds
        self.group_gap_seconds = group_gap_seconds
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
        self._runtime_events: list[dict] = []
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
        session.on("speech_created", diag.on_speech_created)
        session.on("error", diag.on_error)
        bridge.add_accepted_turn_observer(diag.observe_turn)
        bridge.add_close_observer(diag.close)

    def audio_tap(self, bridge):
        """session_audio_tap: frames forwarded to Gemini for this session."""
        diag = self._sessions.get(id(bridge.conversation))
        return None if diag is None else diag.observe_frame

    def runtime_event(self, kind: str, **fields) -> None:
        """Runtime-level event outside any wake session (e.g. Hello renewal)."""
        self._runtime_events.append(
            {"at": _now(), "kind": kind, "session_count": self._session_count, **fields}
        )
        # Rare events: written in order, synchronously, so the newest list wins.
        try:
            self._write_now("runtime-events.json", list(self._runtime_events))
        except OSError:
            LOGGER.warning("Voice diagnostics runtime event write failed")

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
        self._gap_started: float | None = None
        self._gap_timer = None
        self._agent_speaking = False
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
    #
    # LiveKit's local VAD ends a segment after a short silence (~0.55 s), while
    # Gemini ends a user turn only after 800 ms. One spoken request therefore
    # often arrives as two VAD segments but one transcript. Segments that start
    # within GROUP_GAP of the previous one, with no Jarvis reply in between,
    # form one utterance: its audio is recorded continuously across the pause
    # (plus a short tail), and a transcript matches any of its activity epochs.

    def on_user_state(self, event) -> None:
        if self._closed:
            return
        now = time.monotonic()
        if event.new_state == "speaking":
            current = self._current
            if (
                current is not None
                and self._gap_started is not None
                # Exclusive: Windows' monotonic clock ticks every ~15.6 ms, so
                # two quick events can share a timestamp; gap 0 must never group.
                and now - self._gap_started < self._owner.group_gap_seconds
            ):
                self._cancel_gap_timer()
                self._gap_started = None
                self._open_segment(current, now)
                return
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
                "epochs": [],
                "segments": [],
                "speech_seconds": 0.0,
                "overlapped_reply": self._agent_speaking,
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
            self._chunks = [chunk for chunk, _ in self._pre_roll]
            self._chunk_seconds = self._pre_roll_seconds
            self._open_segment(self._current, now)
        elif event.new_state == "listening" and event.old_state == "speaking":
            current = self._current
            if current is None or not current["segments"]:
                return
            segment = current["segments"][-1]
            if segment.get("ended_at") is None:
                segment["ended_at"] = _now()
                current["speech_seconds"] = round(
                    current["speech_seconds"] + now - segment["_t0"], 2
                )
            current["speech_ended_at"] = segment["ended_at"]
            self._speech_ended = now
            self._gap_started = now
            self._schedule_gap_close()

    def _open_segment(self, utterance, now) -> None:
        segment = {"started_at": _now(), "ended_at": None, "_t0": now}
        utterance["segments"].append(segment)
        if self._agent_speaking:
            utterance["overlapped_reply"] = True
        # The runtime's own speech-start handler advances the activity epoch;
        # read it once that handler has run (same event-loop turn).

        def assign():
            epoch = self._conversation.user_activity_epoch
            segment["epoch"] = epoch
            if epoch not in utterance["epochs"]:
                utterance["epochs"].append(epoch)

        try:
            asyncio.get_running_loop().call_soon(assign)
        except RuntimeError:
            assign()

    def _schedule_gap_close(self) -> None:
        self._cancel_gap_timer()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        current = self._current

        def close_if_still_open():
            self._gap_timer = None
            if self._current is current and self._gap_started is not None:
                self._finish_utterance()

        self._gap_timer = loop.call_later(
            self._owner.group_gap_seconds, close_if_still_open
        )

    def _cancel_gap_timer(self) -> None:
        if self._gap_timer is not None:
            self._gap_timer.cancel()
            self._gap_timer = None

    def _finish_utterance(self) -> None:
        current = self._current
        self._cancel_gap_timer()
        self._gap_started = None
        if current is None:
            return
        self._current = None
        for segment in current["segments"]:
            segment.pop("_t0", None)
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
                    "covers_segments": len(current["segments"]),
                }
            else:
                current["flags"].append("audio_not_kept_run_limit")
        self._chunks = []
        self._chunk_seconds = 0.0
        self._pre_roll.clear()
        self._pre_roll_seconds = 0.0

    def _utterance_for_epoch(self, epoch):
        for utterance in reversed(self.utterances):
            if epoch in utterance["epochs"]:
                return utterance
        current = self._current
        if current is not None and not current["epochs"]:
            return current  # epoch not assigned yet (same event-loop turn)
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
        if target is None:
            self._unmatched("recognition_without_utterance", entry)
        else:
            target["asr"].append(entry)

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
                self._unmatched("accepted_without_speech", entry)
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
            epoch = self._conversation.user_activity_epoch
            target = self._utterance_for_epoch(epoch)
            if target is None:
                # Epoch 0: Jarvis spoke before any owner speech in this session
                # (wake acknowledgement / proactive prompt), so there is no
                # utterance it could answer.
                self._unmatched(
                    "assistant_before_any_owner_speech"
                    if epoch == 0
                    else "assistant_reply_without_utterance",
                    entry,
                )
            else:
                target["assistant"].append(entry)

    # -- responses ------------------------------------------------------------

    def on_agent_state(self, event) -> None:
        self._agent_speaking = event.new_state == "speaking"
        if event.new_state != "speaking":
            return
        if self._current is not None and self._gap_started is not None:
            # Jarvis is answering: the utterance before it is complete.
            self._finish_utterance()
        target = self._utterance_for_epoch(self._conversation.user_activity_epoch)
        if target is not None and target["latency_ms"] is None and self._speech_ended:
            target["latency_ms"] = round((time.monotonic() - self._speech_ended) * 1000)

    def on_speech_created(self, event) -> None:
        """Every response LiveKit schedules, including Gemini's automatic tool
        follow-up (user_initiated=False), so a reply that never played shows."""
        entry = {
            "at": _now(),
            "kind": "speech_created",
            "source": str(getattr(event, "source", "")),
            "user_initiated": bool(getattr(event, "user_initiated", False)),
        }
        target = self._utterance_for_epoch(self._conversation.user_activity_epoch)
        if target is None:
            self._unmatched("speech_without_utterance", entry)
        else:
            target["responses"].append(entry)

    def on_tools(self, event) -> None:
        target = self._utterance_for_epoch(self._conversation.user_activity_epoch)
        outputs = tuple(getattr(event, "function_call_outputs", ()) or ())
        for index, call in enumerate(getattr(event, "function_calls", ()) or ()):
            entry = {"at": _now(), "name": getattr(call, "name", "unknown")}
            output = outputs[index] if index < len(outputs) else None
            if output is not None:
                # Outcome only: an error flag and the tool's own status word.
                entry["is_error"] = bool(getattr(output, "is_error", False))
                raw = getattr(output, "output", None)
                status = _tool_status(raw)
                if status is not None:
                    entry["status"] = status
                ok = _tool_ok(raw)
                if ok is not None:
                    entry["ok"] = ok  # the tool's own success flag
                verified = _tool_verified(raw)
                if verified is not None:
                    entry["verified"] = verified  # observed postcondition
            if target is None:
                self._unmatched("tool_without_utterance", entry)
            else:
                target["tools"].append(entry)

    def on_error(self, event) -> None:
        error = getattr(event, "error", None)
        entry = {
            "at": _now(),
            "error": getattr(error, "label", type(error).__name__),
            "recoverable": bool(getattr(error, "recoverable", False)),
        }
        target = self._latest()
        if target is None:
            self._unmatched("error_without_utterance", entry)
        else:
            target["errors"].append(entry)

    def project_event(self, kind: str, fields: dict) -> None:
        epoch = fields.pop("epoch", self._conversation.user_activity_epoch)
        target = self._utterance_for_epoch(epoch)
        entry = {"at": _now(), "kind": kind, **fields}
        if kind in {"response_withheld", "response_played"}:
            bucket = "responses"
        else:
            bucket = "project"
        if target is None:
            self._unmatched(
                "project_event_before_any_owner_speech"
                if epoch == 0
                else "project_event_without_utterance",
                entry,
            )
        else:
            target[bucket].append(entry)

    def _unmatched(self, kind: str, entry: dict) -> None:
        """Keep an event no utterance can own, with a reason (never dropped)."""
        self.unmatched.append(
            {
                "unmatched_kind": kind,
                "session": self.number,
                "epoch": self._conversation.user_activity_epoch,
                **entry,
            }
        )

    # -- close ----------------------------------------------------------------

    def close(self) -> None:
        if self._closed:
            return
        self._finish_utterance()
        self._closed = True
        for utterance in self.utterances:
            if not utterance["accepted"]:
                utterance["flags"].append("no_accepted_transcript")
                utterance["unmatched_reason"] = classify_unmatched(utterance)
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


def _tool_payload(output):
    """The tool's returned mapping. LiveKit passes ``str(dict)`` (a Python
    literal), not JSON, so both are parsed; never evaluated as code."""
    if isinstance(output, dict):
        return output
    if not isinstance(output, str) or not output.lstrip().startswith("{"):
        return None
    try:
        parsed = json.loads(output)
    except ValueError:
        import ast

        try:
            parsed = ast.literal_eval(output)
        except (ValueError, SyntaxError, MemoryError, RecursionError):
            return None
    return parsed if isinstance(parsed, dict) else None


def _tool_status(output):
    payload = _tool_payload(output)
    if payload is None:
        return None
    value = payload.get("status", payload.get("ok"))
    return value if isinstance(value, str | bool) else None


def _tool_ok(output):
    payload = _tool_payload(output)
    value = None if payload is None else payload.get("ok")
    return value if isinstance(value, bool) else None


def _tool_verified(output):
    """Hands' observed postcondition (``final_observation.verified``)."""
    payload = _tool_payload(output)
    observation = None if payload is None else payload.get("final_observation")
    value = observation.get("verified") if isinstance(observation, dict) else None
    return value if isinstance(value, bool) else None


def classify_unmatched(utterance) -> str:
    """Why speech has no accepted transcript. Evidence only, never "dropped"."""
    if any(not a.get("duplicate") for a in utterance["asr"]):
        return "recognised_but_not_accepted"
    if utterance.get("overlapped_reply"):
        return "during_jarvis_reply_echo_or_barge_in"
    if utterance.get("speech_seconds", 0) < 0.4:
        return "very_short_segment"
    return "no_recognition_listen_to_audio"


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
            for name in (_REPORT, _ACCEPTANCE):
                report = run / name
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
    events = (
        json.loads(read("runtime-events.json.sealed"))
        if (run_dir / "runtime-events.json.sealed").exists()
        else []
    )
    return {
        "run": json.loads(read("run.json.sealed")),
        "sessions": sessions,
        "audio": audio,
        "runtime_events": events,
    }


_CHANGES = {"created", "switched", "new_thread"}
_STOP = frozenset(
    [
        "the",
        "a",
        "an",
        "and",
        "or",
        "but",
        "to",
        "of",
        "in",
        "on",
        "at",
        "for",
        "with",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "we",
        "i",
        "you",
        "it",
        "this",
        "that",
        "my",
        "your",
        "our",
        "me",
        "us",
        "will",
        "can",
        "do",
        "does",
        "did",
        "have",
        "has",
        "had",
        "not",
        "no",
        "yes",
        "okay",
        "ok",
        "so",
        "then",
        "now",
        "what",
        "which",
        "who",
        "how",
        "when",
        "where",
        "why",
        "please",
        "just",
    ]
)
_BENIGN_UNMATCHED = frozenset(
    {
        "assistant_before_any_owner_speech",
        "project_event_before_any_owner_speech",
        "speech_without_utterance",  # e.g. the wake acknowledgement
    }
)


def _content_words(text) -> set[str]:
    import re

    return {
        w
        for w in re.findall(r"[^\W\d_]+", (text or "").casefold())
        if len(w) > 2 and w not in _STOP
    }


def _named_words(text) -> set[str]:
    """Capitalised words that are not sentence-initial (names like 'Jimny')."""
    import re

    names = set()
    for sentence in re.split(r"(?<=[.!?])\s+", text or ""):
        for word in re.findall(r"[^\W\d_][\w'’-]*", sentence)[1:]:
            if word[0].isupper() and word.casefold() not in _STOP and len(word) > 2:
                names.add(word.casefold())
    return names


def _ms_between(start, end):
    if not start or not end:
        return None
    try:
        delta = datetime.fromisoformat(end) - datetime.fromisoformat(start)
    except ValueError:
        return None
    return round(delta.total_seconds() * 1000)


def _latency(u) -> dict:
    """Where the time went, relative to the end of the owner's speech."""
    base = u.get("speech_ended_at")
    project = u["project"]

    def first(items, kind=None):
        for item in items:
            if kind is None or item.get("kind") == kind:
                return item.get("at")
        return None

    finals = [a for a in u["asr"] if a["final"]]
    stages = {
        "first_recognition": first(u["asr"]),
        "final_recognition": first(finals),
        "transcript_accepted": first(u["accepted"]),
        "fast_path_decided": first(project, "fast_path"),
        "tool_called": first(project, "tool_called"),
        "turn_saved": first(project, "prepared"),
        "context_delivered": first(project, "delivered_to_model"),
        "first_answer_withheld": first(u["responses"], "response_withheld"),
        "repair_requested": first(project, "repair_requested"),
        "fallback": first(project, "fallback"),
        "answer_released": first(u["responses"], "response_played"),
        "reply_committed": first(u["assistant"]),
    }
    breakdown = {k: _ms_between(base, v) for k, v in stages.items() if v}
    breakdown["first_audio_ms"] = u.get("latency_ms")
    prepared = next((p for p in project if p.get("kind") == "prepared"), None)
    if prepared is not None:
        breakdown["save_prepare_ms"] = prepared.get("prepare_ms")
    return breakdown


def _words(name) -> set[str]:
    from jarvis.memory.project_routing import normalize_name

    return set(normalize_name(name or "").split())


def assess(data: dict) -> dict:
    """Machine-readable PASS / FAIL / REVIEW for one diagnostics run.

    FAIL: a deterministic contradiction (misrouting, an unexpected project
    change, a false success claim, a save mismatch, an unrecovered withheld
    answer). REVIEW: needs a human with the audio (speech without transcript,
    recovered gate, fallback, clarification, duplicates, an interruption test
    that did not happen). Recognised text is never treated as what was said.
    """
    from jarvis.memory.project_routing import (
        embedded_project_command,
        parse_project_command,
    )
    from jarvis.voice.project_claims import false_project_claims

    results = []
    known_words: set[str] = set()  # what the owner said or Jarvis was given
    interrupted_seen = False
    interruption_followed = False
    previous_interrupted = False
    for session in data["sessions"]:
        # What the session preload gave the model (before any owner speech).
        for event in session["unmatched"]:
            if event.get("kind") == "context_preloaded":
                for row in event.get("history", ()):
                    known_words |= _content_words(row.get("text"))
        for u in session["utterances"]:
            fail, review, info = [], [], []
            accepted = [
                a["text"] for a in u["accepted"] if not a.get("duplicate_event")
            ]
            prepared = [p for p in u["project"] if p["kind"] == "prepared"]
            kinds = [p["kind"] for p in u["project"]]
            responses = [r["kind"] for r in u["responses"]]
            if previous_interrupted and accepted:
                interruption_followed = "response_played" in responses or bool(
                    u["assistant"]
                )
            previous_interrupted = False
            if not accepted:
                review.append(
                    "unmatched_speech:" + (u.get("unmatched_reason") or "unknown")
                )
            text = accepted[-1] if accepted else ""
            name, command_kind = parse_project_command(text) if text else (None, None)
            if command_kind == "select_if_known":
                name = None  # "go to sleep": a command only if it names a project
            last = prepared[-1] if prepared else None
            action = last.get("action") if last else None
            if accepted and last is None:
                fail.append("accepted_turn_not_prepared")
            if last is not None:
                status = last.get("status")
                if status == "failed":
                    fail.append("save_failed")
                elif status == "not_saved":
                    review.append("not_saved:" + str(last.get("reason")))
                elif status == "clarification":
                    review.append("clarification_asked")
                if status == "ready":
                    saved = last.get("saved_text")
                    if last.get("read_back_error"):
                        fail.append("save_read_back_failed")
                    elif saved != text:
                        fail.append("save_mismatch")
                    # A command must land in the project it names (exact or
                    # the one similar name routing accepted), never elsewhere.
                    target = _words(last.get("project"))
                    if name is not None and not (
                        _words(name) <= target or target <= _words(name)
                    ):
                        fail.append("command_misrouted")
                    if name is None and action in _CHANGES:
                        # The only change an ordinary turn may make: opening the
                        # default General workspace when NO project is active
                        # (fresh lab, or after the active one was forgotten).
                        bootstrap = (
                            "previous_selection" in last
                            and last["previous_selection"] is None
                            and _words(last.get("project")) == {"general"}
                            and action in {"created", "switched"}
                        )
                        if bootstrap:
                            info.append("default_workspace_opened")
                        else:
                            fail.append("unexpected_project_change")
                    if last.get("ambiguous_references"):
                        review.append("ambiguous_project_reference")
                    if name is None and embedded_project_command(text)[0]:
                        review.append("embedded_project_command")
            for reply in u["assistant"]:
                if false_project_claims(
                    reply["text"],
                    action if last and last.get("status") == "ready" else None,
                ):
                    fail.append("false_project_claim")
                if reply.get("interrupted"):
                    interrupted_seen = True
                    previous_interrupted = True
            if "correction_spoken" in kinds:
                review.append("correction_spoken")
            if "response_withheld" in responses:
                if (
                    "response_played"
                    not in responses[responses.index("response_withheld") :]
                ):
                    fail.append("withheld_answer_not_recovered")
                elif "fallback" in kinds:
                    review.append("context_gate_fallback")
                else:
                    review.append("context_gate_recovered")
            if any(a.get("duplicate") for a in u["asr"]) or any(
                a.get("duplicate_event") for a in u["accepted"] + u["assistant"]
            ):
                review.append("duplicate_events")
            if accepted and u["asr"]:
                finals = [a["text"] for a in u["asr"] if a["final"]]
                if finals and finals[-1].strip() != text:
                    review.append("recognition_differs_from_accepted")
            if len(accepted) > 1:
                review.append("several_transcripts_for_one_utterance")
            # -- capture: was what the owner SAID kept? (persistence != capture)
            capture = []
            saved_words = (
                set().union(*(_content_words(t) for t in accepted))
                if accepted
                else set()
            )
            first_accept = u["accepted"][0]["at"] if u["accepted"] else None
            late = set()
            for asr in u["asr"]:
                if (
                    first_accept
                    and asr["at"] > first_accept
                    and not asr.get("duplicate")
                ):
                    late |= _content_words(asr["text"]) - saved_words
            if late:
                # Gemini finalises the transcript when it calls a tool; words
                # recognised afterwards were heard but are not in the saved turn.
                fail.append("recognised_words_not_saved:" + ",".join(sorted(late)))
                capture.append("late_recognition")
            seconds = u.get("speech_seconds") or 0
            if accepted and seconds >= 1.5 and len(text.split()) / seconds < 1.2:
                review.append("transcript_may_be_incomplete")
                capture.append("few_words_for_speech_duration")
            if "fast_path" in kinds and "tool_called" not in kinds:
                info.append("answered_from_preloaded_context")
            if "late_routing" in kinds:
                # Recognition looked ordinary when the answer started; the final
                # transcript needed routing (announced / re-preloaded / review).
                review.append("late_project_routing")
            delivered = [
                p
                for p in u["project"]
                if p["kind"] in {"delivered_to_model", "context_preloaded"}
            ]
            for item in delivered:
                for row in item.get("history", ()):
                    known_words |= _content_words(row.get("text"))
                    known_words |= _content_words(row.get("from_project"))
            known_words |= saved_words
            for p in prepared:
                known_words |= _content_words(p.get("project"))
                known_words |= _content_words(p.get("previous"))
            unsupported = set()
            for reply in u["assistant"]:
                unsupported |= _named_words(reply["text"]) - known_words
            if unsupported:
                # The model knew something the saved record does not contain:
                # it heard the audio itself (see late_recognition), or invented it.
                review.append(
                    "reply_uses_unsaved_names:" + ",".join(sorted(unsupported))
                )
                capture.append("reply_beyond_saved_record")
            verdict = "FAIL" if fail else "REVIEW" if review else "PASS"
            results.append(
                {
                    "id": u["id"],
                    "verdict": verdict,
                    "fail": sorted(set(fail)),
                    "review": sorted(set(review)),
                    "info": sorted(set(info)),
                    "accepted_transcript": text or None,
                    "action": action,
                    "project": last.get("project") if last else None,
                    "segments": len(u.get("segments", ())),
                    "capture": "anomaly" if capture else "not_verified_listen_to_audio",
                    "capture_signals": capture,
                    "latency_ms": _latency(u),
                }
            )
    run_review = []
    not_tested = []
    if not interrupted_seen:
        not_tested.append("interruption")
        run_review.append("interruption_not_exercised")
    elif not interruption_followed:
        run_review.append("interruption_not_followed_by_answer")
    uncorrelated = [
        {
            "kind": e.get("unmatched_kind", e.get("kind", "unknown")),
            "session": e.get("session"),
            "epoch": e.get("epoch"),
            "at": e.get("at"),
            "event": e.get("kind") if "unmatched_kind" in e else None,
            "benign": e.get("unmatched_kind") in _BENIGN_UNMATCHED,
        }
        for s in data["sessions"]
        for e in s["unmatched"]
    ]
    unexplained = [e for e in uncorrelated if not e["benign"]]
    if unexplained:
        run_review.append(f"uncorrelated_events:{len(unexplained)}")
    stages = {}
    for r in results:
        for stage, value in r["latency_ms"].items():
            if isinstance(value, int | float):
                stages.setdefault(stage, []).append(value)
    latency_summary = {
        stage: {
            "median": sorted(v)[len(v) // 2],
            "max": max(v),
            "count": len(v),
        }
        for stage, v in stages.items()
    }
    counts = {
        v: sum(r["verdict"] == v for r in results) for v in ("PASS", "FAIL", "REVIEW")
    }
    overall = (
        "FAIL"
        if counts["FAIL"]
        else "REVIEW"
        if counts["REVIEW"] or run_review
        else "PASS"
    )
    return {
        "schema": "jarvis-voice-acceptance-v1",
        "run_id": data["run"]["run_id"],
        "verdict": overall,
        "counts": counts,
        "speech_segments": sum(r["segments"] for r in results),
        "utterances": len(results),
        "accepted_turns": sum(r["accepted_transcript"] is not None for r in results),
        "run_review": run_review,
        "not_tested": not_tested,
        "uncorrelated_events": uncorrelated,
        "capture_anomalies": sum(r["capture"] == "anomaly" for r in results),
        "capture_verified_automatically": False,
        "latency_summary_ms": latency_summary,
        "results": results,
        "note": (
            "PASS means the pipeline was internally consistent: routing, saving and "
            "replies agree with each other. It does NOT verify that the saved text "
            "is what the owner said; recognition accuracy is measured only by "
            "listening to the audio. Recognised text is Gemini speech recognition, "
            "not ground truth."
        ),
    }


def _cell(value) -> str:
    return html.escape("" if value is None else str(value))


def render_report(data: dict, verdicts: dict | None = None) -> str:
    verdicts = verdicts or assess(data)
    by_id = {r["id"]: r for r in verdicts["results"]}
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
                {
                    "response_withheld": "withheld",
                    "response_played": "played",
                }.get(r["kind"], "scheduled")
                for r in u["responses"]
            )
            if u.get("unmatched_reason"):
                flags.append("reason: " + u["unmatched_reason"])
            if len(u.get("segments", ())) > 1:
                flags.append(f"{len(u['segments'])} speech segments, one utterance")
            verdict = by_id.get(
                u["id"], {"verdict": "", "fail": [], "review": [], "latency_ms": {}}
            )
            timeline = ", ".join(
                f"{k} {v}" for k, v in verdict["latency_ms"].items() if v is not None
            )
            rows.append(
                "<tr>"
                f"<td><b class='{verdict['verdict']}'>{_cell(verdict['verdict'])}</b><br>"
                f"<small>{_cell(' '.join(verdict['fail'] + verdict['review']))}</small></td>"
                f"<td>{_cell(u['id'])}<br><small>{_cell(u['speech_started_at'])}</small></td>"
                f"<td>{player}<br><small>{_cell((u.get('audio') or {}).get('seconds'))} s</small></td>"
                f"<td><small>{_cell(' … '.join(partials[-3:]))}</small><br>{_cell(finals[-1] if finals else '')}</td>"
                f"<td>{_cell(accepted[-1] if accepted else '— none —')}</td>"
                f"<td>{routing}{('<br><small>' + other + '</small>') if other else ''}</td>"
                f"<td>{_cell(saved[-1] if saved else '')}<br><small>{receipts}</small></td>"
                f"<td>{replies}<br><small>{_cell(responses)}</small></td>"
                f"<td>{_cell(', '.join(t['name'] for t in u['tools']))}<br>"
                f"<small>{_cell(u['latency_ms'])} ms<br>{_cell(timeline)}</small></td>"
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
.note{{background:#fff7d6;padding:8px;border:1px solid #e6d27a}}
.FAIL{{color:#b00020}}.REVIEW{{color:#a15c00}}.PASS{{color:#1b6e20}}</style></head><body>
<h1>Voice diagnostics — run {_cell(run["run_id"])}</h1>
<p class="note"><b>Recognition is not ground truth.</b> “Recognised” and “Accepted” columns are
Gemini's speech recognition, not what you said. Play the audio to compare. The audio is
what Jarvis forwarded to Gemini after the wake word, plus a short pre-roll.
This file is a plaintext copy of encrypted lab diagnostics; it is deleted at the next lab
start, or with <code>-CleanupDiagnostics</code>.</p>
<p>Utterances detected: {totals["utterances"]} · without accepted transcript: {totals["no_transcript"]} · saved to project memory: {totals["saved"]} · with a withheld answer: {totals["withheld"]} · unmatched events: {unmatched}</p>
<p><b>Acceptance: <span class="{verdicts["verdict"]}">{verdicts["verdict"]}</span></b> ·
PASS {verdicts["counts"]["PASS"]} · REVIEW {verdicts["counts"]["REVIEW"]} · FAIL
{verdicts["counts"]["FAIL"]} · speech segments {verdicts["speech_segments"]} in
{verdicts["utterances"]} utterances · run checks: {_cell(", ".join(verdicts["run_review"]) or "none")}.
Machine-readable: <code>acceptance.json</code> next to this file.</p>
<p class="note"><b>PASS ≠ heard correctly.</b> PASS means routing, saving and replies are
consistent with each other. It does not verify that the saved text is what you said: listen to
each row. Capture anomalies: {verdicts["capture_anomalies"]}.
<b>Not tested in this run:</b> {_cell(", ".join(verdicts["not_tested"]) or "nothing")}.
Uncorrelated events: {_cell("; ".join(f"{e['kind']} (session {e['session']}, {e['at']})" for e in verdicts["uncorrelated_events"]) or "none")}.</p>
<table><tr><th>Verdict</th><th>Utterance</th><th>Audio</th><th>Recognised (partials … final)</th>
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
    data = load_run(run_dir, protector)
    verdicts = assess(data)
    (run_dir / _ACCEPTANCE).write_text(
        json.dumps(verdicts, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    path = run_dir / _REPORT
    path.write_text(render_report(data, verdicts), encoding="utf-8")
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
