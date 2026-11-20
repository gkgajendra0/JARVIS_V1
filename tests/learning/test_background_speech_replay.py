"""Background speech accepted as the owner's words (R2-D), replayed offline.

These tests pin what the installed build (f7e64c7f) does with the recorded
sequences. They pass today; a fix is expected to turn each "currently" test
into its opposite.

Recorded evidence (production logs, read-only):
- 2026-11-08 07:22:43-07:24:44 UTC (Diagnostics/retest-20261108T071624Z):
  wake, owner "Which hotel are we staying at?", reply ends 07:22:51.140, then
  98 s of TV audio. Voice-activity bursts re-armed the 15 s follow-up timer
  every time (gaps 13.0, 5.0, 7.7, 10.7, 11.3 s ...), so the wake never closed.
  Three TV lines were accepted as owner turns, saved to Nepal trip history and
  queued for personal learning; Jarvis answered two. Enrolled-speaker shadow
  scores 0.3634, 0.3770, 0.2370 (owner turns that run: 0.61-0.76), logged
  with authority_effect=False.
- 2026-11-17 07:02-07:16 UTC (live log): ten TV/video lines saved the same way
  over 14 minutes during the voice stall later fixed by #323.
"""

import asyncio
from collections import defaultdict
from types import SimpleNamespace

import pytest
import test_project_voice as project_voice_tests
from test_project_voice import Wake, settle
from test_runtime import conversation as learning_conversation
from test_runtime import runtime as learning_runtime

from jarvis.config import JarvisConfig
from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.learning_contracts import LearningBatch
from jarvis.memory.live_context import LiveContext
from jarvis.voice.canonical_active_speaker_runtime import (
    CanonicalActiveSpeakerRuntimeController,
)
from jarvis.voice.livekit_session import LiveKitConversationBridge

lab = project_voice_tests.lab  # shared real-archive fixture


class _FakeSession:  # as tests/test_long_utterance_activity.py
    def __init__(self):
        self.handlers = defaultdict(list)

    def on(self, event, callback):
        self.handlers[event].append(callback)
        return callback

    def emit(self, event, value):
        for callback in tuple(self.handlers[event]):
            callback(value)


class _FakeAudio:
    pass


def _session_pair():
    session = _FakeSession()
    bridge = LiveKitConversationBridge(
        session,
        ConversationSession(),
        LiveContext(max_recent_turns=8),
        show_transcript=False,
    )
    return session, bridge


def _mark_session_ready(session):
    session.emit(
        "agent_state_changed",
        SimpleNamespace(old_state="initializing", new_state="listening"),
    )


TV_LINES = (
    "somehow swallow him whole.",
    (
        "Elsword, two of the segments most likely to stop this menace have been "
        "knocked unconscious."
    ),
    "Guadalupita",
)

# 2026-11-08, seconds after 07:22:00 UTC. ("agent"/"user", old, new) or
# ("transcript", text). Wake at 43.966; owner turn 47.299.
RECORDED_0722 = [
    (44.966, "agent", "initializing", "listening"),
    (45.028, "user", "listening", "speaking"),
    (46.107, "user", "speaking", "listening"),
    (47.299, "transcript", "Which hotel are we staying at?"),
    (47.385, "agent", "listening", "thinking"),
    (48.109, "agent", "thinking", "speaking"),
    (51.140, "agent", "speaking", "listening"),  # last reply ends
    (51.646, "user", "listening", "speaking"),
    (51.966, "user", "speaking", "listening"),
    (64.986, "user", "listening", "speaking"),
    (66.747, "user", "speaking", "listening"),
    (67.547, "user", "listening", "speaking"),
    (68.666, "user", "speaking", "listening"),
    (69.406, "user", "listening", "speaking"),
    (71.927, "user", "speaking", "listening"),
    (76.956, "user", "listening", "speaking"),
    (77.277, "user", "speaking", "listening"),
    (84.956, "user", "listening", "speaking"),
    (85.755, "user", "speaking", "listening"),
    (96.446, "user", "listening", "speaking"),
    (97.726, "user", "speaking", "listening"),
    (101.496, "user", "listening", "speaking"),
    (102.106, "user", "speaking", "listening"),
    (107.545, "user", "listening", "speaking"),
    (109.976, "user", "speaking", "listening"),
    (111.069, "user", "listening", "speaking"),
    (115.447, "user", "speaking", "listening"),
    (126.716, "user", "listening", "speaking"),
    (138.616, "user", "speaking", "listening"),
    (139.167, "user", "listening", "speaking"),
    (142.486, "user", "speaking", "listening"),
    (143.547, "user", "listening", "speaking"),
    (143.898, "user", "speaking", "listening"),
    (144.318, "user", "listening", "speaking"),
    (145.018, "user", "speaking", "listening"),
    (145.496, "user", "listening", "speaking"),
    (149.499, "transcript", TV_LINES[0]),
]
LAST_REPLY_END = 51.140
FIRST_TV_TURN = 149.499


