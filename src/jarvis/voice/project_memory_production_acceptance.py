"""Production project-memory acceptance: an auditable record of one real run.

The owner speaks the scripted steps to the installed Jarvis. Afterwards this
tool, run on the same PC, builds the record from evidence instead of
recollection:

1. the production log (``jarvis.jsonl``): what was transcribed, what Jarvis
   said, and the project-memory receipts ("turn saved | action=...", forget
   commits, clarifications);
2. the existing production memory database, opened through SQLCipher/DPAPI
   with URI ``mode=ro`` and ``query_only`` (no creation or migrations):
   which projects exist, how many owner rows each holds, whether the checked
   facts are present or absent, and personal-learning plan facts.

Each step is PASS, FAIL or NOT TESTED, with the expected reply, the actual
transcript and reply, the receipt and the database check. The record holds
your own conversation text (it is your machine), never key material. The
protected database key is unsealed internally to read encrypted memory.

Keyword checks are smoke checks, not semantic proof. Overall PASS also needs
an evidence-bound review of answers, observed restart, and actual spoken audio.

    python -m jarvis.voice.project_memory_production_acceptance --since 2026-11-04T13:00:00Z
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class Step:
    step_id: str
    say: str
    match: tuple[str, ...]  # words the owner's utterance contains
    reply_any: tuple[str, ...] = ()  # one of these must be in the reply
    reply_none: tuple[str, ...] = ()  # none of these may be in the reply
    action: str | None = None  # expected project receipt action
    forget: bool = False  # expects a forget commit


# The real-machine scenario. Memory may start non-empty: every check is about
# what this run said and stored.
SCENARIO = (
    Step(
        "1-create",
        "Create a project. Called Nepal trip.",
        ("create", "project", "nepal"),
        ("nepal trip",),
        action="created",
    ),
    Step("1-fact-vehicle", "We will take the Jimny.", ("jimny",)),
    Step("1-fact-hotel", "Our hotel is Yak and Yeti.", ("yak",)),
    Step(
        "1-fact-tentative",
        "Maybe we'll visit Pokhara, not decided yet.",
        ("pokhara", "maybe"),
    ),
    Step(
        "2-recall",
        "(new wake) Which vehicle are we taking, and is Pokhara decided?",
        ("vehicle",),
        ("jimny",),
    ),
    Step(
        "3-correct",
        "Correction: we will take the Thar, not the Jimny.",
        ("correction", "thar"),
    ),
    Step(
        "3-recall-corrected",
        "(new wake) Which vehicle are we taking?",
        ("vehicle",),
        ("thar",),
    ),
    Step(
        "4-create-second",
        "Create a project called Interview prep.",
        ("interview", "create"),
        ("interview prep",),
        action="created",
    ),
    Step("4-fact", "The interview panel is on Friday at ten.", ("panel", "friday")),
    Step(
        "4-isolation",
        "(new wake) Which hotel are we staying at?",
        ("hotel",),
        reply_none=("yak",),
    ),
    Step(
        "5-switch",
        "Can you switch to Nepal trip?",
        ("switch", "nepal"),
        ("nepal trip",),
        action="switched",
    ),
    Step(
        "5-forget",
        "Forget the Yak and Yeti hotel. (approve Windows Hello)",
        ("forget", "yak"),
        forget=True,
    ),
    Step(
        "5-recall-forgotten",
        "(new wake) Which hotel are we staying at?",
        ("hotel",),
        reply_none=("yak",),
    ),
    Step(
        "6-restart-other",
        "(restart Jarvis) Switch to Interview prep. When is the interview panel?",
        ("interview", "panel"),
        ("friday",),
    ),
    Step(
        "6-restart-tentative",
        "Switch to Nepal trip. Is Pokhara decided?",
        ("pokhara", "decided"),
        ("not",),
    ),
)

# Database facts after the full scenario.
DB_EXPECT_PRESENT = (
    ("Nepal trip", "Jimny"),
    ("Nepal trip", "Thar"),
    ("Nepal trip", "Pokhara"),
    ("Interview prep", "Friday"),
)
DB_EXPECT_ABSENT = ("Yak and Yeti", "Yeti")


# -- the production log -------------------------------------------------------------

_TRANSCRIPT = re.compile(r'^(user|assistant): "(.*)" \| turn_id=', re.DOTALL)
_SAVED = re.compile(r"^Project voice turn saved \| action=(\w+)")
_FORGET = re.compile(r"^Project history forget committed \| owner_rows=(\d+)")
_NOT_SAVED = re.compile(r"^Project voice turn not saved \| stage=(\w+)")


@dataclass
class Turn:
    at: str
    user: str
    reply: str = ""
    saved_action: str | None = None
    forget_owner_rows: int | None = None
    not_saved: str | None = None
    turn_id: str | None = None
    session_id: str | None = None


def _log_identity(event):
    return dict(re.findall(r"(?:^| \| )(turn_id|session_id)=([^ |]+)", event))


def read_timeline(log: Path, since: datetime) -> list[Turn]:
    turns: list[Turn] = []
    by_identity = {}
    latest_by_session = {}
    with log.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                entry = json.loads(line)
                if not isinstance(entry, dict):
                    continue
                stamp = str(entry.get("timestamp", ""))
                at = datetime.fromisoformat(stamp)
            except (ValueError, TypeError):
                continue
            if at.tzinfo is None or at < since:
                continue
            event = str(entry.get("event", ""))
            metadata = _log_identity(event)
            identity = metadata.get("turn_id"), metadata.get("session_id")
            if match := _TRANSCRIPT.match(event):
                role, text = match.groups()
                try:  # the transcript is logged as a JSON string
                    text = json.loads(f'"{text}"')
                except ValueError:
                    text = text.replace('\\"', '"')
                session_id = metadata.get("session_id")
                if role == "user":
                    turn = Turn(
                        stamp,
                        text,
                        turn_id=metadata.get("turn_id"),
                        session_id=session_id,
                    )
                    previous = latest_by_session.get(session_id)
                    if previous is not None and not previous.reply:
                        previous.not_saved = turn.not_saved = (
                            "ambiguous_reply_attribution"
                        )
                    turns.append(turn)
                    if all(identity) and identity not in by_identity:
                        by_identity[identity] = turn
                    elif all(identity):
                        by_identity[identity].not_saved = turn.not_saved = (
                            "duplicate_turn_identity"
                        )
                    latest_by_session[session_id] = turn
                elif session_id and (turn := latest_by_session.get(session_id)):
                    turn.reply = (turn.reply + " " + text).strip()
                continue
            # Receipt completion may arrive after a newer user transcript.
            # Legacy anonymous receipts provide no acceptance evidence.
            turn = by_identity.get(identity) if all(identity) else None
            if turn is None:
                continue
            if match := _SAVED.match(event):
                turn.saved_action = match.group(1)
            elif match := _FORGET.match(event):
                turn.forget_owner_rows = int(match.group(1))
            elif match := _NOT_SAVED.match(event):
                turn.not_saved = match.group(1)
    return turns


# -- the production database (read-only) --------------------------------------------


def read_database(open_connection, *, turn_ids=(), since=None) -> dict:
    connection = open_connection()
    try:
        connection.execute("PRAGMA query_only = ON")
        project_rows = list(
            connection.execute(
                "SELECT w.title, "
                "SUM(CASE WHEN e.role='user' THEN 1 ELSE 0 END), "
                "SUM(CASE WHEN e.role='assistant' THEN 1 ELSE 0 END) "
                "FROM conversation_workspace w "
                "LEFT JOIN conversation_thread t ON t.project_id=w.project_id "
                "LEFT JOIN conversation_event e ON e.thread_id=t.thread_id "
                "WHERE w.forgotten_at IS NULL GROUP BY w.project_id, w.title"
            )
        )
        projects = {
            title: {"owner_rows": owner, "jarvis_rows": jarvis}
            for title, owner, jarvis in project_rows
        }

        def owner_rows_with(word, title=None):
            sql = (
                "SELECT count(*) FROM conversation_event e "
                "JOIN conversation_thread t ON t.thread_id=e.thread_id "
                "JOIN conversation_workspace w ON w.project_id=t.project_id "
                "WHERE e.role='user' AND w.forgotten_at IS NULL "
                "AND instr(lower(e.text), lower(?)) > 0"
            )
            args = [word]
            if title is not None:
                sql += " AND w.title = ?"
                args.append(title)
            return int(connection.execute(sql, args).fetchone()[0])

        present = {
            f"{title}: {word}": owner_rows_with(word, title)
            for title, word in DB_EXPECT_PRESENT
        }
        absent = {word: owner_rows_with(word) for word in DB_EXPECT_ABSENT}
        plans, run_plans = [], []
        for value, recorded in connection.execute(
            "SELECT value_json, system_from FROM semantic_assertion "
            "WHERE predicate LIKE 'plan_%' AND state='active'"
        ):
            label = json.loads(value).get("label")
            plans.append(label)
            try:
                recorded_at = datetime.fromisoformat(str(recorded))
            except ValueError:
                recorded_at = None
            # Unknown time counts as this run: never hide a possible regression.
            if since is None or recorded_at is None or recorded_at >= since:
                run_plans.append(label)
        titles = [row[0] for row in project_rows]
        duplicates = sorted(
            {
                t
                for t in titles
                if [x.casefold() for x in titles].count(t.casefold()) > 1
            }
        )
        # Restrict exported content to canonical IDs from this run's log. Old
        # rows with the same words cannot satisfy a new turn's evidence.
        turns = {}
        for turn_id in set(turn_ids):
            if not turn_id:
                continue
            row = connection.execute(
                "SELECT w.title,e.text FROM conversation_event e "
                "JOIN conversation_thread t ON t.thread_id=e.thread_id "
                "JOIN conversation_workspace w ON w.project_id=t.project_id "
                "WHERE e.event_id=? AND e.role='user' AND w.forgotten_at IS NULL",
                (turn_id,),
            ).fetchone()
            if row:
                turns[turn_id] = {"project": row[0], "text": row[1]}
        return {
            "turns": turns,
            "projects": projects,
            "present": present,
            "absent": absent,
            "duplicate_titles": duplicates,
            "active_plan_labels": plans,
            "run_plan_labels": run_plans,
        }
    finally:
        connection.close()


# -- grading ------------------------------------------------------------------------


@dataclass
class StepResult:
    step_id: str
    say: str
    verdict: str
    transcript: str | None = None
    reply: str | None = None
    receipt: str | None = None
    reasons: list[str] = field(default_factory=list)


def _words(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.casefold()))


NEW_WAKE_STEPS = frozenset(
    {"2-recall", "3-recall-corrected", "4-isolation", "5-recall-forgotten"}
)
FORGOTTEN_STEPS = frozenset({"1-fact-hotel", "5-forget"})


def _expected_project(step_id):
    return (
        "Interview prep"
        if step_id.startswith("4-") or step_id == "6-restart-other"
        else "Nepal trip"
    )


def grade(timeline: list[Turn], db: dict | None, *, review=None) -> dict:
    results: list[StepResult] = []
    cursor = 0
    previous_session = None
    for step in SCENARIO:
        found = None
        for index in range(cursor, len(timeline)):
            if set(step.match) <= _words(timeline[index].user):
                found = index
                break
        if found is None:
            results.append(StepResult(step.step_id, step.say, "NOT TESTED"))
            continue
        cursor = found + 1
        turn = timeline[found]
        reply = turn.reply.casefold()
        reasons = []
        if not turn.reply.strip():
            reasons.append("no assistant reply")
        if not step.forget and not turn.saved_action:
            reasons.append("no save receipt")
        if step.step_id in NEW_WAKE_STEPS:
            if not turn.session_id or not previous_session:
                reasons.append("new wake has no session ID evidence")
            elif turn.session_id == previous_session:
                reasons.append("recall remained in the preceding wake session")
        previous_session = turn.session_id
        if db is not None and step.step_id not in FORGOTTEN_STEPS:
            row = db.get("turns", {}).get(turn.turn_id)
            if (
                not row
                or row["project"] != _expected_project(step.step_id)
                or row["text"] != turn.user
            ):
                reasons.append("canonical turn missing from expected project")
        if step.reply_any and not any(w in reply for w in step.reply_any):
            reasons.append(f"reply lacks any of {list(step.reply_any)}")
        for word in step.reply_none:
            if word in reply:
                reasons.append(f"reply contains '{word}'")
        if step.action and turn.saved_action != step.action:
            reasons.append(f"receipt action {turn.saved_action!r} != {step.action!r}")
        if step.forget and not turn.forget_owner_rows:
            reasons.append("no forget commit")
        if turn.not_saved:
            reasons.append(f"not saved at stage {turn.not_saved}")
        receipt = (
            f"saved action={turn.saved_action}"
            if turn.saved_action
            else ("not saved" if turn.not_saved else "no receipt")
        )
        if turn.forget_owner_rows is not None:
            receipt += f"; forget owner_rows={turn.forget_owner_rows}"
        results.append(
            StepResult(
                step.step_id,
                step.say,
                "FAIL" if reasons else "PASS",
                turn.user,
                turn.reply,
                receipt,
                reasons,
            )
        )
    db_checks = []
    if db is None:
        db_checks.append({"check": "database", "verdict": "NOT TESTED"})
    else:
        for key, count in db["present"].items():
            db_checks.append(
                {"check": f"present {key}", "verdict": "PASS" if count else "FAIL"}
            )
        for word, count in db["absent"].items():
            db_checks.append(
                {"check": f"absent {word}", "verdict": "FAIL" if count else "PASS"}
            )
        db_checks.append(
            {
                "check": "no duplicate project titles",
                "verdict": "FAIL" if db["duplicate_titles"] else "PASS",
            }
        )
        db_checks.append(
            {
                "check": "no plan learned from a project command",
                # Plans recorded before this run (e.g. the 2026-11-04 fact the
                # owner chose to keep) are listed, not judged: they predate the
                # fix. Without a run start, every plan counts.
                "verdict": "PASS"
                if not {"nepal trip", "interview prep"}
                & {
                    str(p).casefold()
                    for p in db.get("run_plan_labels", db["active_plan_labels"])
                }
                else "REVIEW",
            }
        )
    material = {
        "schema": 1,
        "scenario": [asdict(s) for s in SCENARIO],
        "timeline": [asdict(t) for t in timeline],
        "database": db,
    }
    digest = hashlib.sha256(
        json.dumps(material, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    review_checks = _review_checks(digest, review)
    verdicts = (
        [r.verdict for r in results]
        + [c["verdict"] for c in db_checks]
        + [c["verdict"] for c in review_checks]
    )
    overall = (
        "FAIL"
        if "FAIL" in verdicts
        else ("INCOMPLETE" if any(v != "PASS" for v in verdicts) else "PASS")
    )
    return {
        "overall": overall,
        "evidence_sha256": digest,
        "review_checks": review_checks,
        "reviewer": review["reviewer"].strip()
        if isinstance(review, dict) and isinstance(review.get("reviewer"), str)
        else None,
        "steps": [asdict(r) for r in results],
        "database": db,
        "database_checks": db_checks,
    }


REVIEW_ITEMS = tuple(s.step_id for s in SCENARIO) + ("observed-restart", "spoken-audio")


def review_template(record):
    """A human review record; generating it never approves any evidence."""
    return {
        "evidence_sha256": record["evidence_sha256"],
        "reviewer": "",
        "checks": {
            key: {"verdict": "NOT TESTED", "evidence": ""} for key in REVIEW_ITEMS
        },
    }


def _review_checks(digest, review):
    if (
        not isinstance(review, dict)
        or review.get("evidence_sha256") != digest
        or not isinstance(review.get("reviewer"), str)
        or not review["reviewer"].strip()
    ):
        return [
            {"check": "evidence-bound answer/lifecycle review", "verdict": "NOT TESTED"}
        ]
    checks = review.get("checks", {})
    output = []
    for key in REVIEW_ITEMS:
        item = checks.get(key, {}) if isinstance(checks, dict) else {}
        verdict = (
            item.get("verdict", "NOT TESTED")
            if isinstance(item, dict)
            else "NOT TESTED"
        )
        note = item.get("evidence", "") if isinstance(item, dict) else ""
        if (
            not isinstance(verdict, str)
            or verdict not in {"PASS", "FAIL", "NOT TESTED"}
            or not isinstance(note, str)
            or not note.strip()
        ):
            verdict = "NOT TESTED"
        output.append({"check": key, "verdict": verdict, "evidence": note})
    return output


def render_markdown(record: dict) -> str:
    lines = [
        f"# Project memory acceptance — {record['overall']}",
        "",
        f"Run: {record.get('since')} → {record.get('generated')}",
        "",
        "| Step | Verdict | Said (transcript) | Jarvis replied | Receipt | Why |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in record["steps"]:
        lines.append(
            "| {step_id} | {verdict} | {t} | {rep} | {rec} | {why} |".format(
                step_id=r["step_id"],
                verdict=r["verdict"],
                t=(r["transcript"] or r["say"]).replace("|", "/"),
                rep=(r["reply"] or "").replace("|", "/")[:160],
                rec=r["receipt"] or "",
                why="; ".join(r["reasons"]),
            )
        )
    lines += ["", "| Database check | Verdict |", "| --- | --- |"]
    lines += [f"| {c['check']} | {c['verdict']} |" for c in record["database_checks"]]
    lines += [
        "",
        "Evidence SHA256: " + record["evidence_sha256"],
        "",
        "Answer meaning, restart and audible output require explicit review.",
    ]
    lines += [f"- Review {c['check']}: {c['verdict']}" for c in record["review_checks"]]
    if record.get("database"):
        lines += ["", "Projects: " + json.dumps(record["database"]["projects"])]
    return "\n".join(lines) + "\n"


def _production_opener():
    from jarvis.memory.database import open_existing_memory_database_read_only
    from jarvis.memory.runtime import default_memory_database_path
    from jarvis.security.dpapi import WindowsDpapiKeyProtector

    return lambda: open_existing_memory_database_read_only(
        default_memory_database_path(), key_protector=WindowsDpapiKeyProtector()
    )


def main(argv=None, *, opener=None) -> int:
    from jarvis.observability.logging import default_jsonl_log_path

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--since", required=True, help="UTC start, ISO 8601")
    parser.add_argument("--log", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--no-database", action="store_true")
    parser.add_argument(
        "--review", type=Path, help="completed review JSON bound to this evidence"
    )
    args = parser.parse_args(argv)
    since = datetime.fromisoformat(args.since)
    if since.tzinfo is None:
        since = since.replace(tzinfo=UTC)
    log = args.log or default_jsonl_log_path()
    timeline = read_timeline(log, since)
    db = None
    if not args.no_database:
        db = read_database(
            opener or _production_opener(),
            turn_ids=[t.turn_id for t in timeline],
            since=since,
        )
    review = (
        json.loads(args.review.read_text(encoding="utf-8")) if args.review else None
    )
    record = grade(timeline, db, review=review)
    record["since"] = since.isoformat()
    record["generated"] = datetime.now(UTC).isoformat()
    out = args.out or log.parent.parent / "acceptance"
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    (out / f"project-memory-{stamp}.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    report = out / f"project-memory-{stamp}.md"
    report.write_text(render_markdown(record), encoding="utf-8")
    if args.review is None:
        (out / f"project-memory-{stamp}.review.json").write_text(
            json.dumps(review_template(record), indent=2), encoding="utf-8"
        )
    print(render_markdown(record))
    print(f"Saved: {report}")
    return 0 if record["overall"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
