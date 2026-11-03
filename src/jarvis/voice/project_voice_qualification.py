"""One focused live qualification of project memory in voice (lab only).

The owner runs the voice lab with ``--qualification --record-diagnostics``
against an isolated lab profile. That exposes the normal production tool set
(Hands, research and canonical memory tools) with project memory, like the
production flag would. This module then grades the sealed diagnostics run
without making any model call.

A step never passes merely because a tool was called, a transcript exists or
a response was generated: each needs evidence of the OUTCOME. Rules (revised
after the live run at 8155df0d, whose Q2 was a false FAIL and Q3 a false PASS):

Q1 recall    ``search_project_history`` returned rows that were NOT in the
             session preload, and an audible reply uses a distinctive word of
             one of those rows that the owner's question did not contain.
Q2 forget    In ONE forget request (utterance): some ``forget_memory`` attempt
             committed (later attempts count; earlier predicate errors do not
             fail it) AND the saved conversation was forgotten. Only one of
             them: FAIL ``partial_forget``. No confirmation may play before
             both completed. A later wake session never receives the forgotten
             words in its context, and no reply there says a forgotten word the
             owner did not say in that session.
Q3 tools     Hands: the tool's own result says ``ok`` and ``succeeded`` with a
             verified postcondition (unavailable/failed = FAIL; no verification
             evidence = REVIEW). Research: a search actually ran and returned
             evidence (``*_researched`` / authoritative). Invocation, execution
             and verification are reported separately; a reply must play.
Q4 renewal   The wake whose turns waited for the fresh Windows Hello grant:
             approved, then the owner's first command there was captured, saved
             exactly once and answered audibly. No speech in that wake: NOT_RUN
             (incomplete, not a lost request). Speech without a transcript:
             REVIEW (listen). Captured but not saved, or saved but unanswered:
             FAIL. Denied/timed out: the paused notice and nothing saved
             (REVIEW).
Q5 capture   Every utterance's recognised and accepted transcripts, tool
             outcomes, spoken replies and latency. FAIL: the normal acceptance
             check fails, an accepted request got no audible reply, or internal
             text (prompt echo, reasoning trace) was spoken. REVIEW: speech
             with no transcript (listen to the sealed audio).

Verdicts: PASS, FAIL, NOT_RUN (step not attempted), REVIEW (needs a human).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from jarvis.voice.voice_output_safety import non_user_facing_reason

HANDS_TOOLS = frozenset({"use_computer", "computer_action", "control_computer"})
RESEARCH_TOOLS = frozenset({"search_web"})
RESEARCHED = frozenset(
    {"web_researched", "multi_source_researched", "authoritative_source_present"}
)
_FAILED_STATUSES = frozenset(
    {
        "denied",
        "unavailable",
        "failed",
        "not_forgotten",
        "too_broad",
        "resolution_required",
        "invalid_selection",
        "research_unavailable",
        "research_not_warranted",
        "insufficient_evidence",
    }
)
_STOPWORDS = frozenset(
    [
        "the",
        "a",
        "an",
        "and",
        "or",
        "but",
        "our",
        "your",
        "my",
        "we",
        "you",
        "i",
        "is",
        "are",
        "was",
        "were",
        "be",
        "to",
        "of",
        "in",
        "on",
        "at",
        "for",
        "with",
        "that",
        "this",
        "it",
        "its",
        "did",
        "do",
        "does",
        "what",
        "which",
        "who",
        "when",
        "where",
        "how",
        "about",
        "from",
        "have",
        "has",
        "had",
        "tell",
        "told",
        "me",
        "us",
        "they",
        "them",
        "there",
        "their",
        "then",
        "than",
    ]
)
_WAKE_NAMES = re.compile(
    r"^(?:hey |ok |okay )?(?:j[aeo]+r?v[iy]s|jeeves)[.!?]*$", re.IGNORECASE
)


def _words(text) -> set[str]:
    return set(re.findall(r"[^\W_]+", (text or "").casefold()))


def _distinctive(text, *, excluding=()) -> set[str]:
    excluded = set().union(*(_words(t) for t in excluding)) if excluding else set()
    return {
        w
        for w in _words(text)
        if len(w) >= 3 and w not in _STOPWORDS and w not in excluded
    }


def _ok(tool) -> bool:
    """The tool's own outcome, not merely that it was called."""
    if tool.get("is_error", False) or tool.get("ok") is False:
        return False
    status = tool.get("status")
    return not (isinstance(status, str) and status in _FAILED_STATUSES)


