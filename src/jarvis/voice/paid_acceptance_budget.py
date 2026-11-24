"""Lab-only Paid lane for slice-1 development acceptance (owner approval
2026-11-23: up to USD 1, development acceptance only).

One durable SQLite ledger holds a single fixed budget shared by every Paid
request of every Paid acceptance lab, including retries and resumes. Before
each actual provider request a conservative worst-case cost is reserved and
committed to disk; the request is refused (never sent) if the reservation
does not fit. After the request, a reservation is settled to the cost of the
provider-reported usage. A request whose usage is unknown (provider error,
timeout, cancellation, crash, missing usage) keeps its full reservation; it is
never counted as zero. The ceiling is fixed at creation: there is no reset and
no increase. A settled cost above its reservation halts the budget.

Every request is checked before anything is reserved or sent: the model must
be the priced model and only the request options the slice-1 clients use are
accepted (an unpriced model or option is refused). A named allowance (for
example the checkpoint's USD 0.10) caps a slice of the shared budget.

Nothing here is used by Jarvis outside the acceptance lab.
"""

from __future__ import annotations

import json
import math
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from jarvis.ai_provider import gemini_credential_ref

PAID_CREDENTIAL_REF = gemini_credential_ref("paid")
BUDGET_ID = "slice1-paid-dev-acceptance-2026-11-23"
CEILING_MICRO_USD = 1_000_000  # USD 1.00, owner-approved; never raised here

# Verified paid-tier list prices for gemini-3.5-flash-lite (ai.google.dev
# pricing, checked 2026-11-23): input $0.30 / 1M tokens (text), output
# $2.50 / 1M tokens including thinking tokens. Cached-input discounts are
# ignored (conservative).
PRICING = {
    "model": "gemini-3.5-flash-lite",
    "input_usd_per_million": 0.30,
    "output_usd_per_million": 2.50,
    "source": "https://ai.google.dev/pricing (paid tier, checked 2026-11-23)",
}
# Input is bounded by the UTF-8 byte length of everything sent (system
# instruction, input and response schema), plus overhead: a token is never
# shorter than one byte. Output is bounded by the request's own
# max_output_tokens, which Google documents as the combined total of thinking
# and output tokens ("max_output_tokens applies to the combined total of
# thinking tokens and output tokens"; thinking is billed as output:
# https://ai.google.dev/gemini-api/docs/thinking). A settled cost above its
# reservation still halts the ledger, so a wrong bound cannot keep spending.
INPUT_OVERHEAD_TOKENS = 256
MAX_OUTPUT_TOKENS_LIMIT = 8192
ALLOWED_REQUEST_KEYS = frozenset(
    {
        "model",
        "input",
        "system_instruction",
        "response_format",
        "store",
        "generation_config",
    }
)
ALLOWED_RESPONSE_FORMAT_KEYS = frozenset({"type", "mime_type", "schema"})


class PaidBudgetExhausted(RuntimeError):
    """The next Paid request cannot fit in the remaining budget; nothing sent."""


class PaidBudgetHalted(RuntimeError):
    """The ledger is halted (a cost exceeded its reservation); nothing sent."""


class PaidAllowanceExhausted(PaidBudgetExhausted):
    """The next request does not fit in the named allowance; nothing sent."""


class PaidRequestRefused(RuntimeError):
    """Unpriced model or request option; nothing reserved or sent."""


