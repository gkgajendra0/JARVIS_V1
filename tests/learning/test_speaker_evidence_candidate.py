"""Speaker-evidence and bounded follow-up candidates (R2-D), offline.

Both candidates are off by default (JarvisConfig.speaker_evidence_enforcement,
JarvisConfig.follow_up_window_bounded). These tests cover:
- linking the enrolled-speaker score to the exact accepted transcript;
- owner / non_owner / unknown status, never "owner" without a score;
- with enforcement on, project history and personal learning keep out only
  later turns with positive non-owner evidence; opening and unknown turns,
  commands and follow-ups behave as before;
- the bounded window on the recorded 2026-11-08 timeline and at its edges.
"""

import asyncio
from types import SimpleNamespace

import numpy as np
import pytest
import test_project_voice as project_voice_tests
from test_background_speech_replay import (
    RECORDED_0722,
    TV_LINES,
    RecordingExtractor,
    _FakeAudio,
    _mark_session_ready,
    _session_pair,
)
from test_project_voice import Wake, settle
from test_runtime import conversation as learning_conversation
from test_runtime import runtime as learning_runtime

from jarvis.config import JarvisConfig
from jarvis.conversation import ConversationRole
from jarvis.identity.speaker_shadow import SpeakerShadowScore
from jarvis.identity.speaker_turn import SpeakerTurnAudio
from jarvis.voice import canonical_active_speaker_runtime as canonical
from jarvis.voice.canonical_active_speaker_runtime import (
    FOLLOW_UP_TRANSCRIPT_GRACE,
    CanonicalActiveSpeakerRuntimeController,
)
from jarvis.voice.runtime import canonical_user_turn_id
from jarvis.voice.speaker_turn_evidence import (
    SpeakerTurnEvidenceBook,
    SpeakerTurnStatus,
)

lab = project_voice_tests.lab

# Recorded enrolled-speaker scores (2026-11-08 07:22-07:24 UTC).
OWNER_QUESTION = ("Which hotel are we staying at?", 0.6637)
TV_SCORES = (0.3634, 0.3770, 0.2370)
OWNER_FOLLOW_UP = ("We will take the Jimny.", 0.7216)
SHORT_COMMAND = "Go back to sleep, Jarvis."  # too short to score (recorded)


def accept(conversation, book, text):
    turn = conversation.accept_turn(ConversationRole.USER, text)
    book.observe_turn(turn)
    return turn


# --- status ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_comes_only_from_evidence_and_unknown_is_never_owner():
    book = SpeakerTurnEvidenceBook(threshold=0.45, enforce=True, follow_up=False)
    c = learning_conversation()
    opening = accept(c, book, OWNER_QUESTION[0])
    tv = accept(c, book, TV_LINES[0])
    short = accept(c, book, SHORT_COMMAND)
    follow = accept(c, book, OWNER_FOLLOW_UP[0])
    book.resolve(opening.turn_id, score=None, reason="speaker_quality_rejected")
    book.resolve(tv.turn_id, score=TV_SCORES[0], reason="scored")
    book.resolve(short.turn_id, score=None, reason="speaker_quality_rejected")
    book.resolve(follow.turn_id, score=OWNER_FOLLOW_UP[1], reason="scored")
    got = {t.text: await book.wait(t.turn_id) for t in (opening, tv, short, follow)}
    # The opening turn is not verified owner speech without a score.
    assert got[OWNER_QUESTION[0]].status is SpeakerTurnStatus.UNKNOWN
    assert got[OWNER_QUESTION[0]].opening
    assert got[TV_LINES[0]].status is SpeakerTurnStatus.NON_OWNER
    assert got[SHORT_COMMAND].status is SpeakerTurnStatus.UNKNOWN
    assert got[OWNER_FOLLOW_UP[0]].status is SpeakerTurnStatus.OWNER
    # Only positive non-owner evidence on a later turn is withheld.
    assert [book.withholds(e) for e in got.values()] == [False, True, False, False]