def _played(u) -> list[str]:
    """When an audible reply started in this utterance (gate or recovery)."""
    return [r["at"] for r in u["responses"] if r["kind"] == "response_played"] + [
        p["at"] for p in u["project"] if p["kind"] == "unplayed_reply_replayed"
    ]


def _played_after(u, at) -> bool:
    return any(t >= at for t in _played(u))


def _said(u) -> list[str]:
    return [a["text"] for a in u["accepted"]]


def _utterances(data):
    for session in data["sessions"]:
        for u in session["utterances"]:
            yield session, u


def _preloaded_texts(session) -> set[str]:
    texts = set()
    for event in session.get("unmatched", ()):
        if event.get("kind") == "context_preloaded":
            texts |= {r["text"] for r in event.get("history", ())}
    for u in session["utterances"]:
        for p in u["project"]:
            if p["kind"] == "context_preloaded":
                texts |= {r["text"] for r in p.get("history", ())}
    return texts


def _given_to_model(session) -> list[str]:
    """Every saved-history text the model was given in this session."""
    given = list(_preloaded_texts(session))
    for u in session["utterances"]:
        for p in u["project"]:
            given += [r.get("text", "") for r in p.get("history", ())]
    return given


def _summary(u) -> dict:
    return {
        "id": u["id"],
        "recognised": [a["text"] for a in u["asr"] if a.get("final")],
        "accepted": _said(u),
        "tools": [
            {
                k: t[k]
                for k in ("name", "ok", "status", "verified", "is_error")
                if k in t
            }
            for t in u["tools"]
        ],
        "replies": [a["text"] for a in u["assistant"]],
        "audible": bool(_played(u)),
        "first_audio_ms": u.get("latency_ms"),
        "errors": [e.get("error") for e in u.get("errors", ())],
    }


def q1_recall(data) -> dict:
    searched = False
    for session, u in _utterances(data):
        preloaded = _preloaded_texts(session)
        for p in u["project"]:
            if p["kind"] != "history_searched":
                continue
            searched = True
            if not p.get("hits"):
                continue
            older = [r["text"] for r in p["history"] if r["text"] not in preloaded]
            result = {"utterance": u["id"], "search_ms": p.get("search_ms")}
            if not older:
                return {
                    **result,
                    "verdict": "FAIL",
                    "reason": "search_returned_only_preloaded_rows",
                }
            # Words only a found row could have supplied (not the question).
            evidence = set().union(
                *(_distinctive(t, excluding=_said(u)) for t in older)
            )
            replies = [a["text"] for a in u["assistant"]]
            used = sorted(evidence & set().union(*map(_words, replies), set()))
            result["found_outside_preload"] = older
            result["result_bytes"] = p.get("bytes")
            if not _played_after(u, p["at"]):
                return {**result, "verdict": "FAIL", "reason": "no_audible_reply"}
            if not used:
                return {
                    **result,
                    "verdict": "FAIL",
                    "reason": "reply_does_not_use_found_rows",
                }
            return {**result, "verdict": "PASS", "reply_uses": used}
    return {
        "verdict": "NOT_RUN" if not searched else "FAIL",
        "reason": "search_project_history_not_called"
        if not searched
        else "search_found_nothing",
    }


def _forget_request(session, u) -> dict | None:
    canonical = [t for t in u["tools"] if t["name"] == "forget_memory"]
    history_tools = [t for t in u["tools"] if t["name"] == "forget_saved_history"]
    forgotten = [p for p in u["project"] if p["kind"] == "history_forgotten"]
    if not (canonical or history_tools or forgotten):
        return None
    canonical_ok = [t for t in canonical if _ok(t)]
    history_ok = forgotten or [
        t for t in history_tools if _ok(t) and t.get("status") == "forgotten"
    ]
    done = [x["at"] for x in (canonical_ok[:1] + list(history_ok[:1]))]
    return {
        "session": session["session"],
        "utterance": u["id"],
        "canonical_attempts": len(canonical),
        "canonical_failed_attempts": len(canonical) - len(canonical_ok),
        "canonical_forgotten": bool(canonical_ok),
        "history_forgotten": bool(history_ok),
        "terms": sorted({t for p in forgotten for t in p.get("terms", ())}),
        "removed": [
            {k: p[k] for k in ("owner_rows", "jarvis_rows", "projects") if k in p}
            for p in forgotten
        ],
        "_both_at": max(done) if len(done) == 2 else None,
        "_u": u,
    }


