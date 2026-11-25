"""Held-out execution for personal-memory slice 1 (lab only).

The sealed held-out cases (docs/evals/personal-memory-heldout.md) are never
read by code or by the developer. At execution time, after separate owner
approval, the operator transcribes each case's conversation into a script
(JSON, below) on the PC. This player runs the script once through the same
frozen code and lab path as development acceptance (real learning, the voice
agent's personal-context instructions and the real tools), on isolated
fictional memory per case, and records everything needed for manual grading
against the sealed expectations. It grades nothing itself: every case is
REVIEW. The script's sha256 and the held-out file's sha256 are recorded.

Script::

    {"cases": [
      {"id": "H1",
       "steps": [
         {"seed": [{"category": "owned_item", "label": "Pulsar 150",
                    "kind": "vehicle"}]},
         {"say": "...", "told_at": "2026-11-17T10:00:00+05:30"},
         {"say": "...", "told_at": "...", "same_conversation": true},
         {"restart": true},
         {"say": "...", "told_at": "...", "explicit_tools": true}
       ]}
    ]}

A case may only seed, say and restart. "same_conversation" continues the
previous turn's conversation (default: a new one). "explicit_tools" offers
the explicit memory tools (remember/correct/forget, Windows Hello) for that
turn, as in D3/D17.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from jarvis.voice import personal_memory_acceptance as acceptance

_CASE_ID = re.compile(r"^H\d{1,2}$")
_SEED_KEYS = {"category", "label", "kind", "details", "aliases", "plan_status", "state"}
_SEED_CATEGORIES = {"owned_item", "plan"}


class HeldoutScriptError(ValueError):
    pass


def _told(value, where):
    try:
        moment = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise HeldoutScriptError(f"{where}: told_at must be ISO 8601") from None
    if moment.tzinfo is None:
        raise HeldoutScriptError(f"{where}: told_at needs a UTC offset")
    return moment


def load_script(path: Path):
    """Validated steps per case: (groups_map, checks_map, planned, sha256)."""
    raw = Path(path).read_bytes()
    try:
        script = json.loads(raw)
    except ValueError:
        raise HeldoutScriptError("script is not JSON") from None
    cases = script.get("cases") if isinstance(script, dict) else None
    if not isinstance(cases, list) or not cases:
        raise HeldoutScriptError("script needs a non-empty 'cases' list")
    groups, checks, seen = {}, {}, set()
    for case in cases:
        cid = case.get("id") if isinstance(case, dict) else None
        if not isinstance(cid, str) or not _CASE_ID.match(cid) or cid in seen:
            raise HeldoutScriptError(f"bad or repeated case id: {cid!r}")
        seen.add(cid)
        steps, says = [], 0
        for n, item in enumerate(case.get("steps") or (), 1):
            where = f"{cid} step {n}"
            if (
                not isinstance(item, dict)
                or len({"seed", "say", "restart"} & set(item)) != 1
            ):
                raise HeldoutScriptError(f"{where}: exactly one of seed/say/restart")
            if "seed" in item:
                facts = []
                for fact in item["seed"] or ():
                    if not isinstance(fact, dict) or set(fact) - _SEED_KEYS:
                        raise HeldoutScriptError(f"{where}: unknown seed fields")
                    if fact.get("category") not in _SEED_CATEGORIES or not fact.get(
                        "label"
                    ):
                        raise HeldoutScriptError(
                            f"{where}: seeds are owned items or plans with a label"
                        )
                    facts.append(
                        acceptance.SeedFact(
                            category=fact["category"],
                            label=fact["label"],
                            kind=fact.get("kind", "other"),
                            details=fact.get("details"),
                            aliases=tuple(fact.get("aliases") or ()),
                            plan_status=fact.get("plan_status"),
                            state=fact.get("state", "owned"),
                        )
                    )
                if not facts:
                    raise HeldoutScriptError(f"{where}: empty seed")
                steps.append(acceptance.Seed(f"{cid}-{n:02d}", tuple(facts)))
            elif "restart" in item:
                steps.append(acceptance.Restart(f"{cid}-{n:02d}"))
            else:
                text = item.get("say")
                if not isinstance(text, str) or not text.strip():
                    raise HeldoutScriptError(f"{where}: empty say")
                if set(item) - {
                    "say",
                    "told_at",
                    "same_conversation",
                    "explicit_tools",
                }:
                    raise HeldoutScriptError(f"{where}: unknown fields")
                if item.get("same_conversation") and says == 0:
                    raise HeldoutScriptError(f"{where}: nothing to continue")
                steps.append(
                    acceptance.Say(
                        f"{cid}-{n:02d}",
                        cid,
                        text,
                        _told(item.get("told_at"), where),
                        new_session=not item.get("same_conversation", False),
                        explicit_tools=bool(item.get("explicit_tools", False)),
                    )
                )
                says += 1
        if not says:
            raise HeldoutScriptError(f"{cid}: a case needs at least one say")
        steps.append(acceptance.Check(f"{cid}-record", cid))
        groups[cid] = tuple(steps)
        checks[cid] = _recorder(
            tuple(s.id for s in steps if isinstance(s, acceptance.Say))
        )
    return groups, checks, tuple(groups), hashlib.sha256(raw).hexdigest()


def _summary(row):
    value = acceptance._value(row)
    return {
        "current": row["current"],
        "category": value.get("category"),
        "label": value.get("label"),
        "value": value.get("value"),
        "state": value.get("state"),
        "certainty": value.get("certainty"),
        "plan_status": value.get("plan_status"),
        "slots": value.get("slots"),
        "acquired": value.get("acquired"),
        "disposed": value.get("disposed"),
        "temporal": value.get("temporal"),
        "evidence_text": row.get("evidence_text"),
    }


def _recorder(say_ids):
    async def record(context, log):
        rows = await acceptance._rows(context.memory)
        replies = {
            sid: {
                "answer": (context.replies.get(sid) or {}).get("answer"),
                "tools": (context.replies.get(sid) or {}).get("tools"),
                "learning": (context.replies.get(sid) or {}).get("learning"),
            }
            for sid in say_ids
        }
        return [
            {
                "check": "stored records (current and history), for manual grading",
                "level": "a",
                "status": acceptance.REVIEW,
                "detail": [_summary(r) for r in rows],
            },
            {
                "check": "lookups, learning outcomes and answers, for manual grading",
                "level": "c",
                "status": acceptance.REVIEW,
                "detail": replies,
            },
        ]

    return record
