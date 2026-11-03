"""Grading of the single live qualification run (synthetic diagnostics).

The shapes marked "live" reproduce the run at 8155df0d
(20261103T100642Z-20dd6e), whose grader verdicts were wrong twice: Q2 was a
false FAIL (the first of three forget_memory attempts failed, the third
committed) and Q3 a false PASS (open_app returned status=failed,
verified=False, but the grader only looked at is_error).
"""

from jarvis.voice import project_voice_qualification as q

T = "2026-11-03T10:00:{:02d}.000+00:00"


def utterance(
    session,
    index,
    *,
    said="",
    tools=(),
    project=(),
    replies=(),
    played=True,
    played_at=4,
    saved=True,
):
    return {
        "id": f"r/s{session}/u{index}",
        "asr": [{"text": said, "final": True, "at": T.format(1)}] if said else [],
        "accepted": [{"text": said, "at": T.format(2)}] if said else [],
        "tools": [{"at": T.format(3), **t} for t in tools],
        "project": [
            {"at": T.format(3), **p}
            for p in (
                [
                    {
                        "kind": "prepared",
                        "status": "ready",
                        "turn_id": f"t{session}.{index}",
                        "saved_text": said,
                    }
                ]
                if said and saved
                else []
            )
            + list(project)
        ],
        "responses": [{"kind": "response_played", "at": T.format(played_at)}]
        if played
        else [],
        "assistant": [{"text": r, "at": T.format(5)} for r in replies],
        "segments": [{}],
        "speech_seconds": 1.0,
        "speech_ended_at": T.format(0),
        "latency_ms": 700,
        "errors": [],
        "flags": [],
    }


def session(number, utterances, preloaded=(), events=()):
    return {
        "session": number,
        "utterances": utterances,
        "unmatched": [
            {
                "kind": "context_preloaded",
                "unmatched_kind": "project_event_before_any_owner_speech",
                "history": [{"role": "user", "text": t} for t in preloaded],
            },
            *events,
        ],
    }


def run(*sessions, events=()):
    return {
        "run": {"run_id": "r"},
        "sessions": list(sessions),
        "runtime_events": list(events),
    }


FORGET_TOOLS = (
    {"name": "forget_memory", "is_error": False, "ok": True, "status": True},
    {"name": "forget_saved_history", "is_error": False, "status": "forgotten"},
)
HANDS_OK = {
    "name": "use_computer",
    "is_error": False,
    "ok": True,
    "status": "succeeded",
    "verified": True,
}
# live: Hands could not find the winapp CLI; the tool returned normally.
HANDS_LIVE = {
    "name": "use_computer",
    "is_error": False,
    "ok": False,
    "status": "failed",
    "verified": False,
}
RESEARCH_OK = {
    "name": "search_web",
    "is_error": False,
    "ok": True,
    "status": "multi_source_researched",
}
RENEWED = {
    "kind": "renewal_ready_for_wake",
    "unmatched_kind": "project_event_before_any_owner_speech",
    "waited_ms": 2100,
}
RENEWAL_EVENTS = [
    {"kind": "renewal_requested", "session_count": 2},
    {"kind": "renewal_succeeded", "session_count": 3},
    {"kind": "renewal_ready_for_wake", "session_count": 3, "waited_ms": 2100},
]


def full_run(later_reply="I don't have a vehicle saved.", renewed=None):
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
                tools=[HANDS_OK],
                replies=["Notepad is open."],
            ),
            utterance(
                1,
                4,
                said="What's the weather in Kathmandu?",
                tools=[RESEARCH_OK],
                replies=["It is sunny."],
            ),
        ],
        preloaded=["Packing note 29."],
    )
    s2 = session(
        2, [utterance(2, 1, said="Which vehicle do I own?", replies=[later_reply])]
    )
    s3 = session(
        3,
        renewed
        if renewed is not None
        else [
            utterance(3, 1, said="Add a stove to the packing list.", replies=["Added."])
        ],
        events=[RENEWED],
    )
    return run(s1, s2, s3, events=RENEWAL_EVENTS)


def verdicts(result):
    return {k: v["verdict"] for k, v in result["steps"].items()}


