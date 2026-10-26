from tests.gemini_fallback.test_hands_memory import shared

from jarvis.config import JarvisConfig
from jarvis.model_routing.gemini import GeminiFallbackConfig


def test_effective_status_reports_slots_price_budget_and_live_blocker_without_keys(
    tmp_path, monkeypatch
):
    from jarvis.model_routing.status import gemini_fallback_status

    runtime, _ = shared(tmp_path, monkeypatch, {})
    status = gemini_fallback_status(runtime)
    assert status["mode"] == "free_first_paid_fallback"
    assert status["free_credential_available"] and status["paid_credential_available"]
    assert status["ceiling_inr_minor"] == 35000
    assert status["spent_inr_minor"] == status["reserved_inr_minor"] == 0
    assert status["unknown_reservations"] == 0
    assert status["live_paid_available"] is False
    assert status["live_paid_reason"] == "live_transport_bound_unavailable"
    assert status["pricing_error"] is None
    assert status["target_health"]
    assert "private-canary" not in str(status)


def test_preflight_fallback_unavailable_does_not_disable_free_or_probe_paid(
    tmp_path, monkeypatch
):
    from jarvis.preflight import _gemini_fallback_check

    monkeypatch.delenv("JARVIS_GEMINI_PAID_API_KEY", raising=False)
    check = _gemini_fallback_check(
        JarvisConfig(
            ai_provider="gemini",
            gemini_fallback=GeminiFallbackConfig(
                enabled=True, pricing_path=tmp_path / "missing.json"
            ),
        )
    )
    assert check.ok
    assert "paid_credential_available=False" in check.detail
    assert "reviewed_pricing_unavailable" in check.detail
    assert "35000" in check.detail
    assert "live_transport_bound_unavailable" in check.detail


def test_status_missing_prices_and_paid_balance_block_are_explicit(
    tmp_path, monkeypatch
):
    from google.genai.errors import APIError

    from jarvis.model_routing.status import gemini_fallback_status
    from jarvis.provider_resilience import classify_provider_failure

    runtime, _ = shared(tmp_path, monkeypatch, {})
    runtime.store.disable_paid_credential(
        failure=classify_provider_failure(APIError(402, {}), provider="gemini"),
        now_epoch=100,
    )
    status = gemini_fallback_status(runtime)
    assert status["paid_credential_blocked"] is True
    assert status["free_credential_available"] is True


def test_status_includes_scoped_health_and_versioned_price_metadata(
    tmp_path, monkeypatch
):
    from google.genai.errors import APIError

    from jarvis.model_routing.status import gemini_fallback_status
    from jarvis.provider_resilience import classify_provider_failure

    runtime, _ = shared(tmp_path, monkeypatch, {})
    free = runtime.targets_for("memory.extraction", "gemini-budget-test")[0]
    runtime.store.record_pressure(
        target=free,
        failure=classify_provider_failure(APIError(429, {}), provider="gemini"),
        config=runtime.config,
        now_epoch=100,
    )
    status = gemini_fallback_status(runtime)
    assert status["target_health"][free.target_id]["cooldown_until_epoch"] == 160
    metadata = status["price_versions"][0]
    assert metadata["model_id"] == "gemini-budget-test"
    assert metadata["price_version"] == 1 and metadata["fx_version"]
