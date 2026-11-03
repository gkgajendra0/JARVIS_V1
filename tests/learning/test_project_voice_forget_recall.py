"""Voice forgetting, long-term recall and Windows Hello renewal.

Real archive, FTS5 index, provenance edges and history authority; fake Windows
session/Hello (``authority_parts``) and fake Gemini session.

P1  "Forget that ..." removes every saved row mentioning the owner's words (any
    live project), the Jarvis replies generated with them, and the request
    itself, after a fresh Hello approval. Unrelated history is kept, nothing
    resurfaces after a restart, and the index no longer holds the words.
P2  Older facts beyond the preload/packet windows are found with a bounded,
    authorized FTS5 search; newer owner corrections come last (current).
P3  After a Windows lock/unlock, the next eligible wake asks for a fresh grant;
    the revoked one is never reused; a denial leaves ordinary voice.
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
    wake.transcript("What did we say about permits?")
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
    assert voice.available() is False  # this wake: ordinary voice...
    await voice.drain()  # ...while a fresh Hello approval is requested
    assert voice.metrics.renewals == 1 and voice.access.grant != old
    assert issuer.validate(old).status != "active"  # never reused
    assert voice.available() is True  # the next wake has project memory again
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
    assert voice.available() is False
    await voice.drain()
    assert voice.metrics.renewal_failures == 1
    calls = len(authority_parts.hello.calls)
    assert voice.available() is False
    assert voice.request_renewal() is False  # no prompt on every wake
    assert len(authority_parts.hello.calls) == calls
    # After the cooldown the owner is asked again, and approval restores it.
    authority_parts.hello.denied = False
    monkeypatch.setattr(project_voice, "monotonic", lambda: 10**9)
    assert voice.available() is False
    await voice.drain()
    assert voice.available() is True


@pytest.mark.asyncio
async def test_renewal_after_shutdown_never_attaches(lab, authority_parts):
    voice = await nepal(lab)
    authority_parts.windows.lock_unlock()
    voice.available()
    await voice.aclose()  # drains the renewal; the new grant is revoked
    assert voice.available() is False
    await asyncio.sleep(0)


# -- D1: bounded Hello wait on the first wake after lock/unlock ---------------


@pytest.mark.asyncio
async def test_first_wake_after_unlock_waits_for_hello_and_uses_memory(
    lab, authority_parts
):
    voice = await nepal(lab)
    authority_parts.windows.lock_unlock()
    assert await voice.prepare_wake(timeout=5) is None  # approved in time
    assert voice.available() is True and voice.metrics.renewals == 1
    wake = Wake(voice)  # this same wake saves turns again
    await wake.ask("We will also take a stove.", "Noted.")
    assert "We will also take a stove." in texts(lab)


@pytest.mark.asyncio
async def test_denied_hello_on_wake_says_memory_is_paused_once(lab, authority_parts):
    voice = await nepal(lab)
    authority_parts.windows.lock_unlock()
    authority_parts.hello.denied = True
    notice = await voice.prepare_wake(timeout=5)
    assert notice == project_voice.PAUSED_NOTICE_INSTRUCTIONS
    assert voice.available() is False
    calls = len(authority_parts.hello.calls)
    # Within the 5-minute cooldown: no wait, no new prompt, no repeated notice.
    assert await voice.prepare_wake(timeout=5) is None
    assert len(authority_parts.hello.calls) == calls


@pytest.mark.asyncio
async def test_slow_hello_never_blocks_the_wake_beyond_the_bound(lab, authority_parts):
    import threading

    voice = await nepal(lab)
    authority_parts.windows.lock_unlock()
    release = threading.Event()
    real = voice._opener

    def slow_opener():
        release.wait(5)
        return real()

    voice._opener = slow_opener
    loop = asyncio.get_running_loop()
    started = loop.time()
    notice = await voice.prepare_wake(timeout=0.1)
    assert loop.time() - started < 2
    assert notice == project_voice.PAUSED_NOTICE_INSTRUCTIONS
    release.set()  # the owner approves a moment later
    await voice.drain()
    assert await voice.prepare_wake(timeout=0.1) is None
    assert voice.available() is True


@pytest.mark.asyncio
async def test_current_grant_needs_no_wait(lab, authority_parts):
    voice = await nepal(lab)
    calls = len(authority_parts.hello.calls)
    assert await voice.prepare_wake(timeout=0.01) is None
    assert len(authority_parts.hello.calls) == calls


def test_wake_notice_is_spoken_as_the_sessions_first_prompt():
    import inspect

    from jarvis.voice.runtime import VoiceRuntimeController

    source = inspect.getsource(VoiceRuntimeController._run_one_session_owned)
    hook = source.index("notice = await self._before_conversation_session()")
    assert hook < source.index("session, bridge = self._session_factory(self.config)")
    assert "initial_instructions = notice" in source


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
    await voice.prepare_wake(timeout=5)
    await diagnostics.aclose()
    data = vd.load_run(diagnostics.run_dir, FakeProtector())
    kinds = [e["kind"] for e in data["runtime_events"]]
    assert kinds == ["renewal_requested", "renewal_succeeded", "renewal_ready_for_wake"]
