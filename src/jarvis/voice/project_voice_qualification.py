"""One focused live qualification of project memory in voice (lab only).

The owner runs the voice lab with ``--qualification --record-diagnostics``
against an isolated lab profile. That exposes the normal production tool set
(Hands, research and canonical memory tools) with project memory, like the
production flag would. This module then grades the sealed diagnostics run
without making any model call:

Q1 recall    An older fact outside the session preload is found by
             ``search_project_history`` and the reply plays.
Q2 forget    One request forgets the canonical fact (``forget_memory``) and the
             saved conversation (``forget_saved_history``). A later wake
             session never receives or speaks the forgotten words. If only one
             of the two succeeded: FAIL ``partial_forget``.
Q3 tools     One Hands action and one web research request complete with
             blocking tools, and a reply plays after each.
Q4 renewal   After a Windows lock/unlock: renewal requested, approved within
             the bounded wait, and that same wake saves turns again; or, on
             denial/timeout, the paused notice is spoken (REVIEW).
Q5 capture   Every utterance's recognised and accepted transcripts, tool
             calls, spoken replies and latency are listed. Any FAIL from the
             normal acceptance check is a FAIL here.

Verdicts: PASS, FAIL, NOT_RUN (step not attempted), REVIEW (needs a human).
"""

from __future__ import annotations

import json
from pathlib import Path

HANDS_TOOLS = frozenset({"use_computer", "computer_action", "control_computer"})
RESEARCH_TOOLS = frozenset({"search_web"})


def _words(text) -> str:
    return (text or "").casefold()


def _ok(tool) -> bool:
    return not tool.get("is_error", False) and tool.get("status") not in {
        "denied",
        "unavailable",
        "not_forgotten",
        "too_broad",
    }


def _played_after(u, at) -> bool:
    return any(
        r["kind"] == "response_played" and r["at"] >= at for r in u["responses"]
    ) or any(a["at"] >= at for a in u["assistant"])


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
    """Every text the model was given in this session, plus its replies."""
    given = list(_preloaded_texts(session))
    for u in session["utterances"]:
        for p in u["project"]:
            given += [r.get("text", "") for r in p.get("history", ())]
        given += [a.get("text", "") for a in u["assistant"]]
    return given


def _summary(u) -> dict:
    return {
        "id": u["id"],
        "recognised": [a["text"] for a in u["asr"] if a.get("final")],
        "accepted": [a["text"] for a in u["accepted"]],
        "tools": [
            {k: t[k] for k in ("name", "status", "is_error") if k in t}
            for t in u["tools"]
        ],
        "replies": [a["text"] for a in u["assistant"]],
        "first_audio_ms": u.get("latency_ms"),
        "errors": [e.get("error") for e in u.get("errors", ())],
    }


def q1_recall(data) -> dict:
    for session, u in _utterances(data):
        preloaded = _preloaded_texts(session)
        for p in u["project"]:
            if p["kind"] != "history_searched" or not p.get("hits"):
                continue
            older = [r["text"] for r in p["history"] if r["text"] not in preloaded]
            if older and (u["assistant"] or "response_played" in str(u["responses"])):
                return {
                    "verdict": "PASS",
                    "utterance": u["id"],
                    "found_outside_preload": older,
                    "search_ms": p.get("search_ms"),
                    "result_bytes": p.get("bytes"),
                }
            return {
                "verdict": "FAIL",
                "utterance": u["id"],
                "reason": "search_returned_only_preloaded_rows"
                if not older
                else "no_reply_after_search",
            }
    return {"verdict": "NOT_RUN", "reason": "search_project_history_not_called"}