def check_request(kwargs: dict) -> int:
    """Refuse anything the pricing does not cover. Returns max_output_tokens."""
    extra = set(kwargs) - ALLOWED_REQUEST_KEYS
    if extra:
        raise PaidRequestRefused(f"unpriced request options refused: {sorted(extra)}")
    if kwargs.get("model") != PRICING["model"]:
        raise PaidRequestRefused(
            f"model {kwargs.get('model')!r} is not the priced {PRICING['model']!r}"
        )
    if not isinstance(kwargs.get("input"), str) or not isinstance(
        kwargs.get("system_instruction"), str
    ):
        raise PaidRequestRefused("paid requests send text input and instruction only")
    if kwargs.get("store", False) is not False:
        raise PaidRequestRefused("stored interactions are refused")
    response_format = kwargs.get("response_format")
    if response_format is not None and (
        not isinstance(response_format, dict)
        or set(response_format) - ALLOWED_RESPONSE_FORMAT_KEYS
        or response_format.get("type") != "text"
    ):
        raise PaidRequestRefused("unpriced response format refused")
    config = kwargs.get("generation_config")
    if not isinstance(config, dict) or set(config) != {"max_output_tokens"}:
        raise PaidRequestRefused(
            "generation_config must be exactly {max_output_tokens}; other options"
            " (thinking, tools, caching, media) are refused"
        )
    bound = config["max_output_tokens"]
    if type(bound) is not int or not 0 < bound <= MAX_OUTPUT_TOKENS_LIMIT:
        raise PaidRequestRefused("max_output_tokens must be 1..8192")
    return bound


def _micro(tokens: int, usd_per_million: float) -> int:
    """tokens x (USD per million tokens) is micro-USD; rounded up."""
    return math.ceil(tokens * usd_per_million)


def worst_case(input_bytes: int, max_output_tokens: int) -> tuple[int, int, int]:
    input_bound = input_bytes + INPUT_OVERHEAD_TOKENS
    output_bound = max_output_tokens  # includes thinking (Google docs)
    cost = _micro(input_bound, PRICING["input_usd_per_million"]) + _micro(
        output_bound, PRICING["output_usd_per_million"]
    )
    return input_bound, output_bound, cost


def usage_cost(usage: dict[str, int] | None) -> int | None:
    """Cost of provider-reported usage, or None when it is unknown."""
    if not usage or type(usage.get("input_tokens")) is not int:
        return None
    inp = usage["input_tokens"]
    if type(usage.get("tool_use_tokens")) is int:
        inp += usage["tool_use_tokens"]  # billed as input
    out = usage.get("output_tokens")
    thoughts = usage.get("reasoning_tokens") or 0
    total = usage.get("total_tokens")
    candidates = []
    if type(out) is int:
        candidates.append(out + thoughts)
    if type(total) is int:
        candidates.append(total - inp)
    if not candidates:
        return None
    billed_output = max(candidates)  # never undercount thinking
    return _micro(inp, PRICING["input_usd_per_million"]) + _micro(
        billed_output, PRICING["output_usd_per_million"]
    )