def test_a_complete_qualification_passes_with_evidence():
    result = q.qualify(full_run())
    assert verdicts(result) == {
        "Q1_recall": "PASS",
        "Q2_forget": "PASS",
        "Q3_tools": "PASS",
        "Q4_renewal": "PASS",
        "Q5_capture": "PASS",
    }
    assert result["verdict"] == "PASS"
    q1 = result["steps"]["Q1_recall"]
    assert q1["found_outside_preload"] == ["Our hotel is Yak and Yeti."]
    assert q1["reply_uses"] == ["yak", "yeti"]
    first = result["steps"]["Q5_capture"]["utterances"][0]
    assert first["recognised"] == ["Which hotel did we book in Kathmandu?"]
    assert first["tools"] == [{"name": "search_project_history", "status": "complete"}]
    assert first["replies"] == ["Yak and Yeti."] and first["first_audio_ms"] == 700


# -- Q1 ----------------------------------------------------------------------------


def test_search_returning_only_preloaded_rows_fails():
    data = full_run()
    data["sessions"][0]["unmatched"][0]["history"].append(
        {"role": "user", "text": "Our hotel is Yak and Yeti."}
    )
    assert q.q1_recall(data)["reason"] == "search_returned_only_preloaded_rows"


def test_a_reply_that_ignores_the_found_rows_is_not_recall():
    data = full_run()
    data["sessions"][0]["utterances"][0]["assistant"] = [
        {"text": "I don't have the hotel saved.", "at": T.format(5)}
    ]
    assert q.q1_recall(data)["reason"] == "reply_does_not_use_found_rows"
    data = full_run()
    data["sessions"][0]["utterances"][0]["responses"] = []
    assert q.q1_recall(data)["reason"] == "no_audible_reply"


# -- Q2 ----------------------------------------------------------------------------


def live_forget_run():
    """live: 'car' and 'suzuki_jimny' had no current memory; the third
    forget_memory committed; history forget removed 2 owner/13 Jarvis rows; the
    later answer said 'car' because the owner asked about the car."""
    s3 = session(
        3,
        [
            utterance(
                3,
                1,
                said="Forget that my car is a Suzuki Jimny.",
                tools=[
                    {"name": "forget_memory", "is_error": True},
                    {"name": "forget_memory", "is_error": True},
                    {"name": "forget_memory", "is_error": False, "ok": True},
                    {"name": "forget_saved_history", "status": "forgotten"},
                ],
                project=[
                    {
                        "kind": "history_forgotten",
                        "terms": ["car", "suzuki", "jimny"],
                        "owner_rows": 2,
                        "jarvis_rows": 13,
                        "projects": 1,
                    }
                ],
                replies=["I have removed that."],
            )
        ],
    )
    s4 = session(
        4,
        [
            utterance(
                4,
                1,
                said="What car do I own now?",
                tools=[{"name": "inspect_memory", "is_error": True}],
                replies=["I do not have access to information about the car you own."],
            )
        ],
    )
    return run(s3, s4)


def test_live_forget_with_two_failed_predicate_guesses_passes():
    result = q.q2_forget(live_forget_run())
    assert result["verdict"] == "PASS", result
    assert result["canonical_attempts"] == 3
    assert result["canonical_failed_attempts"] == 2
    assert result["removed"] == [{"owner_rows": 2, "jarvis_rows": 13, "projects": 1}]


def test_a_forgotten_word_the_owner_did_not_say_later_fails():
    data = live_forget_run()
    data["sessions"][1]["utterances"][0]["assistant"][0]["text"] = (
        "You own a Suzuki Jimny."
    )
    assert q.q2_forget(data)["reason"] == "resurfaced_in_reply:jimny,suzuki"


def test_forgotten_words_given_to_the_model_later_fail():
    data = live_forget_run()
    data["sessions"][1]["unmatched"][0]["history"].append(
        {"role": "user", "text": "My car is a Suzuki Jimny."}
    )
    assert q.q2_forget(data)["reason"].startswith("resurfaced_in_context:")


