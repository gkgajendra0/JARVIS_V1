"""Voice forgetting, long-term recall and Windows Hello renewal.

Real archive, FTS5 index, provenance edges and history authority; fake Windows
session/Hello (``authority_parts``) and fake Gemini session.

P1  "Forget that ..." removes every saved row mentioning the owner's words (any
    live project), the Jarvis replies generated with them, and the request
    itself, after a fresh Hello approval. Unrelated history is kept, nothing
    resurfaces after a restart, and the index no longer holds the words.
P2  Older facts beyond the preload/packet windows are found with a bounded,
    authorized FTS5 search; newer owner corrections come last (current).
P3  After a Windows lock/unlock, the next wake asks for a fresh grant and starts
    at once; its turns wait (bounded) for the approval, so a command spoken
    while Hello is open is saved once and answered. The revoked grant is never
    reused; a denial or timeout leaves ordinary voice, said once, saving
    nothing.
"""

import asyncio
import sqlite3
from types import SimpleNamespace

import pytest
import test_project_voice as project_voice_tests
from test_project_voice import Wake, settle
from test_project_voice_fast_path import FastWake, nepal

from jarvis.memory import project_controls
from jarvis.voice import project_voice
from jarvis.voice.project_voice import (
    FORGET_HISTORY_NUDGE,
    SEARCH_MAX_CHARS,
    SEARCHES_PER_UTTERANCE,
)

lab = project_voice_tests.lab  # shared real-archive fixture


def texts(lab):
    return [r[1] for r in lab.rows()]


def index_hits(lab, word):
    with sqlite3.connect(lab.db) as c:
        return c.execute(
            "SELECT count(*) FROM conversation_event_fts WHERE "
            "conversation_event_fts MATCH ?",
            (f'"{word}"',),
        ).fetchone()[0]


async def ask_to_forget(wake, utterance, words):
    wake.speech()
    wake.partial(utterance)
    wake.transcript(utterance)
    return await wake.turns.forget_history(words)


# -- P1: reliable forgetting --------------------------------------------------


@pytest.mark.asyncio
async def test_forget_removes_mentions_and_dependants_and_keeps_the_rest(
    lab, authority_parts
):
    voice = await nepal(lab)
    wake = FastWake(voice)
    retired = []
    wake.turns.bind_retire(lambda: retired.append(1))
    await wake.preload()
    approvals = len(authority_parts.hello.calls)
    result = await ask_to_forget(wake, "Forget that we will take the Jimny.", "Jimny")
    assert result["status"] == "forgotten", result
    # The Jimny turn and the forget request itself; the two replies made with
    # the Jimny turn in context ("Noted." and "Good.").
    assert (result["your_messages"], result["jarvis_replies"]) == (2, 2)
    assert len(authority_parts.hello.calls) == approvals + 1  # fresh Hello
    remaining = texts(lab)
    assert not any("Jimny" in t for t in remaining)
    assert {"create project called Nepal trip", "The permits are sorted."} <= set(
        remaining
    )
    assert "Created project Nepal trip." in remaining  # made before the Jimny turn
    # The confirmation is never saved, and the wake session ends after it.
    wake.response()
    wake.reply("Okay, that's forgotten.")
    await settle(voice)
    assert "Okay, that's forgotten." not in texts(lab) and retired == [1]
    assert index_hits(lab, "Jimny") == 0  # gone from the search index too
    wake.close()
    await voice.aclose()

    # Restart: nothing resurfaces in the preload, search or a context packet.
    restarted = FastWake(await lab.runtime())
    await restarted.preload()
    assert "Jimny" not in "".join(restarted.agent.injected())
    restarted.speech()
    restarted.transcript("Which vehicle are we taking?")
    found = await restarted.turns.search_history("Jimny vehicle")
    assert "Jimny" not in str(found)
    packet = await restarted.turns.prepare()
    assert "Jimny" not in str(packet)


