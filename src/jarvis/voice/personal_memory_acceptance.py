"""Personal memory slice 1: frozen development acceptance (D1-D27), text lab.

Runs the frozen development cases in ``docs/evals/personal-memory-acceptance.md``
(never the sealed held-out file) through the real slice-1 code with fictional
data in isolated lab databases:

- every owner utterance is accepted into a conversation and observed by the
  real learning runtime (Gemini extraction and resolution, deterministic
  policy, reconciler, admission), exactly as live Jarvis does;
- Jarvis's reply is produced by a text driver: the Free-lane answer model
  receives the voice agent's own personal-context instructions
  (``PERSONAL_LEARNING_QUERY_INSTRUCTIONS``) and calls the real
  ``read_personal_context_for_question`` (with paging) and, on explicit
  memory-command turns only (D3, D17), the real catalog and memory tools.
  This is controlled text, not Gemini Live voice;
- each case is graded at (a) stored record and (b) release automatically;
  (c) answers are recorded for manual grading (keyword flags only locate
  problems, they never pass an answer).

Told dates: the frozen cases state when things were said (for example "told
Wed 2026-11-18"). The lab sets each accepted turn's time to that told time so
relative dates anchor exactly as specified. ``recorded_at`` in releases is the
real time the lab wrote the fact.

Provider failures (owner policy 2026-11-21, ``jarvis.provider_retry``): a
temporary provider failure (503/502/500, lost connection) is retried at most
twice, inside the existing deadline. Learning retries are made by Jarvis's
learning runtime itself (the product behaviour); answer steps use the same
policy here, with one owner per call. Every attempt is recorded. 429, quota,
permission, invalid-request, invalid-output and stall failures are never
retried. A failure that remains interrupts the run after recording that step;
completed steps and their results are kept, and ``--resume-lab`` continues from
the next step that never started. An interrupted step is rerun only with the
explicit ``--retry-interrupted`` owner option and is then recorded as attempt 2.
The summary reports first-attempt reliability separately from eventual
completion; stalls stay explicitly unresolved.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
import re
import time
from dataclasses import dataclass, field
from dataclasses import replace as dc_replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, create_model

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.provider_retry import policy_summary

KIND = "personal-memory-slice1-dev-acceptance-v1"
ACCEPTANCE_FILE = "docs/evals/personal-memory-acceptance.md"
HELDOUT_FILE = "docs/evals/personal-memory-heldout.md"
FROZEN_SHA256 = {
    ACCEPTANCE_FILE: "ed249d688826a18263fd578ff7980a2619057845a674c28d94763bbd5cb3823b",
    HELDOUT_FILE: "fb2c36a4f29eb4638b863d9e1db142599b3c7b265ffbab6db360195dd21d08a1",
}
# Owner-approved amendments (2026-11-23 18:51 IST). Kept in their own file;
# the frozen case files above are never edited. The lab refuses to start if an
# active amendment's file differs from the approved version.
AMENDMENT_1_FILE = "docs/evals/personal-memory-acceptance-amendment-1.md"
AMENDMENT_2_FILE = "docs/evals/personal-memory-acceptance-amendment-2.md"
ACCEPTANCE_AMENDMENTS = (
    {
        "id": "amendment-1",
        "status": "active",
        "approved": "2026-11-23 18:51 IST",
        "file": AMENDMENT_1_FILE,
        "sha256": "003f2fedca2b6c02a528d1158ecc4e012be1526aa3424348317605f94c0ba2d5",
        "replaces": {"D1": "D1-A1"},
        "adds": ["D1-R"],
        "supersedes": (
            "frozen D1 expectation that 'have a Royal Enfield Classic 350 from"
            " 2021' sets purchase year 2021"
        ),
    },
    {
        "id": "amendment-2",
        "status": "active",
        "approved": "2026-11-25 13:40 IST",
        "file": AMENDMENT_2_FILE,
        "sha256": "57772e6b568b9b9db81c939fecf34cc83c75a638224b22fd4abf49f1975b3b2e",
        "replaces": {"D6": "D6-A2"},
        "adds": ["D28", "D29", "D30"],
        "supersedes": (
            "frozen D6 expectation that destination options are stored from the"
            " single statement, before the owner confirms them"
        ),
    },
)
D6_CONFIRMATION = "Yes, still deciding between those."
D1_FROZEN_TEXT = (
    "I have a Royal Enfield Classic 350 from 2021, a Tata Tigor I bought in"
    " March 2017, and last month I got a Jimny."
)
D1_A1_TEXT = (
    "I have a Royal Enfield Classic 350 I bought in 2021, a Tata Tigor I bought"
    " in March 2017, and last month I got a Jimny."
)
OWNER_TZ = timezone(timedelta(hours=5, minutes=30), "IST")
MAX_DRIVER_STEPS = 8
SEED_BATCH = 40
CHILD_LEASE_SECONDS = 31
PASS, FAIL, REVIEW, UNTESTED = "PASS", "FAIL", "REVIEW", "UNTESTED"
# An expectation an approved amendment replaced: reported with the observed
# value for the record, never PASS or FAIL, and never part of any verdict.
SUPERSEDED = "SUPERSEDED"


DEFAULT_CALL_SPACING_SECONDS = 6.0


class FreeLanePacer:
    """One shared budget for every model call of the run (learning
    extraction, learning resolution and answer steps all use the same Free
    key): on average one call per ``spacing`` seconds.

    It never waits inside Jarvis's learning deadline (run 2: waiting there
    consumed up to 6 s of the 25 s inference budget). Instead the harness
    waits for a free slot (:meth:`ready`) before an owner turn is observed;
    the learning calls then run as production would, and are counted
    afterwards (:meth:`note`), pushing the next slot later. Answer steps wait
    as usual (:meth:`wait`). At most the turn's two learning calls run back
    to back. This lowers the chance of a per-minute limit; it cannot rule
    out every limit (daily quota, token limits, provider-side bursts), and a
    refusal still stops the run without a retry."""

    def __init__(self, spacing, *, clock=time.monotonic, sleep=None):
        import asyncio

        if not 0 < float(spacing) <= 120:
            raise ValueError("call spacing must be in (0, 120] seconds")
        self.spacing = float(spacing)
        self._clock = clock
        self._sleep = sleep or asyncio.sleep
        self._lock = asyncio.Lock()
        self._next = None  # earliest start of the next paced call
        self.calls = 0
        self.waited = 0.0

    def _advance(self):
        now = self._clock()
        base = self._next if self._next is not None and self._next > now else now
        self._next = base + self.spacing
        self.calls += 1

    async def ready(self):
        """Wait until the next call may start, without using the slot."""
        async with self._lock:
            if self._next is not None:
                delay = self._next - self._clock()
                if delay > 0:
                    self.waited += delay
                    await self._sleep(delay)

    def note(self, count=1):
        """Count calls that ran without waiting (inside a learning turn)."""
        for _ in range(max(0, int(count))):
            self._advance()

    async def wait(self):
        """Wait for a slot and use it (answer steps)."""
        await self.ready()
        async with self._lock:
            self._advance()


class AcceptanceInterrupted(RuntimeError):
    """A provider failure stopped the run; completed steps are preserved."""


class AcceptanceStoppedOnFailure(RuntimeError):
    """A definite acceptance failure (FAIL, or UNTESTED from a broken
    prerequisite) was recorded; dependent cases are not run."""


class _CheckpointReached(Exception):
    pass


class AcceptanceRecoveryRefused(RuntimeError):
    """The requested recovery's preconditions do not hold; nothing was run."""


# D17 consent recovery (owner instruction 2026-11-24 14:48): only when D17
# stopped because fresh owner consent (Windows Hello) was not granted, the
# correct item was selected and deletion was never attempted. Reruns only the
# forget turn and its check, as a new attempt; the original attempt stays in
# the logs, Windows Hello stays mandatory, and the run pauses after the check.
D17_RECOVERY_ID = "d17-consent-recovery-1"
D17_RECOVERY_STEPS = ("story-18", "story-18c")


# Paid checkpoint (owner instruction 2026-11-24): learning (story-01..04),
# a lookup and an answer (story-05, "When did I sell it?"), with the D1-A1,
# D2 and D5 checks; then pause for review.
CHECKPOINT_STOP_AFTER = "story-05c"


def told(day, hour=10, minute=0, month=11):
    return datetime(2026, month, day, hour, minute, tzinfo=OWNER_TZ)


def frozen_hashes(repo: Path) -> dict[str, str]:
    """Refuse to run unless both frozen case files are unchanged.

    The hash is of the committed content: a Windows checkout's CRLF line
    endings are normalized back to LF first, so only a real edit differs."""
    observed = {}
    for name, expected in FROZEN_SHA256.items():
        content = (repo / name).read_bytes().replace(b"\r\n", b"\n")
        digest = hashlib.sha256(content).hexdigest()
        if digest != expected:
            raise ValueError(f"frozen case file changed: {name}")
        observed[name] = digest
    return observed


def active_amendments(repo: Path) -> list[dict]:
    """Refuse to run unless every active amendment file is the approved one
    (CRLF normalized, as for the frozen files)."""
    out = []
    for amendment in ACCEPTANCE_AMENDMENTS:
        content = (repo / amendment["file"]).read_bytes().replace(b"\r\n", b"\n")
        if hashlib.sha256(content).hexdigest() != amendment["sha256"]:
            raise ValueError(f"approved amendment file changed: {amendment['file']}")
        out.append(dict(amendment))
    return out


# ---------------------------------------------------------------- script --


@dataclass(frozen=True)
class SeedFact:
    """A harness seed admitted through the real learning admission path with
    a fixed proposal (no model call). Seeds are setup, never graded."""

    category: str
    label: str
    kind: str = "other"
    details: str | None = None
    aliases: tuple[str, ...] = ()
    plan_status: str | None = None
    state: str = "owned"
    told_at: datetime = field(default_factory=lambda: told(10))

    def sentence(self):
        if self.category == "plan":
            return f"We are planning the {self.label}."
        text = f"I have a {self.label}"
        if self.details:
            text += f", {self.details}"
        if self.aliases:
            text += ", which I also call " + " or ".join(self.aliases)
        return text + "."


@dataclass(frozen=True)
class Seed:
    id: str
    facts: tuple[SeedFact, ...]
    note: str = ""


@dataclass(frozen=True)
class Say:
    id: str
    case: str
    text: str
    told_at: datetime
    new_session: bool = True
    explicit_tools: bool = False
    note: str = ""


@dataclass(frozen=True)
class SeedExplicit:
    """A legacy explicit record written through the explicit service path
    (harness setup, no Hello): used for D3's pre-existing combined record."""

    id: str
    predicate: str
    value: str
    told_at: datetime


@dataclass(frozen=True)
class Restart:
    id: str
    note: str = "Restart: the encrypted database is closed and reopened, with a new conversation and learning runtime."


@dataclass(frozen=True)
class Check:
    id: str
    case: str


def _vehicles(prefix, count, *, kind="vehicle", **extra):
    return tuple(
        SeedFact("owned_item", f"{prefix} {i:02d}", kind=kind, **extra)
        for i in range(1, count + 1)
    )


_LONG = (
    "a fictional long-distance touring build with aluminium panniers, crash"
    " guards, a tall adjustable screen, heated grips, auxiliary fog lamps, a"
    " luggage rack and two spare fuel cans strapped behind the pillion seat"
)

GROUPS = {
    # One continuing owner story. Cases run in an order consistent with the
    # frozen text: D13's plan is stated first (told September); D23 sells the
    # Classic 350 after D14-D16 rely on it; D17 forgets it last.
    "story": (
        Say(
            "story-01",
            "D13",
            "We're planning a Rishikesh trip in October 2026.",
            told(15, month=9),
            note="D13 setup: the plan is stored before it elapses (harness-chosen fictional wording)",
        ),
        Say(
            "story-02",
            "D1-A1",
            D1_A1_TEXT,
            told(17),
            note="amendment-1 wording (D1-A1 replaces the frozen D1 wording)",
        ),
        Check("story-02c", "D1-A1"),
        Say(
            "story-03",
            "D2",
            "I bought the Tigor in March 2017, it's the diesel one.",
            told(17, 15),
        ),
        Check("story-03c", "D2"),
        Say("story-04", "D5", "I sold the Tigor last week.", told(18)),
        Say(
            "story-05",
            "D5",
            "When did I sell it?",
            told(18, 10, 1),
            new_session=False,
        ),
        Check("story-05c", "D5"),
        Say("story-06", "D22", "Which vehicles do I own?", told(18, 11)),
        Check("story-06c", "D22"),
        Say(
            "story-07",
            "D6-A2",
            "I'm planning a Ladakh or winter Spiti trip in January.",
            told(18, 12),
        ),
        Say(
            "story-07b",
            "D6-A2",
            D6_CONFIRMATION,
            told(18, 12, 1),
            new_session=False,
            note="amendment-2 confirmation turn (D6-A2)",
        ),
        Check("story-07c", "D6-A2"),
        Say("story-08", "D7", "Maybe we'll do Goa this winter.", told(18, 13)),
        Check("story-08c", "D7"),
        Say(
            "story-09",
            "D8",
            "Kaza or Manali, which has better fuel stations?",
            told(18, 14),
        ),
        Check("story-09c", "D8"),
        Say(
            "story-10",
            "D10",
            "We're going with winter Spiti, and we'll take the Jimny.",
            told(19),
        ),
        Check("story-10c", "D10"),
        Say("story-11", "D11", "Cancel the Goa plan.", told(19, 11)),
        Check("story-11c", "D11"),
        Say(
            "story-12",
            "D12",
            "I misspoke, the Jimny is from September, not October.",
            told(19, 12),
        ),
        Check("story-12c", "D12"),
        Say("story-13", "D13", "What's coming up?", told(20)),
        Check("story-13c", "D13"),
        Restart("story-restart"),
        Say(
            "story-14",
            "D14",
            "Which vehicles do I own and since when?",
            told(20, 10, 5),
        ),
        Check("story-14c", "D14"),
        Say(
            "story-15",
            "D15",
            "Which of my vehicles is best for a snowy Spiti trip?",
            told(20, 10, 10),
        ),
        Check("story-15c", "D15"),
        Say(
            "story-16",
            "D16",
            "How do you know I have a Jimny, and when did I tell you?",
            told(20, 10, 15),
        ),
        Check("story-16c", "D16"),
        Say("story-17", "D23", "I sold the Classic 350 in October.", told(20, 11)),
        Check("story-17c", "D23"),
        Say(
            "story-18",
            "D17",
            "Forget the Classic 350.",
            told(20, 12),
            explicit_tools=True,
        ),
        Check("story-18c", "D17"),
        Check("story-18d", "D26"),
        Check("story-18e", "D21"),
    ),
    "explicit-list": (
        SeedExplicit("list-00", "devices", "a Kindle and a Fitbit", told(10)),
        Say(
            "list-01",
            "D3",
            "Remember my devices are a Dell XPS and an iPad Air.",
            told(17),
            explicit_tools=True,
        ),
        Check("list-01c", "D3"),
    ),
    "ambiguous-bike": (
        Seed(
            "bike-00",
            (
                SeedFact("owned_item", "Classic 350", kind="vehicle"),
                SeedFact("owned_item", "Pulsar 150", kind="vehicle"),
                SeedFact(
                    "plan",
                    "Spiti trip in January",
                    plan_status="planned",
                    state="planned",
                ),
            ),
            note="D4 setup: two bikes saved (and one trip)",
        ),
        Say(
            "bike-01",
            "D4",
            "Should I service my bike before the trip?",
            told(17),
        ),
        Check("bike-01c", "D4"),
    ),
    "idiom": (
        Say(
            "idiom-01",
            "D9",
            "We're going to Spiti in January, Thar or no Thar.",
            told(18),
        ),
        Say(
            "idiom-02",
            "D9",
            "Either way, January.",
            told(18, 10, 1),
            new_session=False,
        ),
        Check("idiom-02c", "D9"),
    ),
    "scale-11": (
        Seed("s11-00", _vehicles("Vehicle", 11), note="D18 setup: 11 vehicles"),
        Say("s11-01", "D18", "Which vehicles do I own?", told(17)),
        Check("s11-01c", "D18"),
    ),
    "scale-90": (
        Seed(
            "s90-00",
            tuple(
                SeedFact(
                    "plan",
                    f"Weekend trip to Harbourtown {i:02d}",
                    plan_status="planned",
                    state="planned",
                )
                for i in range(1, 46)
            )
            + _vehicles("Gadget", 45, kind="device"),
            note="D19 setup: 45 plans and 45 devices (90 standard rows)",
        ),
        Say(
            "s90-01",
            "D19",
            "I just bought a Hero Xoom scooter.",
            told(17),
            note="D19 learning (harness-chosen fictional wording)",
        ),
        Say(
            "s90-02",
            "D19",
            "What trips am I planning?",
            told(17, 10, 5),
            note="D19 lookup (harness-chosen fictional wording)",
        ),
        Check("s90-02c", "D19"),
    ),
    "bytes": (
        Seed(
            "bytes-00",
            tuple(
                SeedFact(
                    "owned_item",
                    f"Tourer {i:02d}",
                    kind="vehicle",
                    details=f"{_LONG} number {i:02d}",
                    aliases=(
                        f"the long-haul highway tourer for mountain passes {i:02d}",
                        f"the big adventure machine with the tall screen {i:02d}",
                        f"the mountain expedition ride with heated grips {i:02d}",
                        f"the fully loaded touring motorcycle for Spiti {i:02d}",
                    ),
                )
                for i in range(1, 7)
            ),
            note="D20 setup: 6 vehicles with long details (over 3,000 bytes)",
        ),
        Say(
            "bytes-01",
            "D20",
            "Which vehicles do I own?",
            told(17),
            note="D20 question (harness-chosen fictional wording)",
        ),
        Check("bytes-01c", "D20"),
    ),
    "ambiguous-plan": (
        Seed(
            "plan40-00",
            tuple(
                SeedFact(
                    "plan",
                    f"paragliding trip {i:02d}",
                    plan_status="planned",
                    state="planned",
                )
                for i in range(1, 41)
            ),
            note="D24 setup: 40 near-identical trip plans",
        ),
        Say("plan40-01", "D24", "Add Bir to the paragliding trip.", told(17)),
        Check("plan40-01c", "D24"),
    ),
    # Amendment 1: the frozen D1 wording verbatim, on its own isolated memory.
    # "from 2021" is ambiguous and must never invent a purchase date.
    "d1-regression": (
        Say("d1r-01", "D1-R", D1_FROZEN_TEXT, told(17)),
        Check("d1r-01c", "D1-R"),
    ),
    # Amendment 2: the other answers to a question about plan alternatives,
    # each in its own conversation on this group's isolated memory.
    "alternatives": (
        Say(
            "alt-01", "D28", "We're going to Spiti in January, Thar or Jimny.", told(18)
        ),
        Say(
            "alt-02",
            "D28",
            "We'll take the Jimny.",
            told(18, 10, 1),
            new_session=False,
        ),
        Check("alt-02c", "D28"),
        Say(
            "alt-03",
            "D29",
            "We're going to Kerala in March, train or flight.",
            told(18, 11),
        ),
        Say(
            "alt-04",
            "D29",
            "Doesn't matter, either is fine.",
            told(18, 11, 1),
            new_session=False,
        ),
        Check("alt-04c", "D29"),
        Say(
            "alt-05",
            "D30",
            "We're going to Goa in April, Airbnb or hotel.",
            told(18, 12),
        ),
        Say(
            "alt-06",
            "D30",
            "What's the weather like there in April?",
            told(18, 12, 1),
            new_session=False,
        ),
        Say("alt-07", "D30", D6_CONFIRMATION, told(18, 13)),
        Check("alt-07c", "D30"),
    ),
    "pages": (
        Seed("p40-00", _vehicles("Vehicle", 40), note="D25 setup: 40 vehicles"),
        Say("p40-01", "D25", "List all my vehicles.", told(17)),
        Check("p40-01c", "D25"),
    ),
}

