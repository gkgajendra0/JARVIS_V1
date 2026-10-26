import pytest

from .helpers import profile, usage


def normalize(raw, **changes):
    from jarvis.voice.gemini_live_usage import normalize_operational_usage

    kwargs = {
        "profile": profile(),
        "round_id": "r1",
        "sequence": 3,
        "after_round_complete": True,
        "last_output_sequence": 2,
    }
    kwargs.update(changes)
    return normalize_operational_usage(raw, **kwargs)


def test_partial_fields_remain_missing():
    raw = usage()
    del raw["thoughts_token_count"]
    report = normalize(raw)
    assert report.complete is False and report.usage["output_tokens"] == 4
    assert report.unknown_reason is None


def test_thought_cache_and_transcription_mapping_is_explicit():
    report = normalize(usage())
    assert report.complete is True
    assert dict(report.usage) == {
        "input_tokens": 5,
        "input_audio_tokens": 10,
        "output_tokens": 6,
        "output_audio_tokens": 7,
    }
    assert report.profile_ref == profile().fingerprint


def test_early_snapshot_is_not_final():
    assert normalize(usage(), after_round_complete=False).complete is False
    assert normalize(usage(), sequence=2, last_output_sequence=3).complete is False


def test_generation_and_cumulative_counts_are_not_interchangeable():
    first = normalize(usage())
    second = normalize(usage(), profile=profile(counter_scope="connection"))
    assert first.profile_ref != second.profile_ref
    assert (
        first.usage == second.usage
    )  # summation belongs to the governor, never this parser


@pytest.mark.parametrize(
    "field,value",
    [
        ("total_token_count", 29),
        ("cached_content_token_count", 16),
        ("tool_use_prompt_token_count", 1),
        ("thoughts_token_count", -1),
        ("response_token_count", True),
    ],
)
def test_contradictory_or_unsupported_billing_stops(field, value):
    raw = usage()
    raw[field] = value
    report = normalize(raw)
    assert report.complete is False and report.unknown_reason is not None


def test_unknown_or_duplicate_modality_is_never_zero():
    for modality in ("VIDEO", "TEXT"):
        raw = usage()
        raw["prompt_tokens_details"].append({"modality": modality, "token_count": 1})
        assert normalize(raw).unknown_reason is not None


def test_documented_omission_rule_is_explicit_and_bound_to_profile():
    raw = usage()
    del raw["cached_content_token_count"]
    assert normalize(raw).complete is False
    p = profile(zero_rules={"cached_content_token_count": "documented_omitted_zero"})
    assert normalize(raw, profile=p).complete is True


def test_post_completion_window_has_its_own_profile():
    p = profile(terminal_mode="post_turn_complete")
    assert normalize(usage(), profile=p).complete is True
    assert normalize(usage(), profile=p, after_round_complete=False).complete is False
