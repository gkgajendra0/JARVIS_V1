import json
from dataclasses import replace
from decimal import Decimal

import pytest

from .helpers import budget_fixture, exposure


def test_decimal_quote_and_margin_round_up(tmp_path):
    _, _, target, price = budget_fixture(tmp_path / "cost.db")
    assert (
        price.quote(
            {"input_tokens": 5000, "output_tokens": 5000}, now_epoch=100, target=target
        )
        == 20000
    )
    adjusted = replace(price, inr_per_usd=Decimal("99.5"), margin_bps=100)
    assert (
        adjusted.quote(
            {"input_tokens": 1, "output_tokens": 1}, now_epoch=100, target=target
        )
        == 5
    )


@pytest.mark.parametrize(
    "change",
    [
        {"inr_per_usd": Decimal("NaN")},
        {"inr_per_usd": Decimal(-1)},
        {"inr_per_usd": None},
        {"fx_source": ""},
        {"fx_version": ""},
        {"fx_effective_to_epoch": 99},
        {"source": ""},
    ],
)
def test_missing_or_stale_price_fx_never_admits_paid(tmp_path, change):
    from jarvis.model_routing.pricing import PricingUnavailable

    governor, _, target, price = budget_fixture(tmp_path / "cost.db")
    with pytest.raises((ValueError, TypeError, PricingUnavailable)):
        bad = replace(price, **change)
        governor.reserve(
            invocation_id="blocked", target=target, exposure=exposure(), pricing=bad
        )
    assert governor.status().reserved_inr_minor == 0


def test_profile_unknown_rate_or_wrong_model_rejected(tmp_path):
    from jarvis.model_routing.pricing import PricingUnavailable

    governor, _, target, price = budget_fixture(tmp_path / "cost.db")
    for bad in (
        replace(
            price, profile=replace(price.profile, input_usd_per_million_tokens=None)
        ),
        replace(price, model_id="wrong-model"),
    ):
        with pytest.raises(PricingUnavailable):
            governor.reserve(
                invocation_id="blocked", target=target, exposure=exposure(), pricing=bad
            )
    with pytest.raises(PricingUnavailable):
        price.quote(
            {"input_audio_tokens": 20, "output_audio_tokens": 20},
            now_epoch=100,
            target=target,
        )


def test_versioned_pricing_file_roundtrip_and_reject_unknown_schema(tmp_path):
    from jarvis.model_routing.pricing import PricingUnavailable, load_pricing_snapshot

    _, _, target, price = budget_fixture(tmp_path / "cost.db")
    path = tmp_path / "price.json"
    payload = price.to_payload()
    path.write_text(json.dumps(payload), encoding="utf-8")
    loaded = load_pricing_snapshot(path, now_epoch=100)
    assert (
        loaded.quote(
            {"input_tokens": 5000, "output_tokens": 5000}, now_epoch=100, target=target
        )
        == 20000
    )
    payload["schema_version"] = 999
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PricingUnavailable):
        load_pricing_snapshot(path, now_epoch=100)


def test_modality_cost_profile_prices_known_usage_only():
    from jarvis.model_routing.cost import estimate_profile_usage_cost_usd
    from jarvis.model_routing.models import CostProfile

    profile = CostProfile(
        profile_id="synthetic-audio",
        version=1,
        effective_from_epoch=0,
        usage_rates_usd_per_million=(
            ("input_audio_tokens", 2.0),
            ("output_audio_tokens", 8.0),
        ),
    )
    assert (
        estimate_profile_usage_cost_usd(
            profile, {"input_audio_tokens": 1000000, "output_audio_tokens": 500000}
        )
        == 6.0
    )
    assert estimate_profile_usage_cost_usd(profile, {"input_audio_tokens": 100}) is None