def q2_forget(data) -> dict:
    requests = [
        r for s, u in _utterances(data) if (r := _forget_request(s, u)) is not None
    ]
    if not requests:
        return {"verdict": "NOT_RUN", "reason": "no_forget_request"}
    # The latest request is graded; earlier ones never count as its evidence.
    request = requests[-1]
    u = request.pop("_u")
    both_at = request.pop("_both_at")
    result = dict(request, earlier_requests=len(requests) - 1)
    canonical_ok, history_ok = (
        result["canonical_forgotten"],
        result["history_forgotten"],
    )
    if canonical_ok != history_ok:
        return dict(
            result,
            verdict="FAIL",
            reason="partial_forget:"
            + ("canonical_only" if canonical_ok else "history_only"),
        )
    if not canonical_ok:
        return dict(result, verdict="FAIL", reason="forget_did_not_complete")
    premature = [t for t in _played(u) if t < both_at]
    if premature:
        return dict(result, verdict="FAIL", reason="confirmed_before_both_forgot")
    if not _played_after(u, both_at):
        return dict(result, verdict="FAIL", reason="no_audible_confirmation")
    later = [s for s in data["sessions"] if s["session"] > result["session"]]
    if not later:
        return dict(result, verdict="REVIEW", reason="no_new_session_after_forget")
    terms = set(result["terms"])
    in_context = sorted(
        {
            t
            for s in later
            for text in _given_to_model(s)
            for t in terms
            if t in _words(text)
        }
    )
    if in_context:
        return dict(
            result,
            verdict="FAIL",
            reason="resurfaced_in_context:" + ",".join(in_context),
        )
    spoken = set()
    for s in later:
        owner = set().union(
            set(), *(_words(t) for v in s["utterances"] for t in _said(v))
        )
        for v in s["utterances"]:
            for a in v["assistant"]:
                spoken |= (_words(a["text"]) & terms) - owner
    if spoken:
        return dict(
            result,
            verdict="FAIL",
            reason="resurfaced_in_reply:" + ",".join(sorted(spoken)),
        )
    asked = any(v["accepted"] for s in later for v in s["utterances"])
    if not asked:
        return dict(result, verdict="REVIEW", reason="no_question_asked_after_forget")
    return dict(result, verdict="PASS", later_sessions=len(later))


def _hands(u, t) -> dict:
    item = {
        "utterance": u["id"],
        "tool": t["name"],
        "invoked": True,
        "executed_ok": _ok(t),
        "status": t.get("status"),
        "verified": t.get("verified"),
        "reply_played": _played_after(u, t["at"]),
        "first_audio_ms": u.get("latency_ms"),
    }
    if not item["executed_ok"] or t.get("status") not in (None, "succeeded"):
        item.update(verdict="FAIL", reason=f"hands_{t.get('status') or 'failed'}")
    elif "status" not in t or t.get("verified") is None:
        item.update(verdict="REVIEW", reason="no_outcome_evidence_check_the_screen")
    elif t.get("verified") is not True:
        item.update(verdict="FAIL", reason="postcondition_not_verified")
    elif not item["reply_played"]:
        item.update(verdict="FAIL", reason="no_audible_reply")
    else:
        item["verdict"] = "PASS"
    return item