GROUP_ORDER = tuple(GROUPS)
CASES_RUN = tuple(
    sorted(
        {s.case for g in GROUPS.values() for s in g if hasattr(s, "case")},
        key=lambda c: (int(re.match(r"D(\d+)", c).group(1)), c),
    )
)
NOT_RUN_HERE = {
    "D27": "Recorded from the owner-run migration rehearsal on the real encrypted database (commit 40211ad5, 2026-11-21): PASS. Not rerun in this lab.",
}


# ----------------------------------------------------------- lab clock ----


class LabConversation(ConversationSession):
    """A conversation whose accepted turns carry the frozen case's told time."""

    def accept_at(self, role, text, at):
        turn = self.accept_turn(role, text)
        stamped = dc_replace(turn, accepted_at=at.astimezone(UTC))
        self._turns[-1] = stamped
        return stamped


# --------------------------------------------------------- results files --


class ResultLog:
    """Append-only JSONL files; a step is complete only once its row is written."""

    def __init__(self, root: Path, *, commit, hashes, models, echo=False):
        self.root = root
        self.echo = echo
        self.events = root / "acceptance-events.jsonl"
        self.steps = root / "acceptance-steps.jsonl"
        self.cases = root / "acceptance-cases.jsonl"
        self.summary = root / "acceptance-summary.json"
        self.meta = {
            "kind": KIND,
            "source_commit": commit,
            "case_files": hashes,
            "acceptance_amendments": [
                {k: a[k] for k in ("id", "status", "file", "sha256")}
                for a in ACCEPTANCE_AMENDMENTS
            ],
            "evidence_kind": "controlled_text",
            **models,
        }

    def _append(self, path, row):
        row = {**row, "at": datetime.now(UTC).isoformat()}
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            stream.flush()

    def event(self, row):
        self._append(self.events, {"lane": self.meta.get("lane"), **row})

    def step(self, row):
        self._append(self.steps, {**self.meta, **row})
        if self.echo and row["status"] != "checked":
            extra = row.get("learning") or row.get("reason") or row.get("seeded") or ""
            print(
                f"[{row['group']}] {row['step_id']} {row['status']} {extra}", flush=True
            )

    def case(self, row):
        self._append(self.cases, {**self.meta, **row})
        if self.echo:
            print(f"[{row['group']}] {row['case']} {row['status']}", flush=True)

    def read(self, path):
        if not path.is_file():
            return []
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def step_states(self):
        """Latest recorded status per step id."""
        states = {}
        for row in self.read(self.steps):
            states[row["step_id"]] = row
        return states


# ------------------------------------------------------- recording model --


class RecordingAdapter:
    """Wraps the real learning adapter: records every provider attempt
    (proposals, decisions, failures). It never retries; retries of temporary
    failures are made by the learning runtime, the single retry owner."""

    def __init__(self, inner, log, group, pacer=None):
        self.inner, self.log, self.group = inner, log, group
        self.pacer = pacer
        self.step_id = None
        self.provider_failures = []
        self.stage_attempts = {}
        self.stage_final = {}

    def unrecovered(self):
        """Stages whose last attempt this step was a provider failure."""
        return [s for s, status in self.stage_final.items() if status != "ok"]

    def start_step(self, step_id):
        self.step_id = step_id
        self.provider_failures = []
        self.stage_attempts = {}
        self.stage_final = {}

    def bind_source_validator(self, validator):
        binder = getattr(self.inner, "bind_source_validator", None)
        if callable(binder):
            binder(validator)

    async def extract(self, source, open_questions=()):
        if open_questions:
            # Jarvis's open questions (amendment 2), passed through unchanged.
            return await self._call(
                "extraction",
                lambda s: self.inner.extract(s, open_questions=open_questions),
                source,
            )
        return await self._call("extraction", self.inner.extract, source)

    async def resolve(self, source, batch, catalog):
        return await self._call(
            "resolution", self.inner.resolve, source, batch, catalog
        )

    async def _call(self, stage, operation, *args):
        # Never wait here: this runs inside Jarvis's learning deadline. The
        # harness waited for a pacing slot before the turn was observed.
        attempts = getattr(self.inner, "attempts", None)
        attempt = self.stage_attempts.get(stage, 0) + 1
        self.stage_attempts[stage] = attempt
        started = time.perf_counter()
        try:
            result = await operation(*args)
        except BaseException as exc:
            self._count(attempts)
            if not isinstance(exc, Exception):
                # Cancelled at the learning deadline: the call was still
                # waiting for the provider (no retry follows).
                self.log.event(
                    {
                        "group": self.group,
                        "step_id": self.step_id,
                        "kind": "learning_" + stage,
                        "attempt": attempt,
                        "status": "cancelled_at_deadline",
                        "latency_ms": round((time.perf_counter() - started) * 1000),
                    }
                )
                raise
            failure = getattr(self.inner, "last_failure", None)
            provider = str(exc) == "learning_provider_unavailable"
            self.stage_final[stage] = "provider_failure" if provider else "ok"
            kind = getattr(
                getattr(getattr(exc, "failure", None), "kind", None), "value", None
            )
            if provider:
                self.provider_failures.append(
                    {
                        "stage": stage,
                        "attempt": attempt,
                        "failure_kind": kind,
                        **(failure or {}),
                    }
                )
            self.log.event(
                {
                    "group": self.group,
                    "step_id": self.step_id,
                    "kind": "learning_" + stage,
                    "attempt": attempt,
                    "status": "provider_failure" if provider else "failed",
                    "failure_kind": kind,
                    "error": str(exc)
                    if str(exc).startswith("learning_")
                    else type(exc).__name__,
                    "failure": failure,
                    "latency_ms": round((time.perf_counter() - started) * 1000),
                }
            )
            raise
        self._count(attempts)
        self.stage_final[stage] = "ok"
        self.log.event(
            {
                "group": self.group,
                "step_id": self.step_id,
                "kind": "learning_" + stage,
                "attempt": attempt,
                "status": "ok",
                "output": result.model_dump(mode="json"),
                "latency_ms": round((time.perf_counter() - started) * 1000),
            }
        )
        return result

    def _count(self, attempts_before):
        """Count the provider calls this adapter call made (none when the
        resolver decided deterministically)."""
        if self.pacer is None:
            return
        after = getattr(self.inner, "attempts", None)
        if isinstance(attempts_before, int) and isinstance(after, int):
            self.pacer.note(after - attempts_before)
        else:
            self.pacer.note(1)


# ------------------------------------------------------------ text driver --


DRIVER_PREAMBLE = """You are Jarvis, the owner's personal assistant, in a controlled TEXT test with
fictional data. Reply to the latest owner utterance. Each response is exactly one
JSON action matching the schema: either call one tool or give the final spoken
answer. Tool results so far are in tool_results; never repeat an identical call.
Tools available on this turn are listed in available_tools with their exact
descriptions. Answer in short natural speech, in the owner's language.
"""


class _Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: str = Field(min_length=1, max_length=4000)


def _driver_model(tools):
    from jarvis.voice.project_answer_provider import _ProjectPersonalRequest

    class _ReadArgs(BaseModel):
        model_config = ConfigDict(extra="forbid")
        requests: list[_ProjectPersonalRequest] = Field(min_length=1, max_length=4)
        page_token: str | None = Field(default=None, min_length=1, max_length=512)

    class _Read(BaseModel):
        model_config = ConfigDict(extra="forbid")
        read_personal_context_for_question: _ReadArgs

    class _CatalogArgs(BaseModel):
        model_config = ConfigDict(extra="forbid")

    class _Catalog(BaseModel):
        model_config = ConfigDict(extra="forbid")
        personal_context_catalog: _CatalogArgs

    class _FacetArgs(BaseModel):
        model_config = ConfigDict(extra="forbid")
        catalog_id: str = Field(min_length=1, max_length=128)
        facet_indices: list[int] = Field(min_length=1, max_length=4)

    class _Facets(BaseModel):
        model_config = ConfigDict(extra="forbid")
        read_personal_context: _FacetArgs

    class _RememberArgs(BaseModel):
        model_config = ConfigDict(extra="forbid")
        predicate: str = Field(min_length=1, max_length=128)
        value: str = Field(min_length=1, max_length=1000)

    class _Remember(BaseModel):
        model_config = ConfigDict(extra="forbid")
        remember_memory: _RememberArgs

    class _ChangeArgs(BaseModel):
        model_config = ConfigDict(extra="forbid")
        predicate: str = Field(min_length=1, max_length=128)
        value: str | None = Field(default=None, max_length=1000)
        catalog_id: str | None = Field(default=None, max_length=128)
        facet_index: int | None = Field(default=None, ge=0, le=127)

    class _Correct(BaseModel):
        model_config = ConfigDict(extra="forbid")
        correct_memory: _ChangeArgs

    class _Forget(BaseModel):
        model_config = ConfigDict(extra="forbid")
        forget_memory: _ChangeArgs

    class _Status(BaseModel):
        model_config = ConfigDict(extra="forbid")
        memory_status: _CatalogArgs

    variants = [_Answer]
    table = {
        "memory_status": _Status,
        "read_personal_context_for_question": _Read,
        "personal_context_catalog": _Catalog,
        "read_personal_context": _Facets,
        "remember_memory": _Remember,
        "correct_memory": _Correct,
        "forget_memory": _Forget,
    }
    variants += [table[name] for name in tools]
    payload = variants[0]
    for variant in variants[1:]:
        payload = payload | variant
    return create_model("JarvisTextStep", response=(payload, ...))


def tool_descriptions(names):
    """The live tools' own descriptions (from their definitions)."""
    from jarvis.voice import personal_context
    from jarvis.voice.memory_tools import MemoryAgentTools

    def doc(obj):
        for candidate in (
            getattr(getattr(obj, "info", None), "description", None),
            getattr(obj, "__doc__", None),
            getattr(getattr(obj, "__wrapped__", None), "__doc__", None),
        ):
            if isinstance(candidate, str) and candidate.strip():
                return " ".join(candidate.split())
        return ""

    known = {
        "read_personal_context_for_question": personal_context._QUESTION_QUERY_SCHEMA[
            "description"
        ]
        + " Arguments: requests (one to four {scope_key, optional target_quote}); "
        + personal_context._QUESTION_QUERY_SCHEMA["parameters"]["properties"][
            "page_token"
        ]["description"],
        "personal_context_catalog": doc(
            getattr(
                personal_context.PersonalContextAgentTools,
                "personal_context_catalog",
                None,
            )
        ),
        "read_personal_context": doc(
            getattr(
                personal_context.PersonalContextAgentTools,
                "read_personal_context",
                None,
            )
        ),
        "remember_memory": doc(MemoryAgentTools.remember_memory),
        "correct_memory": doc(MemoryAgentTools.correct_memory),
        "forget_memory": doc(MemoryAgentTools.forget_memory),
        "memory_status": doc(MemoryAgentTools.memory_status),
    }
    return {name: known[name] for name in names}


class FreeLaneDriverClient:
    """Answer-model client for the lab: the Free credential only, SDK retries
    off, no router and no Paid credential, so a Paid request is impossible.
    The single retry owner for answer calls is :class:`TextDriver`."""

    def __init__(self, client):
        self._client = client
        self.model_name = getattr(client, "model_name", None)

    async def parse_with_telemetry(
        self, *, system_prompt, input_payload, response_model, **_routing_ids
    ):
        return await self._client.parse_with_telemetry(
            system_prompt=system_prompt,
            input_payload=input_payload,
            response_model=response_model,
        )

    async def aclose(self):
        close = getattr(self._client, "aclose", None)
        if callable(close):
            await close()


def _invalid_output(exc) -> bool:
    from pydantic import ValidationError

    from jarvis.hands.provider_adapters import StructuredOutputError

    return isinstance(exc, StructuredOutputError | ValidationError | ValueError)