def q2_forget(data) -> dict:
    canonical = history = None
    terms: list[str] = []
    for session, u in _utterances(data):
        for t in u["tools"]:
            if t["name"] == "forget_memory" and canonical is None:
                canonical = (session["session"], u["id"], _ok(t))
        for p in u["project"]:
            if p["kind"] == "history_forgotten" and history is None:
                history = (session["session"], u["id"], True)
                terms = p.get("terms", [])
        for t in u["tools"]:
            if t["name"] == "forget_saved_history" and not _ok(t) and history is None:
                history = (session["session"], u["id"], False)
    if canonical is None and history is None:
        return {"verdict": "NOT_RUN", "reason": "no_forget_request"}
    canonical_ok = bool(canonical and canonical[2])
    history_ok = bool(history and history[2])
    result = {
        "canonical_forgotten": canonical_ok,
        "history_forgotten": history_ok,
        "terms": terms,
    }
    if canonical_ok != history_ok:
        result.update(
            verdict="FAIL",
            reason="partial_forget:"
            + ("canonical_only" if canonical_ok else "history_only"),
        )
        return result
    if not canonical_ok:
        result.update(verdict="FAIL", reason="forget_did_not_complete")
        return result
    forgot_in = max(canonical[0], history[0])
    later = [s for s in data["sessions"] if s["session"] > forgot_in]
    if not later:
        result.update(verdict="REVIEW", reason="no_new_session_after_forget")
        return result
    leaked = sorted(
        {
            term
            for s in later
            for text in _given_to_model(s)
            for term in terms
            if term in _words(text)
        }
    )
    if leaked:
        result.update(verdict="FAIL", reason="resurfaced:" + ",".join(leaked))
        return result
    asked = any(u["accepted"] for s in later for u in s["utterances"])
    result.update(
        verdict="PASS" if asked else "REVIEW",
        later_sessions=len(later),
        **({} if asked else {"reason": "no_question_asked_after_forget"}),
    )
    return result


def q3_tools(data) -> dict:
    found = {}
    for _, u in _utterances(data):
        for t in u["tools"]:
            for kind, names in (("hands", HANDS_TOOLS), ("research", RESEARCH_TOOLS)):
                if t["name"] in names and kind not in found:
                    found[kind] = {
                        "utterance": u["id"],
                        "tool": t["name"],
                        "ok": _ok(t),
                        "reply_played": _played_after(u, t["at"]),
                        "first_audio_ms": u.get("latency_ms"),
                    }
    results = {}
    for kind in ("hands", "research"):
        item = found.get(kind)
        if item is None:
            results[kind] = {"verdict": "NOT_RUN"}
        else:
            item["verdict"] = "PASS" if item["ok"] and item["reply_played"] else "FAIL"
            results[kind] = item
    verdicts = {r["verdict"] for r in results.values()}
    overall = (
        "FAIL" if "FAIL" in verdicts else "NOT_RUN" if "NOT_RUN" in verdicts else "PASS"
    )
    return {"verdict": overall, **results}


def q4_renewal(data) -> dict:
    events = data.get("runtime_events", [])
    kinds = [e["kind"] for e in events]
    if "renewal_requested" not in kinds:
        return {"verdict": "NOT_RUN", "reason": "no_lock_unlock_observed"}
    if "renewal_ready_for_wake" in kinds:
        ready = events[kinds.index("renewal_ready_for_wake")]
        wake_session = ready.get("session_count", 0) + 1
        saved = any(
            p["kind"] == "prepared" and p.get("status") == "ready"
            for s in data["sessions"]
            if s["session"] == wake_session
            for u in s["utterances"]
            for p in u["project"]
        )
        return {
            "verdict": "PASS" if saved else "FAIL",
            "waited_ms": ready.get("waited_ms"),
            "renewed_wake_session": wake_session,
            **({} if saved else {"reason": "renewed_wake_saved_nothing"}),
        }
    if "paused_notice_spoken" in kinds:
        return {
            "verdict": "REVIEW",
            "reason": "renewal_not_approved_in_time_paused_notice_spoken",
            "events": kinds,
        }
    return {"verdict": "FAIL", "reason": "renewal_neither_ready_nor_announced"}


def qualify(data) -> dict:
    from jarvis.voice.voice_diagnostics import assess

    acceptance = assess(data)
    utterances = [_summary(u) for _, u in _utterances(data)]
    q5 = {
        "verdict": "FAIL" if acceptance["counts"]["FAIL"] else "PASS",
        "acceptance_fail": [
            {"id": r["id"], "fail": r["fail"]}
            for r in acceptance["results"]
            if r["fail"]
        ],
        "utterances": utterances,
    }
    steps = {
        "Q1_recall": q1_recall(data),
        "Q2_forget": q2_forget(data),
        "Q3_tools": q3_tools(data),
        "Q4_renewal": q4_renewal(data),
        "Q5_capture": q5,
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
        "schema": "jarvis-project-voice-qualification-v1",
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
