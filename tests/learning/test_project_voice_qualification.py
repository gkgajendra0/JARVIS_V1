"""Grading of the single live qualification run (synthetic diagnostics)."""

from jarvis.voice import project_voice_qualification as q

T = "2026-11-03T10:00:{:02d}.000+00:00"


def utterance(
    session, index, *, said="", tools=(), project=(), replies=(), played=True
):
    return {
        "id": f"r/s{session}/u{index}",
        "asr": [{"text": said, "final": True, "at": T.format(1)}] if said else [],
        "accepted": [{"text": said, "at": T.format(2)}] if said else [],
        "tools": [{"at": T.format(3), **t} for t in tools],
        "project": [
            {"at": T.format(3), **p}
            for p in (
                [{"kind": "prepared", "status": "ready", "saved_text": said}]
                if said
                else []
            )
            + list(project)
        ],
        "responses": [{"kind": "response_played", "at": T.format(4)}] if played else [],
        "assistant": [{"text": r, "at": T.format(5)} for r in replies],
        "segments": [{}],
        "speech_seconds": 1.0,
        "speech_ended_at": T.format(0),
        "latency_ms": 700,
        "errors": [],
        "flags": [],
    }


def session(number, utterances, preloaded=()):
    return {
        "session": number,
        "utterances": utterances,
        "unmatched": [
            {
                "kind": "context_preloaded",
                "unmatched_kind": "project_event_before_any_owner_speech",
                "history": [{"role": "user", "text": t} for t in preloaded],
            }
        ],
    }


def run(*sessions, events=()):
    return {
        "run": {"run_id": "r"},
        "sessions": list(sessions),
        "runtime_events": list(events),
    }


FORGET_TOOLS = (
    {"name": "forget_memory", "is_error": False, "status": True},
    {"name": "forget_saved_history", "is_error": False, "status": "forgotten"},
)


def full_run(later_reply="I don't have a vehicle saved."):
    s1 = session(
        1,
        [
            utterance(
                1,
                1,
                said="Which hotel did we book in Kathmandu?",
                tools=[{"name": "search_project_history", "status": "complete"}],
                project=[
                    {
                        "kind": "history_searched",
                        "hits": 1,
                        "history": [
                            {"role": "owner", "text": "Our hotel is Yak and Yeti."}
                        ],
                    }
                ],
                replies=["Yak and Yeti."],
            ),
            utterance(
                1,
                2,
                said="Forget that I own a Jimny.",
                tools=FORGET_TOOLS,
                project=[{"kind": "history_forgotten", "terms": ["jimny"]}],
                replies=["Done."],
            ),
            utterance(
                1,
                3,
                said="Open Notepad.",
                tools=[{"name": "use_computer", "is_error": False}],
                replies=["Notepad is open."],
            ),
            utterance(
                1,
                4,
                said="What's the weather in Kathmandu?",
                tools=[{"name": "search_web", "is_error": False}],
                replies=["It is sunny."],
            ),
        ],
        preloaded=["Packing note 29."],
    )
    s2 = session(
        2, [utterance(2, 1, said="Which vehicle do I own?", replies=[later_reply])]
    )
    s3 = session(3, [utterance(3, 1, said="Add a stove.", replies=["Noted."])])
    events = [
        {"kind": "renewal_requested", "session_count": 2},
        {"kind": "renewal_succeeded", "session_count": 2},
        {"kind": "renewal_ready_for_wake", "session_count": 2, "waited_ms": 2100},
    ]
    return run(s1, s2, s3, events=events)


def test_a_complete_qualification_passes_with_evidence():
    result = q.qualify(full_run())
    assert {k: v["verdict"] for k, v in result["steps"].items()} == {
        "Q1_recall": "PASS",
        "Q2_forget": "PASS",
        "Q3_tools": "PASS",
        "Q4_renewal": "PASS",
        "Q5_capture": "PASS",
    }
    assert result["verdict"] == "PASS"
    assert result["steps"]["Q1_recall"]["found_outside_preload"] == [
        "Our hotel is Yak and Yeti."
    ]
    first = result["steps"]["Q5_capture"]["utterances"][0]
    assert first["recognised"] == ["Which hotel did we book in Kathmandu?"]
    assert first["tools"] == [{"name": "search_project_history", "status": "complete"}]
    assert first["replies"] == ["Yak and Yeti."] and first["first_audio_ms"] == 700


def test_forgotten_words_spoken_in_a_later_session_fail():
    result = q.qualify(full_run(later_reply="You own a Jimny."))
    assert result["steps"]["Q2_forget"]["reason"] == "resurfaced:jimny"
    assert result["verdict"] == "FAIL"


def test_partial_forget_is_reported_either_way():
    data = full_run()
    tools = data["sessions"][0]["utterances"][1]["tools"]
    tools[1].update(status="not_forgotten")  # Hello denied for history
    data["sessions"][0]["utterances"][1]["project"] = [
        p
        for p in data["sessions"][0]["utterances"][1]["project"]
        if p["kind"] != "history_forgotten"
    ]
    assert q.q2_forget(data)["reason"] == "partial_forget:canonical_only"
    data = full_run()
    data["sessions"][0]["utterances"][1]["tools"][0].update(is_error=True)
    assert q.q2_forget(data)["reason"] == "partial_forget:history_only"


def test_missing_steps_are_not_run_not_pass():
    data = run(session(1, [utterance(1, 1, said="Hello.", replies=["Hi."])]))
    result = q.qualify(data)
    assert result["verdict"] == "NOT_RUN"
    assert result["steps"]["Q4_renewal"]["reason"] == "no_lock_unlock_observed"


def test_search_returning_only_preloaded_rows_fails():
    data = full_run()
    data["sessions"][0]["unmatched"][0]["history"].append(
        {"role": "user", "text": "Our hotel is Yak and Yeti."}
    )
    assert q.q1_recall(data)["reason"] == "search_returned_only_preloaded_rows"


def test_paused_notice_is_review_and_unsaved_renewal_fails():
    data = full_run()
    data["runtime_events"] = [
        {"kind": "renewal_requested", "session_count": 2},
        {"kind": "renewal_failed", "session_count": 2},
        {"kind": "paused_notice_spoken", "session_count": 2},
    ]
    assert q.q4_renewal(data)["verdict"] == "REVIEW"
    data = full_run()
    data["sessions"][2]["utterances"][0]["project"] = []
    assert q.q4_renewal(data)["reason"] == "renewed_wake_saved_nothing"


def test_tool_outcome_status_is_captured():
    from jarvis.voice.voice_diagnostics import _tool_status

    assert _tool_status('{"status": "forgotten", "your_messages": 2}') == "forgotten"
    assert _tool_status({"ok": True}) is True
    assert _tool_status("not json") is None