@pytest.mark.asyncio
async def test_forget_reaches_other_projects_but_only_matching_rows(lab):
    voice = await nepal(lab)
    wake = Wake(voice)
    await wake.ask("create project called garage", "Created.")
    await wake.ask("The Jimny needs new tyres.", "Noted.")
    await wake.ask("The bike needs oil.", "Okay.")
    wake.close()
    wake = FastWake(voice)
    await wake.preload()
    result = await ask_to_forget(
        wake, "Please forget everything about the Jimny", "Jimny"
    )
    assert result["status"] == "forgotten"
    assert sorted(result["projects"]) == ["Nepal trip", "garage"]
    remaining = texts(lab)
    assert not any("Jimny" in t for t in remaining)
    assert {"The permits are sorted.", "The bike needs oil."} <= set(remaining)


@pytest.mark.asyncio
async def test_a_denied_hello_deletes_nothing(lab, authority_parts):
    voice = await nepal(lab)
    wake = FastWake(voice)
    await wake.preload()
    authority_parts.hello.denied = True
    before = texts(lab)
    result = await ask_to_forget(wake, "Forget the Jimny.", "Jimny")
    assert result["status"] == "not_forgotten"
    after = texts(lab)
    assert after == [*before, "Forget the Jimny."]  # only the request was saved
    assert index_hits(lab, "Jimny") > 0


@pytest.mark.parametrize(
    ("utterance", "words", "reason"),
    [
        ("Forget that we will take the Jimny.", "Thar", "words_not_said"),
        ("Forget it.", "forget", "words_not_said"),
        ("We will take the Jimny.", "Jimny", "not_a_forget_request"),
    ],
)
@pytest.mark.asyncio
async def test_forget_needs_a_forget_request_and_the_owners_words(
    lab, utterance, words, reason
):
    voice = await nepal(lab)
    wake = FastWake(voice)
    await wake.preload()
    before = len(lab.rows())
    result = await ask_to_forget(wake, utterance, words)
    assert (result["status"], result["reason"]) == ("denied", reason)
    await settle(voice)
    assert len(lab.rows()) == before + 1  # the utterance itself, nothing removed


@pytest.mark.asyncio
async def test_too_broad_forget_deletes_nothing(lab, monkeypatch):
    monkeypatch.setattr(project_controls, "MAX_FORGET_ROWS", 1)
    voice = await nepal(lab)
    wake = FastWake(voice)
    await wake.preload()
    result = await ask_to_forget(wake, "Forget the Jimny.", "Jimny")
    assert result["status"] == "too_broad"
    assert any("Jimny" in t for t in texts(lab))


@pytest.mark.asyncio
async def test_a_request_naming_nothing_saved_forgets_only_itself(lab, authority_parts):
    voice = await nepal(lab)
    wake = FastWake(voice)
    await wake.preload()
    calls = len(authority_parts.hello.calls)
    result = await ask_to_forget(wake, "Forget the Gypsy.", "Gypsy")
    # The request itself mentions it, so it is found and forgotten alone.
    assert result["status"] == "forgotten"
    assert (result["your_messages"], result["jarvis_replies"]) == (1, 0)
    assert len(authority_parts.hello.calls) == calls + 1


@pytest.mark.asyncio
async def test_canonical_forget_is_followed_by_history_forget(lab):
    voice = await nepal(lab)
    wake = FastWake(voice)
    await wake.preload()
    wake.speech()
    wake.transcript("Forget that I own a Jimny.")
    # forget_memory (canonical) succeeded in this utterance...
    wake.turns.observe_tools_executed(
        SimpleNamespace(
            function_calls=[SimpleNamespace(name="forget_memory")],
            function_call_outputs=[SimpleNamespace(is_error=False)],
        )
    )
    wake.response()
    wake.reply("Done, I've forgotten that you own a Jimny.")
    await settle(voice)
    # ...its confirmation is not saved and history forgetting is requested.
    assert "Done, I've forgotten that you own a Jimny." not in texts(lab)
    assert wake.session.replies == [FORGET_HISTORY_NUDGE]
    result = await wake.turns.forget_history("Jimny")
    assert result["status"] == "forgotten"
    assert not any("Jimny" in t for t in texts(lab))


@pytest.mark.asyncio
async def test_failed_canonical_forget_requests_nothing(lab):
    voice = await nepal(lab)
    wake = FastWake(voice)
    await wake.preload()
    wake.speech()
    wake.transcript("Forget my diet.")
    wake.turns.observe_tools_executed(
        SimpleNamespace(
            function_calls=[SimpleNamespace(name="forget_memory")],
            function_call_outputs=[SimpleNamespace(is_error=True)],
        )
    )
    wake.response()
    wake.reply("I couldn't find that.")
    await settle(voice)
    assert wake.session.replies == []


