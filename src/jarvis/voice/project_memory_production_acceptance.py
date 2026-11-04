"""Production project-memory acceptance: an auditable record of one real run.

The owner speaks the scripted steps to the installed Jarvis. Afterwards this
tool, run on the same PC, builds the record from evidence instead of
recollection:

1. the production log (``jarvis.jsonl``): what was transcribed, what Jarvis
   said, and the project-memory receipts ("turn saved | action=...", forget
   commits, clarifications);
2. the production memory database, opened through the normal SQLCipher/DPAPI
   path and then switched to ``PRAGMA query_only`` (nothing can be written):
   which projects exist, how many owner rows each holds, whether the checked
   facts are present or absent, and personal-learning plan facts.

Each step is PASS, FAIL or NOT TESTED, with the expected reply, the actual
transcript and reply, the receipt and the database check. The record holds
your own conversation text (it is your machine) but never keys or
credentials.

    python -m jarvis.voice.project_memory_production_acceptance --since 2026-11-04T13:00:00Z
"""

from __future__ import annotations

import argparse
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


def read_timeline(log: Path, since: datetime) -> list[Turn]:
    turns: list[Turn] = []
    with log.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            stamp = str(entry.get("timestamp", ""))
            try:
                at = datetime.fromisoformat(stamp)
            except ValueError:
                continue
            if at < since:
                continue
            event = str(entry.get("event", ""))
            if match := _TRANSCRIPT.match(event):
                role, text = match.groups()
                text = text.replace('\\"', '"')
                if role == "user":
                    turns.append(Turn(stamp, text))
                elif turns:
                    turns[-1].reply = (turns[-1].reply + " " + text).strip()
            elif turns and (match := _SAVED.match(event)):
                turns[-1].saved_action = match.group(1)
            elif turns and (match := _FORGET.match(event)):
                turns[-1].forget_owner_rows = int(match.group(1))
            elif turns and (match := _NOT_SAVED.match(event)):
                turns[-1].not_saved = match.group(1)
    return turns


# -- the production database (read-only) --------------------------------------------


def read_database(open_connection) -> dict:
    connection = open_connection()
    try:
        connection.execute("PRAGMA query_only = ON")
        projects = {
            title: {"owner_rows": owner, "jarvis_rows": jarvis}
            for title, owner, jarvis in connection.execute(
                "SELECT w.title, "
                "SUM(CASE WHEN e.role='user' THEN 1 ELSE 0 END), "
                "SUM(CASE WHEN e.role='assistant' THEN 1 ELSE 0 END) "
                "FROM conversation_workspace w "
                "LEFT JOIN conversation_thread t ON t.project_id=w.project_id "
                "LEFT JOIN conversation_event e ON e.thread_id=t.thread_id "
                "WHERE w.forgotten_at IS NULL GROUP BY w.project_id, w.title"
            )
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
        plans = [
            json.loads(value).get("label")
            for (value,) in connection.execute(
                "SELECT value_json FROM semantic_assertion "
                "WHERE predicate LIKE 'plan_%' AND state='active'"
            )
        ]
        titles = list(projects)
        duplicates = sorted(
            {
                t
                for t in titles
                if [x.casefold() for x in titles].count(t.casefold()) > 1
            }
        )
        return {
            "projects": projects,
            "present": present,
            "absent": absent,
            "duplicate_titles": duplicates,
            "active_plan_labels": plans,
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


def grade(timeline: list[Turn], db: dict | None) -> dict:
    results: list[StepResult] = []
    cursor = 0
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
                "verdict": "PASS"
                if not {"nepal trip", "interview prep"}
                & {str(p).casefold() for p in db["active_plan_labels"]}
                else "REVIEW",
            }
        )
    verdicts = [r.verdict for r in results] + [c["verdict"] for c in db_checks]
    overall = (
        "FAIL"
        if "FAIL" in verdicts
        else ("INCOMPLETE" if "NOT TESTED" in verdicts else "PASS")
    )
    return {
        "overall": overall,
        "steps": [asdict(r) for r in results],
        "database": db,
        "database_checks": db_checks,
    }


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
    if record.get("database"):
        lines += ["", "Projects: " + json.dumps(record["database"]["projects"])]
    return "\n".join(lines) + "\n"


def _production_opener():
    from jarvis.memory.database import SqlCipherMemoryDatabaseFactory
    from jarvis.memory.runtime import default_memory_database_path
    from jarvis.security.dpapi import WindowsDpapiKeyProtector

    factory = SqlCipherMemoryDatabaseFactory(
        default_memory_database_path(), key_protector=WindowsDpapiKeyProtector()
    )
    return factory.open


def main(argv=None, *, opener=None) -> int:
    from jarvis.observability.logging import default_jsonl_log_path

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--since", required=True, help="UTC start, ISO 8601")
    parser.add_argument("--log", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--no-database", action="store_true")
    args = parser.parse_args(argv)
    since = datetime.fromisoformat(args.since)
    if since.tzinfo is None:
        since = since.replace(tzinfo=UTC)
    log = args.log or default_jsonl_log_path()
    timeline = read_timeline(log, since)
    db = None
    if not args.no_database:
        db = read_database(opener or _production_opener())
    record = grade(timeline, db)
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
    print(render_markdown(record))
    print(f"Saved: {report}")
    return 0 if record["overall"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
