from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from google.genai.errors import APIError
from tests.gemini_fallback.helpers import make_router

from jarvis.model_routing.eligibility import TargetHealthEligibility
from jarvis.model_routing.gemini import GeminiFallbackConfig, build_gemini_role_targets
from jarvis.provider_resilience import classify_provider_failure


def targets(role="work", model="gemini-test"):
    return build_gemini_role_targets(
        role=role,
        model=model,
        adapter_id="gemini",
        config=GeminiFallbackConfig(enabled=True),
    )


@pytest.mark.parametrize(
    "status,want",
    [
        (400, "request_rejected"),
        (401, "authentication_failed"),
        (402, "balance_exhausted"),
        (403, "permission_denied"),
        (404, "model_unavailable"),
        (429, "quota_exhausted"),
        (503, "service_unavailable"),
    ],
)
def test_http_status_cannot_be_overridden_by_stray_quota_text(status, want):
    failure = classify_provider_failure(
        APIError(
            status,
            {
                "error": {
                    "message": "model quota exceeded",
                    "status": "RESOURCE_EXHAUSTED",
                }
            },
        ),
        provider="gemini",
    )
    assert failure.kind.value == want
    if status == 402:
        assert failure.retryable is False
        assert "balance" in failure.spoken_message.casefold()


@pytest.mark.parametrize("status", [400, 401, 402, 403, 404, 429, 503])
def test_paid_edge_only_free_pressure(status):
    from jarvis.model_routing.gemini import gemini_paid_fallback_allowed

    failure = classify_provider_failure(
        APIError(status, {"error": {"message": "quota exceeded"}}), provider="gemini"
    )
    free, paid = targets()
    assert gemini_paid_fallback_allowed(failure, source_target=free) is (status == 429)
    assert not gemini_paid_fallback_allowed(failure, source_target=paid)
    assert not gemini_paid_fallback_allowed(
        replace(failure, provider="openai"), source_target=free
    )


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError("timed out"),
        RuntimeError("unclassified"),
        RuntimeError("server overloaded"),
    ],
)
def test_timeout_unknown_overload_never_create_new_paid_edge(error):
    from jarvis.model_routing.gemini import gemini_paid_fallback_allowed

    assert not gemini_paid_fallback_allowed(
        classify_provider_failure(error, provider="gemini"), source_target=targets()[0]
    )


def test_live_statusless_quota_preserves_paid_edge():
    from jarvis.model_routing.gemini import gemini_paid_fallback_allowed

    f = classify_provider_failure(
        RuntimeError("Live API resource_exhausted"), provider="gemini"
    )
    assert gemini_paid_fallback_allowed(f, source_target=targets("voice.live")[0])


def test_trusted_google_retry_details_and_ambiguous_text_are_distinct():
    error = APIError(
        429,
        {
            "error": {
                "status": "RESOURCE_EXHAUSTED",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                        "violations": [
                            {
                                "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
                                "quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
                            }
                        ],
                    },
                    {
                        "@type": "type.googleapis.com/google.rpc.RetryInfo",
                        "retryDelay": "35.5s",
                    },
                ],
            }
        },
    )
    failure = classify_provider_failure(error, provider="gemini")
    assert failure.quota_period == "day"
    assert failure.retry_after_seconds == 35.5
    ambiguous = classify_provider_failure(
        RuntimeError("RESOURCE_EXHAUSTED daily quota retry after 1000s"),
        provider="gemini",
    )
    assert ambiguous.quota_period is None
    assert ambiguous.retry_after_seconds is None


@pytest.mark.parametrize("delay", ["nan", "-1", "inf", "secret-canary"])
def test_invalid_retry_header_is_discarded(delay):
    error = APIError(
        429,
        {"error": {"message": "quota exceeded"}},
        response=SimpleNamespace(headers={"Retry-After": delay}),
    )
    assert (
        classify_provider_failure(error, provider="gemini").retry_after_seconds is None
    )


def test_pressure_is_model_local_and_backoff_is_bounded(tmp_path):
    _, store = make_router(tmp_path)
    free, paid = targets()
    failure = classify_provider_failure(
        RuntimeError("resource_exhausted"), provider="gemini"
    )
    for n, until in enumerate([160, 220, 340, 580, 1000, 1000], 1):
        record = store.record_pressure(
            target=free,
            failure=failure,
            config=GeminiFallbackConfig(enabled=True),
            now_epoch=100,
        )
        assert record.cooldown_until_epoch == until
        assert record.consecutive_failures == n
    assert store.get_health(paid.target_id) is None
    assert store.get_health(targets(model="other")[0].target_id) is None


@pytest.mark.parametrize(
    "start,want",
    [
        ("2026-03-08T08:30:00+00:00", "2026-03-09T07:00:00+00:00"),
        ("2026-11-01T07:30:00+00:00", "2026-11-02T08:00:00+00:00"),
    ],
)
def test_verified_daily_reset_observes_pacific_dst(tmp_path, start, want):
    _, store = make_router(tmp_path)
    from jarvis.provider_resilience import ProviderFailure, ProviderFailureKind

    record = store.record_pressure(
        target=targets()[0],
        failure=ProviderFailure(
            "gemini", ProviderFailureKind.QUOTA_EXHAUSTED, quota_period="day"
        ),
        config=GeminiFallbackConfig(enabled=True),
        now_epoch=datetime.fromisoformat(start).timestamp(),
    )
    assert datetime.fromtimestamp(record.cooldown_until_epoch, UTC).isoformat() == want


def test_trusted_retry_after_prevents_premature_recovery(tmp_path):
    _, store = make_router(tmp_path)
    from jarvis.provider_resilience import ProviderFailure, ProviderFailureKind

    record = store.record_pressure(
        target=targets()[0],
        failure=ProviderFailure(
            "gemini", ProviderFailureKind.RATE_LIMITED, retry_after_seconds=1200
        ),
        config=GeminiFallbackConfig(enabled=True),
        now_epoch=100,
    )
    assert record.cooldown_until_epoch == 1300


def test_paid_balance_failure_blocks_only_paid_credential_including_new_targets(
    tmp_path,
):
    router, store = make_router(tmp_path)
    failure = classify_provider_failure(
        APIError(402, {"error": {"message": "balance depleted"}}), provider="gemini"
    )
    free, paid = targets()
    store.disable_paid_credential(failure=failure, now_epoch=100)
    assert store.credential_blocked("JARVIS_GEMINI_PAID_API_KEY")
    assert not store.credential_blocked("GOOGLE_API_KEY")
    assert not store.credential_blocked("JARVIS_TTS_GOOGLE_API_KEY")
    state = router._runtime_state(now_epoch=101)
    assert state.target_health[paid.target_id] is TargetHealthEligibility.UNAVAILABLE
    assert (
        state.target_health.get(free.target_id)
        is not TargetHealthEligibility.UNAVAILABLE
    )