def test_partial_forget_is_reported_either_way():
    data = full_run()
    u = data["sessions"][0]["utterances"][1]
    u["tools"][1].update(status="not_forgotten")  # Hello denied for history
    u["project"] = [p for p in u["project"] if p["kind"] != "history_forgotten"]
    assert q.q2_forget(data)["reason"] == "partial_forget:canonical_only"
    data = full_run()
    data["sessions"][0]["utterances"][1]["tools"][0].update(is_error=True)
    assert q.q2_forget(data)["reason"] == "partial_forget:history_only"


def test_an_earlier_unrelated_deletion_is_not_evidence_for_this_request():
    data = live_forget_run()
    earlier = session(
        1,
        [
            utterance(
                1,
                1,
                said="Forget my old phone.",
                tools=[{"name": "forget_memory", "is_error": False, "ok": True}],
            )
        ],
    )
    current = data["sessions"][0]["utterances"][0]
    current["tools"] = [t for t in current["tools"] if t["name"] != "forget_memory"]
    data["sessions"].insert(0, earlier)
    result = q.q2_forget(data)
    assert result["reason"] == "partial_forget:history_only"
    assert result["earlier_requests"] == 1


def test_a_confirmation_heard_before_both_systems_forgot_fails():
    data = live_forget_run()
    data["sessions"][0]["utterances"][0]["responses"] = [
        {"kind": "response_played", "at": T.format(2)},
        {"kind": "response_played", "at": T.format(4)},
    ]
    assert q.q2_forget(data)["reason"] == "confirmed_before_both_forgot"


# -- Q3 ----------------------------------------------------------------------------


def test_live_unavailable_hands_is_a_failure_not_a_pass():
    data = full_run()
    u = data["sessions"][0]["utterances"][2]
    u["tools"] = [{"at": T.format(3), **HANDS_LIVE}]
    u["assistant"] = [
        {"text": "I am unable to open Notepad as the required application", "at": T}
    ]
    result = q.q3_tools(data)
    hands = result["hands"]["attempts"][0]
    assert hands["invoked"] is True and hands["executed_ok"] is False
    assert hands["verified"] is False
    assert hands["verdict"] == "FAIL" and hands["reason"] == "hands_failed"
    assert result["research"]["verdict"] == "PASS"  # Exa research still works
    assert result["verdict"] == "FAIL"


def test_hands_needs_verified_evidence_not_just_a_call():
    data = full_run()
    tool = data["sessions"][0]["utterances"][2]["tools"][0]
    tool.update(verified=False)
    assert q.q3_tools(data)["hands"]["attempts"][0]["reason"] == (
        "postcondition_not_verified"
    )
    for key in ("status", "verified", "ok"):
        tool.pop(key, None)  # an old record: only "called, no error"
    assert q.q3_tools(data)["hands"]["verdict"] == "REVIEW"


def test_research_that_never_searched_is_not_a_pass():
    data = full_run()
    tool = data["sessions"][0]["utterances"][3]["tools"][0]
    tool.update(ok=False, status="research_not_warranted")
    assert q.q3_tools(data)["research"]["attempts"][0]["reason"] == (
        "research_research_not_warranted"
    )


# -- Q4 ----------------------------------------------------------------------------


def silent(session_number, index, *, segments=True, asr=()):
    u = utterance(session_number, index, played=False)
    u["segments"] = [{}] if segments else []
    u["asr"] = [{"text": t, "final": True, "at": T.format(1)} for t in asr]
    return u


def test_renewal_without_a_spoken_command_is_incomplete_not_lost():
    """live: renewal approved, then no owner speech in that wake."""
    result = q.q4_renewal(full_run(renewed=[]))
    assert result["verdict"] == "NOT_RUN"
    assert result["reason"] == "renewed_but_no_owner_speech"


