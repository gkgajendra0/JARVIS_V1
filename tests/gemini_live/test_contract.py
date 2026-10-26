from dataclasses import replace
from decimal import Decimal

import pytest

from jarvis.voice.gemini_live_contract import (
    LiveAuxiliaryBounds,
    LiveContractUnavailable,
    normalize_live_usage,
    reviewed_live_contract,
)


def synthetic_contract():
    return reviewed_live_contract(
        "gemini-3.8-live",
        auxiliary_bounds=LiveAuxiliaryBounds(
            model_id="gemini-3.8-live",
            max_listening_tokens=1000,
            max_input_transcript_tokens=2000,
            max_output_transcript_tokens=3000,
            transcript_usage_mode="response_text",
            source="synthetic:test-only-auxiliary-proof",
            version=1,
        ),
    )


@pytest.mark.parametrize(
    "model",
    [
        "gemini-live",
        "gemini-3.8-live-latest",
        "gemini-3.8-live-extended-thinking",
        "other-model",
    ],
)
def test_unknown_alias_or_extended_thinking_denied_before_client(model):
    with pytest.raises(LiveContractUnavailable):
        reviewed_live_contract(model)


def test_model_limit_alone_does_not_qualify_unknown_auxiliary_bound():
    with pytest.raises(LiveContractUnavailable, match="auxiliary"):
        reviewed_live_contract("gemini-3.8-live")
    original = synthetic_contract().auxiliary_bounds
    for field in (
        "max_listening_tokens",
        "max_input_transcript_tokens",
        "max_output_transcript_tokens",
    ):
        with pytest.raises(LiveContractUnavailable):
            reviewed_live_contract(
                "gemini-3.8-live", auxiliary_bounds=replace(original, **{field: None})
            )
    with pytest.raises(LiveContractUnavailable):
        reviewed_live_contract(
            "gemini-3.8-live",
            auxiliary_bounds=replace(original, model_id="other-model"),
        )


def test_full_context_and_transcription_exposure_is_priced(tmp_path):
    from tests.gemini_fallback.helpers import budget_fixture

    _, _, target, price = budget_fixture(tmp_path / "cost.db")
    profile = replace(
        price.profile,
        input_usd_per_million_tokens=None,
        output_usd_per_million_tokens=None,
        usage_rates_usd_per_million=(
            ("input_tokens", 1.0),
            ("input_audio_tokens", 1.0),
            ("output_tokens", 1.0),
            ("output_audio_tokens", 1.0),
        ),
    )
    price = replace(
        price,
        model_id="gemini-3.8-live",
        service_key="live",
        profile=profile,
        inr_per_usd=Decimal(100),
    )
    target = replace(target, model_id="gemini-3.8-live", cost_profile=profile)
    bound = synthetic_contract().exposure("same-canonical-session")
    assert bound.scope_kind == "voice"
    assert dict(bound.usage_bounds) == {
        "input_tokens": 131072,
        "input_audio_tokens": 132072,
        "output_tokens": 70536,
        "output_audio_tokens": 65536,
    }
    assert bound.max_seconds == 60
    assert price.quote(bound.usage_bounds, now_epoch=100, target=target) == 3993


def raw_usage():
    return {
        "prompt_token_count": 20,
        "response_token_count": 30,
        "thoughts_token_count": 4,
        "total_token_count": 54,
        "cached_content_token_count": 0,
        "tool_use_prompt_token_count": 0,
        "prompt_tokens_details": [
            {"modality": "TEXT", "token_count": 8},
            {"modality": "AUDIO", "token_count": 12},
        ],
        "response_tokens_details": [
            {"modality": "TEXT", "token_count": 10},
            {"modality": "AUDIO", "token_count": 20},
        ],
    }


@pytest.mark.parametrize(
    "field",
    [
        "thoughts_token_count",
        "total_token_count",
        "prompt_tokens_details",
        "response_tokens_details",
        "cached_content_token_count",
        "tool_use_prompt_token_count",
    ],
)
def test_partial_or_unpriced_usage_not_zero(field):
    raw = raw_usage()
    raw.pop(field)
    _, complete = normalize_live_usage(raw, contract=synthetic_contract())
    assert complete is False


def test_thought_cache_modal_totals_and_repeated_snapshots():
    raw = raw_usage()
    usage, complete = normalize_live_usage(raw, contract=synthetic_contract())
    assert complete is True
    assert usage == {
        "input_tokens": 8,
        "input_audio_tokens": 12,
        "output_tokens": 14,
        "output_audio_tokens": 20,
    }
    assert normalize_live_usage(raw, contract=synthetic_contract()) == (usage, True)
    raw["cached_content_token_count"] = 5
    cached, complete = normalize_live_usage(raw, contract=synthetic_contract())
    assert (
        complete is True and cached == usage
    )  # cached input conservatively full price
    raw["response_tokens_details"].append({"modality": "VIDEO", "token_count": 1})
    assert normalize_live_usage(raw, contract=synthetic_contract())[1] is False


@pytest.mark.parametrize(
    "change",
    [
        {"total_token_count": 0},
        {"thoughts_token_count": True},
        {"prompt_token_count": -1},
        {"tool_use_prompt_token_count": 3},
    ],
)
def test_inconsistent_or_unpriced_metadata_cannot_settle(change):
    raw = raw_usage()
    raw.update(change)
    assert normalize_live_usage(raw, contract=synthetic_contract())[1] is False


def test_public_sdk_metadata_preserves_explicit_counts():
    from google.genai.types import UsageMetadata

    usage, complete = normalize_live_usage(
        UsageMetadata.model_validate(raw_usage()), contract=synthetic_contract()
    )
    assert complete is True
    assert usage == {
        "input_tokens": 8,
        "input_audio_tokens": 12,
        "output_tokens": 14,
        "output_audio_tokens": 20,
    }


def test_live_exposure_binds_auxiliary_provenance_not_only_equal_token_totals():
    contract = synthetic_contract()
    changed = replace(
        contract, auxiliary_bounds=replace(contract.auxiliary_bounds, version=2)
    )
    assert (
        contract.exposure("session").to_payload()["contract_ref"]
        != changed.exposure("session").to_payload()["contract_ref"]
    )