class TextDriver:
    """One Jarvis reply: model steps with real tool calls.

    Each model step may retry a temporary provider failure under
    ``jarvis.provider_retry`` (at most two retries) inside a step budget equal
    to learning's processing budget; each attempt's timeout is limited by the
    time remaining. Tool calls run once, only after a successful model
    response, so no tool, approval or memory write is ever repeated. A stall
    (no response before the timeout), invalid output, 429 or any other
    non-temporary failure is never retried and interrupts the run."""

    def __init__(
        self, client, log, *, model, pacer=None, sleep=None, rng=random.random
    ):
        self.client, self.log, self.model = client, log, model
        self.pacer = pacer
        self._sleep = sleep or asyncio.sleep
        self._rng = rng

    async def _model_step(self, *, group, step, index, request):
        from jarvis.memory.learning_limits import INFERENCE_TIMEOUT, PROCESSING_BUDGET
        from jarvis.provider_resilience import classify_provider_failure
        from jarvis.provider_retry import RetryDecision, decide_retry

        step_started = time.monotonic()
        attempt = 0
        while True:
            attempt += 1
            remaining = PROCESSING_BUDGET - (time.monotonic() - step_started)
            started = time.perf_counter()
            base = {
                "group": group,
                "step_id": step.id,
                "kind": "driver_step",
                "index": index,
                "attempt": attempt,
            }
            try:
                telemetry = await asyncio.wait_for(
                    request(), min(INFERENCE_TIMEOUT, remaining)
                )
                return telemetry, attempt, started
            except TimeoutError:
                self.log.event(
                    {
                        **base,
                        "status": "stall_unresolved",
                        "latency_ms": round((time.perf_counter() - started) * 1000),
                    }
                )
                raise AcceptanceInterrupted(
                    "answer call stalled (no provider response before the "
                    "timeout; unresolved, not retried)"
                ) from None
            except Exception as exc:  # noqa: BLE001 - classified, never retried blindly
                remaining = PROCESSING_BUDGET - (time.monotonic() - step_started)
                if _invalid_output(exc):
                    failure, decision = None, RetryDecision(False, "invalid_output")
                else:
                    failure = classify_provider_failure(exc, provider="gemini")
                    decision = decide_retry(
                        failure, attempt=attempt, remaining=remaining, rng=self._rng
                    )
                status = getattr(failure, "status_code", None)
                self.log.event(
                    {
                        **base,
                        "status": "invalid_output"
                        if failure is None
                        else "provider_failure",
                        "error": type(exc).__name__,
                        "failure_kind": getattr(
                            getattr(failure, "kind", None), "value", None
                        ),
                        "status_code": status if type(status) is int else None,
                        "decision": decision.reason,
                        "delay_seconds": decision.delay,
                        "remaining_seconds": round(remaining, 3),
                        "latency_ms": round((time.perf_counter() - started) * 1000),
                    }
                )
                if not decision.retry:
                    raise AcceptanceInterrupted(type(exc).__name__) from None
            await self._sleep(decision.delay)
            if self.pacer is not None:
                self.pacer.note(1)  # the retry is a provider call too

    def system_prompt(self):
        from jarvis.voice.agent import PERSONAL_LEARNING_QUERY_INSTRUCTIONS

        return DRIVER_PREAMBLE + PERSONAL_LEARNING_QUERY_INSTRUCTIONS

    async def reply(
        self,
        *,
        group,
        step,
        conversation,
        personal,
        memory_tools,
        explicit,
        learning_notes=(),
    ):
        tools = ["read_personal_context_for_question"]
        if getattr(memory_tools, "_receipts", None) is not None:
            tools.append("memory_status")
        if explicit:
            tools += [
                "personal_context_catalog",
                "read_personal_context",
                "remember_memory",
                "correct_memory",
                "forget_memory",
            ]
        descriptions = tool_descriptions(tools)
        results = []
        session_turns = [
            {"role": t.role.value, "text": t.text} for t in conversation.turns[-8:]
        ]
        for index in range(MAX_DRIVER_STEPS):
            remaining = MAX_DRIVER_STEPS - index
            names = tools if remaining > 1 else []
            payload = {
                "conversation": session_turns,
                "latest_owner_utterance": step.text,
                "tool_results": results,
                "available_tools": [
                    {"name": n, "description": descriptions[n]} for n in names
                ],
                "remaining_steps": remaining,
            }
            if learning_notes:
                # "Meaning unclear" learning outcomes (from Jarvis, not the
                # owner). Live voice asks about them after the reply; here
                # learning has already finished, so the reply receives them.
                payload["learning_notes"] = list(learning_notes)
            if self.pacer is not None:
                await self.pacer.wait()

            def request(payload=payload, names=names, index=index):
                return self.client.parse_with_telemetry(
                    system_prompt=self.system_prompt(),
                    input_payload=payload,
                    response_model=_driver_model(names),
                    scope_id=f"{group}:{step.id}",
                    operation_id=f"reply-{index}",
                )

            telemetry, attempt, started = await self._model_step(
                group=group, step=step, index=index, request=request
            )
            action = telemetry.parsed.response
            row = {
                "group": group,
                "step_id": step.id,
                "kind": "driver_step",
                "index": index,
                "attempt": attempt,
                "status": "ok",
                "input": payload,
                "output": action.model_dump(mode="json"),
                "usage": dict(getattr(telemetry, "usage", {}) or {}),
                "latency_ms": round((time.perf_counter() - started) * 1000),
            }
            self.log.event(row)
            if isinstance(action, _Answer):
                return action.answer, results
            # Omitted optional arguments are absent, as in a live tool call.
            name, arguments = next(
                iter(action.model_dump(mode="json", exclude_none=True).items())
            )
            result = await self._dispatch(name, arguments, personal, memory_tools)
            results.append({"tool": name, "arguments": arguments, "result": result})
            self.log.event(
                {
                    "group": group,
                    "step_id": step.id,
                    "kind": "tool_result",
                    "tool": name,
                    "arguments": arguments,
                    "result": result,
                }
            )
        return None, results

    async def _dispatch(self, name, arguments, personal, memory_tools):
        from jarvis.voice.memory_tools import _EXPECTED_MEMORY_ERRORS

        try:
            if name == "read_personal_context_for_question":
                requests = arguments["requests"]
                token = arguments.get("page_token")
                if token is None:
                    return await personal.query_for_question(requests)
                return await personal.query_for_question(requests, token)
            if name == "personal_context_catalog":
                return await personal.catalog()
            if name == "read_personal_context":
                return await personal.read(
                    arguments["catalog_id"], arguments["facet_indices"]
                )
            if name == "memory_status":
                # Learning has already finished when the lab driver replies.
                return await memory_tools.verified_memory_status(wait=0)
            clean = {k: v for k, v in arguments.items() if v is not None}
            if name == "remember_memory":
                return memory_tools._record(await memory_tools.remember(**clean))
            if name == "correct_memory":
                return memory_tools._record(await memory_tools.correct(**clean))
            if name == "forget_memory":
                clean.pop("value", None)
                return memory_tools._record(await memory_tools.forget(**clean))
        except _EXPECTED_MEMORY_ERRORS as exc:
            return {"ok": False, "error": type(exc).__name__, "message": str(exc)}
        except PermissionError as exc:
            return {"ok": False, "error": "PermissionError", "message": str(exc)}
        raise ValueError("unknown tool")


# ----------------------------------------------------------------- runner --


@dataclass
class LabDeps:
    """What the runner needs; the Windows lab and the offline test supply it."""

    open_memory: object  # async callable(path) -> started MemoryRuntime
    capability: object
    learning_authority: object
    learning_grant: object
    extractor: object
    resolver: object
    driver_client: object
    models: dict
    # Seeding issues two short-lived learning child permits per fact; the
    # authority allows 128 live at once (30 s lease). The lab waits out the
    # lease every SEED_BATCH facts; the offline test advances its clock.
    pause: object = None
    # Shared spacing for every model call (FreeLanePacer); None = unpaced.
    pacer: object = None