async def replay_window(monkeypatch, events):
    """Replay recorded state changes against the real controller with a
    virtual clock; return the time the inactivity timer ended the wake, or
    None if it stayed open through the whole recording."""
    config = JarvisConfig()  # production defaults: 8 s initial, 15 s follow-up
    session, bridge = _session_pair()
    runtime = CanonicalActiveSpeakerRuntimeController(
        config, _FakeAudio(), session_factory=lambda _: (session, bridge)
    )
    runtime._active_end = asyncio.Event()
    runtime._session_factory(config)
    bridge.conversation.start()
    now = [events[0][0]]
    timers = []

    def call_later(delay, callback):
        handle = SimpleNamespace(due=now[0] + delay, callback=callback, cancelled=False)
        handle.cancel = lambda: setattr(handle, "cancelled", True)
        timers.append(handle)
        return handle

    with monkeypatch.context() as patch:
        patch.setattr(asyncio.get_running_loop(), "call_later", call_later)
        ended = None
        for at, kind, *rest in events:
            for handle in sorted(timers, key=lambda h: h.due):
                if not handle.cancelled and handle.due <= at and ended is None:
                    now[0] = handle.due
                    handle.cancelled = True
                    handle.callback()
                    if runtime._active_end.is_set():
                        ended = handle.due
            if ended is not None:
                break
            now[0] = at
            if kind == "agent":
                if rest == ["initializing", "listening"]:
                    _mark_session_ready(session)
                else:
                    session.emit(
                        "agent_state_changed",
                        SimpleNamespace(old_state=rest[0], new_state=rest[1]),
                    )
            elif kind == "user":
                session.emit(
                    "user_state_changed",
                    SimpleNamespace(old_state=rest[0], new_state=rest[1]),
                )
            else:
                bridge.conversation.accept_turn(ConversationRole.USER, rest[0])
        runtime._cancel_timeout()
    return ended, config


@pytest.mark.asyncio
async def test_currently_tv_voice_activity_keeps_the_wake_open(monkeypatch):
    ended, config = await replay_window(monkeypatch, RECORDED_0722)
    # Installed behavior: every burst cancels the timer and every pause re-arms
    # the full follow-up timeout, so the wake is still open when the first TV
    # line is transcribed 98 s after the last reply.
    assert ended is None
    # A window measured from the last reply would have closed long before.
    assert LAST_REPLY_END + config.follow_up_timeout_seconds < FIRST_TV_TURN


@pytest.mark.asyncio
async def test_without_tv_audio_the_same_wake_closes_after_the_follow_up_window(
    monkeypatch,
):
    quiet = [e for e in RECORDED_0722 if e[0] <= LAST_REPLY_END]
    quiet.append((FIRST_TV_TURN, "transcript", TV_LINES[0]))
    ended, config = await replay_window(monkeypatch, quiet)
    assert ended == pytest.approx(LAST_REPLY_END + config.follow_up_timeout_seconds)


@pytest.mark.asyncio
async def test_currently_a_final_transcript_is_an_owner_turn_for_every_observer():
    session, bridge = _session_pair()
    bridge.conversation.start()
    seen = {"project": [], "personal": [], "learning": []}
    for observed in seen.values():
        bridge.add_accepted_turn_observer(observed.append)
    for text in TV_LINES:
        session.emit(
            "user_input_transcribed",
            SimpleNamespace(transcript=text, is_final=True, item_id=None),
        )
    # No speaker evidence is consulted: each line becomes a USER turn and is
    # handed to project history, personal context and learning at once.
    for observed in seen.values():
        assert [t.text for t in observed] == list(TV_LINES)
        assert all(t.role is ConversationRole.USER for t in observed)


@pytest.mark.asyncio
async def test_currently_tv_lines_are_saved_to_project_history(lab):
    voice = await lab.runtime()
    wake = Wake(voice)
    await wake.ask("create project called Nepal trip", "Created project Nepal trip.")
    await wake.ask("Which hotel are we staying at?", "I don't have that.")
    for line in TV_LINES:
        wake.speech()
        wake.transcript(line)
        await settle(voice)
    owner_rows = [text for role, text, *_ in lab.rows() if role == "user"]
    assert owner_rows[-3:] == list(TV_LINES)
    wake.close()


class RecordingExtractor:
    def __init__(self):
        self.sources = []

    async def extract(self, source):
        self.sources.append(source.text)
        return LearningBatch()


@pytest.mark.asyncio
async def test_currently_tv_lines_are_sent_to_personal_learning(learning):
    extractor = RecordingExtractor()
    r = learning_runtime(learning, extractor)
    c = learning_conversation()
    observe = r.bind(c, learning.grant)
    try:
        observe(c.accept_turn(ConversationRole.USER, "Which hotel are we staying at?"))
        for line in TV_LINES:
            observe(c.accept_turn(ConversationRole.USER, line))
        await r.drain()
        # Every TV line reached the extractor as an owner statement; nothing
        # was learned only because the lines held no facts.
        assert extractor.sources[-3:] == list(TV_LINES)
    finally:
        await r.close()