def _research(u, t) -> dict:
    status = t.get("status")
    item = {
        "utterance": u["id"],
        "tool": t["name"],
        "invoked": True,
        "executed_ok": _ok(t),
        "status": status,
        "reply_played": _played_after(u, t["at"]),
        "first_audio_ms": u.get("latency_ms"),
    }
    if not item["executed_ok"]:
        item.update(verdict="FAIL", reason=f"research_{status or 'failed'}")
    elif status is None:
        item.update(verdict="REVIEW", reason="no_outcome_evidence")
    elif status not in RESEARCHED:
        item.update(verdict="FAIL", reason=f"research_{status}")
    elif not item["reply_played"]:
        item.update(verdict="FAIL", reason="no_audible_reply")
    else:
        item["verdict"] = "PASS"
    return item


def q3_tools(data) -> dict:
    found: dict[str, list[dict]] = {"hands": [], "research": []}
    for _, u in _utterances(data):
        for t in u["tools"]:
            if t["name"] in HANDS_TOOLS:
                found["hands"].append(_hands(u, t))
            elif t["name"] in RESEARCH_TOOLS:
                found["research"].append(_research(u, t))
    results = {}
    for kind, items in found.items():
        if not items:
            results[kind] = {"verdict": "NOT_RUN"}
            continue
        # Every attempt is shown; the step passes only if every one did.
        verdicts = [i["verdict"] for i in items]
        worst = next(v for v in ("FAIL", "REVIEW", "PASS") if v in verdicts)
        results[kind] = {"verdict": worst, "attempts": items}
    verdicts = {r["verdict"] for r in results.values()}
    overall = next(v for v in ("FAIL", "NOT_RUN", "REVIEW", "PASS") if v in verdicts)
    return {"verdict": overall, **results}


def _renewed_session(data):
    for session in data["sessions"]:
        events = list(session.get("unmatched", ())) + [
            p for u in session["utterances"] for p in u["project"]
        ]
        for e in events:
            if e.get("kind") == "renewal_ready_for_wake":
                return session, e
    for e in data.get("runtime_events", ()):
        if e["kind"] == "renewal_ready_for_wake":
            number = e.get("session_count", 0)
            match = [s for s in data["sessions"] if s["session"] == number]
            return (match[0] if match else None), e
    return None, None


def _saves(session) -> list[dict]:
    return [
        p
        for u in session["utterances"]
        for p in u["project"]
        if p["kind"] == "prepared" and p.get("status") == "ready"
    ]


def q4_renewal(data) -> dict:
    kinds = [e["kind"] for e in data.get("runtime_events", [])]
    if "renewal_requested" not in kinds:
        return {"verdict": "NOT_RUN", "reason": "no_lock_unlock_observed"}
    session, ready = _renewed_session(data)
    if ready is None:
        if "paused_notice_spoken" in kinds:
            paused = [
                s
                for s in data["sessions"]
                if any(
                    p.get("kind") == "project_memory_paused"
                    for p in list(s.get("unmatched", ()))
                    + [p for u in s["utterances"] for p in u["project"]]
                )
            ]
            if any(_saves(s) for s in paused):
                return {"verdict": "FAIL", "reason": "saved_while_paused"}
            return {
                "verdict": "REVIEW",
                "reason": "renewal_not_approved_in_time_paused_notice_spoken",
                "events": kinds,
            }
        if "renewal_succeeded" in kinds:
            return {
                "verdict": "NOT_RUN",
                "reason": "approved_after_the_wake_ended_no_command_given",
                "events": kinds,
            }
        return {"verdict": "FAIL", "reason": "renewal_neither_ready_nor_announced"}
    result = {
        "renewed_wake_session": None if session is None else session["session"],
        "waited_ms": ready.get("waited_ms"),
    }
    utterances = [] if session is None else session["utterances"]
    accepted = [u for u in utterances if u["accepted"]]
    if not accepted:
        if any(a.get("final") and a.get("text") for u in utterances for a in u["asr"]):
            return dict(result, verdict="FAIL", reason="recognised_but_not_accepted")
        if any(u["segments"] for u in utterances):
            return dict(
                result,
                verdict="REVIEW",
                reason="speech_detected_without_transcript_listen_to_audio",
            )
        return dict(result, verdict="NOT_RUN", reason="renewed_but_no_owner_speech")
    first = accepted[0]
    result["command"] = _said(first)
    prepared = [p for p in first["project"] if p["kind"] == "prepared"]
    saved = [p for p in prepared if p.get("status") == "ready"]
    if not saved:
        reasons = sorted({p.get("reason") or p.get("status") for p in prepared})
        return dict(
            result,
            verdict="FAIL",
            reason="captured_but_not_saved"
            + (":" + ",".join(reasons) if reasons else ""),
        )
    turns = {p.get("turn_id") for p in saved}
    if len(saved) > len(turns) or len(first["accepted"]) > 1:
        return dict(result, verdict="FAIL", reason="saved_more_than_once")
    if not _played(first):
        return dict(result, verdict="FAIL", reason="saved_but_no_audible_reply")
    return dict(result, verdict="PASS")