def forget_attempts(wake, *errors):
    """forget_memory calls in this utterance, as Gemini made them live."""
    wake.turns.observe_tools_executed(
        SimpleNamespace(
            function_calls=[SimpleNamespace(name="forget_memory") for _ in errors],
            function_call_outputs=[SimpleNamespace(is_error=e) for e in errors],
        )
    )


@pytest.mark.asyncio
async def test_no_forget_confirmation_plays_before_both_systems_forgot(lab):
    """Live shape (8155df0d): two failed predicate guesses, then a committed
    canonical forget, then forget_saved_history. Gemini's "I have removed that"
    must not be heard while the saved conversation still holds the words."""
    voice = await nepal(lab)
    wake = FastWake(voice)
    await wake.preload()
    wake.speech()
    wake.transcript("Forget that we will take the Jimny.")
    forget_attempts(wake, True, True)  # 'car', 'suzuki_jimny': no such predicate
    forget_attempts(wake, False)  # the third attempt committed
    allowed, handle = wake.response()  # premature confirmation
    assert allowed is False and handle.interrupted
    assert wake.session.replies == [FORGET_HISTORY_NUDGE]  # asked exactly once
    allowed, _ = wake.response()
    assert allowed is False and wake.session.replies == [FORGET_HISTORY_NUDGE]
    result = await wake.turns.forget_history("Jimny")
    assert result["status"] == "forgotten"
    allowed, _ = wake.response()  # now the confirmation is true and may play
    assert allowed is True
    await settle(voice)
    assert not any("jimny" in t.casefold() for t in texts(lab))
    # Unrelated owner history (the permits) is kept.
    assert "The permits are sorted." in texts(lab)


@pytest.mark.asyncio
async def test_a_history_forget_that_never_follows_is_reported_honestly(
    lab, monkeypatch
):
    monkeypatch.setattr(project_voice, "FORGET_HISTORY_SECONDS", 0.05)
    voice = await nepal(lab)
    wake = FastWake(voice)
    await wake.preload()
    wake.speech()
    wake.transcript("Forget that we will take the Jimny.")
    forget_attempts(wake, False)
    assert wake.response()[0] is False
    await asyncio.sleep(0.15)  # Gemini never calls forget_saved_history
    assert wake.session.replies == [
        FORGET_HISTORY_NUDGE,
        project_voice.FORGET_INCOMPLETE_INSTRUCTIONS,
    ]
    assert wake.response()[0] is True  # the honest partial notice plays
    # Never replayed as a full-success confirmation through recovery either.
    turn = wake.reply("I have removed that from your memory.")
    assert wake.turns.allow_unplayed_reply(turn) is False


@pytest.mark.asyncio
async def test_forget_keeps_unrelated_owner_history_and_says_what_else_went(lab):
    """FIX3 check of the live receipt (owner_rows=2, jarvis_rows=13): owner
    rows are removed only if they contain the words; every Jarvis reply made
    with a removed row in its context is removed too (by design: it may
    paraphrase it), including replies about other topics, since the preload
    puts recent rows in every reply's context. Owner facts about the hotel or
    packing are never removed; the count is reported, not hidden."""
    voice = await nepal(lab)
    wake = FastWake(voice)
    await wake.preload()
    await wake.fast("Where is our hotel?", "I don't have the hotel saved.")
    wake.close()
    nxt = FastWake(voice)
    await nxt.preload()
    nxt.speech()
    nxt.transcript("Forget that we will take the Jimny.")
    result = await nxt.turns.forget_history("Jimny")
    await settle(voice)
    assert result["your_messages"] == 2  # the fact and this request
    assert result["jarvis_replies"] == 3  # replies made with it in context
    assert texts(lab) == [
        "create project called Nepal trip",
        "Created project Nepal trip.",
        "The permits are sorted.",
        "Where is our hotel?",
    ]


# -- P2: long-term recall -----------------------------------------------------