@pytest.mark.asyncio
async def test_opening_turn_is_never_withheld_and_follow_up_sessions_have_none():
    book = SpeakerTurnEvidenceBook(threshold=0.45, enforce=True, follow_up=False)
    c = learning_conversation()
    opening = accept(c, book, "for me now. Put my father in quarantine.")
    book.resolve(opening.turn_id, score=0.3398, reason="scored")  # recorded
    evidence = await book.wait(opening.turn_id)
    assert evidence.status is SpeakerTurnStatus.NON_OWNER and evidence.opening
    assert not book.withholds(evidence)
    follow = SpeakerTurnEvidenceBook(threshold=0.45, enforce=True, follow_up=True)
    turn = accept(learning_conversation(), follow, TV_LINES[1])
    follow.resolve(turn.turn_id, score=TV_SCORES[1], reason="scored")
    assert follow.withholds(await follow.wait(turn.turn_id))


@pytest.mark.asyncio
async def test_missing_evidence_times_out_as_unknown_and_enforcement_off_never_withholds():
    book = SpeakerTurnEvidenceBook(
        threshold=0.45, enforce=True, follow_up=True, wait_seconds=0.01
    )
    turn = accept(learning_conversation(), book, TV_LINES[2])
    evidence = await book.wait(turn.turn_id)
    assert evidence.status is SpeakerTurnStatus.UNKNOWN
    assert evidence.reason == "evidence_timeout"
    off = SpeakerTurnEvidenceBook(threshold=0.45, enforce=False, follow_up=True)
    turn = accept(learning_conversation(), off, TV_LINES[2])
    off.resolve(turn.turn_id, score=TV_SCORES[2], reason="scored")
    assert not off.withholds(await off.wait(turn.turn_id))


# --- linking --------------------------------------------------------------


def test_the_gemini_item_is_linked_to_its_own_transcript_turn():
    c = learning_conversation()
    first = c.accept_turn(ConversationRole.USER, "Which hotel?", external_item_id="a")
    c.accept_turn(ConversationRole.ASSISTANT, "I don't know.")
    second = c.accept_turn(ConversationRole.USER, TV_LINES[0])
    item = SimpleNamespace(id="a", text_content="Which hotel?")
    assert canonical_user_turn_id(c, item) == first.turn_id
    item = SimpleNamespace(id="b", text_content=f" {TV_LINES[0]} ")
    assert canonical_user_turn_id(c, item) == second.turn_id
    assert canonical_user_turn_id(c, SimpleNamespace(id=None, text_content="x")) is None


def _speech(seconds=3.0):
    rate = 16000
    t = np.arange(int(seconds * rate)) / rate
    return SpeakerTurnAudio(
        samples=(3000 * np.sin(2 * np.pi * 220 * t)).astype(np.int16),
        sample_rate=rate,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("quality", "score", "status", "reason"),
    [
        (True, 0.3634, SpeakerTurnStatus.NON_OWNER, "scored"),
        (True, 0.7216, SpeakerTurnStatus.OWNER, "scored"),
        (False, None, SpeakerTurnStatus.UNKNOWN, "speaker_quality_rejected"),
    ],
)
async def test_the_shadow_score_resolves_the_linked_turn(
    monkeypatch, quality, score, status, reason
):
    observer = SimpleNamespace(
        score=lambda samples, sample_rate: SpeakerShadowScore(
            "scored", score, 1.0, ("speaker_shadow_score_observed_no_threshold",)
        )
    )
    session, bridge = _session_pair()
    runtime = CanonicalActiveSpeakerRuntimeController(
        JarvisConfig(),
        _FakeAudio(),
        session_factory=lambda _: (session, bridge),
        speaker_shadow_observer=observer,
    )
    runtime._session_factory(JarvisConfig())
    book = runtime._speaker_evidence
    assert book is not None and not book.enforcing  # off by default
    bridge.conversation.start()
    turn = bridge.conversation.accept_turn(ConversationRole.USER, TV_LINES[0])
    bridge._notify_accepted_turn(turn)
    monkeypatch.setattr(
        canonical,
        "assess_speaker_segment",
        lambda samples, sample_rate: SimpleNamespace(
            accepted=quality, rms_dbfs=-20.0, reason_codes=()
        ),
    )

    async def no_active_speaker(*args, **kwargs):
        return None

    monkeypatch.setattr(runtime, "_inspect_active_speaker_turn", no_active_speaker)
    runtime._speech_region_detector = None
    await runtime._inspect_shadow_turn(
        _speech(), audio_turn_id="audio-1", conversation_turn_id=turn.turn_id
    )
    evidence = await book.wait(turn.turn_id)
    assert (evidence.status, evidence.score, evidence.reason) == (
        status,
        score,
        reason,
    )