class AcceptanceRunner:
    def __init__(
        self,
        root: Path,
        deps: LabDeps,
        log: ResultLog,
        *,
        retry_interrupted=False,
        stop_after=None,
        stop_on_failure=False,
        stop_on="any",
        recover_d17_consent=False,
        groups_map=None,
        checks_map=None,
        planned_cases=None,
        not_run_here=None,
    ):
        self.root, self.deps, self.log = root, deps, log
        # The development set by default; a held-out script supplies its own
        # steps, record checks and planned cases (heldout_player).
        self.groups = GROUPS if groups_map is None else groups_map
        self.checks = CHECKS if checks_map is None else checks_map
        self.planned = CASES_RUN if planned_cases is None else tuple(planned_cases)
        self.not_run_here = NOT_RUN_HERE if not_run_here is None else not_run_here
        self.retry_interrupted = retry_interrupted
        self.stop_after = stop_after
        self.stop_on_failure = stop_on_failure
        # "any": a FAIL or UNTESTED case stops (the default); "invariant": only
        # a failed safety invariant stops, quality failures are measured.
        if stop_on not in {"any", "invariant"}:
            raise ValueError("stop_on must be 'any' or 'invariant'")
        self.stop_on = stop_on
        self.recover_d17_consent = recover_d17_consent
        if recover_d17_consent:
            self.stop_after = D17_RECOVERY_STEPS[-1]

    def _latest_cases(self):
        latest = {}
        for row in self.log.read(self.log.cases):
            latest[row["case"]] = row
        return latest

    def _recorded_failure(self, ignore=()):
        # The latest result per case decides. A case can only have a newer
        # result than a recorded failure through an explicit recovery.
        for case, row in self._latest_cases().items():
            if case in ignore:
                continue
            if self.stop_on == "invariant":
                if _invariant_failed(row.get("checks") or ()):
                    return row
            elif row["status"] in {FAIL, UNTESTED}:
                return row
        return None

    def _check_d17_recovery(self):
        """Refuse unless D17's latest result is exactly the consent failure
        with the correct item selected and no deletion attempted, and nothing
        else has failed."""
        d17 = self._latest_cases().get("D17")
        if d17 is None or d17["status"] != FAIL or d17["step_id"] != "story-18c":
            raise AcceptanceRecoveryRefused("D17 has no recorded failure to recover")
        checks = {c["check"]: c for c in d17["checks"]}
        stage = (checks.get("forget gate (stage diagnosis)") or {}).get("detail") or {}
        if stage.get("failed_stage") != "owner_consent_not_granted":
            raise AcceptanceRecoveryRefused(
                f"D17 failed at {stage.get('failed_stage')!r}, not at consent"
            )
        # The correct item was selected when every forget call aimed at it.
        calls = stage.get("forget_calls") or []
        if not calls or not all(
            c.get("targets_item")
            and (c.get("result") or {}).get("error") == "PermissionError"
            for c in calls
        ):
            raise AcceptanceRecoveryRefused(
                "a forget call ran past consent or aimed at another item"
            )
        if not stage.get("lineage_remaining"):
            raise AcceptanceRecoveryRefused("the item is no longer stored")
        if other := self._recorded_failure(ignore={"D17"}):
            raise AcceptanceRecoveryRefused(
                f"{other['case']} is also recorded {other['status']}"
            )
        if any(
            r.get("recovery") == D17_RECOVERY_ID for r in self.log.read(self.log.steps)
        ):
            raise AcceptanceRecoveryRefused(f"{D17_RECOVERY_ID} was already used")
        return d17

    def _reopen_for_d17_recovery(self, failed):
        """Append (never rewrite) a reopening row for the forget turn and its
        check; the original attempt's rows stay in every log. When the lab's
        marker records an earlier build, record which build runs the recovery
        (and may continue it); the marker itself is never changed."""
        marker = self.root / "project-memory.marker"
        commit = self.log.meta.get("source_commit")
        if marker.is_file():
            original = json.loads(marker.read_text()).get("commit")
            if original != commit:
                path = self.root / "recovery-source.json"
                if path.exists():
                    raise AcceptanceRecoveryRefused(
                        "a recovery source is already recorded"
                    )
                path.write_text(
                    json.dumps(
                        {
                            "recovery": D17_RECOVERY_ID,
                            "original_commit": original,
                            "recovery_commit": commit,
                            "at": datetime.now(UTC).isoformat(),
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )
        states = self.log.step_states()
        self.log.event(
            {
                "group": "story",
                "step_id": D17_RECOVERY_STEPS[0],
                "kind": "recovery_started",
                "recovery": D17_RECOVERY_ID,
                "reason": "fresh owner consent (Windows Hello) was not granted;"
                " the correct item was selected and deletion was never attempted",
                "original_case_result": {
                    "status": failed["status"],
                    "step_id": failed["step_id"],
                },
            }
        )
        for step_id in D17_RECOVERY_STEPS:
            prior = states[step_id]
            self.log.step(
                {
                    "group": "story",
                    "step_id": step_id,
                    "status": "reopened_for_recovery",
                    "attempt": int(prior.get("attempt", 1)),
                    "recovery": D17_RECOVERY_ID,
                    "original_status": prior["status"],
                }
            )

    async def run(self, groups=None):
        groups = tuple(self.groups) if groups is None else groups
        if self.recover_d17_consent:
            if tuple(groups) != ("story",):
                raise AcceptanceRecoveryRefused(
                    "the D17 recovery runs the story group only"
                )
            failed = self._check_d17_recovery()
            self._reopen_for_d17_recovery(failed)
        ignore = {"D17"} if self.recover_d17_consent else set()
        if self.stop_on_failure and (failed := self._recorded_failure(ignore)):
            # Never resume into cases that depend on a failed prerequisite.
            self.write_summary(stopped=failed)
            raise AcceptanceStoppedOnFailure(
                f"{failed['case']} was recorded {failed['status']} at"
                f" {failed['step_id']}; the run does not continue"
            )
        states = self.log.step_states()
        for group in groups:
            for step in self.groups[group]:
                prior = states.get(step.id)
                if prior is not None and prior.get("status") == "started":
                    # A crash may have happened after a provider response or a
                    # committed tool operation, before the completion row. The
                    # interrupted-step flag cannot make those effects replay-safe.
                    self.write_summary(interrupted=step.id)
                    raise AcceptanceInterrupted(
                        f"step {step.id} has an unresolved started attempt;"
                        " reconcile recorded provider/tool/memory effects before recovery"
                    )
        if self.stop_after and self._done(states.get(self.stop_after)):
            return self.write_summary(paused_after=self.stop_after)
        try:
            for group in groups:
                await self._run_group(group, self.groups[group], states)
        except _CheckpointReached:
            return self.write_summary(paused_after=self.stop_after)
        return self.write_summary()

    async def _run_group(self, group, steps, states):
        from jarvis.memory.learning_reconciliation import LearningReconciler
        from jarvis.memory.learning_runtime import PersonalLearningRuntime

        pending = [s for s in steps if not self._done(states.get(s.id))]
        if not pending:
            return
        memory = await self.deps.open_memory(self.root / group / "memory.db")
        pacer = self.deps.pacer
        extractor = RecordingAdapter(self.deps.extractor, self.log, group, pacer)
        resolver = (
            extractor
            if self.deps.resolver is self.deps.extractor
            else RecordingAdapter(self.deps.resolver, self.log, group, pacer)
        )
        context = _GroupContext(group, memory, self.deps, extractor, resolver)
        context._path = self.root / group / "memory.db"
        context.restore(self.log)
        try:
            context.start_learning(PersonalLearningRuntime, LearningReconciler)
            for step in steps:
                if self._done(states.get(step.id)):
                    if isinstance(step, Restart):
                        await context.restart(
                            PersonalLearningRuntime, LearningReconciler
                        )
                    continue
                prior = states.get(step.id)
                if (
                    prior is not None
                    and prior["status"] == "interrupted"
                    and not self.retry_interrupted
                ):
                    raise AcceptanceInterrupted(
                        f"step {step.id} was interrupted earlier; rerun only with --retry-interrupted"
                    )
                attempt = 1 if prior is None else int(prior.get("attempt", 1)) + 1
                if self.recover_d17_consent and step.id == D17_RECOVERY_STEPS[0]:
                    rows = await _rows(context.memory)
                    if not _named(_items(rows, current=False), "classic 350"):
                        raise AcceptanceRecoveryRefused(
                            "the Classic 350 is no longer stored; nothing to recover"
                        )
                await self._run_step(context, group, step, attempt)
                if step.id == self.stop_after:
                    raise _CheckpointReached
        finally:
            await context.close()

    @staticmethod
    def _done(state):
        return state is not None and state["status"] in {"completed", "checked"}

    async def _run_step(self, context, group, step, attempt):
        self.log.step(
            {
                "group": group,
                "step_id": step.id,
                "status": "started",
                "attempt": attempt,
            }
        )
        try:
            if isinstance(step, Seed):
                count = await context.seed(step)
                record = {"seeded": count}
            elif isinstance(step, SeedExplicit):
                record = await context.seed_explicit(step, self.log)
            elif isinstance(step, Restart):
                await context.restart_now()
                record = {}
            elif isinstance(step, Say):
                record = await context.say(step, self.log)
            else:
                checks = _tiered(await self.checks[step.case](context, self.log))
                status = _overall(checks)
                self.log.case(
                    {
                        "group": group,
                        "step_id": step.id,
                        "case": step.case,
                        "status": status,
                        "attempt": attempt,
                        "checks": checks,
                    }
                )
                self.log.step(
                    {
                        "group": group,
                        "step_id": step.id,
                        "status": "checked",
                        "attempt": attempt,
                        "case": step.case,
                        "case_status": status,
                    }
                )
                if self.stop_on_failure and (
                    _invariant_failed(checks)
                    if self.stop_on == "invariant"
                    else status in {FAIL, UNTESTED}
                ):
                    failed = {"case": step.case, "step_id": step.id, "status": status}
                    self.write_summary(stopped=failed)
                    raise AcceptanceStoppedOnFailure(
                        f"{step.case} {status} at {step.id}; dependent cases not run"
                    )
                return
        except AcceptanceInterrupted as exc:
            self.log.step(
                {
                    "group": group,
                    "step_id": step.id,
                    "status": "interrupted",
                    "attempt": attempt,
                    "reason": str(exc),
                }
            )
            self.write_summary(interrupted=step.id)
            raise
        self.log.step(
            {
                "group": group,
                "step_id": step.id,
                "status": "completed",
                "attempt": attempt,
                **record,
            }
        )

    def write_summary(self, interrupted=None, paused_after=None, stopped=None):
        cases, history = {}, {}
        for row in self.log.read(self.log.cases):
            cases[row["case"]] = {
                "status": row["status"],
                "step_id": row["step_id"],
                "checks": row["checks"],
                "source_commit": row.get("source_commit"),
                "evidence_kind": row.get("evidence_kind", "unspecified"),
                "attempt": row.get("attempt"),
                "at": row.get("at"),
            }
            history.setdefault(row["case"], []).append(
                {
                    "status": row["status"],
                    "step_id": row["step_id"],
                    "at": row.get("at"),
                    "source_commit": row.get("source_commit"),
                    "evidence_kind": row.get("evidence_kind", "unspecified"),
                    "attempt": row.get("attempt"),
                }
            )
        source_commits = sorted(
            {
                row["source_commit"]
                for rows in history.values()
                for row in rows
                if row.get("source_commit")
            }
        )
        summary = {
            **self.log.meta,
            "summary_source_commit": self.log.meta.get("source_commit"),
            "source_commits": source_commits,
            "mixed_source_commits": len(source_commits) > 1,
            "planned_cases": list(self.planned),
            "not_run_here": self.not_run_here,
            "cases": cases,
            "untested": [c for c in self.planned if c not in cases],
            "interrupted_at": interrupted,
            "run_state": (
                "interrupted"
                if interrupted
                else "stopped_on_failure"
                if stopped
                else "checkpoint_paused_for_review"
                if paused_after
                else "complete"
                if not [c for c in self.planned if c not in cases]
                else "partial"
            ),
            "checkpoint_paused_after": paused_after,
            # Every earlier result of a case that was rerun by a recovery is
            # kept here and in acceptance-cases.jsonl; "cases" shows the latest.
            "earlier_case_results": {
                c: h[:-1] for c, h in history.items() if len(h) > 1
            },
            "recoveries": [
                {k: r.get(k) for k in ("recovery", "step_id", "original_status", "at")}
                for r in self.log.read(self.log.steps)
                if r.get("status") == "reopened_for_recovery"
            ],
            "stopped_on_failure": (
                {k: stopped[k] for k in ("case", "step_id", "status")}
                if stopped
                else None
            ),
            # Every planned case is a required gate (D17 included); D27 is
            # recorded from the rehearsal. REVIEW = automatic checks passed
            # and the answer awaits manual grading.
            "required_gates": list(self.planned),
            "automatic_verdict": (
                FAIL
                if any(c["status"] == FAIL for c in cases.values())
                else UNTESTED
                if [c for c in self.planned if c not in cases]
                or any(c["status"] == UNTESTED for c in cases.values())
                else "PASS_PENDING_MANUAL_REVIEW"
            ),
            "d17_failed_stage": next(
                (
                    c["detail"].get("failed_stage")
                    for c in (cases.get("D17") or {}).get("checks", ())
                    if c["check"] == "forget gate (stage diagnosis)"
                ),
                None,
            ),
            "superseded_expectations": [
                {"case": case, **c}
                for case, row in cases.items()
                for c in row["checks"]
                if c["status"] == SUPERSEDED
            ],
            "tiers": _tier_summary(
                cases, missing=[c for c in self.planned if c not in cases]
            ),
            # Replies that claimed a memory change the record of that turn did
            # not show, and the correction given from the record.
            "memory_claims": [
                {"step_id": e.get("step_id"), "case": e.get("case"), **e["correction"]}
                for e in self.log.read(self.log.events)
                if e.get("kind") == "reply" and e.get("correction")
            ],
            "stop_on": self.stop_on,
            "answer_quality": "manual_review_required",
            "retry_policy": policy_summary(),
            "provider_reliability": provider_reliability(
                self.log.read(self.log.events)
            ),
            "limits": (
                f"Controlled text through the {self.log.meta.get('lane', 'free')}"
                "-lane answer model with the voice "
                "agent's personal-context instructions and the real tools, not Gemini "
                "Live voice. Told dates are simulated per the frozen cases; recorded_at "
                "is real lab time. Keyword flags only locate problems."
            ),
        }
        tmp = self.log.summary.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        tmp.replace(self.log.summary)
        return summary


_CALL_KINDS = {"learning_extraction", "learning_resolution", "driver_step"}
_STALLS = {"stall_unresolved", "cancelled_at_deadline"}


def provider_reliability(events):
    """First-attempt reliability, kept separate from eventual completion.

    A *call* is one model request of one step (a learning stage, or one answer
    step) with all its attempts. Successful recovery never hides the failed
    attempts before it; stalls are reported as unresolved."""
    calls = []
    current = {}
    for row in events:
        kind = row.get("kind")
        if kind not in _CALL_KINDS:
            continue
        key = (row.get("group"), row.get("step_id"), kind, row.get("index"))
        attempt = row.get("attempt") or 1
        if attempt == 1 or key not in current:
            current[key] = {"key": key, "attempts": []}
            calls.append(current[key])
        current[key]["attempts"].append(row)
    by_kind = {}
    summary = {
        "calls": len(calls),
        "attempts": sum(len(c["attempts"]) for c in calls),
        "first_attempt_ok": 0,
        "completed_after_retry": 0,
        "unrecovered_provider_failures": 0,
        "stalls_unresolved": 0,
        "failed_attempts_by_kind": by_kind,
        "steps_completed_only_after_retry": [],
        "steps_with_unrecovered_failure": [],
        "steps_with_unresolved_stall": [],
    }
    for call in calls:
        attempts = call["attempts"]
        for row in attempts:
            if row.get("status") == "provider_failure":
                name = row.get("failure_kind") or "unclassified"
                by_kind[name] = by_kind.get(name, 0) + 1
        first, last = attempts[0].get("status"), attempts[-1].get("status")
        step = attempts[-1].get("step_id")
        responded = {"ok", "failed", "invalid_output"}
        if first in responded:
            summary["first_attempt_ok"] += 1
        elif last in responded:
            summary["completed_after_retry"] += 1
            summary["steps_completed_only_after_retry"].append(step)
        if last == "provider_failure":
            summary["unrecovered_provider_failures"] += 1
            summary["steps_with_unrecovered_failure"].append(step)
        elif last in _STALLS:
            summary["stalls_unresolved"] += 1
            summary["steps_with_unresolved_stall"].append(step)
    if calls:
        summary["first_attempt_ok_rate"] = round(
            summary["first_attempt_ok"] / len(calls), 4
        )
        summary["eventual_completion_rate"] = round(
            (summary["first_attempt_ok"] + summary["completed_after_retry"])
            / len(calls),
            4,
        )
    return summary


# Deterministic safety and integrity guarantees that code enforces whatever
# the model says: consent, forgetting, history, isolation of unrelated facts,
# pending alternatives, release and paging correctness. A failure here is
# investigated at once. Every other check measures model quality (what the
# model understood or chose): it is recorded as a rate, and its failure is a
# known limitation unless it repeats in real use (owner rule, 27 November).
INVARIANT_CHECKS = frozenset(
    {
        "2 sources",
        "3 distinct sources",
        "90+ standard rows, no overflow",
        "A not retracted",
        "A validity unchanged",
        "Tigor and Jimny facts and evidence intact",
        "changes superseded with unknown or known effective time",
        "complete false",
        "complete false on first page",
        "every current row has a source",
        "every page bound to the same question permit",
        "first page released <= 8",
        "history row keeps the options",
        "lineage gone",
        "more_remaining with total 40",
        "no destination options stored before confirmation",
        "no evidence text names Classic 350",
        "no orphan sources",
        "no plural record",
        "no residual in any personal-memory store",
        "no truncated item",
        "old row retracted",
        "old row superseded, valid_to NULL",
        "owned items unchanged",
        "page ends by bytes (fewer than 6, <= 3000 bytes)",
        "refine predecessors superseded, validity untouched",
        "release date_status passed_outcome_unknown",
        "released evidence: owner's words and told date, apart from recorded_at",
        "seeded combined record unchanged",
        "skip recorded with reason",
        "the new conversation carries no old question",
        "total 11",
        "total 45 plans, complete reported truthfully",
    }
)


# D17's forget stages: the code failed (invariant) or the model did not pick
# the item / the owner did not approve (deletion never reached: quality).
_CODE_FORGET_STAGES = frozenset(
    {"forget_operation_failed", "deleted_but_residual_remains"}
)
_DELETION_CHECKS = frozenset({"lineage gone", "no evidence text names Classic 350"})


def _tiered(checks):
    stage = next(
        (
            (c.get("detail") or {}).get("failed_stage")
            for c in checks
            if c.get("check") == "forget gate (stage diagnosis)"
        ),
        "absent",
    )
    for check in checks:
        name = check.get("check")
        invariant = name in INVARIANT_CHECKS
        if (
            name == "forget gate (stage diagnosis)"
            or name in _DELETION_CHECKS
            and stage not in {None, "absent"}
        ):
            invariant = stage in _CODE_FORGET_STAGES
        check["tier"] = "invariant" if invariant else "quality"
    return checks


def _invariant_failed(checks):
    return any(c.get("tier") == "invariant" and c.get("status") == FAIL for c in checks)


def _overall(checks):
    statuses = {c["status"] for c in checks} - {SUPERSEDED}
    if FAIL in statuses:
        return FAIL
    if UNTESTED in statuses:
        return UNTESTED
    if REVIEW in statuses:
        return REVIEW
    return PASS


def _tier_summary(cases, missing=()):
    """Invariants (each must hold) apart from quality measurements (rates).
    ``missing``: planned cases that did not run."""
    invariant_fail, invariant_untested, invariant_review = [], [], []
    invariant_pass = 0
    untested_cases = [case for case, row in cases.items() if row["status"] == UNTESTED]
    quality = {PASS: 0, FAIL: 0, REVIEW: 0, UNTESTED: 0}
    quality_fail = []
    for case, row in cases.items():
        for check in row["checks"]:
            status = check.get("status")
            if status == SUPERSEDED:
                continue
            tier = check.get("tier") or (
                "invariant" if check.get("check") in INVARIANT_CHECKS else "quality"
            )
            if tier == "invariant":
                if status == FAIL:
                    invariant_fail.append({"case": case, "check": check["check"]})
                elif status == PASS:
                    invariant_pass += 1
                elif status == REVIEW:
                    invariant_review.append({"case": case, "check": check["check"]})
                else:
                    invariant_untested.append({"case": case, "check": check["check"]})
            else:
                quality[status] = quality.get(status, 0) + 1
                if status == FAIL:
                    quality_fail.append({"case": case, "check": check["check"]})
    graded = quality[PASS] + quality[FAIL]
    return {
        "invariants": {
            "passed": invariant_pass,
            "failed": invariant_fail,
            # Not checked: an invariant left UNTESTED, or a case whose missing
            # prerequisite left its checks unrun. Never reported as PASS.
            "untested": invariant_untested,
            "untested_cases": untested_cases,
            # Needs the owner's decision before it counts as passing.
            "review": invariant_review,
            "verdict": FAIL
            if invariant_fail
            else UNTESTED
            if invariant_untested or untested_cases or missing
            else REVIEW
            if invariant_review
            else PASS,
        },
        "quality": {
            **{k.lower(): v for k, v in quality.items()},
            "failed_checks": quality_fail,
            "automatic_pass_rate": round(quality[PASS] / graded, 3) if graded else None,
        },
    }


class ConsentRecorder:
    """Lab-only, content-free record of each fresh-consent request: operation,
    duration and outcome ("granted", or the exception class when consent was
    not granted). It calls the real authority unchanged and never alters,
    retries or bypasses consent."""

    def __init__(self, inner, log, group, step_id):
        self._inner, self._log = inner, log
        self._group, self._step_id = group, step_id

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def authorize_personal_context(self, **kwargs):
        started = time.monotonic()
        outcome = "granted"
        try:
            return self._inner.authorize_personal_context(**kwargs)
        except BaseException as exc:
            outcome = type(exc).__name__
            raise
        finally:
            if kwargs.get("operation") != "read":
                self._log.event(
                    {
                        "group": self._group,
                        "step_id": self._step_id,
                        "kind": "consent_outcome",
                        "operation": kwargs.get("operation"),
                        "outcome": outcome,
                        "seconds": round(time.monotonic() - started, 1),
                    }
                )


class _GroupContext:
    def __init__(self, group, memory, deps, extractor, resolver):
        self.group, self.memory, self.deps = group, memory, deps
        self.extractor, self.resolver = extractor, resolver
        self.learning = None
        self.conversation = None
        self.replies = {}  # step id -> {"answer", "tools"}
        self.marks = {}  # named snapshots for checks
        self._path = None

    def restore(self, log):
        """On resume: replies, snapshots and marks of completed steps."""
        for row in log.read(log.events):
            if row.get("group") != self.group:
                continue
            if row.get("kind") == "reply":
                self.replies[row["step_id"]] = {
                    "answer": row.get("answer"),
                    "tools": row.get("tools") or [],
                    "learning": row.get("learning") or {},
                }
            elif row.get("kind") == "before_snapshot":
                self.marks.setdefault("before", {})[row["step_id"]] = row["snapshot"]
            elif row.get("kind") == "mark":
                self.marks[row["name"]] = row["value"]

    # learning runtime -----------------------------------------------------
    def start_learning(self, runtime_cls, reconciler_cls):
        self.memory.bind_learning_authority(self.deps.learning_authority)
        self.reconciler = reconciler_cls(
            self.memory.service.canonical_reader, self.deps.learning_authority
        )
        self.learning = runtime_cls(
            self.deps.learning_authority,
            self.memory.service,
            self.extractor,
            self.resolver,
            self.reconciler,
            diagnostics=False,
            retry_observer=self._record_learning_retry,
        )

    def _record_learning_retry(self, record):
        # The learning runtime's content-free decision for a failed attempt.
        log = getattr(self, "_log", None)
        if log is not None:
            log.event(
                {
                    "group": self.group,
                    "step_id": self.extractor.step_id,
                    "kind": "learning_retry_decision",
                    **record,
                }
            )

    async def restart_now(self):
        from jarvis.memory.learning_reconciliation import LearningReconciler
        from jarvis.memory.learning_runtime import PersonalLearningRuntime

        await self.restart(PersonalLearningRuntime, LearningReconciler)

    async def restart(self, runtime_cls, reconciler_cls):
        path = self.memory_path
        await self.close()
        self.memory = await self.deps.open_memory(path)
        self.conversation = None
        self.start_learning(runtime_cls, reconciler_cls)

    @property
    def memory_path(self):
        return self._path

    async def close(self):
        if self.learning is not None:
            await self.learning.close()
            self.learning = None
        if self.conversation is not None:
            self.conversation.close()
            self.conversation = None
        await self.memory.close()

    # setup ----------------------------------------------------------------
    async def seed(self, step):
        from time import monotonic

        from jarvis.memory.learning_contracts import (
            AcceptedLearningSource,
            EvidenceSpan,
            LearningBatch,
            LearningCandidate,
            LearningResolution,
            LearningResolutionBatch,
        )

        authority, grant = self.deps.learning_authority, self.deps.learning_grant
        count = 0
        for fact in step.facts:
            if count and count % SEED_BATCH == 0:
                await self._pause(CHILD_LEASE_SECONDS)
            conversation = LabConversation()
            conversation.start()
            text = fact.sentence()
            turn = conversation.accept_at(ConversationRole.USER, text, fact.told_at)
            source = AcceptedLearningSource.from_turn(
                authority.runtime_id_for(grant), conversation, turn, now=monotonic()
            )
            authority.register_source(grant, source.receipt_id, source=source)
            try:
                candidate = LearningCandidate(
                    category=fact.category,
                    kind=fact.kind,
                    intent="new",
                    label=fact.label,
                    value=fact.label,
                    state=fact.state,
                    certainty="confirmed",
                    details=fact.details,
                    aliases=list(fact.aliases),
                    plan_status=fact.plan_status,
                    evidence=[
                        EvidenceSpan(turn_id=turn.turn_id, start=0, end=len(text))
                    ],
                )
                batch = LearningBatch(candidates=[candidate])
                catalog = await self.reconciler.catalog(source, batch, grant)
                plan = self.reconciler.plan(
                    source,
                    batch,
                    catalog,
                    LearningResolutionBatch(
                        resolutions=[
                            LearningResolution(candidate_index=0, decision="new")
                        ]
                    ),
                )
                if not plan.mutations or plan.outcomes:
                    raise RuntimeError("seed was not admissible")
                result = await self.memory.service.admit_learning(
                    plan, authority.issue_child(grant, plan.binding())
                )
                if result.status != "committed":
                    raise RuntimeError("seed did not commit")
                count += 1
            finally:
                authority.release_source(grant, source.receipt_id)
                conversation.close()
        return count

    async def _pause(self, seconds):
        import asyncio

        pause = self.deps.pause or asyncio.sleep
        await pause(seconds)

    async def seed_explicit(self, step, log=None):
        from jarvis.memory.explicit import build_owner_explicit_source
        from jarvis.memory.types import Sensitivity

        conversation = LabConversation()
        conversation.start()
        turn = conversation.accept_at(
            ConversationRole.USER,
            f"Remember that my {step.predicate} are {step.value}.",
            step.told_at,
        )
        source = build_owner_explicit_source(
            conversation=conversation, turn=turn, sensitivity=Sensitivity.STANDARD
        )
        result = await self.memory.service.remember_text(
            predicate=step.predicate,
            value=step.value,
            source=source,
            sensitivity=Sensitivity.STANDARD,
        )
        conversation.close()
        self.marks["combined_record"] = {
            "assertion_id": result.record.assertion_id,
            "predicate": result.predicate,
            "value": result.record.value,
        }
        if log is not None:
            log.event(
                {
                    "group": self.group,
                    "step_id": step.id,
                    "kind": "mark",
                    "name": "combined_record",
                    "value": self.marks["combined_record"],
                }
            )
        return {"seeded_explicit": result.predicate}

    # one owner utterance --------------------------------------------------
    async def say(self, step, log):
        from jarvis.voice.memory_tools import MemoryAgentTools
        from jarvis.voice.personal_context import PersonalContextSession

        resumed_follow_up = not step.new_session and self.conversation is None
        if step.new_session or self.conversation is None:
            if self.conversation is not None:
                self.conversation.close()
            self.conversation = LabConversation()
            self.conversation.start()
            self.observer = self.learning.bind(
                self.conversation, self.deps.learning_grant
            )
        before_snapshot = await snapshot_counts(self.memory)
        self.marks.setdefault("before", {})[step.id] = before_snapshot
        log.event(
            {
                "group": self.group,
                "step_id": step.id,
                "kind": "before_snapshot",
                "snapshot": before_snapshot,
            }
        )
        turn = self.conversation.accept_at(
            ConversationRole.USER, step.text, step.told_at
        )
        self._log = log
        for adapter in {
            id(self.extractor): self.extractor,
            id(self.resolver): self.resolver,
        }.values():
            adapter.start_step(step.id)
        before = self.learning.status()
        outcome_sql = (
            "SELECT receipt_id, candidate_ordinal, category_key, reason_code"
            " FROM personal_learning_outcome"
        )
        outcomes_before = set(await _query(self.memory, outcome_sql))
        if self.deps.pacer is not None:
            # Outside the learning deadline: the turn's learning calls then
            # start as soon as Jarvis makes them.
            await self.deps.pacer.ready()
        self.observer(turn)
        await self.learning.drain()
        after = self.learning.status()
        skipped = sorted(
            (row[2], row[3])
            for row in set(await _query(self.memory, outcome_sql)) - outcomes_before
        )
        failures = self.extractor.provider_failures + (
            self.resolver.provider_failures
            if self.resolver is not self.extractor
            else []
        )
        learning = {
            "processed": after.processed - before.processed,
            "committed": after.committed - before.committed,
            "dropped": after.dropped - before.dropped,
            "reason": after.reason,
            "skipped": [{"category": c, "reason": r} for c, r in skipped],
            "failed_provider_attempts": len(failures),
        }
        log.event(
            {
                "group": self.group,
                "step_id": step.id,
                "kind": "learning_status",
                **learning,
            }
        )
        if learning["dropped"] and after.reason in {"timeout", "cancelled"}:
            # A turn whose learning did not finish is not completed setup:
            # stop here (stalls are not retried, no reseeding); later cases
            # would test missing prerequisites. Rerun only with
            # --retry-interrupted.
            raise AcceptanceInterrupted(f"learning incomplete: {after.reason}")
        unrecovered = self.extractor.unrecovered() + (
            self.resolver.unrecovered() if self.resolver is not self.extractor else []
        )
        if unrecovered and learning["dropped"]:
            # The learning runtime's bounded retries did not recover it.
            raise AcceptanceInterrupted(
                "learning provider failure: " + json.dumps(failures)
            )
        # Failed attempts followed by a successful retry are recorded above
        # and counted in the summary's first-attempt reliability.
        notes = [
            n.model_view()
            for n in self.learning.clarifications.take(
                self.conversation.session_id, turn.turn_id
            )
        ]
        learning["clarification_notes"] = notes
        personal = PersonalContextSession(
            conversation=self.conversation,
            retrieval=self.memory.retrieval,
            authority=ConsentRecorder(self.deps.capability, log, self.group, step.id),
            retire=lambda: None,
            learning_authority=self.deps.learning_authority,
            learning_grant=self.deps.learning_grant,
        )
        tools = MemoryAgentTools(
            self.memory.service,
            self.conversation,
            personal_context=personal,
            receipts=self.learning.receipts,
        )
        driver = TextDriver(
            self.deps.driver_client,
            log,
            model=self.deps.models.get("answer_model"),
            pacer=self.deps.pacer,
        )
        try:
            answer, results = await driver.reply(
                group=self.group,
                step=step,
                conversation=self.conversation,
                personal=personal,
                memory_tools=tools,
                explicit=step.explicit_tools,
                learning_notes=notes,
            )
        finally:
            personal.close()
        correction = None
        if answer:
            self.conversation.accept_at(
                ConversationRole.ASSISTANT, answer, step.told_at + timedelta(seconds=5)
            )
            # The live claim check (jarvis.voice.memory_claims), with the turn's
            # learning already finished: a claimed change the record does not
            # show is corrected from the record (here in code; live, Jarvis
            # speaks the correction from the same facts).
            from jarvis.voice.memory_claims import correction_facts, unsupported_claims

            operations = self.learning.receipts.operations(
                self.conversation.session_id, turn.turn_id
            )
            false = unsupported_claims(answer, operations)
            if false:
                correction = {
                    "claims": sorted(false),
                    "spoken": "Correction: " + correction_facts(operations) + ".",
                }
                learning["memory_claim_check"] = correction
        self.replies[step.id] = {
            "answer": answer,
            "correction": correction,
            "tools": results,
            "learning": learning,
        }
        log.event(
            {
                "group": self.group,
                "step_id": step.id,
                "case": step.case,
                "kind": "reply",
                "utterance": step.text,
                "told_at": step.told_at.isoformat(),
                "answer": answer,
                "correction": correction,
                "tools": results,
                "learning": learning,
            }
        )
        return {
            "case": step.case,
            "learning": learning,
            "answered": answer is not None,
            # A follow-up resumed after an interruption has no earlier turn.
            "follow_up_context_lost": resumed_follow_up,
        }


# ------------------------------------------------------------ db helpers --


async def _rows(memory):
    def read(connection):
        rows = connection.execute(
            "SELECT a.assertion_id, a.predicate, a.state, a.valid_from, a.valid_to,"
            " a.system_from, a.system_to, a.supersedes_id, a.value_json,"
            " a.normalized_text, a.source_id, s.evidence_text, s.observed_at,"
            " s.source_class FROM semantic_assertion a"
            " LEFT JOIN memory_source s ON s.source_id = a.source_id"
            " WHERE a.subject_scope = 'personal' AND a.subject = 'owner'"
        ).fetchall()
        keys = [
            "assertion_id",
            "predicate",
            "state",
            "valid_from",
            "valid_to",
            "system_from",
            "system_to",
            "supersedes_id",
            "value_json",
            "normalized_text",
            "source_id",
            "evidence_text",
            "observed_at",
            "source_class",
        ]
        out = []
        for row in rows:
            item = dict(zip(keys, row, strict=True))
            try:
                item["value"] = json.loads(item["value_json"])
            except (TypeError, ValueError):
                item["value"] = item["value_json"]
            item["current"] = (
                item["state"] == "active"
                and item["system_to"] is None
                and item["valid_to"] is None
            )
            out.append(item)
        return out

    return await memory._reader.run(read)


async def _query(memory, sql, args=()):
    return await memory._reader.run(lambda c: c.execute(sql, args).fetchall())


async def snapshot_counts(memory):
    rows = await _rows(memory)
    return {
        "current_ids": sorted(r["assertion_id"] for r in rows if r["current"]),
        "all_ids": sorted(r["assertion_id"] for r in rows),
        # Predicate and label of every current row (D17 target diagnosis).
        "current_labels": {r["predicate"]: _label(r) for r in rows if r["current"]},
    }


def _value(row):
    return row["value"] if isinstance(row["value"], dict) else {}


def _label(row):
    value = _value(row)
    return str(value.get("label") or value.get("value") or row["value"] or "")


def _items(rows, kind=None, *, current=True):
    return [
        r
        for r in rows
        if _value(r).get("category") == "owned_item"
        and (kind is None or _value(r).get("kind") == kind)
        and (r["current"] or not current)
    ]


def _plans(rows, *, current=True):
    return [
        r
        for r in rows
        if _value(r).get("category") == "plan" and (r["current"] or not current)
    ]


def _named(rows, needle):
    needle = needle.casefold()
    return [
        r
        for r in rows
        if needle in _label(r).casefold()
        or any(needle in str(a).casefold() for a in _value(r).get("aliases") or ())
    ]


def _check(name, level, ok, detail=None, *, review=False):
    status = (REVIEW if review else PASS) if ok else FAIL
    return {"check": name, "level": level, "status": status, "detail": detail}


def _untested(name, level, detail):
    return {"check": name, "level": level, "status": UNTESTED, "detail": detail}


def _reply(context, step_id):
    return context.replies.get(step_id) or {}


def _reads(reply):
    return [
        t
        for t in reply.get("tools") or ()
        if t["tool"] == "read_personal_context_for_question"
    ]


def _time(value, key):
    stated = value.get(key) or {}
    return (stated.get("precision"), stated.get("earliest"), stated.get("latest"))


def _answer_check(context, step_id, name, flags=()):
    reply = _reply(context, step_id)
    answer = reply.get("answer")
    if not answer:
        return _untested(name, "c", "no answer was produced")
    found = {
        flag: bool(re.search(pattern, answer, re.IGNORECASE)) for flag, pattern in flags
    }
    return {
        "check": name,
        "level": "c",
        "status": REVIEW,
        "detail": {"answer": answer, "keyword_flags": found},
    }


def _learning_happened(context, step_id):
    """Learning finished for that turn (it was processed and not dropped)."""
    learning = (_reply(context, step_id) or {}).get("learning") or {}
    return learning.get("processed", 0) > 0 and not learning.get("dropped", 0)


# ------------------------------------------------------------------ checks --


def _d1_items(rows):
    items = _items(rows, "vehicle")
    return items, tuple(_named(items, n) for n in ("classic 350", "tigor", "jimny"))


def _d1_shape_checks(items, classic, tigor, jimny):
    return [
        _check(
            "3 vehicle rows",
            "a",
            len(classic) == len(tigor) == len(jimny) == 1,
            [_label(r) for r in items],
        ),
        _check(
            "3 distinct sources",
            "a",
            len({r["source_id"] for r in classic + tigor + jimny}) == 3,
        ),
        _check(
            "valid_from NULL on all",
            "a",
            all(r["valid_from"] is None for r in classic + tigor + jimny),
        ),
    ]


_D1_ACQUIRED = {
    "classic 350": ("year", "2021-01-01", "2021-12-31"),
    "tigor": ("month", "2017-03-01", "2017-03-31"),
    "jimny": ("month", "2026-10-01", "2026-10-31"),
}


async def check_d1_r(context, log):
    """Amendment 1, D1-R: the frozen D1 wording verbatim. The Classic must be
    stored without a purchase date; the frozen year-2021 expectation is
    reported as SUPERSEDED (never PASS or FAIL)."""
    rows = await _rows(context.memory)
    if not _learning_happened(context, "d1r-01"):
        return [_untested("learning ran", "a", "no learning happened for D1-R")]
    items, (classic, tigor, jimny) = _d1_items(rows)
    checks = _d1_shape_checks(items, classic, tigor, jimny)
    classic_acquired = _value(classic[0]).get("acquired") if classic else None
    checks.append(
        _check(
            "no Classic purchase date invented from 'from 2021'",
            "a",
            bool(classic) and not classic_acquired,
            classic_acquired,
        )
    )
    checks.append(
        {
            "check": "frozen D1 expectation: Classic acquired year 2021",
            "level": "a",
            "status": SUPERSEDED,
            "detail": {
                "superseded_by": "amendment-1",
                "frozen_expected": list(_D1_ACQUIRED["classic 350"]),
                "observed": _time(_value(classic[0]), "acquired") if classic else None,
                "current_requirement": "no Classic purchase date invented",
            },
        }
    )
    for name, rows_for in (("tigor", tigor), ("jimny", jimny)):
        got = _time(_value(rows_for[0]), "acquired") if rows_for else None
        checks.append(_check(f"acquired {name}", "a", got == _D1_ACQUIRED[name], got))
    return checks


async def check_d1(context, log):
    """D1-A1 (amendment 1): the frozen D1 expectations, unchanged, on the
    amended wording with explicit purchase words."""
    rows = await _rows(context.memory)
    if not _learning_happened(context, "story-02"):
        return [_untested("learning ran", "a", "no learning happened for D1-A1")]
    items, (classic, tigor, jimny) = _d1_items(rows)
    checks = _d1_shape_checks(items, classic, tigor, jimny)
    for name, rows_for in (
        ("classic 350", classic),
        ("tigor", tigor),
        ("jimny", jimny),
    ):
        got = _time(_value(rows_for[0]), "acquired") if rows_for else None
        checks.append(_check(f"acquired {name}", "a", got == _D1_ACQUIRED[name], got))
    others = {
        "classic 350": ("tigor", "jimny"),
        "tigor": ("classic", "jimny"),
        "jimny": ("classic", "tigor"),
    }
    for name, rows_for in (
        ("classic 350", classic),
        ("tigor", tigor),
        ("jimny", jimny),
    ):
        quote = (rows_for[0]["evidence_text"] or "") if rows_for else ""
        checks.append(
            _check(
                f"evidence names only {name}",
                "a",
                bool(quote) and not any(o in quote.casefold() for o in others[name]),
                quote,
            )
        )
    return checks


async def check_d2(context, log):
    if not _learning_happened(context, "story-03"):
        return [_untested("learning ran", "a", "no learning happened for D2")]
    rows = await _rows(context.memory)
    vehicles = _items(rows, "vehicle")
    tigors_current = _named(vehicles, "tigor")
    history = _named(_items(rows, "vehicle", current=False), "tigor")
    ops = await _query(
        context.memory,
        "SELECT operation_type, target_id FROM memory_operation WHERE operation_type = 'refine'",
    )
    refined = [r for r in tigors_current if r["supersedes_id"]]
    old = next(
        (
            r
            for r in history
            if refined and r["assertion_id"] == refined[0]["supersedes_id"]
        ),
        None,
    )
    return [
        _check(
            "one current Tigor",
            "a",
            len(tigors_current) == 1,
            [_label(r) for r in tigors_current],
        ),
        _check("Tigor B supersedes A", "a", bool(refined) and old is not None),
        _check(
            "operation is refine",
            "a",
            any(t == refined[0]["assertion_id"] for _, t in ops) if refined else False,
            ops,
        ),
        _check(
            "A not retracted", "a", old is not None and old["state"] == "superseded"
        ),
        _check(
            "A validity unchanged",
            "a",
            old is not None
            and old["valid_to"] is None
            and old["valid_from"] == (refined[0]["valid_from"] if refined else None),
        ),
        _check(
            "diesel detail added",
            "a",
            bool(refined)
            and "diesel" in str(_value(refined[0]).get("details", "")).casefold(),
            _value(refined[0]).get("details") if refined else None,
        ),
        _check("no new item", "a", len(vehicles) == 3, [_label(r) for r in vehicles]),
    ]


async def check_d3(context, log):
    rows = await _rows(context.memory)
    reply = _reply(context, "list-01")
    remember = [t for t in reply.get("tools") or () if t["tool"] == "remember_memory"]
    if not remember:
        return [
            _untested(
                "explicit remember called",
                "a",
                "the model did not call remember_memory",
            )
        ]
    devices = _items(rows, "device")
    dell, ipad = _named(devices, "dell xps"), _named(devices, "ipad air")
    combined = context.marks.get("combined_record") or {}
    current_ids = {r["assertion_id"] for r in rows if r["current"]}
    plural = [
        r
        for r in rows
        if r["current"]
        and r["assertion_id"] != combined.get("assertion_id")
        and "dell" in str(r["value"]).casefold()
        and "ipad" in str(r["value"]).casefold()
    ]
    return [
        _check(
            "remember succeeded",
            "a",
            any(t["result"].get("ok") for t in remember),
            [t["result"] for t in remember],
        ),
        _check(
            "2 device rows",
            "a",
            len(dell) == 1 and len(ipad) == 1,
            [_label(r) for r in devices],
        ),
        _check("2 sources", "a", len({r["source_id"] for r in dell + ipad}) == 2),
        _check("no plural record", "a", not plural, [r["value"] for r in plural]),
        _check(
            "seeded combined record unchanged",
            "a",
            combined.get("assertion_id") in current_ids,
        ),
        {
            "check": "one Hello",
            "level": "a",
            "status": REVIEW,
            "detail": "owner observation: count the Windows Hello prompts during D3",
        },
    ]


async def check_d4(context, log):
    reply = _reply(context, "bike-01")
    reads = _reads(reply)
    return [
        _check(
            "vehicles looked up",
            "b",
            any(r["result"].get("status") == "selected" for r in reads),
            [r["result"].get("status") for r in reads],
        )
        if reads
        else _untested("vehicles looked up", "b", "no lookup happened"),
        _answer_check(
            context,
            "bike-01",
            "clarifies or names both bikes",
            (
                ("names Classic", r"classic"),
                ("names Pulsar", r"pulsar"),
                ("asks which", r"which|kaun"),
            ),
        ),
    ]


async def check_d5(context, log):
    if not _learning_happened(context, "story-04"):
        return [_untested("learning ran", "a", "no learning happened for D5")]
    rows = await _rows(context.memory)
    current = _named(_items(rows, "vehicle"), "tigor")
    history = _named(_items(rows, "vehicle", current=False), "tigor")
    sold = current[0] if current else None
    old = next(
        (r for r in history if sold and r["assertion_id"] == sold["supersedes_id"]),
        None,
    )
    ops = await _query(
        context.memory,
        "SELECT operation_type FROM memory_operation WHERE target_id = ?",
        (sold["assertion_id"] if sold else "",),
    )
    observed = sold["observed_at"] if sold else None
    observed_day = (
        datetime.fromisoformat(observed).astimezone(OWNER_TZ).date().isoformat()
        if observed
        else None
    )
    return [
        _check(
            "new state sold",
            "a",
            sold is not None and _value(sold).get("state") == "sold",
            _value(sold).get("state") if sold else None,
        ),
        _check("historical_change", "a", ("historical_change",) in ops, ops),
        _check(
            "old row superseded, valid_to NULL",
            "a",
            old is not None
            and old["state"] == "superseded"
            and old["valid_to"] is None,
        ),
        _check(
            "unknown effective time (valid_from NULL)",
            "a",
            sold is not None and sold["valid_from"] is None,
        ),
        _check(
            "disposed week 2026-11-09..15",
            "a",
            sold is not None
            and _time(_value(sold), "disposed") == ("week", "2026-11-09", "2026-11-15"),
            _time(_value(sold), "disposed") if sold else None,
        ),
        _check("observed_at 2026-11-18", "a", observed_day == "2026-11-18", observed),
        (
            _check(
                "follow-up lookup completed",
                "b",
                any(
                    r["result"].get("status") == "selected"
                    for r in _reads(_reply(context, "story-05"))
                ),
                [
                    r["result"].get("status")
                    for r in _reads(_reply(context, "story-05"))
                ],
            )
            if _reads(_reply(context, "story-05"))
            else _untested("follow-up lookup completed", "b", "no lookup happened")
        ),
        _answer_check(
            context,
            "story-05",
            "when did I sell it",
            (
                ("last week", r"last week|pichhle hafte"),
                ("9-15 Nov", r"\b9\b.*\b15\b|9.?.?15"),
                ("claims exact day", r"\bon (?:the )?\d{1,2}(?:st|nd|rd|th)? nov"),
            ),
        ),
    ]


async def check_d22(context, log):
    rows = await _rows(context.memory)
    owned = [r for r in _items(rows, "vehicle") if _value(r).get("state") == "owned"]
    sold = _named(_items(rows, "vehicle"), "tigor")
    reads = _reads(_reply(context, "story-06"))
    return [
        _check(
            "current owned list excludes Tigor",
            "a",
            not _named(owned, "tigor"),
            [_label(r) for r in owned],
        ),
        _check(
            "sold row: valid_from NULL, week precision, no exact day",
            "a",
            bool(sold)
            and sold[0]["valid_from"] is None
            and _time(_value(sold[0]), "disposed")[0] == "week",
        ),
        _check(
            "lookup released",
            "b",
            any(r["result"].get("status") == "selected" for r in reads),
        )
        if reads
        else _untested("lookup released", "b", "no lookup happened"),
        _answer_check(
            context,
            "story-06",
            "owned vehicles",
            (("mentions Tigor", r"tigor"), ("says sold", r"sold|bech")),
        ),
    ]


async def check_d6(context, log):
    if not _learning_happened(context, "story-07"):
        return [_untested("learning ran", "a", "no learning happened for D6")]
    rows = await _rows(context.memory)
    plans = [p for p in _plans(rows) if "ladakh" in json.dumps(_value(p)).casefold()]
    plan = _value(plans[0]) if plans else {}
    destination = (plan.get("slots") or {}).get("destination") or {}
    when = (plan.get("slots") or {}).get("when") or {}
    options = [o.casefold() for o in destination.get("options") or ()]
    return [
        _check("one plan", "a", len(plans) == 1, len(plans)),
        _check(
            "status planned",
            "a",
            plan.get("plan_status") == "planned",
            plan.get("plan_status"),
        ),
        _check(
            "destination options [Ladakh, winter Spiti]",
            "a",
            destination.get("value") is None
            and any("ladakh" in o for o in options)
            and any("spiti" in o for o in options),
            destination,
        ),
        _check(
            "when January",
            "a",
            "january" in str(when.get("value", "")).casefold(),
            when,
        ),
    ]


def _notes(context, step_id):
    """The open questions that reached this turn's reply (amendment 2)."""
    learning = (_reply(context, step_id) or {}).get("learning") or {}
    return learning.get("clarification_notes") or []


def _row_slot(row, name):
    return (_value(row).get("slots") or {}).get(name) or {}


async def check_d6_a2(context, log):
    """Amendment 2, D6-A2: alternatives wait for the owner. Before the
    confirmation the plan keeps its clear parts only; after it the same plan
    holds the destination options, undecided. The frozen D6 expectation
    (options straight from the single statement) is reported as SUPERSEDED."""
    if not _learning_happened(context, "story-07"):
        return [_untested("learning ran", "a", "no learning happened for D6-A2")]
    rows = await _rows(context.memory)
    before_ids = set(context.marks["before"]["story-07b"]["all_ids"])
    ladakh = [
        p
        for p in _plans(rows, current=False)
        if "ladakh" in json.dumps(_value(p)).casefold()
    ]
    first = [p for p in ladakh if p["assertion_id"] in before_ids]
    first_destination = _row_slot(first[-1], "destination") if first else {}
    current = [p for p in ladakh if p["current"]]
    plan = _value(current[0]) if current else {}
    destination = (plan.get("slots") or {}).get("destination") or {}
    when = (plan.get("slots") or {}).get("when") or {}
    options = [o.casefold() for o in destination.get("options") or ()]
    notes = _notes(context, "story-07")
    asked = [n for n in notes if n.get("question") == "confirm_alternatives"]
    checks = [
        _check("one plan after the statement", "a", len(first) == 1, len(first)),
        _check(
            "no destination options stored before confirmation",
            "a",
            bool(first) and not first_destination.get("options"),
            first_destination,
        ),
        _check(
            "one question about the destination choices",
            "b",
            len(asked) == 1 and "destination" in (asked[0].get("choices") or {}),
            notes,
        ),
    ]
    if not _learning_happened(context, "story-07b"):
        checks.append(
            _untested("confirmation learned", "a", "no learning for story-07b")
        )
    else:
        checks += [
            _check(
                "same plan after confirmation (one current, superseding)",
                "a",
                len(current) == 1 and current[0]["supersedes_id"] is not None,
                len(current),
            ),
            _check(
                "status planned",
                "a",
                plan.get("plan_status") == "planned",
                plan.get("plan_status"),
            ),
            _check(
                "destination options [Ladakh, winter Spiti], undecided",
                "a",
                destination.get("value") is None
                and any("ladakh" in o for o in options)
                and any("spiti" in o for o in options),
                destination,
            ),
            _check(
                "when January",
                "a",
                "january" in str(when.get("value", "")).casefold(),
                when,
            ),
        ]
    checks.append(
        {
            "check": "frozen D6 expectation: destination options from the statement",
            "level": "a",
            "status": SUPERSEDED,
            "detail": {
                "superseded_by": "amendment-2",
                "frozen_expected": ["Ladakh", "winter Spiti"],
                "observed_before_confirmation": first_destination,
                "current_requirement": "options stored only after the owner confirms",
            },
        }
    )
    checks.append(
        _answer_check(
            context,
            "story-07",
            "asks once whether still choosing, no storage claim",
            (("claims saved", r"saved|noted|updated my memory"), ("asks", r"\?")),
        )
    )
    return checks


async def check_d7(context, log):
    if not _learning_happened(context, "story-08"):
        return [_untested("learning ran", "a", "no learning happened for D7")]
    rows = await _rows(context.memory)
    goa = [p for p in _plans(rows) if "goa" in json.dumps(_value(p)).casefold()]
    return [
        _check("one Goa plan", "a", len(goa) == 1, len(goa)),
        _check(
            "status considering",
            "a",
            bool(goa) and _value(goa[0]).get("plan_status") == "considering",
            _value(goa[0]).get("plan_status") if goa else None,
        ),
    ]


async def check_d8(context, log):
    if not _learning_happened(context, "story-09"):
        return [_untested("learning ran", "a", "no learning happened for D8")]
    rows = await _rows(context.memory)
    before = set(context.marks["before"]["story-09"]["all_ids"])
    new = [r for r in rows if r["assertion_id"] not in before]
    return [
        _check(
            "no plan written",
            "a",
            not [r for r in new if _value(r).get("category") == "plan"],
            [_label(r) for r in new],
        ),
        _check("no fact written", "a", not new, [_label(r) for r in new]),
    ]


async def check_d9(context, log):
    if not _learning_happened(context, "idiom-01"):
        return [_untested("learning ran", "a", "no learning happened for D9")]
    rows = await _rows(context.memory)
    plans = [p for p in _plans(rows) if "spiti" in json.dumps(_value(p)).casefold()]
    plan = _value(plans[0]) if plans else {}
    slots = plan.get("slots") or {}
    vehicle = slots.get("vehicle") or {}
    when = slots.get("when") or {}
    return [
        _check("one Spiti plan", "a", len(plans) == 1, len(plans)),
        _check(
            "status planned",
            "a",
            plan.get("plan_status") == "planned",
            plan.get("plan_status"),
        ),
        _check(
            "destination Spiti",
            "a",
            "spiti"
            in str((slots.get("destination") or {}).get("value", "")).casefold(),
            slots.get("destination"),
        ),
        _check(
            "no vehicle options",
            "a",
            not vehicle.get("options") and "thar" not in json.dumps(vehicle).casefold(),
            vehicle,
        ),
        _check(
            "when January confirmed",
            "a",
            "january" in str(when.get("value", "")).casefold()
            and when.get("certainty") == "confirmed",
            when,
        ),
        _check("no owned Thar", "a", not _named(_items(rows), "thar")),
        # Amendment 2: no question is required; at most one, about the vehicle.
        _check(
            "at most one question, only about the vehicle",
            "b",
            _at_most_one_vehicle_question(context, ("idiom-01", "idiom-02")),
            [_notes(context, s) for s in ("idiom-01", "idiom-02")],
        ),
    ]


def _at_most_one_vehicle_question(context, steps):
    notes = [n for s in steps for n in _notes(context, s)]
    details = [set(n.get("choices") or {}) | set(n.get("unclear") or ()) for n in notes]
    return len(notes) <= 1 and all(d == {"vehicle"} for d in details)


async def check_d10(context, log):
    if not _learning_happened(context, "story-10"):
        return [_untested("learning ran", "a", "no learning happened for D10")]
    rows = await _rows(context.memory)
    spiti = [p for p in _plans(rows) if "spiti" in json.dumps(_value(p)).casefold()]
    plan = _value(spiti[0]) if spiti else {}
    slots = plan.get("slots") or {}
    history = [
        p
        for p in _plans(rows, current=False)
        if not p["current"] and "ladakh" in json.dumps(_value(p)).casefold()
    ]
    before_items = {r for r in context.marks["before"]["story-10"]["current_ids"]}
    items_now = {r["assertion_id"] for r in _items(rows)}
    items_before = {
        r["assertion_id"]
        for r in _items(rows, current=False)
        if r["assertion_id"] in before_items
    }
    return [
        _check(
            "same plan changed (one current Spiti plan, superseding)",
            "a",
            len(spiti) == 1 and spiti[0]["supersedes_id"] is not None,
            len(spiti),
        ),
        _check(
            "destination winter Spiti",
            "a",
            "spiti" in str((slots.get("destination") or {}).get("value", "")).casefold()
            and not (slots.get("destination") or {}).get("options"),
            slots.get("destination"),
        ),
        _check(
            "vehicle slot Jimny",
            "a",
            "jimny" in str((slots.get("vehicle") or {}).get("value", "")).casefold(),
            slots.get("vehicle"),
        ),
        _check(
            "owned items unchanged",
            "a",
            items_now == items_before,
            sorted(items_now ^ items_before),
        ),
        _check("history row keeps the options", "a", bool(history), len(history)),
    ]


async def check_d11(context, log):
    if not _learning_happened(context, "story-11"):
        return [_untested("learning ran", "a", "no learning happened for D11")]
    rows = await _rows(context.memory)
    goa = [p for p in _plans(rows) if "goa" in json.dumps(_value(p)).casefold()]
    return [
        _check(
            "Goa status cancelled",
            "a",
            bool(goa) and _value(goa[0]).get("plan_status") == "cancelled",
            _value(goa[0]).get("plan_status") if goa else None,
        ),
        _answer_check(
            context,
            "story-11",
            "reply does not assume Goa",
            (("claims saved", r"saved|noted|updated my memory"),),
        ),
    ]


async def check_d12(context, log):
    if not _learning_happened(context, "story-12"):
        return [_untested("learning ran", "a", "no learning happened for D12")]
    rows = await _rows(context.memory)
    jimny = _named(_items(rows, "vehicle"), "jimny")
    history = _named(_items(rows, "vehicle", current=False), "jimny")
    current = jimny[0] if jimny else None
    old = next(
        (
            r
            for r in history
            if current and r["assertion_id"] == current["supersedes_id"]
        ),
        None,
    )
    ops = await _query(
        context.memory,
        "SELECT operation_type FROM memory_operation WHERE target_id = ?",
        (current["assertion_id"] if current else "",),
    )
    return [
        _check(
            "acquired month 2026-09",
            "a",
            current is not None
            and _time(_value(current), "acquired")
            == ("month", "2026-09-01", "2026-09-30"),
            _time(_value(current), "acquired") if current else None,
        ),
        _check(
            "year marked inferred, owner's month wording kept",
            "a",
            current is not None
            and _value(current).get("acquired", {}).get("basis") == "inferred_year"
            and "september"
            in str(
                _value(current).get("acquired", {}).get("expression", "")
            ).casefold(),
            _value(current).get("acquired") if current else None,
        ),
        _check(
            "old row retracted",
            "a",
            old is not None and old["state"] == "retracted",
            old["state"] if old else None,
        ),
        _check(
            "correction (not refine or change)",
            "a",
            ("correct",) in ops
            and ("refine",) not in ops
            and ("historical_change",) not in ops,
            ops,
        ),
        # Run 5: the correction replaced the Jimny's value with "September".
        _check(
            "item identity kept (value is still the Jimny)",
            "a",
            current is not None
            and "jimny" in str(_value(current).get("value", "")).casefold(),
            _value(current).get("value") if current else None,
        ),
    ]


async def check_d13(context, log):
    reads = _reads(_reply(context, "story-13"))
    statuses = [
        f.get("temporal", {}).get("date_status")
        for r in reads
        for f in r["result"].get("facts") or ()
        if "rishikesh" in json.dumps(f).casefold()
    ]
    return [
        _check(
            "release date_status passed_outcome_unknown",
            "b",
            "passed_outcome_unknown" in statuses,
            statuses,
        )
        if reads
        else _untested("release date_status", "b", "no lookup happened"),
        _answer_check(
            context,
            "story-13",
            "elapsed plan not called done/cancelled/upcoming",
            (
                ("mentions Rishikesh", r"rishikesh"),
                (
                    "done/cancelled/upcoming wording",
                    r"completed|you went|cancel|upcoming|coming up next",
                ),
            ),
        ),
    ]


async def check_d14(context, log):
    # Graded against D1-A1 (amendment 1): the story states the Classic was
    # bought in 2021, so "Classic 2021" is expected exactly as frozen.
    return [
        _answer_check(
            context,
            "story-14",
            "restart recall",
            (
                ("Classic 2021", r"classic.*2021|2021.*classic"),
                ("Jimny September", r"jimny.*sept|sept.*jimny"),
                ("added a day", r"\b\d{1,2}(?:st|nd|rd|th)? (?:sept|march|jan)"),
                ("Tigor", r"tigor"),
            ),
        )
    ]


_D15_CONTEXT_STEPS = ("story-14",)  # the conversation since the restart


async def check_d15(context, log):
    """D15 needs the decided plan (D10) to reach the answer model - released
    in this turn, or already in this turn's authorised conversation - and an
    answer consistent with it. A lookup alone is not proof the advice used it;
    unrelated plans must stay out. (Run 6's check, "used owned vehicles and
    plans", tested only the vehicle scope; that recorded PASS stands as it
    was.)"""
    rows = await _rows(context.memory)
    decided = [
        p
        for p in _plans(rows)
        if "spiti" in json.dumps(_value(p)).casefold()
        and ((_value(p).get("slots") or {}).get("vehicle") or {}).get("value")
        and ((_value(p).get("slots") or {}).get("destination") or {}).get("value")
    ]
    if not decided:
        return [
            _untested("decided plan", "b", "no decided Spiti plan (D10 not met)"),
            _answer_check(context, "story-15", "useful advice"),
        ]
    vehicle = _value(decided[0])["slots"]["vehicle"]["value"]
    reply = _reply(context, "story-15")
    released = [
        f
        for r in _reads(reply)
        for f in (r.get("result") or {}).get("facts") or ()
        if f.get("scope_key") == "plan"
    ]
    plan_released = [
        f
        for f in released
        if "spiti" in json.dumps(f).casefold()
        and ((f.get("slots") or {}).get("vehicle") or {}).get("value")
    ]
    earlier = [_reply(context, s).get("answer") or "" for s in _D15_CONTEXT_STEPS]
    in_context = any(
        "spiti" in a.casefold() and vehicle.casefold() in a.casefold() for a in earlier
    )
    reached = bool(plan_released) or in_context
    unrelated = [f.get("text") for f in released if f not in plan_released]
    answer = reply.get("answer") or ""
    # A sentence recommending another vehicle without naming the decided one
    # contradicts the plan. A comparison naming both ("the Classic 350 ...
    # but the Jimny ... much better") cannot be read reliably by a pattern:
    # it is flagged for the manual review below, never auto-failed (eea8eea5
    # lab: a correct Jimny answer was failed this way).
    other = r"\b(classic|enfield|tigor)\b[^.!?]*\b(best|better|behtar|recommend)"
    sentences = re.split(r"(?<=[.!?])\s+", answer)
    recommends_other = any(
        re.search(other, s, re.IGNORECASE) and vehicle.casefold() not in s.casefold()
        for s in sentences
    )
    return [
        _check(
            "decided plan reached the model (released this turn or in context)",
            "b",
            reached,
            {
                "released_plans": [f.get("text") for f in plan_released],
                "in_conversation": in_context,
            },
        ),
        _check("unrelated plans left out", "b", not unrelated, unrelated),
        _check(
            "answer consistent with the decided plan",
            "b",
            reached
            and vehicle.casefold() in answer.casefold()
            and not recommends_other,
            {"decided_vehicle": vehicle, "answer": answer},
        )
        if reached
        else _untested(
            "answer consistent with the decided plan",
            "b",
            "the decided plan never reached the model",
        ),
        _answer_check(
            context,
            "story-15",
            "useful advice",
            (
                ("mentions Jimny", r"jimny"),
                ("re-asks", r"which vehicles do you|what vehicles do you"),
                (
                    "compares with another vehicle (check which is recommended)",
                    r"\b(classic|enfield|tigor)\b[^.!?]*\b(best|better|behtar|recommend)",
                ),
            ),
        ),
    ]


async def check_d16(context, log):
    jimny = [
        f
        for r in _reads(_reply(context, "story-16"))
        for f in (r.get("result") or {}).get("facts") or ()
        if "jimny" in str(f.get("text", "")).casefold()
    ]
    told = [(f.get("told") or {}, f.get("first_told") or {}) for f in jimny]
    evidence = (
        _check(
            "released evidence: owner's words and told date, apart from recorded_at",
            "b",
            any(t.get("quote") and t.get("date") and t.get("how") for t, _ in told),
            [
                {
                    "told": t,
                    "first_told": first,
                    "acquired": f.get("acquired"),
                    "recorded_at": f.get("recorded_at"),
                }
                for (t, first), f in zip(told, jimny, strict=True)
            ],
        )
        if jimny
        else _untested(
            "released evidence: owner's words and told date, apart from recorded_at",
            "b",
            "the Jimny was not looked up",
        )
    )
    return [
        evidence,
        _answer_check(
            context,
            "story-16",
            "evidence and told time",
            (
                (
                    "quotes/paraphrases",
                    r"you (?:said|told|mentioned)|last month I got a Jimny",
                ),
                ("purchase month", r"sept|october"),
            ),
        ),
    ]


async def check_d23(context, log):
    if not _learning_happened(context, "story-17"):
        return [_untested("learning ran", "a", "no learning happened for D23")]
    rows = await _rows(context.memory)
    classic = _named(_items(rows, "vehicle"), "classic 350")
    row = classic[0] if classic else None
    return [
        _check(
            "state sold",
            "a",
            row is not None and _value(row).get("state") == "sold",
            _value(row).get("state") if row else None,
        ),
        _check(
            "disposed month 2026-10",
            "a",
            row is not None
            and _time(_value(row), "disposed") == ("month", "2026-10-01", "2026-10-31"),
            _time(_value(row), "disposed") if row else None,
        ),
        _check(
            "year marked inferred, owner's month wording kept",
            "a",
            row is not None
            and _value(row).get("disposed", {}).get("basis") == "inferred_year"
            and "october"
            in str(_value(row).get("disposed", {}).get("expression", "")).casefold(),
            _value(row).get("disposed") if row else None,
        ),
        _check(
            "effective time unknown", "a", row is not None and row["valid_from"] is None
        ),
        _check(
            "not currently owned",
            "a",
            row is not None and _value(row).get("state") != "owned",
        ),
    ]


FORGET_STAGES = (
    "item_absent_from_available_catalog",
    "model_did_not_select_available_item",
    "forget_operation_failed",
    "deleted_but_residual_remains",
    # Kept apart from deletion correctness: the forget was correctly aimed,
    # but fresh owner consent (Windows Hello) was not granted, so nothing was
    # attempted. Consent is never weakened to get past this.
    "owner_consent_not_granted",
)
CONSENT_REFUSED = "Fresh owner consent was not granted"


def _consent_check(consent, detail):
    """Granted only when a consent request for the forget was answered
    "granted". No request at all means the flow never reached consent (for
    example the item was never selected): that is not a pass, it is
    UNTESTED with the reason. A request that was not granted is a FAIL."""
    if any(e.get("outcome") == "granted" for e in consent):
        status = PASS
    elif consent:
        status = FAIL
    else:
        status = UNTESTED
    return {
        "check": "fresh owner consent granted (Windows Hello)",
        "level": "a",
        "status": status,
        "detail": {
            "consent_outcomes": consent,
            "reached": bool(consent),
            "forget_calls": detail.get("forget_calls"),
            "target_reads": detail.get("target_reads"),
        },
    }


def diagnose_forget(tools, target_predicates, lineage_remaining, residual):
    """Which stage of D17 failed, or None when it fully passed.

    ``tools`` are the driver's tool calls with results for the D17 turn;
    ``target_predicates`` are the predicates that held the Classic 350 just
    before the turn; ``lineage_remaining`` counts its rows left afterwards;
    ``residual`` is the residual report. Stages, in order:
    1. item_absent_from_available_catalog: no catalog result the model
       received listed the item's predicate (or no catalog was obtained);
    2. model_did_not_select_available_item: it was listed, but no
       forget_memory call targeted it (no call, another facet, bad index);
    3. forget_operation_failed: a call targeted it, but none succeeded
       (refused, Hello declined, error) or rows of it remain;
    4. deleted_but_residual_remains: it was deleted, but a personal-memory
       store still holds the term.
    """
    targets = set(target_predicates)
    catalogs = {}
    for call in tools:
        result = call.get("result") or {}
        if call["tool"] == "personal_context_catalog" and result.get("catalog_id"):
            catalogs[result["catalog_id"]] = list(result.get("facets") or ())
    listed = targets & {f for facets in catalogs.values() for f in facets}
    shown = any(
        "classic 350" in json.dumps(call.get("result"), default=str).casefold()
        for call in tools
        if call["tool"] == "read_personal_context"
    )
    forgets = [call for call in tools if call["tool"] == "forget_memory"]

    def target_of(call):
        arguments = call.get("arguments") or {}
        facets = catalogs.get(arguments.get("catalog_id"), [])
        index = arguments.get("facet_index")
        if isinstance(index, int) and 0 <= index < len(facets):
            return facets[index]
        return arguments.get("predicate")

    aimed = [call for call in forgets if target_of(call) in targets]
    detail = {
        "catalogs_received": len(catalogs),
        "listed_in_catalog": bool(listed),
        "shown_by_read": shown,
        # Each read's selection and status (an opaque catalog is resolved
        # by reading; refused reads are where target resolution stops).
        "target_reads": [
            {
                "facet_indices": (call.get("arguments") or {}).get("facet_indices"),
                "status": (call.get("result") or {}).get("status"),
                "reason": (call.get("result") or {}).get("reason"),
            }
            for call in tools
            if call["tool"] == "read_personal_context"
        ],
        "forget_calls": [
            {
                "target": target_of(c),
                "targets_item": target_of(c) in targets,
                "result": c.get("result"),
            }
            for c in forgets
        ],
        "lineage_remaining": lineage_remaining,
        "residual": residual,
    }
    if not listed:
        return FORGET_STAGES[0], detail
    if not aimed:
        return FORGET_STAGES[1], detail
    if not any((c.get("result") or {}).get("ok") for c in aimed) and all(
        CONSENT_REFUSED in str((c.get("result") or {}).get("message", ""))
        for c in aimed
    ):
        return FORGET_STAGES[4], detail
    if not any((c.get("result") or {}).get("ok") for c in aimed) or lineage_remaining:
        return FORGET_STAGES[2], detail
    if any(residual.values()):
        return FORGET_STAGES[3], detail
    return None, detail


async def check_d17(context, log):
    """D17 is a required gate: any failing stage fails the case."""
    from jarvis.memory.forget_residuals import residual_report

    reply = _reply(context, "story-18")
    before = (context.marks.get("before") or {}).get("story-18") or {}
    targets = [
        predicate
        for predicate, label in (before.get("current_labels") or {}).items()
        if "classic 350" in label.casefold()
    ]
    if not reply or not targets:
        return [
            _untested(
                "forget gate",
                "a",
                "the D17 turn did not run"
                if not reply
                else "no Classic 350 fact existed before D17",
            )
        ]
    rows = await _rows(context.memory)
    remaining = len([r for r in rows if r["predicate"] in set(targets)])
    report = await context.memory._reader.run(
        lambda c: residual_report(c, ["Classic 350"])
    )
    context.marks["residual"] = report
    stage, detail = diagnose_forget(
        reply.get("tools") or (), targets, remaining, report
    )
    others = [
        r
        for r in rows
        if r["current"] and any(n in _label(r).casefold() for n in ("tigor", "jimny"))
    ]
    # Only the latest attempt's consent requests (a recovery reruns the turn;
    # the earlier attempt's outcomes stay in the log and the case history).
    started = [
        r.get("at")
        for r in log.read(log.steps)
        if r["step_id"] == "story-18" and r["status"] == "started"
    ]
    consent = [
        e
        for e in log.read(log.events)
        if e.get("kind") == "consent_outcome"
        and e.get("step_id") == "story-18"
        and (not started or (e.get("at") or "") >= (started[-1] or ""))
    ]
    if stage == "owner_consent_not_granted":
        # Deletion was never attempted, so its correctness is untested here.
        return [
            _check(
                "fresh owner consent granted (Windows Hello)",
                "a",
                False,
                {"consent_outcomes": consent, **detail},
            ),
            {
                "check": "forget gate (stage diagnosis)",
                "level": "a",
                "status": UNTESTED,
                "detail": {"failed_stage": stage, **detail},
            },
            _untested("lineage gone", "a", "deletion not attempted"),
            _untested(
                "no evidence text names Classic 350", "a", "deletion not attempted"
            ),
            _check(
                "Tigor and Jimny facts and evidence intact",
                "a",
                len(others) >= 2 and all(r["evidence_text"] for r in others),
                [(_label(r), bool(r["evidence_text"])) for r in others],
            ),
        ]
    return [
        _consent_check(consent, detail),
        {
            "check": "forget gate (stage diagnosis)",
            "level": "a",
            "status": PASS if stage is None else FAIL,
            "detail": {"failed_stage": stage, **detail},
        },
        _check("lineage gone", "a", remaining == 0, remaining),
        _check(
            "no evidence text names Classic 350",
            "a",
            report["evidence_quotes"] == 0,
            report,
        ),
        _check(
            "Tigor and Jimny facts and evidence intact",
            "a",
            len(others) >= 2 and all(r["evidence_text"] for r in others),
            [(_label(r), bool(r["evidence_text"])) for r in others],
        ),
        {
            "check": "project-history whole-row redaction",
            "level": "a",
            "status": PASS,
            "detail": "known limitation recorded (project history not used in this lab)",
        },
    ]


async def check_d26(context, log):
    from jarvis.memory.forget_residuals import residual_report

    rows = await _rows(context.memory)
    if _named(_items(rows, current=False), "classic 350"):
        return [
            _untested(
                "no residual after forget",
                "a",
                "D17 did not delete the Classic 350, so there is nothing to check yet (D17 fails the gate)",
            )
        ]
    report = context.marks.get("residual") or await context.memory._reader.run(
        lambda c: residual_report(c, ["Classic 350"])
    )
    return [
        _check(
            "no residual in any personal-memory store",
            "a",
            all(v == 0 for v in report.values()),
            report,
        ),
        {
            "check": "diagnostic logs and backups",
            "level": "a",
            "status": PASS,
            "detail": "listed as retained (known limits); this lab keeps no diagnostic text logs",
        },
    ]


async def check_d21(context, log):
    rows = await _rows(context.memory)
    by_id = {r["assertion_id"]: r for r in rows}
    ops = await _query(
        context.memory, "SELECT operation_type, target_id FROM memory_operation"
    )
    refines = [by_id.get(t) for kind, t in ops if kind == "refine" and t in by_id]
    corrects = [by_id.get(t) for kind, t in ops if kind == "correct" and t in by_id]
    changes = [
        by_id.get(t) for kind, t in ops if kind == "historical_change" and t in by_id
    ]

    def predecessor(row):
        return by_id.get(row["supersedes_id"]) if row and row["supersedes_id"] else None

    orphans = await _query(
        context.memory,
        "SELECT count(*) FROM memory_source s WHERE NOT EXISTS (SELECT 1 FROM semantic_assertion a WHERE a.source_id = s.source_id) AND NOT EXISTS (SELECT 1 FROM memory_operation o WHERE o.source_id = s.source_id)",
    )
    current = [r for r in rows if r["current"]]
    return [
        _check(
            "refine predecessors superseded, validity untouched",
            "a",
            bool(refines)
            and all(
                predecessor(r)
                and predecessor(r)["state"] == "superseded"
                and predecessor(r)["valid_to"] is None
                for r in refines
            ),
            len(refines),
        ),
        _check(
            "corrections retracted",
            "a",
            bool(corrects)
            and all(
                predecessor(r) and predecessor(r)["state"] == "retracted"
                for r in corrects
            ),
            len(corrects),
        ),
        _check(
            "changes superseded with unknown or known effective time",
            "a",
            bool(changes)
            and all(
                predecessor(r) and predecessor(r)["state"] == "superseded"
                for r in changes
            ),
            len(changes),
        ),
        _check("no orphan sources", "a", orphans[0][0] == 0, orphans[0][0]),
        _check(
            "every current row has a source",
            "a",
            all(r["source_id"] and r["source_class"] for r in current),
        ),
    ]


async def check_d18(context, log):
    reads = _reads(_reply(context, "s11-01"))
    if not reads:
        return [_untested("lookup", "b", "no lookup happened")]
    first = reads[0]["result"].get("paging") or {}
    released = {
        _label({"value": f, "current": True}) or f.get("text", "")
        for r in reads
        for f in r["result"].get("facts") or ()
    }
    answer = _reply(context, "s11-01").get("answer") or ""
    named = [
        f"Vehicle {i:02d}"
        for i in range(1, 12)
        if f"vehicle {i:02d}" in answer.casefold()
    ]
    return [
        _check("total 11", "b", first.get("total") == 11, first.get("total")),
        _check(
            "first page released <= 8",
            "b",
            (first.get("this_page") or {}).get("to", 99) <= 8,
            first.get("this_page"),
        ),
        _check("complete false on first page", "b", first.get("complete") is False),
        _check(
            "paging completed if attempted (partial answer also allowed)",
            "b",
            len(reads) == 1
            or (reads[-1]["result"].get("paging") or {}).get("complete") is True,
            [len(r["result"].get("facts") or ()) for r in reads],
            review=False,
        ),
        _answer_check(
            context,
            "s11-01",
            "partial or all 11 named",
            (("says partial/11", r"\b11\b|partial|more"),),
        )
        | {
            "detail": {
                "answer": answer,
                "named_count": len(named),
                "released_count": len(released),
                "pagination_exercised": len(reads) >= 2,
            }
        },
    ]


async def check_d19(context, log):
    rows = await _rows(context.memory)
    scooter = _named(_items(rows, "vehicle"), "xoom")
    reads = _reads(_reply(context, "s90-02"))
    first = (reads[0]["result"].get("paging") or {}) if reads else {}
    checks = [
        _check(
            "90+ standard rows, no overflow",
            "a",
            len([r for r in rows if r["current"]]) >= 90,
        ),
        _check(
            "learning candidate resolved (scooter saved)",
            "a",
            len(scooter) == 1,
            [_label(r) for r in scooter],
        )
        if _learning_happened(context, "s90-01")
        else _untested("learning", "a", "no learning happened"),
    ]
    if reads:
        checks += [
            _check(
                "lookup selected",
                "b",
                reads[0]["result"].get("status") == "selected",
                reads[0]["result"].get("status"),
            ),
            _check(
                "total 45 plans, complete reported truthfully",
                "b",
                first.get("total") == 45 and first.get("complete") is False,
                {"total": first.get("total"), "complete": first.get("complete")},
            ),
        ]
    else:
        checks.append(_untested("lookup", "b", "no lookup happened"))
    checks.append(
        _answer_check(
            context,
            "s90-02",
            "partial truthfully",
            (("says 45/partial", r"\b45\b|partial|more"),),
        )
    )
    return checks


async def check_d20(context, log):
    reads = _reads(_reply(context, "bytes-01"))
    if not reads:
        return [_untested("lookup", "b", "no lookup happened")]
    first = reads[0]["result"]
    facts = first.get("facts") or ()
    encoded = len(json.dumps(facts, ensure_ascii=False, separators=(",", ":")).encode())
    return [
        _check(
            "page ends by bytes (fewer than 6, <= 3000 bytes)",
            "b",
            0 < len(facts) < 6 and encoded <= 3000,
            {"facts": len(facts), "bytes": encoded},
        ),
        _check(
            "complete false", "b", (first.get("paging") or {}).get("complete") is False
        ),
        _check(
            "no truncated item",
            "b",
            all(
                "omitted" not in f and str(f.get("details", "")).startswith(_LONG)
                for f in facts
            ),
        ),
        _answer_check(
            context,
            "bytes-01",
            "partial list",
            (("says partial/6", r"\b6\b|six|partial|more"),),
        ),
    ]


async def check_d24(context, log):
    if not _learning_happened(context, "plan40-01"):
        return [_untested("learning ran", "a", "no learning happened for D24")]
    rows = await _rows(context.memory)
    before = context.marks["before"]["plan40-01"]
    outcomes = await _query(
        context.memory, "SELECT reason_code FROM personal_learning_outcome"
    )
    reasons = [r[0] for r in outcomes]
    new = [r for r in rows if r["assertion_id"] not in set(before["all_ids"])]
    return [
        _check(
            "skip recorded with reason",
            "a",
            any(
                r in {"catalog_page_ambiguous", "ambiguous_existing_fact"}
                for r in reasons
            ),
            reasons,
        ),
        _check("no new or changed fact", "a", not new, [_label(r) for r in new]),
        _answer_check(
            context,
            "plan40-01",
            "does not claim saved",
            (("claims saved/added", r"\b(?:added|saved|updated|noted)\b"),),
        ),
    ]


async def check_d25(context, log):
    reads = _reads(_reply(context, "p40-01"))
    if not reads:
        return [_untested("lookup", "b", "no lookup happened")]
    released = sum(len(r["result"].get("facts") or ()) for r in reads)
    last = reads[-1]["result"].get("paging") or {}
    return [
        _check(
            "first page plus 3 extra pages (32 items)",
            "b",
            len(reads) == 4 and released == 32,
            {"pages": len(reads), "released": released},
        ),
        _check(
            "more_remaining with total 40",
            "b",
            last.get("more_remaining") is True and last.get("total") == 40,
            {k: last.get(k) for k in ("more_remaining", "total", "complete")},
        ),
        _check(
            "every page bound to the same question permit",
            "b",
            all(r["result"].get("status") == "selected" for r in reads),
        ),
        _answer_check(
            context,
            "p40-01",
            "says more exist (40)",
            (("says 40/more", r"\b40\b|more"),),
        ),
    ]


def _plan_named(rows, needle, *, current=True):
    return [
        p
        for p in _plans(rows, current=current)
        if needle in json.dumps(_value(p)).casefold()
    ]


def _slot_mentions(rows, needles):
    """Any stored slot (current or history) holding these words."""
    return [
        (_label(r), name, slot)
        for r in rows
        for name, slot in ((_value(r).get("slots") or {}).items())
        if any(n in json.dumps(slot).casefold() for n in needles)
    ]


async def check_d28(context, log):
    """Amendment 2, D28: a final choice is saved on the same plan."""
    if not _learning_happened(context, "alt-01"):
        return [_untested("learning ran", "a", "no learning happened for D28")]
    rows = await _rows(context.memory)
    before_ids = set(context.marks["before"]["alt-02"]["all_ids"])
    spiti = _plan_named(rows, "spiti", current=False)
    first = [p for p in spiti if p["assertion_id"] in before_ids]
    current = [p for p in spiti if p["current"]]
    vehicle = _row_slot(current[0], "vehicle") if current else {}
    slots = (_value(current[0]).get("slots") or {}) if current else {}
    asked = _notes(context, "alt-01")
    return [
        _check(
            "no vehicle stored before the answer",
            "a",
            bool(first) and not _row_slot(first[-1], "vehicle"),
            _row_slot(first[-1], "vehicle") if first else None,
        ),
        _check(
            "one question about the vehicle",
            "b",
            _at_most_one_vehicle_question(context, ("alt-01",)) and len(asked) == 1,
            asked,
        ),
        _check(
            "same plan, vehicle Jimny decided",
            "a",
            len(current) == 1
            and current[0]["supersedes_id"] is not None
            and "jimny" in str(vehicle.get("value", "")).casefold()
            and not vehicle.get("options"),
            vehicle,
        ),
        _check(
            "destination Spiti and January kept",
            "a",
            "spiti" in str((slots.get("destination") or {}).get("value", "")).casefold()
            and "january" in str((slots.get("when") or {}).get("value", "")).casefold(),
            slots,
        ),
        _check(
            "no owned Thar or Jimny added",
            "a",
            not _items(rows),
            [_label(r) for r in _items(rows)],
        ),
    ]


async def check_d29(context, log):
    """Amendment 2, D29: "doesn't matter" discards the pending detail."""
    if not _learning_happened(context, "alt-03"):
        return [_untested("learning ran", "a", "no learning happened for D29")]
    rows = await _rows(context.memory)
    kerala = _plan_named(rows, "kerala", current=False)
    current = [p for p in kerala if p["current"]]
    when = _row_slot(current[0], "when") if current else {}
    return [
        _check("one Kerala plan", "a", len(current) == 1, len(current)),
        _check(
            "March kept", "a", "march" in str(when.get("value", "")).casefold(), when
        ),
        _check(
            "no train/flight stored at any point",
            "a",
            not _slot_mentions(kerala, ("train", "flight")),
            _slot_mentions(kerala, ("train", "flight")),
        ),
    ]


async def check_d30(context, log):
    """Amendment 2, D30: an unrelated reply and the end of the conversation
    leave the pending detail unsaved."""
    if not _learning_happened(context, "alt-05"):
        return [_untested("learning ran", "a", "no learning happened for D30")]
    rows = await _rows(context.memory)
    goa = _plan_named(rows, "goa", current=False)
    current = [p for p in goa if p["current"]]
    when = _row_slot(current[0], "when") if current else {}
    return [
        _check("one Goa plan", "a", len(current) == 1, len(current)),
        _check(
            "April kept", "a", "april" in str(when.get("value", "")).casefold(), when
        ),
        _check(
            "no Airbnb/hotel stored at any point",
            "a",
            not _slot_mentions(goa, ("airbnb", "hotel")),
            _slot_mentions(goa, ("airbnb", "hotel")),
        ),
        _check(
            "the new conversation carries no old question",
            "b",
            not _notes(context, "alt-07"),
            _notes(context, "alt-07"),
        ),
    ]


CHECKS = {
    "D1-A1": check_d1,
    "D1-R": check_d1_r,
    "D2": check_d2,
    "D3": check_d3,
    "D4": check_d4,
    "D5": check_d5,
    "D6-A2": check_d6_a2,
    "D7": check_d7,
    "D8": check_d8,
    "D9": check_d9,
    "D10": check_d10,
    "D11": check_d11,
    "D12": check_d12,
    "D13": check_d13,
    "D14": check_d14,
    "D15": check_d15,
    "D16": check_d16,
    "D17": check_d17,
    "D18": check_d18,
    "D19": check_d19,
    "D20": check_d20,
    "D21": check_d21,
    "D22": check_d22,
    "D23": check_d23,
    "D24": check_d24,
    "D25": check_d25,
    "D26": check_d26,
    "D28": check_d28,
    "D29": check_d29,
    "D30": check_d30,
}