async def long_project(lab, clock, filler=30):
    """A project whose hotel decision is far older than the preload window."""
    voice = await lab.runtime()
    wake = Wake(voice)
    await wake.ask("create project called Nepal trip", "Created.")
    await wake.ask("Our hotel in Kathmandu is Yak and Yeti.", "Noted.")
    for number in range(filler):
        wake.speech()
        wake.transcript(f"Packing note {number}: socks and chargers.")
        if number % 5 == 4:
            await settle(voice)
            clock.advance(31)  # real time passes: read leases expire
    await settle(voice)
    wake.close()
    return voice


@pytest.mark.asyncio
async def test_search_finds_facts_older_than_the_preload(lab, clock):
    voice = await long_project(lab, clock)
    wake = FastWake(voice)
    await wake.preload()
    assert "Yak and Yeti" not in "".join(wake.agent.injected())
    wake.speech()
    wake.transcript("Which hotel did we book in Kathmandu?")
    found = await wake.turns.search_history("hotel Kathmandu")
    assert found["status"] in {"complete", "partial"}
    assert any("Yak and Yeti" in r["text"] for r in found["history"])
    assert sum(len(r["text"]) + 40 for r in found["history"]) <= SEARCH_MAX_CHARS
    # The hit is now evidence for the reply (forgetting it removes the reply).
    reply = await wake.fast("Which hotel did we book in Kathmandu?", "Yak and Yeti.")
    assert "Our hotel in Kathmandu is Yak and Yeti." in lab.evidence(reply.text)
    # Bounded: two searches per utterance.
    wake.speech()
    wake.transcript("And the address?")
    for _ in range(SEARCHES_PER_UTTERANCE):
        assert (await wake.turns.search_history("hotel"))["status"] != "denied"
    assert (await wake.turns.search_history("hotel"))["reason"] == (
        "search_budget_exhausted"
    )
    snapshot = voice.metrics.snapshot()
    assert snapshot["history_searches"] >= 2
    assert snapshot["search_ms"]["max"] < 500  # local FTS5 cost, generous for CI


@pytest.mark.asyncio
async def test_newer_correction_comes_last_and_is_marked_current(lab, clock):
    voice = await long_project(lab, clock, filler=10)
    wake = Wake(voice)
    await wake.ask("Correction: our hotel in Kathmandu is Dwarika's now.", "Noted.")
    wake.close()
    wake = FastWake(voice)
    wake.speech()
    wake.transcript("Which hotel?")
    found = await wake.turns.search_history("hotel Kathmandu")
    owner = [r["text"] for r in found["history"] if r["role"] == "owner"]
    assert owner.index("Our hotel in Kathmandu is Yak and Yeti.") < owner.index(
        "Correction: our hotel in Kathmandu is Dwarika's now."
    )
    assert "newest owner statement is current" in found["guidance"]


@pytest.mark.asyncio
async def test_search_widens_to_other_projects_with_labels(lab):
    voice = await nepal(lab)
    wake = Wake(voice)
    await wake.ask("create project called garage", "Created.")
    wake.close()
    wake = FastWake(voice)
    wake.speech()
    wake.transcript("What did we say about permits in the Nepal trip?")
    found = await wake.turns.search_history("permits")
    assert found["status"] == "other_projects"
    assert {r.get("from_project") for r in found["history"]} == {"Nepal trip"}


# -- P3: Windows Hello renewal ------------------------------------------------


@pytest.mark.asyncio
async def test_lock_unlock_renews_the_grant_at_the_next_wake(lab, authority_parts):
    voice = await nepal(lab)
    old = voice.access.grant
    issuer = voice.access.authority
    authority_parts.windows.lock_unlock()  # Windows lock + unlock
    # The wake starts at once with project memory pending a fresh approval.
    assert voice.available() is True
    assert voice.metrics.paused_sessions == 0
    await voice.drain()  # the owner approves Windows Hello
    assert voice.metrics.renewals == 1 and voice.access.grant != old
    assert issuer.validate(old).status != "active"  # never reused
    assert voice.available() is True
    wake = Wake(voice)
    await wake.ask("We will also take a stove.", "Noted.")
    assert "We will also take a stove." in texts(lab)


