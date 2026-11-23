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

PAID_CREDENTIAL_REF = "JARVIS_GEMINI_PAID_API_KEY"
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
# instruction, input and response schema): a token is never shorter than one
# byte. Output is bounded by the request's own max_output_tokens plus a
# thinking allowance, because the provider documentation does not state
# whether max_output_tokens also bounds thinking tokens.
INPUT_OVERHEAD_TOKENS = 256
THINKING_ALLOWANCE_TOKENS = 8192


class PaidBudgetExhausted(RuntimeError):
    """The next Paid request cannot fit in the remaining budget; nothing sent."""


class PaidBudgetHalted(RuntimeError):
    """The ledger is halted (a cost exceeded its reservation); nothing sent."""


def _micro(tokens: int, usd_per_million: float) -> int:
    """tokens x (USD per million tokens) is micro-USD; rounded up."""
    return math.ceil(tokens * usd_per_million)


def worst_case(input_bytes: int, max_output_tokens: int) -> tuple[int, int, int]:
    input_bound = input_bytes + INPUT_OVERHEAD_TOKENS
    output_bound = max_output_tokens + THINKING_ALLOWANCE_TOKENS
    cost = _micro(input_bound, PRICING["input_usd_per_million"]) + _micro(
        output_bound, PRICING["output_usd_per_million"]
    )
    return input_bound, output_bound, cost


def usage_cost(usage: dict[str, int] | None) -> int | None:
    """Cost of provider-reported usage, or None when it is unknown."""
    if not usage or type(usage.get("input_tokens")) is not int:
        return None
    inp = usage["input_tokens"]
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
            """
        )
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

    def reserve(
        self,
        *,
        lab: str,
        call_path: str,
        model: str,
        input_bytes: int,
        max_output_tokens: int,
    ) -> str:
        input_bound, output_bound, cost = worst_case(input_bytes, max_output_tokens)
        self._db.execute("BEGIN IMMEDIATE")
        try:
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
                " status, input_bound, output_bound, reserved_micro_usd, reserved_at)"
                " VALUES (?, ?, ?, ?, ?, 'reserved', ?, ?, ?, ?)",
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
        return {
            "budget_id": BUDGET_ID,
            "ledger": str(self.path),
            "ceiling_usd": CEILING_MICRO_USD / 1e6,
            "committed_usd": committed / 1e6,
            "remaining_usd": (CEILING_MICRO_USD - committed) / 1e6,
            "halted_reason": halted,
            "pricing": PRICING,
            "thinking_allowance_tokens": THINKING_ALLOWANCE_TOKENS,
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

    def __init__(self, inner, ledger: PaidBudgetLedger, *, lab: str, classify):
        self._inner = inner
        self._ledger = ledger
        self._lab = lab
        self._classify = classify
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
        max_output = (kwargs.get("generation_config") or {}).get("max_output_tokens")
        if type(max_output) is not int or max_output <= 0:
            raise PaidBudgetExhausted("paid request without an output bound refused")
        request_id = self._ledger.reserve(
            lab=self._lab,
            call_path=self._classify(kwargs),
            model=str(kwargs.get("model")),
            input_bytes=len(sent),
            max_output_tokens=max_output,
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


def build_paid_clients(model: str, ledger: PaidBudgetLedger, *, lab: str):
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

    key = resolve_credential_api_key("gemini", PAID_CREDENTIAL_REF)
    learning_inner = genai.Client(
        api_key=key,
        http_options={
            "retry_options": {"attempts": 1},
            "timeout": int(INFERENCE_TIMEOUT * 1000),
        },
    )
    learning_inner.aio.interactions.sdk_configuration.retry_config = None
    learning_model = resolve_ai_role_model(
        "gemini", "memory_candidate_extraction", configured_model=None
    )
    adapter = LearningProviderAdapter(
        "gemini",
        BudgetedGeminiClient(
            learning_inner, ledger, lab=lab, classify=learning_call_path
        ),
        learning_model,
    )
    answer_inner = genai.Client(
        api_key=key, http_options={"retry_options": {"attempts": 0}}
    )
    answer_inner.aio.interactions.sdk_configuration.retry_config = None
    answer = GeminiStructuredOutputClient(
        client=BudgetedGeminiClient(
            answer_inner, ledger, lab=lab, classify=answer_call_path
        ),
        model=model,
        max_output_tokens=2048,
    )
    return adapter, answer
