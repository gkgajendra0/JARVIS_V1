from jarvis.model_routing.eligibility import TargetHealthEligibility
from jarvis.model_routing.health import (
    HealthAction,
    TargetHealthRecord,
    apply_provider_failure,
)
from jarvis.provider_resilience import ProviderFailure, ProviderFailureKind


def _failure(kind: ProviderFailureKind) -> ProviderFailure:
    return ProviderFailure(provider="test", kind=kind)


def test_rate_limit_enters_target_specific_cooldown() -> None:
    record = TargetHealthRecord(target_id="target-a")
    mutation = apply_provider_failure(
        record,
        _failure(ProviderFailureKind.RATE_LIMITED),
        now_epoch=100.0,
        base_cooldown_seconds=30.0,
    )

    assert mutation.record.state is TargetHealthEligibility.COOLDOWN
    assert mutation.record.cooldown_until_epoch == 130.0
    assert mutation.record.consecutive_failures == 1
    assert mutation.action is HealthAction.FALLBACK_ALLOWED


def test_transient_failure_is_bounded_before_cooldown() -> None:
    first = apply_provider_failure(
        TargetHealthRecord(target_id="target-a"),
        _failure(ProviderFailureKind.SERVICE_UNAVAILABLE),
        now_epoch=100.0,
    )
    assert first.record.state is TargetHealthEligibility.DEGRADED
    assert first.action is HealthAction.RETRY_SAME_TARGET

    second = apply_provider_failure(
        first.record,
        _failure(ProviderFailureKind.TIMEOUT),
        now_epoch=110.0,
    )
    assert second.record.state is TargetHealthEligibility.COOLDOWN
    assert second.record.cooldown_until_epoch == 140.0
    assert second.action is HealthAction.FALLBACK_ALLOWED


def test_connection_failure_uses_same_bounded_transient_policy() -> None:
    mutation = apply_provider_failure(
        TargetHealthRecord(target_id="target-a"),
        _failure(ProviderFailureKind.CONNECTION_LOST),
        now_epoch=100.0,
    )

    assert mutation.record.state is TargetHealthEligibility.DEGRADED
    assert mutation.action is HealthAction.RETRY_SAME_TARGET


def test_auth_and_model_configuration_failures_mark_target_unavailable() -> None:
    for kind in (
        ProviderFailureKind.AUTHENTICATION_FAILED,
        ProviderFailureKind.PERMISSION_DENIED,
        ProviderFailureKind.MODEL_UNAVAILABLE,
    ):
        mutation = apply_provider_failure(
            TargetHealthRecord(target_id="target-a"),
            _failure(kind),
            now_epoch=100.0,
        )
        assert mutation.record.state is TargetHealthEligibility.UNAVAILABLE
        assert mutation.action is HealthAction.FALLBACK_ALLOWED


def test_request_rejection_cannot_trigger_cross_provider_fallback() -> None:
    mutation = apply_provider_failure(
        TargetHealthRecord(target_id="target-a"),
        _failure(ProviderFailureKind.REQUEST_REJECTED),
        now_epoch=100.0,
    )

    assert mutation.record.state is TargetHealthEligibility.DEGRADED
    assert mutation.action is HealthAction.FAIL_CLOSED_NO_FALLBACK
    assert mutation.reason_code == "request_rejected_no_provider_hop"


def test_unknown_failure_fails_closed_without_provider_hop() -> None:
    mutation = apply_provider_failure(
        TargetHealthRecord(target_id="target-a"),
        _failure(ProviderFailureKind.UNKNOWN),
        now_epoch=100.0,
    )

    assert mutation.action is HealthAction.FAIL_CLOSED_NO_FALLBACK


def test_cooldown_expiry_becomes_effectively_healthy() -> None:
    record = TargetHealthRecord(
        target_id="target-a",
        state=TargetHealthEligibility.COOLDOWN,
        cooldown_until_epoch=130.0,
        consecutive_failures=1,
        last_failure_kind="rate_limited",
        updated_at_epoch=100.0,
        version=2,
    )

    assert record.effective_state(now_epoch=129.9) is TargetHealthEligibility.COOLDOWN
    assert record.effective_state(now_epoch=130.0) is TargetHealthEligibility.HEALTHY

    recovered = record.recovered(now_epoch=131.0)
    assert recovered.state is TargetHealthEligibility.HEALTHY
    assert recovered.cooldown_until_epoch is None
    assert recovered.consecutive_failures == 0
    assert recovered.version == 3


def test_cooldown_backoff_is_capped() -> None:
    record = TargetHealthRecord(
        target_id="target-a",
        state=TargetHealthEligibility.COOLDOWN,
        consecutive_failures=8,
        updated_at_epoch=100.0,
        version=9,
    )
    mutation = apply_provider_failure(
        record,
        _failure(ProviderFailureKind.RATE_LIMITED),
        now_epoch=200.0,
        base_cooldown_seconds=30.0,
        max_cooldown_seconds=300.0,
    )

    assert mutation.record.cooldown_until_epoch == 500.0