def test_renewal_outcomes_are_told_apart():
    assert q.q4_renewal(full_run(renewed=[silent(3, 1)]))["reason"] == (
        "speech_detected_without_transcript_listen_to_audio"
    )
    assert q.q4_renewal(full_run(renewed=[silent(3, 1, asr=["Add a stove"])]))[
        "reason"
    ] == ("recognised_but_not_accepted")
    unsaved = utterance(3, 1, said="Add a stove.", saved=False)
    unsaved["project"].append(
        {
            "kind": "prepared",
            "status": "not_saved",
            "reason": "project_memory_paused",
            "at": T.format(3),
        }
    )
    assert q.q4_renewal(full_run(renewed=[unsaved]))["reason"] == (
        "captured_but_not_saved:project_memory_paused"
    )
    unanswered = utterance(3, 1, said="Add a stove.", played=False)
    assert q.q4_renewal(full_run(renewed=[unanswered]))["reason"] == (
        "saved_but_no_audible_reply"
    )
    twice = utterance(3, 1, said="Add a stove.")
    twice["project"].append(dict(twice["project"][0]))
    assert q.q4_renewal(full_run(renewed=[twice]))["reason"] == "saved_more_than_once"


def test_paused_notice_is_review_and_saving_while_paused_fails():
    data = full_run()
    data["sessions"][2]["unmatched"] = [
        {"kind": "project_memory_paused", "unmatched_kind": "x"}
    ]
    data["sessions"][2]["utterances"][0]["project"] = []
    data["runtime_events"] = [
        {"kind": "renewal_requested", "session_count": 2},
        {"kind": "renewal_failed", "session_count": 3},
        {"kind": "paused_notice_spoken", "session_count": 3},
    ]
    assert q.q4_renewal(data)["verdict"] == "REVIEW"
    data["sessions"][2]["utterances"] = [utterance(3, 1, said="Add a stove.")]
    assert q.q4_renewal(data)["reason"] == "saved_while_paused"


def test_missing_steps_are_not_run_not_pass():
    data = run(session(1, [utterance(1, 1, said="Hello.", replies=["Hi."])]))
    result = q.qualify(data)
    assert result["verdict"] == "NOT_RUN"
    assert result["steps"]["Q4_renewal"]["reason"] == "no_lock_unlock_observed"


# -- Q5 ----------------------------------------------------------------------------


def test_spoken_internal_text_and_unanswered_requests_fail_capture():
    data = full_run()
    data["sessions"][1]["utterances"][0]["assistant"] = [
        {"text": "Thinking Process:\n1. **Analyze** the request.", "at": T}
    ]
    fails = q.qualify(data)["steps"]["Q5_capture"]["acceptance_fail"]
    assert {"id": "r/s2/u1", "fail": ["internal_text_may_have_been_spoken"]} in fails
    data = full_run()
    data["sessions"][1]["utterances"][0]["responses"] = []
    fails = q.qualify(data)["steps"]["Q5_capture"]["acceptance_fail"]
    assert {"id": "r/s2/u1", "fail": ["accepted_without_audible_reply"]} in fails


def test_a_bare_wake_name_needs_no_reply_and_unheard_speech_is_review():
    data = full_run()
    data["sessions"][1]["utterances"].append(
        utterance(2, 2, said="Jarvis.", played=False)
    )
    data["sessions"][1]["utterances"].append(silent(2, 3))
    step = q.qualify(data)["steps"]["Q5_capture"]
    assert step["verdict"] == "REVIEW"
    assert step["review"] == [{"id": "r/s2/u3", "review": "speech_without_transcript"}]


def test_tool_outcomes_are_parsed_from_livekits_python_repr():
    """LiveKit gives the tool output as str(dict), not JSON."""
    from jarvis.voice.voice_diagnostics import _tool_ok, _tool_status, _tool_verified

    live = str(
        {
            "ok": False,
            "status": "failed",
            "final_observation": {"verified": False, "operation": "open_app"},
        }
    )
    assert (_tool_ok(live), _tool_status(live), _tool_verified(live)) == (
        False,
        "failed",
        False,
    )
    assert _tool_status('{"status": "forgotten", "your_messages": 2}') == "forgotten"
    assert _tool_status({"ok": True}) is True
    assert _tool_status("not json") is None
    assert _tool_status("{__import__('os').system('x')}") is None  # never evaluated


# -- live run at 1b13dfb8 (20261103T115032Z-bc3e16) -------------------------------