# --- project history ------------------------------------------------------


async def recorded_wake(lab, *, enforce):
    voice = await lab.runtime()
    setup = Wake(voice)
    await setup.ask("create project called Nepal trip", "Created project Nepal trip.")
    setup.close()
    wake = Wake(voice)
    book = SpeakerTurnEvidenceBook(threshold=0.45, enforce=enforce, follow_up=False)
    wake.turns.bind_speaker_evidence(book)
    observed = []

    async def say(text, score, reply=None):
        wake.speech()
        turn = wake.transcript(text)
        observed.append(turn)
        book.observe_turn(turn)
        await asyncio.sleep(0)
        book.resolve(turn.turn_id, score=score, reason="scored" if score else "short")
        if reply is not None:
            wake.reply(reply)
        await settle(voice)

    return voice, wake, book, say


@pytest.mark.asyncio
async def test_enforced_history_keeps_out_scored_tv_lines_and_their_replies(lab):
    voice, wake, _book, say = await recorded_wake(lab, enforce=True)
    await say(*OWNER_QUESTION, reply="I don't have that.")
    await say(TV_LINES[0], TV_SCORES[0])
    await say(TV_LINES[1], TV_SCORES[1], reply="The situation appears critical.")
    await say(TV_LINES[2], TV_SCORES[2], reply="I cannot determine that.")
    await say(OWNER_FOLLOW_UP[0], OWNER_FOLLOW_UP[1])
    await say(SHORT_COMMAND, None)
    texts = [text for _, text, *_ in lab.rows()]
    assert OWNER_QUESTION[0] in texts and OWNER_FOLLOW_UP[0] in texts
    assert SHORT_COMMAND in texts  # unscorable command: kept
    assert not set(TV_LINES) & set(texts)
    assert "The situation appears critical." not in texts
    assert voice.metrics.speaker_not_owner == 3
    wake.close()


@pytest.mark.asyncio
async def test_with_enforcement_off_history_is_unchanged(lab):
    voice, wake, _book, say = await recorded_wake(lab, enforce=False)
    await say(*OWNER_QUESTION, reply="I don't have that.")
    for line, score in zip(TV_LINES, TV_SCORES, strict=True):
        await say(line, score)
    texts = [text for _, text, *_ in lab.rows()]
    assert set(TV_LINES) <= set(texts)  # observed only, as installed today
    assert voice.metrics.speaker_not_owner == 0
    wake.close()


# --- personal learning ----------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("enforce", [True, False])
async def test_learning_never_sees_withheld_tv_lines_even_as_context(learning, enforce):
    extractor = RecordingExtractor()
    contexts = []
    original = extractor.extract

    async def extract(source):
        contexts.append([t.text for t in source.turns])
        return await original(source)

    extractor.extract = extract
    r = learning_runtime(learning, extractor)
    c = learning_conversation()
    book = SpeakerTurnEvidenceBook(threshold=0.45, enforce=enforce, follow_up=False)
    observe = r.bind(c, learning.grant, speaker_evidence=book)
    try:
        sequence = [
            OWNER_QUESTION,
            *zip(TV_LINES, TV_SCORES, strict=True),
            ("We are taking the Creta.", 0.7451),
        ]
        for text, score in sequence:
            turn = accept(c, book, text)
            observe(turn)
            await asyncio.sleep(0)
            book.resolve(turn.turn_id, score=score, reason="scored")
        await r.drain()
        seen = {text for context in contexts for text in context}
        if enforce:
            assert extractor.sources == [OWNER_QUESTION[0], "We are taking the Creta."]
            assert not set(TV_LINES) & seen  # not even as earlier context
            assert r.status().reason != "source_denied"
        else:
            assert set(TV_LINES) <= set(extractor.sources)
    finally:
        await r.close()