@pytest.mark.asyncio
async def test_denied_renewal_keeps_ordinary_voice_and_backs_off(
    lab, authority_parts, monkeypatch
):
    voice = await nepal(lab)
    authority_parts.windows.lock_unlock()
    authority_parts.hello.denied = True
    assert voice.available() is True  # pending: this wake waits, bounded
    await voice.drain()
    assert voice.metrics.renewal_failures == 1
    calls = len(authority_parts.hello.calls)
    assert voice.available() is False  # denied: ordinary voice
    assert voice.request_renewal() is False  # no prompt on every wake
    assert len(authority_parts.hello.calls) == calls
    # After the cooldown the owner is asked again, and approval restores it.
    authority_parts.hello.denied = False
    monkeypatch.setattr(project_voice, "monotonic", lambda: 10**9)
    assert voice.available() is True
    await voice.drain()
    assert voice.metrics.renewals == 1
    assert voice.available() is True


@pytest.mark.asyncio
async def test_renewal_after_shutdown_never_attaches(lab, authority_parts):
    voice = await nepal(lab)
    authority_parts.windows.lock_unlock()
    voice.available()
    await voice.aclose()  # drains the renewal; the new grant is revoked
    assert voice.available() is False
    await asyncio.sleep(0)


# -- D1/FIX5: the first wake after lock/unlock -------------------------------
#
# Live qualification at 8155df0d: the wake waited for Windows Hello BEFORE the
# realtime session started, so the owner's first command, spoken while the
# Hello prompt was open, was never captured (renewal succeeded, 0 user turns).
# Now the session starts at once; its turns wait (bounded) for the approval.


def slow_hello(voice):
    import threading

    release = threading.Event()
    real = voice._opener

    def opener():
        release.wait(10)
        return real()

    voice._opener = opener
    return release


def stove_rows(lab):
    return [r for r in lab.rows() if "stove" in r[1].casefold()]


@pytest.mark.asyncio
async def test_first_command_spoken_during_hello_is_saved_once_and_answered(
    lab, authority_parts
):
    voice = await nepal(lab)
    authority_parts.windows.lock_unlock()
    release = slow_hello(voice)
    assert await voice.prepare_wake() is None  # never blocks the wake
    assert voice.available() is True
    wake = Wake(voice)  # the session is live while Hello is still open
    wake.speech()
    wake.transcript("Add a stove to the packing list.")  # captured at once
    # Gemini calls prepare_project_turn: it waits for the fresh grant.
    prepared = asyncio.ensure_future(wake.turns.prepare())
    await asyncio.sleep(0.05)
    assert not prepared.done()  # held: nothing is saved without the grant
    assert stove_rows(lab) == []
    # The wake's inactivity timeout is held open meanwhile (bounded).
    assert (
        0 < wake.turns.approval_pending_seconds() <= project_voice.RENEWAL_WAIT_SECONDS
    )
    release.set()  # the owner approves Hello
    assert (await prepared)["status"] == "ready"
    assert wake.turns.approval_pending_seconds() == 0
    assert wake.response()[0] is True  # the answer plays
    wake.reply("Added a stove.")
    await settle(voice)
    assert stove_rows(lab) == [
        ("user", "Add a stove to the packing list.", "complete", "Nepal trip"),
        ("assistant", "Added a stove.", "complete", "Nepal trip"),
    ]
    assert voice.metrics.renewals == 1
    assert project_voice.PAUSED_NOTICE_INSTRUCTIONS not in wake.session.replies


@pytest.mark.asyncio
async def test_denied_hello_on_wake_saves_nothing_and_says_paused_once(
    lab, authority_parts
):
    voice = await nepal(lab)
    authority_parts.windows.lock_unlock()
    authority_parts.hello.denied = True
    assert voice.available() is True
    wake = Wake(voice)
    wake.speech()
    wake.transcript("Add a stove to the packing list.")
    result = await wake.turns.prepare()
    assert result["status"] == "not_saved"
    assert wake.session.replies == [project_voice.PAUSED_NOTICE_INSTRUCTIONS]
    # Ordinary voice answers; nothing is saved without a grant.
    assert await wake.turns.response_audio_allowed() is True
    wake.reply("Okay.")
    wake.speech()
    wake.transcript("And a lantern.")
    await wake.turns.prepare()
    await settle(voice)
    assert stove_rows(lab) == [] and "And a lantern." not in texts(lab)
    assert wake.session.replies == [project_voice.PAUSED_NOTICE_INSTRUCTIONS]
    calls = len(authority_parts.hello.calls)
    # Within the 5-minute cooldown: no new prompt, ordinary voice.
    assert await voice.prepare_wake() is None
    assert voice.available() is False
    assert len(authority_parts.hello.calls) == calls