class PaidBudgetLedger:
    """Durable shared budget. Every write is committed before it is relied on."""

    def __init__(self, path: Path, *, clock=time.time):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._db = sqlite3.connect(self.path, isolation_level=None, timeout=30)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS budget (
                budget_id TEXT PRIMARY KEY,
                ceiling_micro_usd INTEGER NOT NULL,
                pricing TEXT NOT NULL,
                created_at TEXT NOT NULL,
                halted_reason TEXT
            );
            CREATE TABLE IF NOT EXISTS request (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL UNIQUE,
                budget_id TEXT NOT NULL REFERENCES budget(budget_id),
                lab TEXT NOT NULL,
                call_path TEXT NOT NULL,
                model TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN
                    ('reserved', 'settled', 'unknown_retained')),
                input_bound INTEGER NOT NULL,
                output_bound INTEGER NOT NULL,
                reserved_micro_usd INTEGER NOT NULL,
                charged_micro_usd INTEGER,
                usage TEXT,
                outcome TEXT,
                reserved_at TEXT NOT NULL,
                finished_at TEXT
            );
            CREATE TABLE IF NOT EXISTS allowance (
                allowance_id TEXT PRIMARY KEY,
                budget_id TEXT NOT NULL REFERENCES budget(budget_id),
                cap_micro_usd INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        columns = {r[1] for r in self._db.execute("PRAGMA table_info(request)")}
        if "allowance_id" not in columns:  # ledgers created before allowances
            self._db.execute("ALTER TABLE request ADD COLUMN allowance_id TEXT")
        self._db.execute("BEGIN IMMEDIATE")
        row = self._db.execute(
            "SELECT ceiling_micro_usd FROM budget WHERE budget_id = ?", (BUDGET_ID,)
        ).fetchone()
        if row is None:
            self._db.execute(
                "INSERT INTO budget VALUES (?, ?, ?, ?, NULL)",
                (BUDGET_ID, CEILING_MICRO_USD, json.dumps(PRICING), _now()),
            )
        elif row[0] != CEILING_MICRO_USD:
            self._db.execute("ROLLBACK")
            raise ValueError("paid budget ceiling differs from the approved USD 1")
        others = self._db.execute(
            "SELECT count(*) FROM budget WHERE budget_id != ?", (BUDGET_ID,)
        ).fetchone()[0]
        if others:
            self._db.execute("ROLLBACK")
            raise ValueError("paid ledger holds another budget")
        self._db.execute("COMMIT")

    def close(self):
        self._db.close()

    def _committed(self) -> int:
        settled, held = self._db.execute(
            "SELECT"
            " coalesce(sum(CASE WHEN status = 'settled' THEN charged_micro_usd END), 0),"
            " coalesce(sum(CASE WHEN status != 'settled' THEN reserved_micro_usd END), 0)"
            " FROM request WHERE budget_id = ?",
            (BUDGET_ID,),
        ).fetchone()
        return settled + held

    def _allowance_used(self, allowance_id: str) -> int:
        settled, held = self._db.execute(
            "SELECT"
            " coalesce(sum(CASE WHEN status = 'settled' THEN charged_micro_usd END), 0),"
            " coalesce(sum(CASE WHEN status != 'settled' THEN reserved_micro_usd END), 0)"
            " FROM request WHERE budget_id = ? AND allowance_id = ?",
            (BUDGET_ID, allowance_id),
        ).fetchone()
        return settled + held

    def reserve(
        self,
        *,
        lab: str,
        call_path: str,
        model: str,
        input_bytes: int,
        max_output_tokens: int,
        allowance: tuple[str, int] | None = None,
    ) -> str:
        input_bound, output_bound, cost = worst_case(input_bytes, max_output_tokens)
        self._db.execute("BEGIN IMMEDIATE")
        try:
            allowance_id = None
            if allowance is not None:
                allowance_id, cap = allowance
                row = self._db.execute(
                    "SELECT cap_micro_usd FROM allowance WHERE allowance_id = ?",
                    (allowance_id,),
                ).fetchone()
                if row is None:
                    self._db.execute(
                        "INSERT INTO allowance VALUES (?, ?, ?, ?)",
                        (allowance_id, BUDGET_ID, cap, _now()),
                    )
                elif row[0] != cap:
                    raise ValueError(
                        f"allowance {allowance_id} was fixed at {row[0]} micro-USD"
                    )
                used = self._allowance_used(allowance_id)
                if used + cost > cap:
                    raise PaidAllowanceExhausted(
                        f"next {call_path} request needs up to {cost / 1e6:.6f} USD;"
                        f" allowance {allowance_id} has"
                        f" {(cap - used) / 1e6:.6f} of {cap / 1e6:.2f} USD left"
                    )
            halted = self._db.execute(
                "SELECT halted_reason FROM budget WHERE budget_id = ?", (BUDGET_ID,)
            ).fetchone()[0]
            if halted:
                raise PaidBudgetHalted(halted)
            committed = self._committed()
            if committed + cost > CEILING_MICRO_USD:
                raise PaidBudgetExhausted(
                    f"next {call_path} request needs up to {cost / 1e6:.6f} USD;"
                    f" {(CEILING_MICRO_USD - committed) / 1e6:.6f} USD of"
                    f" {CEILING_MICRO_USD / 1e6:.2f} USD remains uncommitted"
                )
            request_id = str(uuid4())
            self._db.execute(
                "INSERT INTO request (request_id, budget_id, lab, call_path, model,"
                " status, input_bound, output_bound, reserved_micro_usd, reserved_at,"
                " allowance_id) VALUES (?, ?, ?, ?, ?, 'reserved', ?, ?, ?, ?, ?)",
                (
                    request_id,
                    BUDGET_ID,
                    lab,
                    call_path,
                    model,
                    input_bound,
                    output_bound,
                    cost,
                    _now(),
                    allowance_id,
                ),
            )
            self._db.execute("COMMIT")
            return request_id
        except BaseException:
            self._db.execute("ROLLBACK")
            raise

    def settle(self, request_id: str, usage: dict[str, int] | None, outcome: str):
        cost = usage_cost(usage) if outcome == "ok" else None
        self._db.execute("BEGIN IMMEDIATE")
        try:
            reserved = self._db.execute(
                "SELECT reserved_micro_usd FROM request WHERE request_id = ?"
                " AND status = 'reserved'",
                (request_id,),
            ).fetchone()
            if reserved is None:
                raise ValueError("unknown or already finished paid request")
            if cost is None:
                self._db.execute(
                    "UPDATE request SET status = 'unknown_retained',"
                    " charged_micro_usd = reserved_micro_usd, usage = ?, outcome = ?,"
                    " finished_at = ? WHERE request_id = ?",
                    (json.dumps(usage) if usage else None, outcome, _now(), request_id),
                )
            else:
                self._db.execute(
                    "UPDATE request SET status = 'settled', charged_micro_usd = ?,"
                    " usage = ?, outcome = ?, finished_at = ? WHERE request_id = ?",
                    (cost, json.dumps(usage), outcome, _now(), request_id),
                )
                if cost > reserved[0]:
                    self._db.execute(
                        "UPDATE budget SET halted_reason = ? WHERE budget_id = ?",
                        (
                            f"request {request_id} cost {cost} micro-USD above its"
                            + f" reservation {reserved[0]}",
                            BUDGET_ID,
                        ),
                    )
            self._db.execute("COMMIT")
        except BaseException:
            self._db.execute("ROLLBACK")
            raise

    def snapshot(self) -> dict[str, Any]:
        rows = self._db.execute(
            "SELECT call_path, status, count(*), coalesce(sum(charged_micro_usd), 0),"
            " coalesce(sum(reserved_micro_usd), 0) FROM request WHERE budget_id = ?"
            " GROUP BY call_path, status",
            (BUDGET_ID,),
        ).fetchall()
        halted = self._db.execute(
            "SELECT halted_reason FROM budget WHERE budget_id = ?", (BUDGET_ID,)
        ).fetchone()[0]
        committed = self._committed()
        allowances = [
            {
                "allowance_id": a,
                "cap_usd": cap / 1e6,
                "used_usd": self._allowance_used(a) / 1e6,
            }
            for a, cap in self._db.execute(
                "SELECT allowance_id, cap_micro_usd FROM allowance ORDER BY created_at"
            )
        ]
        return {
            "budget_id": BUDGET_ID,
            "ledger": str(self.path),
            "ceiling_usd": CEILING_MICRO_USD / 1e6,
            "committed_usd": committed / 1e6,
            "remaining_usd": (CEILING_MICRO_USD - committed) / 1e6,
            "halted_reason": halted,
            "pricing": PRICING,
            "output_bound": "max_output_tokens (includes thinking, per Google docs)",
            "allowances": allowances,
            "requests": [
                {
                    "call_path": p,
                    "status": s,
                    "count": n,
                    "charged_usd": c / 1e6 if s != "reserved" else None,
                    "held_usd": r / 1e6 if s == "reserved" else None,
                }
                for p, s, n, c, r in rows
            ],
        }


def _now():
    return datetime.now(UTC).isoformat()


@dataclass
class _Interactions:
    owner: BudgetedGeminiClient

    async def create(self, **kwargs):
        return await self.owner._create(**kwargs)

    @property
    def sdk_configuration(self):
        return self.owner._inner.aio.interactions.sdk_configuration


@dataclass
class _Aio:
    owner: BudgetedGeminiClient

    @property
    def interactions(self):
        return _Interactions(self.owner)

    async def aclose(self):
        close = getattr(self.owner._inner.aio, "aclose", None)
        if callable(close):
            await close()


class BudgetedGeminiClient:
    """A google-genai client whose every interactions.create is reserved in
    the shared ledger first, then settled from the reported usage."""

    def __init__(
        self, inner, ledger: PaidBudgetLedger, *, lab: str, classify, allowance=None
    ):
        self._inner = inner
        self._ledger = ledger
        self._lab = lab
        self._classify = classify
        self._allowance = allowance
        self.aio = _Aio(self)

    async def _create(self, **kwargs):
        from jarvis.hands.provider_adapters import _gemini_usage

        sent = json.dumps(
            [
                kwargs.get("system_instruction"),
                kwargs.get("input"),
                kwargs.get("response_format"),
            ],
            ensure_ascii=False,
            default=str,
        ).encode()
        max_output = check_request(kwargs)
        request_id = self._ledger.reserve(
            lab=self._lab,
            call_path=self._classify(kwargs),
            model=str(kwargs.get("model")),
            input_bytes=len(sent),
            max_output_tokens=max_output,
            allowance=self._allowance,
        )
        usage, outcome = None, "unknown"
        try:
            response = await self._inner.aio.interactions.create(**kwargs)
            usage, observed = _gemini_usage(response)
            outcome = "ok" if observed else "usage_missing"
            return response
        except BaseException as exc:
            outcome = f"error:{type(exc).__name__}"
            raise
        finally:
            self._ledger.settle(request_id, usage or None, outcome)


def learning_call_path(kwargs) -> str:
    from jarvis.memory.learning_extractors import EXTRACTION_PROMPT, RESOLUTION_PROMPT

    prompt = kwargs.get("system_instruction")
    if prompt == EXTRACTION_PROMPT:
        return "extraction"
    if prompt == RESOLUTION_PROMPT:
        return "resolution"
    return "learning_other"


def answer_call_path(_kwargs) -> str:
    return "answer"


class PaidLaneDriverClient:
    """Answer-model client for the Paid lab: JARVIS_GEMINI_PAID_API_KEY only,
    SDK retries off, no router and no Free credential (a Free request is
    impossible). The single retry owner for answer calls is TextDriver."""

    lane = "paid"

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


def build_paid_clients(
    model: str, ledger: PaidBudgetLedger, *, lab: str, allowance=None
):
    """(learning adapter, answer client), both on JARVIS_GEMINI_PAID_API_KEY
    only, SDK retries off, each request reserved in ``ledger``. The learning
    adapter is configured exactly as build_learning_adapters configures the
    direct Free adapter, apart from the key; the answer client exactly as
    build_structured_output_client(provider_retries=False), apart from the key.
    """
    from google import genai

    from jarvis.ai_provider import (
        resolve_ai_role_model,
        resolve_credential_api_key,
    )
    from jarvis.hands.provider_adapters import GeminiStructuredOutputClient
    from jarvis.memory.learning_extractors import LearningProviderAdapter
    from jarvis.memory.learning_limits import INFERENCE_TIMEOUT

    learning_model = resolve_ai_role_model(
        "gemini", "memory_candidate_extraction", configured_model=None
    )
    for role, name in (("answer", model), ("learning", learning_model)):
        if name != PRICING["model"]:
            raise PaidRequestRefused(
                f"{role} model {name!r} is not the priced {PRICING['model']!r}"
            )
    key = resolve_credential_api_key("gemini", PAID_CREDENTIAL_REF)
    learning_inner = genai.Client(
        api_key=key,
        http_options={
            "retry_options": {"attempts": 1},
            "timeout": int(INFERENCE_TIMEOUT * 1000),
        },
    )
    learning_inner.aio.interactions.sdk_configuration.retry_config = None
    adapter = LearningProviderAdapter(
        "gemini",
        BudgetedGeminiClient(
            learning_inner,
            ledger,
            lab=lab,
            classify=learning_call_path,
            allowance=allowance,
        ),
        learning_model,
    )
    answer_inner = genai.Client(
        api_key=key, http_options={"retry_options": {"attempts": 0}}
    )
    answer_inner.aio.interactions.sdk_configuration.retry_config = None
    answer = GeminiStructuredOutputClient(
        client=BudgetedGeminiClient(
            answer_inner,
            ledger,
            lab=lab,
            classify=answer_call_path,
            allowance=allowance,
        ),
        model=model,
        max_output_tokens=2048,
    )
    return adapter, answer