def hotel_forget_run(later_preload=(), later_reply=None):
    """Both stores forgot "my hotel in Kathmandu is Yak and Yeti"; the next wake
    still holds unrelated owner rows mentioning the hotel or Kathmandu."""
    s2 = session(
        2,
        [
            utterance(
                2,
                1,
                said="Search our older saved project. Conversation history. What "
                "hotel did I mention in Kathmandu?",
                project=[{"kind": "history_searched", "hits": 0, "history": []}],
                replies=["Your hotel in Kathmandu is the Yak and Yeti."],
            ),
            utterance(
                2,
                2,
                said="search the web for today's weather in Kathmandu.",
                tools=[RESEARCH_OK],
                replies=["Today in Kathmandu, mostly clear and sunny."],
            ),
            utterance(
                2,
                3,
                said="Jervis, forget that my hotel in Kathmandu is Yak and Yeti.",
                tools=FORGET_TOOLS,
                project=[
                    {
                        "kind": "history_forgotten",
                        "terms": ["and", "hotel", "kathmandu", "yak", "yeti"],
                        "owner_rows": 2,
                        "jarvis_rows": 6,
                        "projects": ["General"],
                    }
                ],
                replies=["The information has been removed from my records."],
            ),
        ],
        preloaded=[
            "Remember that my hotel in Kathmandu is Yak and Yeti.",
            "Add a stove to my packing list.",
        ],
    )
    s3 = session(
        3,
        [
            utterance(
                3,
                1,
                said="Which hotel did I tell you about in Kathmandu?",
                project=[{"kind": "history_searched", "hits": 0, "history": []}],
                replies=[
                    later_reply
                    or "I cannot find any mention of a hotel in Kathmandu in our "
                    "previous conversations."
                ],
            )
        ],
        preloaded=[
            (
                "Search our older saved project. Conversation history. What hotel "
                "did I mention in Kathmandu?"
            ),
            "search the web for today's weather in Kathmandu.",
            *later_preload,
        ],
    )
    return run(s2, s3)


def test_generic_words_in_surviving_history_are_not_a_leak():
    """live: Q2 FAIL resurfaced_in_context:hotel,kathmandu was a false FAIL."""
    result = q.q2_forget(hotel_forget_run())
    assert result["verdict"] == "PASS", result
    assert result["distinctive_terms"] == ["yak", "yeti"]


def test_a_real_resurfacing_is_still_caught():
    leaked = hotel_forget_run(later_preload=["We are staying at the Yeti lodge."])
    assert q.q2_forget(leaked)["reason"] == "resurfaced_in_context:yeti"
    whole = hotel_forget_run(later_preload=["My hotel in Kathmandu is Yak and Yeti."])
    assert q.q2_forget(whole)["verdict"] == "FAIL"
    said = hotel_forget_run(later_reply="It was the Yak and Yeti.")
    assert q.q2_forget(said)["reason"] == "resurfaced_in_reply:yak,yeti"


def test_an_answer_from_the_preload_is_not_an_archive_search():
    """live: Q1 'search_found_nothing'. The fact was one of 6 saved rows, inside
    the preload, so search (which never resends preloaded rows) found nothing
    new: the archive was not tested."""
    result = q.q1_recall(hotel_forget_run())
    assert result["verdict"] == "NOT_RUN"
    assert result["reason"] == "fact_was_in_the_preload_not_an_archive_search"
    assert result["answered_from_preload"] == ["yak", "yeti"]


def test_a_wake_acknowledgement_with_internal_text_fails_capture():
    """live: '<wake-ack instructions>Standing by.' was the ack's transcript."""
    from jarvis.voice.runtime import _WAKE_ACK_INSTRUCTIONS

    data = full_run()
    data["sessions"][1]["unmatched"].append(
        {
            "unmatched_kind": "assistant_before_any_owner_speech",
            "epoch": 0,
            "text": _WAKE_ACK_INSTRUCTIONS + "Standing by.",
        }
    )
    fails = q.qualify(data)["steps"]["Q5_capture"]["acceptance_fail"]
    assert {"id": "s2", "fail": ["internal_text_in_wake_acknowledgement"]} in fails
    data["sessions"][1]["unmatched"][-1]["text"] = "Standing by."
    assert q.qualify(data)["steps"]["Q5_capture"]["verdict"] == "PASS"