@pytest.mark.asyncio
async def test_slow_hello_never_holds_the_wake_beyond_the_bound(
    lab, authority_parts, monkeypatch
):
    monkeypatch.setattr(project_voice, "RENEWAL_WAIT_SECONDS", 0.1)
    voice = await nepal(lab)
    authority_parts.windows.lock_unlock()
    release = slow_hello(voice)
    assert voice.available() is True  # renewal requested at the wake
    wake = Wake(voice)
    wake.speech()
    wake.transcript("Add a stove to the packing list.")
    loop = asyncio.get_running_loop()
    started = loop.time()
    assert await wake.turns.response_audio_allowed() is True  # ordinary voice
    assert loop.time() - started < 2
    assert (await wake.turns.prepare())["status"] == "not_saved"
    assert wake.session.replies == [project_voice.PAUSED_NOTICE_INSTRUCTIONS]
    release.set()  # the owner approves a moment later
    await settle(voice)
    assert stove_rows(lab) == []  # the paused wake never saves later
    wake.close()
    nxt = Wake(voice)  # the next wake uses the new grant
    await nxt.ask("Add a stove to the packing list.", "Added the stove.")
    assert len(stove_rows(lab)) == 2  # owner + Jarvis, exactly once


@pytest.mark.asyncio
async def test_current_grant_needs_no_wait(lab, authority_parts):
    voice = await nepal(lab)
    calls = len(authority_parts.hello.calls)
    assert await voice.prepare_wake(timeout=0.01) is None
    assert len(authority_parts.hello.calls) == calls


@pytest.mark.asyncio
async def test_renewal_events_reach_diagnostics(lab, authority_parts, tmp_path):
    from test_voice_diagnostics import FakeProtector

    from jarvis.voice import voice_diagnostics as vd

    root = tmp_path / "profile"
    root.mkdir()
    diagnostics = vd.VoiceDiagnostics(root, protector=FakeProtector())
    voice = await nepal(lab)
    voice.diagnostics = diagnostics
    authority_parts.windows.lock_unlock()
    await voice.prepare_wake()
    wake = Wake(voice)
    await wake.ask("We will also take a stove.", "Noted.")
    await diagnostics.aclose()
    data = vd.load_run(diagnostics.run_dir, FakeProtector())
    kinds = [e["kind"] for e in data["runtime_events"]]
    assert kinds == ["renewal_requested", "renewal_succeeded", "renewal_ready_for_wake"]


@pytest.mark.asyncio
async def test_the_wake_stays_open_while_hello_is_being_approved(monkeypatch):
    """Live qualification: the post-renewal wake ended after 8 s of inactivity
    with no owner turn. While this wake still waits for the Hello approval, the
    inactivity timeout is extended (never beyond the renewal wait); without a
    pending approval it expires exactly as before."""
    from jarvis.voice.canonical_active_speaker_runtime import (
        CanonicalActiveSpeakerRuntimeController,
    )

    runtime = object.__new__(CanonicalActiveSpeakerRuntimeController)
    runtime._standby_requested = False
    runtime._session_ready_for_inactivity = True
    runtime._agent_state = "listening"
    runtime._user_is_speaking = False
    runtime._personal_context = None
    runtime._timeout_handle = None
    runtime._session_conversation = None
    runtime._active_end = asyncio.Event()
    pending = [0.05]
    runtime._project_turns = SimpleNamespace(
        approval_pending_seconds=lambda: pending[0]
    )
    runtime._arm_timeout(0.01)
    await asyncio.sleep(0.03)
    assert not runtime._active_end.is_set()  # approval still pending
    pending[0] = 0.0  # approved (or the bounded wait ended)
    await asyncio.sleep(0.1)
    assert runtime._active_end.is_set()
    runtime._project_turns = None  # ordinary voice: unchanged behaviour
    runtime._active_end = asyncio.Event()
    runtime._arm_timeout(0.01)
    await asyncio.sleep(0.03)
    assert runtime._active_end.is_set()
