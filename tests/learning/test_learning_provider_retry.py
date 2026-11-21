"""Bounded retries for temporary provider failures in personal learning.

Owner-approved policy (2026-11-21): one attempt plus at most two retries, only
for 503/502/500/lost connection, inside the existing processing budget, with
source validity and the learning grant rechecked before every retry. Never on
429, permission, invalid request, timeout/stall, invalid output or wrong
answers. One retry owner: this runtime for direct calls, the router otherwise.
"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import jarvis.memory.learning_runtime as runtime_module
from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.learning_contracts import AcceptedLearningSource
from jarvis.memory.learning_extractors import (
    LearningProviderAdapter,
    LearningProviderUnavailable,
)
from jarvis.memory.learning_limits import INFERENCE_TIMEOUT, PROCESSING_BUDGET
from jarvis.memory.learning_runtime import PersonalLearningRuntime
from jarvis.provider_resilience import ProviderFailure, ProviderFailureKind
from jarvis.provider_retry import (
    ATTEMPTS_EXHAUSTED,
    DEADLINE_INSUFFICIENT,
    MAX_ATTEMPTS,
    MIN_ATTEMPT_SECONDS,
    NOT_TRANSIENT,
    RETRY,
    decide_retry,
)

K = ProviderFailureKind


def failure(kind, status=None):
    return ProviderFailure(provider="gemini", kind=kind, status_code=status)


def unavailable(kind=K.SERVICE_UNAVAILABLE, status=503, owner="runtime"):
    return LearningProviderUnavailable(failure(kind, status), owner)


# -- policy ------------------------------------------------------------------


def test_policy_retries_only_temporary_provider_failures():
    for kind, status in [
        (K.SERVICE_UNAVAILABLE, 503),
        (K.SERVICE_UNAVAILABLE, 502),
        (K.PROVIDER_SERVER_ERROR, 500),
        (K.CONNECTION_LOST, None),
    ]:
        assert decide_retry(failure(kind, status), attempt=1, remaining=25).retry
    for kind, status in [
        (K.RATE_LIMITED, 429),
        (K.QUOTA_EXHAUSTED, 429),
        (K.AUTHENTICATION_FAILED, 401),
        (K.PERMISSION_DENIED, 403),
        (K.REQUEST_REJECTED, 400),
        (K.MODEL_UNAVAILABLE, 404),
        (K.TIMEOUT, 504),
        (K.TIMEOUT, None),
        (K.RESPONSE_CONTRACT_INVALID, None),
        (K.BALANCE_EXHAUSTED, 402),
        (K.UNKNOWN, None),
    ]:
        decision = decide_retry(failure(kind, status), attempt=1, remaining=25)
        assert (decision.retry, decision.reason) == (False, NOT_TRANSIENT)
    assert decide_retry(None, attempt=1, remaining=25).reason == NOT_TRANSIENT


def test_policy_at_most_two_retries_with_growing_randomized_waits():
    f = failure(K.SERVICE_UNAVAILABLE, 503)
    lows = [decide_retry(f, attempt=a, remaining=25, rng=lambda: 0.0) for a in (1, 2)]
    highs = [
        decide_retry(f, attempt=a, remaining=25, rng=lambda: 0.999) for a in (1, 2)
    ]
    assert [d.delay for d in lows] == [1.5, 3.75]
    assert all(d.reason == RETRY for d in lows + highs)
    assert 2.4 < highs[0].delay <= 2.5 and 6.2 < highs[1].delay <= 6.25
    assert MAX_ATTEMPTS == 3
    final = decide_retry(f, attempt=3, remaining=25)
    assert (final.retry, final.reason) == (False, ATTEMPTS_EXHAUSTED)


def test_policy_requires_wait_plus_useful_attempt_inside_remaining_budget():
    f = failure(K.SERVICE_UNAVAILABLE, 503)
    fits = decide_retry(
        f, attempt=1, remaining=2.0 + MIN_ATTEMPT_SECONDS + 0.01, rng=lambda: 0.5
    )
    assert fits.retry and fits.delay == 2.0
    short = decide_retry(
        f, attempt=1, remaining=2.0 + MIN_ATTEMPT_SECONDS - 0.01, rng=lambda: 0.5
    )
    assert (short.retry, short.reason) == (False, DEADLINE_INSUFFICIENT)


# -- runtime retry owner -----------------------------------------------------


class Clock:
    def __init__(self, now=100.0):
        self.now = now

    def __call__(self):
        return self.now


def make_runtime(clock, *, active=lambda: True):
    authority = SimpleNamespace(
        validate=lambda grant: SimpleNamespace(
            status="active" if active() else "revoked"
        ),
        release_source=lambda *a: None,
    )
    observed, sleeps = [], []

    async def sleep(seconds):
        sleeps.append(seconds)
        clock.now += seconds

    runtime = PersonalLearningRuntime(
        authority,
        SimpleNamespace(bind_learning_invalidator=lambda callback: None),
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
        clock=clock,
        retry_observer=observed.append,
        sleep=sleep,
        rng=lambda: 0.5,
    )
    return runtime, observed, sleeps


def registered(runtime, clock):
    c = ConversationSession()
    c.start()
    t = c.accept_turn(ConversationRole.USER, "I own a City")
    source = AcceptedLearningSource.from_turn("runtime", c, t, now=clock.now)
    grant = object()
    runtime._pending[source.receipt_id] = (source, grant)
    return source, grant


def scripted(clock, *outcomes, cost=1.3):
    calls = []

    async def operation():
        calls.append(clock.now)
        clock.now += cost
        outcome = outcomes[len(calls) - 1]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    return operation, calls


@pytest.mark.asyncio
async def test_503_then_success_completes_and_records_both_attempts():
    clock = Clock()
    runtime, observed, sleeps = make_runtime(clock)
    source, grant = registered(runtime, clock)
    operation, calls = scripted(clock, unavailable(), "batch")
    runtime._stage = "extraction"
    assert await runtime._infer(source, operation, source.receipt_id, grant) == "batch"
    assert len(calls) == 2 and sleeps == [2.0]
    assert observed == [
        {
            "stage": "extraction",
            "attempt": 1,
            "failure_kind": "service_unavailable",
            "status": 503,
            "decision": RETRY,
            "delay_seconds": 2.0,
            "remaining_seconds": round(PROCESSING_BUDGET - 1.3, 3),
        }
    ]


@pytest.mark.asyncio
async def test_repeated_503_stops_after_two_retries():
    clock = Clock()
    runtime, observed, sleeps = make_runtime(clock)
    source, grant = registered(runtime, clock)
    operation, calls = scripted(
        clock, unavailable(), unavailable(), unavailable(), "never"
    )
    with pytest.raises(LearningProviderUnavailable):
        await runtime._infer(source, operation, source.receipt_id, grant)
    assert len(calls) == 3
    assert [o["decision"] for o in observed] == [RETRY, RETRY, ATTEMPTS_EXHAUSTED]
    assert sleeps == [2.0, 5.0]
    # Everything happened inside the original budget.
    assert clock.now - source.created_monotonic < PROCESSING_BUDGET


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        unavailable(K.RATE_LIMITED, 429),
        unavailable(K.QUOTA_EXHAUSTED, 429),
        unavailable(K.PERMISSION_DENIED, 403),
        unavailable(K.AUTHENTICATION_FAILED, 401),
        unavailable(K.REQUEST_REJECTED, 400),
        unavailable(K.TIMEOUT, 504),
    ],
)
async def test_non_transient_provider_failures_are_final(error):
    clock = Clock()
    runtime, observed, sleeps = make_runtime(clock)
    source, grant = registered(runtime, clock)
    operation, calls = scripted(clock, error, "never")
    with pytest.raises(LearningProviderUnavailable):
        await runtime._infer(source, operation, source.receipt_id, grant)
    assert len(calls) == 1 and sleeps == []
    assert [o["decision"] for o in observed] == [NOT_TRANSIENT]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("learning_invalid_schema"),
        RuntimeError("learning_invalid_resolution"),
        RuntimeError("learning_unknown_target"),
        PermissionError("Learning source unavailable"),
    ],
)
async def test_invalid_output_and_permission_failures_are_never_retried(error):
    clock = Clock()
    runtime, observed, sleeps = make_runtime(clock)
    source, grant = registered(runtime, clock)
    operation, calls = scripted(clock, error, "never")
    with pytest.raises(type(error)):
        await runtime._infer(source, operation, source.receipt_id, grant)
    assert len(calls) == 1 and sleeps == [] and observed == []


@pytest.mark.asyncio
async def test_router_owned_failures_are_not_retried_again_here():
    clock = Clock()
    runtime, observed, sleeps = make_runtime(clock)
    source, grant = registered(runtime, clock)
    operation, calls = scripted(clock, unavailable(owner="router"), "never")
    with pytest.raises(LearningProviderUnavailable):
        await runtime._infer(source, operation, source.receipt_id, grant)
    assert len(calls) == 1 and sleeps == []
    assert observed[0]["decision"] == "retry_owned_by_router"


@pytest.mark.asyncio
async def test_revocation_during_the_wait_prevents_the_next_dispatch():
    clock = Clock()
    state = {"active": True}
    runtime, _observed, sleeps = make_runtime(clock, active=lambda: state["active"])
    source, grant = registered(runtime, clock)

    async def operation():
        calls.append(1)
        state["active"] = False  # revoked while the first attempt was failing
        raise unavailable()

    calls = []
    with pytest.raises(PermissionError, match="source no longer current"):
        await runtime._infer(source, operation, source.receipt_id, grant)
    assert calls == [1] and sleeps == [2.0]


@pytest.mark.asyncio
async def test_source_withdrawn_during_the_wait_prevents_the_next_dispatch():
    clock = Clock()
    runtime, _observed, _sleeps = make_runtime(clock)
    source, grant = registered(runtime, clock)

    async def operation():
        calls.append(1)
        runtime._pending.pop(source.receipt_id)  # privacy control / forget
        raise unavailable()

    calls = []
    with pytest.raises(PermissionError):
        await runtime._infer(source, operation, source.receipt_id, grant)
    assert calls == [1]


@pytest.mark.asyncio
async def test_retry_without_registered_source_fails_closed():
    clock = Clock()
    runtime, _observed, _sleeps = make_runtime(clock)
    source, _ = registered(runtime, clock)
    operation, calls = scripted(clock, unavailable(), "never")
    with pytest.raises(PermissionError):
        await runtime._infer(source, operation)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_no_retry_when_the_remaining_budget_cannot_hold_wait_and_attempt():
    clock = Clock()
    runtime, observed, sleeps = make_runtime(clock)
    source, grant = registered(runtime, clock)
    # First attempt starts late and fails slowly: about 7.5 s remain.
    clock.now += 19.0
    operation, calls = scripted(clock, unavailable(), "never", cost=1.5)
    with pytest.raises(LearningProviderUnavailable):
        await runtime._infer(source, operation, source.receipt_id, grant)
    assert len(calls) == 1 and sleeps == []
    assert observed[0]["decision"] == DEADLINE_INSUFFICIENT
    assert observed[0]["remaining_seconds"] == pytest.approx(7.5)


@pytest.mark.asyncio
async def test_each_attempt_timeout_is_limited_by_the_remaining_budget(monkeypatch):
    clock = Clock()
    runtime, _observed, _sleeps = make_runtime(clock)
    source, grant = registered(runtime, clock)
    timeouts = []
    real_wait_for = asyncio.wait_for

    async def wait_for(awaitable, timeout):
        timeouts.append(round(timeout, 3))
        return await real_wait_for(awaitable, timeout)

    monkeypatch.setattr(runtime_module.asyncio, "wait_for", wait_for)
    operation, _calls = scripted(clock, unavailable(), unavailable(), "ok", cost=4.0)
    assert await runtime._infer(source, operation, source.receipt_id, grant) == "ok"
    # Attempt 1: full 25 s; attempt 2 after 4 + 2 s: 22 s left; attempt 3 after
    # a further 4 + 5 s: 13 s left. Never more than the original budget.
    assert timeouts == [
        INFERENCE_TIMEOUT,
        PROCESSING_BUDGET - 6.0,
        PROCESSING_BUDGET - 15.0,
    ]


@pytest.mark.asyncio
async def test_a_stall_is_not_retried_and_stays_a_timeout(monkeypatch):
    monkeypatch.setattr(runtime_module, "INFERENCE_TIMEOUT", 0.05)
    clock = Clock()
    runtime, observed, sleeps = make_runtime(clock)
    source, grant = registered(runtime, clock)
    calls = []

    async def stall():
        calls.append(1)
        await asyncio.sleep(5)

    with pytest.raises(TimeoutError):
        await runtime._infer(source, stall, source.receipt_id, grant)
    assert calls == [1] and sleeps == [] and observed == []


@pytest.mark.asyncio
async def test_exhausted_budget_never_dispatches():
    clock = Clock()
    runtime, _observed, _sleeps = make_runtime(clock)
    source, grant = registered(runtime, clock)
    clock.now += PROCESSING_BUDGET
    operation = AsyncMock()
    with pytest.raises(TimeoutError):
        await runtime._infer(source, operation, source.receipt_id, grant)
    operation.assert_not_awaited()


# -- adapter: classification and single owner --------------------------------


class Http503(Exception):
    status_code = 503


class Http429(Exception):
    status_code = 429


def source(text="I own a City"):
    c = ConversationSession()
    c.start()
    t = c.accept_turn(ConversationRole.USER, text)
    return AcceptedLearningSource.from_turn("runtime", c, t, now=100)


def fake_client(*outcomes):
    call = AsyncMock(side_effect=list(outcomes))
    return SimpleNamespace(
        aio=SimpleNamespace(
            interactions=SimpleNamespace(create=call), aclose=AsyncMock()
        )
    ), call


@pytest.mark.asyncio
async def test_direct_adapter_makes_one_request_and_names_the_runtime_as_owner():
    fake, call = fake_client(Http503("PRIVATE BODY"))
    adapter = LearningProviderAdapter("gemini", fake, "model")
    with pytest.raises(RuntimeError, match="learning_provider_unavailable") as raised:
        await adapter.extract(source())
    assert isinstance(raised.value, LearningProviderUnavailable)
    assert raised.value.retry_owner == "runtime"
    assert raised.value.failure.kind is K.SERVICE_UNAVAILABLE
    assert "PRIVATE" not in str(raised.value)
    assert call.await_count == 1 and adapter.attempts == 1


@pytest.mark.asyncio
async def test_direct_adapter_classifies_429_as_rate_limited():
    fake, _call = fake_client(Http429("x"))
    adapter = LearningProviderAdapter("gemini", fake, "model")
    with pytest.raises(LearningProviderUnavailable) as raised:
        await adapter.extract(source())
    assert raised.value.failure.kind is K.RATE_LIMITED
    assert decide_retry(raised.value.failure, attempt=1, remaining=25).reason == (
        NOT_TRANSIENT
    )


@pytest.mark.asyncio
async def test_runtime_and_adapter_together_retry_extraction_once_then_succeed():
    s = source()
    ok = SimpleNamespace(output_text=json.dumps({"candidates": []}))
    fake, call = fake_client(Http503("x"), ok)
    adapter = LearningProviderAdapter("gemini", fake, "model")
    clock = Clock(100.0)
    runtime, observed, _sleeps = make_runtime(clock)
    runtime._pending[s.receipt_id] = (s, object())
    grant = runtime._pending[s.receipt_id][1]
    batch = await runtime._infer(s, lambda: adapter.extract(s), s.receipt_id, grant)
    assert batch.candidates == [] and call.await_count == 2
    assert adapter.attempts == 2  # every real provider attempt is counted
    assert [o["decision"] for o in observed] == [RETRY]


def test_sdk_retries_stay_disabled_so_only_one_owner_retries(monkeypatch):
    import sys

    from jarvis.memory import learning_extractors

    created = {}

    class Config:
        retry_config = "sdk-default"

    class Client:
        def __init__(self, api_key, http_options):
            created["http_options"] = http_options
            self.aio = SimpleNamespace(
                interactions=SimpleNamespace(sdk_configuration=Config())
            )
            created["client"] = self

    monkeypatch.setitem(sys.modules, "google.genai", SimpleNamespace(Client=Client))
    monkeypatch.setattr(
        learning_extractors, "require_provider_api_key", lambda *a, **k: "key"
    )
    monkeypatch.setattr(
        learning_extractors, "resolve_ai_role_model", lambda *a, **k: "model"
    )
    import google

    monkeypatch.setattr(google, "genai", sys.modules["google.genai"], raising=False)
    extractor, resolver = learning_extractors.build_learning_adapters("gemini")
    assert extractor is resolver
    assert created["client"].aio.interactions.sdk_configuration.retry_config is None
    assert created["http_options"]["retry_options"] == {"attempts": 1}


# -- full turn on a real (fictional) lab database -----------------------------


def _employer(source):
    from jarvis.memory.learning_contracts import EvidenceSpan, LearningCandidate

    return LearningCandidate(
        category="personal_fact",
        intent="new",
        label="Northstar Design Limited",
        value="Northstar Design Limited",
        evidence=[EvidenceSpan(turn_id=source.turn_id, start=0, end=len(source.text))],
    )


async def _run_turn(learning, extract, resolve):
    from jarvis.memory.learning_reconciliation import LearningReconciler

    observed = []

    async def no_wait(seconds):
        observed.append(("wait", seconds))

    r = PersonalLearningRuntime(
        learning.authority,
        learning.service,
        SimpleNamespace(extract=extract),
        SimpleNamespace(resolve=resolve),
        LearningReconciler(learning.service.canonical_reader, learning.authority),
        retry_observer=observed.append,
        sleep=no_wait,
        rng=lambda: 0.5,
    )
    c = ConversationSession()
    c.start()
    try:
        r.bind(c, learning.grant)(
            c.accept_turn(ConversationRole.USER, "I work for Northstar Design Limited.")
        )
        await asyncio.wait_for(r.drain(), 10)
        return r.status(), observed
    finally:
        await r.close()


@pytest.mark.asyncio
async def test_turn_with_extraction_503_then_success_commits_exactly_once(learning):
    from jarvis.memory.learning_contracts import (
        LearningBatch,
        LearningResolution,
        LearningResolutionBatch,
    )

    extracts, resolves = [], []

    async def extract(source):
        extracts.append(1)
        if len(extracts) == 1:
            raise unavailable()
        return LearningBatch(candidates=[_employer(source)])

    async def resolve(source, batch, catalog):
        resolves.append(1)
        return LearningResolutionBatch(
            resolutions=[LearningResolution(candidate_index=0, decision="new")]
        )

    status, observed = await _run_turn(learning, extract, resolve)
    assert (status.reason, status.committed, status.dropped) == ("committed", 1, 0)
    assert await learning.count() == 1
    assert (len(extracts), len(resolves)) == (2, 1)
    assert observed[0]["decision"] == RETRY and observed[1] == ("wait", 2.0)


@pytest.mark.asyncio
async def test_turn_with_resolution_503_retries_only_resolution(learning):
    from jarvis.memory.learning_contracts import (
        LearningBatch,
        LearningResolution,
        LearningResolutionBatch,
    )

    extracts, resolves = [], []

    async def extract(source):
        extracts.append(1)
        return LearningBatch(candidates=[_employer(source)])

    async def resolve(source, batch, catalog):
        resolves.append(1)
        if len(resolves) == 1:
            raise unavailable(K.PROVIDER_SERVER_ERROR, 500)
        return LearningResolutionBatch(
            resolutions=[LearningResolution(candidate_index=0, decision="new")]
        )

    status, observed = await _run_turn(learning, extract, resolve)
    assert (status.reason, status.committed) == ("committed", 1)
    assert await learning.count() == 1
    assert (len(extracts), len(resolves)) == (1, 2)
    assert observed[0]["stage"] == "resolution"


@pytest.mark.asyncio
async def test_turn_with_repeated_503_drops_without_saving(learning):
    extracts = []

    async def extract(source):
        extracts.append(1)
        raise unavailable()

    async def resolve(*args):
        raise AssertionError("not reached")

    status, observed = await _run_turn(learning, extract, resolve)
    assert (status.reason, status.committed, status.dropped) == (
        "processing_denied",
        0,
        1,
    )
    assert await learning.count() == 0 and len(extracts) == 3
    decisions = [o["decision"] for o in observed if isinstance(o, dict)]
    assert decisions == [RETRY, RETRY, ATTEMPTS_EXHAUSTED]