@pytest.mark.asyncio
async def test_learning_admits_only_owner_scored_speech_and_records_why(learning):
    """Owner decision 2026-11-27: with enforcement, automatic learning saves
    only from speech positively scored as the owner. An unscored (unknown)
    turn, even the opening one, is not learned from, and memory_status sees
    why instead of a save."""
    from jarvis.memory.memory_receipts import MemoryReceipts

    extractor = RecordingExtractor()
    r = learning_runtime(learning, extractor)
    r.receipts = MemoryReceipts()
    c = learning_conversation()
    book = SpeakerTurnEvidenceBook(threshold=0.45, enforce=True, follow_up=False)
    observe = r.bind(c, learning.grant, speaker_evidence=book)
    try:
        unknown_opening = accept(c, book, "I bought a red Honda City.")
        observe(unknown_opening)
        await asyncio.sleep(0)
        assert r.receipts.pending(c.session_id, unknown_opening.turn_id)
        book.resolve(unknown_opening.turn_id, score=None, reason="too_short")
        owner = accept(c, book, OWNER_FOLLOW_UP[0])
        observe(owner)
        await asyncio.sleep(0)
        book.resolve(owner.turn_id, score=OWNER_FOLLOW_UP[1], reason="scored")
        await r.drain()
        for _ in range(5):
            await asyncio.sleep(0)
        assert extractor.sources == [OWNER_FOLLOW_UP[0]]
        (entry,) = r.receipts.view(c.session_id, [unknown_opening.turn_id])["turns"]
        assert entry["status"] == "nothing_saved"
        assert not r.receipts.pending(c.session_id, unknown_opening.turn_id)
    finally:
        await r.close()


def test_project_history_keeps_the_331_rule_learning_is_stricter():
    from jarvis.voice.speaker_turn_evidence import SpeakerTurnEvidence

    book = SpeakerTurnEvidenceBook(threshold=0.45, enforce=True, follow_up=False)
    unknown = SpeakerTurnEvidence("t", SpeakerTurnStatus.UNKNOWN, None, "short", False)
    owner = SpeakerTurnEvidence("t", SpeakerTurnStatus.OWNER, 0.7, "scored", True)
    assert not book.withholds(unknown)  # history: only non-owner kept out
    assert not book.admits_learning(unknown)
    assert book.admits_learning(owner)
    off = SpeakerTurnEvidenceBook(threshold=0.45, enforce=False, follow_up=False)
    assert off.admits_learning(unknown)


# --- bounded follow-up window --------------------------------------------


async def run_window(monkeypatch, events, *, bounded, enforce=False, verdicts=None):
    """Recorded/constructed events against the real controller on a virtual
    clock. Returns (ended_at, runtime)."""
    config = JarvisConfig(
        follow_up_window_bounded=bounded, speaker_evidence_enforcement=enforce
    )
    observer = SimpleNamespace(score=lambda *a, **k: None) if enforce else None
    session, bridge = _session_pair()
    runtime = CanonicalActiveSpeakerRuntimeController(
        config,
        _FakeAudio(),
        session_factory=lambda _: (session, bridge),
        speaker_shadow_observer=observer,
    )
    runtime._active_end = asyncio.Event()
    loop = asyncio.get_running_loop()
    now = [events[0][0]]
    timers = []

    def call_later(delay, callback, *args):
        handle = SimpleNamespace(
            due=now[0] + delay, callback=callback, args=args, cancelled=False
        )
        handle.cancel = lambda: setattr(handle, "cancelled", True)
        timers.append(handle)
        return handle

    def call_soon(callback, *args):
        return call_later(0.0, callback, *args)

    ended = None
    with monkeypatch.context() as patch:
        patch.setattr(loop, "call_later", call_later)
        patch.setattr(loop, "call_soon", call_soon)
        patch.setattr(loop, "time", lambda: now[0])
        runtime._session_factory(config)
        bridge.conversation.start()
        for at, kind, *rest in [*events, (events[-1][0] + 60, "end")]:
            for handle in sorted(timers, key=lambda h: h.due):
                if handle.cancelled or handle.due > at or ended is not None:
                    continue
                now[0] = max(now[0], handle.due)
                handle.cancelled = True
                handle.callback(*handle.args)
                if runtime._active_end.is_set():
                    ended = handle.due
            if ended is not None or kind == "end":
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
            else:  # transcript: accepted, then the runtime cancels its timer
                turn = bridge.conversation.accept_turn(ConversationRole.USER, rest[0])
                bridge._notify_accepted_turn(turn)
                runtime._cancel_timeout()
                if verdicts and rest[0] in verdicts and runtime._speaker_evidence:
                    runtime._speaker_evidence.resolve(
                        turn.turn_id, score=verdicts[rest[0]], reason="scored"
                    )
        runtime._cancel_timeout()
    return ended, runtime