def q5_capture(data, acceptance) -> dict:
    fail, review = [], []
    for r in acceptance["results"]:
        if r["fail"]:
            fail.append({"id": r["id"], "fail": r["fail"]})
    for session, u in _utterances(data):
        replies = [a["text"] for a in u["assistant"]]
        unsafe = [t for t in replies if non_user_facing_reason(t) is not None]
        if unsafe and _played(u):
            fail.append({"id": u["id"], "fail": ["internal_text_may_have_been_spoken"]})
        said = " ".join(_said(u)).strip()
        if said and not _WAKE_NAMES.match(said) and not _played(u):
            fail.append({"id": u["id"], "fail": ["accepted_without_audible_reply"]})
        if u["segments"] and not u["asr"] and not u["accepted"]:
            review.append({"id": u["id"], "review": "speech_without_transcript"})
        del session
    for session in data["sessions"]:
        for e in session.get("unmatched", ()):
            if e.get("kind") == "unplayed_reply_replayed" and e.get("epoch", 0) == 0:
                fail.append(
                    {"id": f"s{session['session']}", "fail": ["system_turn_replayed"]}
                )
    verdict = "FAIL" if fail else "REVIEW" if review else "PASS"
    return {
        "verdict": verdict,
        "acceptance_fail": fail,
        "review": review,
        "utterances": [_summary(u) for _, u in _utterances(data)],
    }


def qualify(data) -> dict:
    from jarvis.voice.voice_diagnostics import assess

    acceptance = assess(data)
    steps = {
        "Q1_recall": q1_recall(data),
        "Q2_forget": q2_forget(data),
        "Q3_tools": q3_tools(data),
        "Q4_renewal": q4_renewal(data),
        "Q5_capture": q5_capture(data, acceptance),
    }
    verdicts = [s["verdict"] for s in steps.values()]
    overall = (
        "FAIL"
        if "FAIL" in verdicts
        else "NOT_RUN"
        if "NOT_RUN" in verdicts
        else "REVIEW"
        if "REVIEW" in verdicts
        else "PASS"
    )
    return {
        "schema": "jarvis-project-voice-qualification-v2",
        "run_id": data["run"]["run_id"],
        "verdict": overall,
        "steps": steps,
        "latency_summary_ms": acceptance["latency_summary_ms"],
        "note": "Transcripts are Gemini recognition, not ground truth; listen to "
        "the sealed audio for capture accuracy.",
    }


def main() -> None:
    import argparse
    import os

    parser = argparse.ArgumentParser(description="Grade a live qualification run")
    parser.add_argument("--lab-root", type=Path, required=True)
    parser.add_argument("--run")
    args = parser.parse_args()
    lab = args.lab_root.resolve(strict=True)
    if not (lab / "project-memory.marker").is_file():
        parser.error("not an isolated project-memory lab profile")
    if os.name != "nt":
        parser.error("needs Windows DPAPI")
    from jarvis.security.dpapi import WindowsDpapiKeyProtector
    from jarvis.voice.voice_diagnostics import load_run

    runs = sorted(
        p for p in (lab / "voice-diagnostics" / "runs").iterdir() if p.is_dir()
    )
    if args.run:
        runs = [p for p in runs if p.name == args.run]
    if not runs:
        parser.error("no diagnostics run")
    result = qualify(load_run(runs[-1], WindowsDpapiKeyProtector()))
    path = runs[-1] / "qualification.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Qualification: {result['verdict']}  ({path})")
    for name, step in result["steps"].items():
        print(f"  {name}: {step['verdict']}  {step.get('reason', '')}")


if __name__ == "__main__":
    main()