@pytest.mark.asyncio
async def test_bounded_window_closes_the_recorded_tv_wake_after_fifteen_seconds(
    monkeypatch,
):
    ended, _ = await run_window(monkeypatch, RECORDED_0722, bounded=True)
    # A TV burst began at 07:23:04.986, inside the window, and ended at
    # 06.747: held, then the transcript grace. Later bursts began after the
    # deadline and do not hold the wake: it closes at 07:23:09.25, 80 s before
    # the first TV line was transcribed.
    assert ended == pytest.approx(66.747 + FOLLOW_UP_TRANSCRIPT_GRACE)
    assert ended < RECORDED_0722[-1][0]


@pytest.mark.asyncio
async def test_default_window_is_unchanged_on_the_recorded_timeline(monkeypatch):
    ended, _ = await run_window(monkeypatch, RECORDED_0722, bounded=False)
    assert ended is None


def reply_then(*after):
    """Owner question answered at t=10.0; window opens at reply end (t=13)."""
    return [
        (0.0, "agent", "initializing", "listening"),
        (1.0, "user", "listening", "speaking"),
        (3.0, "user", "speaking", "listening"),
        (4.0, "transcript", "Which hotel are we staying at?"),
        (4.1, "agent", "listening", "thinking"),
        (5.0, "agent", "thinking", "speaking"),
        (13.0, "agent", "speaking", "listening"),
        *after,
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("bounded", [True, False])
async def test_owner_speech_starting_just_before_the_deadline_is_answered(
    monkeypatch, bounded
):
    # Recorded 2026-11-17 17:43: speech began 0.39 s before the window closed.
    events = reply_then(
        (27.61, "user", "listening", "speaking"),
        (28.41, "user", "speaking", "listening"),
        (29.28, "transcript", "Go back to sleep."),
        (29.4, "agent", "listening", "thinking"),
        (30.0, "agent", "thinking", "speaking"),
        (31.0, "agent", "speaking", "listening"),
    )
    ended, runtime = await run_window(monkeypatch, events, bounded=bounded)
    assert ended == pytest.approx(31.0 + 15.0)  # a fresh window after the reply
    assert runtime._last_user_in_window


@pytest.mark.asyncio
async def test_speech_starting_after_the_deadline_does_not_hold_the_wake(monkeypatch):
    events = reply_then(
        (20.0, "user", "listening", "speaking"),  # background burst in window
        (21.0, "user", "speaking", "listening"),
        (28.1, "user", "listening", "speaking"),  # 0.1 s after the deadline
        (40.0, "user", "speaking", "listening"),
    )
    ended, _ = await run_window(monkeypatch, events, bounded=True)
    assert ended == pytest.approx(28.0)
    ended, _ = await run_window(monkeypatch, events, bounded=False)
    assert ended == pytest.approx(40.0 + 15.0)  # installed: re-armed and held


@pytest.mark.asyncio
async def test_long_speech_begun_inside_the_window_is_held_to_its_end(monkeypatch):
    events = reply_then(
        (24.0, "user", "listening", "speaking"),
        (36.0, "user", "speaking", "listening"),  # 12 s, past the deadline
    )
    ended, _ = await run_window(monkeypatch, events, bounded=True)
    # No transcript arrived: the wake closes after the transcript grace.
    assert ended == pytest.approx(36.0 + FOLLOW_UP_TRANSCRIPT_GRACE)
    with_transcript = [
        *events,
        (37.0, "transcript", "Help me pack for the trip."),
        (37.1, "agent", "listening", "thinking"),
        (38.0, "agent", "thinking", "speaking"),
        (41.0, "agent", "speaking", "listening"),
    ]
    ended, _ = await run_window(monkeypatch, with_transcript, bounded=True)
    assert ended == pytest.approx(41.0 + 15.0)


@pytest.mark.asyncio
async def test_a_reply_to_speech_begun_after_the_deadline_does_not_reopen(
    monkeypatch,
):
    events = reply_then(
        (27.9, "agent", "listening", "thinking"),  # Gemini answers late TV audio
        (28.5, "transcript", TV_LINES[1]),
        (29.0, "agent", "thinking", "speaking"),
        (32.0, "agent", "speaking", "listening"),
    )
    ended, runtime = await run_window(monkeypatch, events, bounded=True)
    assert ended == pytest.approx(32.0)  # ends right after that reply
    assert not runtime._last_user_in_window
    assert not runtime._follow_up_earned(runtime.config)


@pytest.mark.asyncio
async def test_with_enforcement_a_reply_to_withheld_speech_does_not_reopen(
    monkeypatch,
):
    events = reply_then(
        (20.0, "user", "listening", "speaking"),
        (24.0, "user", "speaking", "listening"),
        (25.0, "transcript", TV_LINES[0]),
        (25.1, "agent", "listening", "thinking"),
        (26.0, "agent", "thinking", "speaking"),
        (27.0, "agent", "speaking", "listening"),
    )
    verdicts = {"Which hotel are we staying at?": 0.6637, TV_LINES[0]: TV_SCORES[0]}
    ended, runtime = await run_window(
        monkeypatch, events, bounded=True, enforce=True, verdicts=verdicts
    )
    assert ended == pytest.approx(28.0)  # the original window, not a new one
    assert not runtime._follow_up_earned(runtime.config)
    # The owner's in-window follow-up does reopen it.
    verdicts[TV_LINES[0]] = 0.7216
    ended, runtime = await run_window(
        monkeypatch, events, bounded=True, enforce=True, verdicts=verdicts
    )
    assert ended == pytest.approx(27.0 + 15.0)
    assert runtime._follow_up_earned(runtime.config)


# --- configuration --------------------------------------------------------


def test_candidates_are_off_by_default_and_configurable(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_MACHINE_CONFIG", str(tmp_path / "absent.json"))
    for name in (
        "JARVIS_FOLLOW_UP_WINDOW_BOUNDED",
        "JARVIS_SPEAKER_EVIDENCE_ENFORCEMENT",
        "JARVIS_SPEAKER_OWNER_MIN_COSINE",
    ):
        monkeypatch.delenv(name, raising=False)
    config = JarvisConfig.from_environment()
    assert not config.follow_up_window_bounded
    assert not config.speaker_evidence_enforcement
    assert config.speaker_owner_min_cosine == 0.45
    monkeypatch.setenv("JARVIS_FOLLOW_UP_WINDOW_BOUNDED", "true")
    monkeypatch.setenv("JARVIS_SPEAKER_EVIDENCE_ENFORCEMENT", "true")
    monkeypatch.setenv("JARVIS_SPEAKER_OWNER_MIN_COSINE", "0.5")
    config = JarvisConfig.from_environment()
    assert config.follow_up_window_bounded and config.speaker_evidence_enforcement
    assert config.speaker_owner_min_cosine == 0.5
    with pytest.raises(ValueError, match="speaker_owner_min_cosine"):
        JarvisConfig(speaker_owner_min_cosine=1.2)
