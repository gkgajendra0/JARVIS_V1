import pytest

from .helpers import usage
from .test_usage import normalize


def test_rejection_identifies_the_actual_counter_invariant():
    raw = usage()
    raw["response_token_count"] = 99
    report = normalize(raw)
    assert not report.complete
    assert report.unknown_reason == "contradictory_response_total"


def test_diagnostics_preserve_numeric_source_and_missing_values_only():
    from jarvis.voice.gemini_live_usage import usage_diagnostics

    raw = usage()
    del raw["thoughts_token_count"]
    raw["response_tokens_details"] = [{"modality": "AUDIO", "token_count": 7}]
    raw["transcript"] = "must never be retained"
    result = usage_diagnostics(raw, normalize(raw))
    assert result["counts"]["thoughts_token_count"] is None
    assert result["counts"]["cached_content_token_count"] == 3
    assert result["details"]["response_tokens_details"] == [
        {"modality": "AUDIO", "token_count": 7}
    ]
    assert "thoughts_token_count" in result["missing_counts"]
    assert "output_tokens" in result["missing_dimensions"]
    assert "transcript" not in str(result) and "must never" not in str(result)


def test_diagnostics_do_not_copy_malformed_provider_strings():
    from jarvis.voice.gemini_live_usage import usage_diagnostics

    raw = usage()
    raw["thoughts_token_count"] = "secret-looking-value"
    result = usage_diagnostics(raw, normalize(raw))
    assert result["counts"]["thoughts_token_count"] is None
    assert "thoughts_token_count" in result["invalid_counts"]
    assert "secret-looking" not in str(result)


@pytest.mark.asyncio
async def test_rejected_sdk_metadata_is_preserved_without_clearing_hold(op_env):
    from jarvis.voice.gemini_live_budget_session import create_connection_budget

    from .test_admission import admission

    budget = create_connection_budget(
        admission(op_env), connection_id="diagnostic", target=op_env.target
    )
    await budget.reserve_round("r1")
    await budget.before_send("setup", "setup")
    await budget.before_send("initial", "initial")
    raw = usage()
    raw["response_token_count"] = 99
    await budget.observe(
        "bad-usage", raw, sequence=3, turn_complete=True, last_output_sequence=2
    )
    await budget.close(teardown_confirmed=True, complete=False)
    with op_env.store.work_store.extension_transaction() as connection:
        values = [
            op_env.store.work_store.decode_extension_json(row[0])
            for row in connection.execute(
                "SELECT event_json FROM paid_fallback_usage_events"
            )
        ]
    event = next(value for value in values if value.get("kind") == "operational_usage")
    assert event["diagnostics"]["counts"]["response_token_count"] == 99
    assert (
        event["diagnostics"]["normalization_reason"] == "contradictory_response_total"
    )
    assert op_env.governor.status().unknown_reservations == 1
    assert op_env.governor.status().reserved_inr_minor == 1000


def test_legacy_capture_can_export_diagnostics_without_inventing_raw_data(op_env):
    from jarvis.model_routing.live_budget_admin import export_capture_diagnostics

    from .test_governor import checkpoint, finish, observe, reserve

    reservation = reserve(op_env)
    checkpoint(op_env, reservation)
    observe(op_env, reservation, complete=False)
    finish(op_env, reservation, complete=False)
    result = export_capture_diagnostics(
        op_env.runtime, reservation_id=reservation.reservation_id
    )
    assert result["teardown_confirmed"]
    assert not result["raw_numeric_metadata_available"]
    assert result["usage_reports"][0]["complete"] is False
    assert op_env.governor.status().unknown_reservations == 1


def test_capture_returns_the_export_failure_instead_of_silent_null(op_env):
    from types import SimpleNamespace

    from tools.research.gemini_operational_live_qualification import capture_result

    from .test_governor import checkpoint, finish, observe, reserve

    reservation = reserve(op_env)
    checkpoint(op_env, reservation)
    observe(op_env, reservation, complete=False)
    finish(op_env, reservation, complete=False)
    op_env.runtime.live_diagnostics = SimpleNamespace(
        reservation_id=reservation.reservation_id
    )
    result = capture_result(op_env.runtime, SimpleNamespace(fingerprint="a" * 64))
    assert result["evidence"] is None
    assert result["evidence_error"] == "Every billed round needs terminal evidence"
    assert result["diagnostics"]["teardown_confirmed"]
    assert result["known_and_held"]["unknown_reservations"] == 1


def test_numeric_diagnostics_are_bounded_and_refuse_extra_fields():
    from jarvis.model_routing.live_usage_evidence import validate_usage_diagnostics
    from jarvis.voice.gemini_live_usage import usage_diagnostics

    raw = usage()
    raw["response_tokens_details"] *= 1000
    result = usage_diagnostics(raw, normalize(raw))
    assert len(result["details"]["response_tokens_details"]) == 16
    assert "truncated_response_tokens_details" in result["issues"]
    result["prompt"] = "must not enter the ledger"
    with pytest.raises(ValueError, match="schema"):
        validate_usage_diagnostics(result)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "phase", ["generation", "drain", "finalization", "close", "cancel", "cancel_close"]
)
async def test_rejected_metadata_during_generation_still_exports_diagnostics(
    op_env, monkeypatch, phase, capsys
):
    import asyncio
    from dataclasses import replace
    from types import SimpleNamespace

    from tools.research import gemini_operational_live_qualification as capture_module

    from jarvis.model_routing.live_policy import digest
    from jarvis.voice import (
        gemini_live_diagnostics,
        gemini_operational_budget,
        livekit_session,
    )
    from jarvis.voice.gemini_live_budget_session import create_connection_budget

    from .admin_helpers import broker
    from .test_diagnostics import plan

    free = replace(
        op_env.target,
        target_id="voice.live.gemini.free.gemini-3.8-live",
        credential_ref="GOOGLE_API_KEY",
        cost_profile=None,
    )
    op_env.runtime.targets_for = lambda *args: (free, op_env.target)

    monkeypatch.setattr(
        gemini_operational_budget, "operational_live_policy", lambda: op_env.policy
    )
    monkeypatch.setattr(
        "jarvis.model_routing.live_budget_admin._profile_sources", lambda *args: None
    )
    original_authorize = gemini_live_diagnostics.authorize_live_experiment

    def authorize(*args, **kwargs):
        auth = original_authorize(*args, **kwargs)
        op_env.runtime.validate_live_experiment = (
            op_env.runtime.live_diagnostics.validate
        )
        return auth

    monkeypatch.setattr(gemini_live_diagnostics, "authorize_live_experiment", authorize)

    class Model:
        def __init__(self, admission):
            self.lease = create_connection_budget(
                admission, connection_id="capture-failure", target=op_env.target
            )
            self.inner = self

        def session(self, **kwargs):
            return self

        async def update_instructions(self, *args):
            pass

        async def update_tools(self, *args):
            pass

        async def update_chat_ctx(self, *args):
            pass

        async def generate_reply(self):
            await self.lease.reserve_round("r1")
            await self.lease.before_send("setup", "setup")
            await self.lease.before_send("initial", "initial")
            raw = usage()
            raw["response_token_count"] = 99
            await self.lease.observe(
                "reject", raw, sequence=3, turn_complete=True, last_output_sequence=2
            )
            if phase == "generation":
                raise RuntimeError("provider-text-secret-must-not-be-exported")
            if phase == "cancel":
                raise asyncio.CancelledError()

            async def empty():
                for value in ():
                    yield value

            async def bad_text():
                raise TimeoutError("provider-text-secret-must-not-be-exported")
                yield "unreachable"

            async def messages():
                if phase == "drain":
                    yield SimpleNamespace(text_stream=bad_text(), audio_stream=empty())

            return SimpleNamespace(message_stream=messages(), function_stream=empty())

        async def wait_for_finalization(self):
            if phase == "finalization":
                raise TimeoutError("provider-text-secret-must-not-be-exported")

        async def aclose(self):
            if phase == "cancel_close":
                raise asyncio.CancelledError()
            await self.lease.close(teardown_confirmed=phase != "close", complete=False)
            if phase == "close":
                raise TimeoutError("provider-text-secret-must-not-be-exported")

    monkeypatch.setattr(
        livekit_session,
        "_create_realtime_model",
        lambda *args, **kwargs: Model(kwargs["transport_state"].controlled_admission),
    )
    b, _ = broker()
    p = plan(op_env, fixture_ref=digest(capture_module.FIXTURE))
    if phase in {"cancel", "cancel_close"}:
        with pytest.raises(asyncio.CancelledError):
            await capture_module.capture(op_env.runtime, p, op_env.profile, broker=b)
        import json

        result = json.loads(capsys.readouterr().err)
    else:
        result = await capture_module.capture(
            op_env.runtime, p, op_env.profile, broker=b
        )
    assert result["status"] == "capture_failed"
    expected = {
        "generation": "RuntimeError",
        "drain": "TimeoutError",
        "finalization": "TimeoutError",
        "close": None,
        "cancel": "CancelledError",
        "cancel_close": None,
    }
    assert result["capture_error"] == expected[phase]
    assert result["teardown_error"] == (
        {"close": "TimeoutError", "cancel_close": "CancelledError"}.get(phase)
    )
    assert result["diagnostics"]["teardown_confirmed"] == (
        phase not in {"close", "cancel_close"}
    )
    assert (
        result["diagnostics"]["numeric_metadata"][0]["counts"]["response_token_count"]
        == 99
    )
    assert result["evidence"] is None
    assert "provider-text-secret" not in str(result)
    assert op_env.governor.status().unknown_reservations == 1


def test_failed_capture_cli_returns_nonzero_without_exporting_evidence(
    op_env, monkeypatch, tmp_path, capsys
):
    import json

    from tools.research import gemini_operational_live_qualification as module

    from .test_diagnostics import plan

    plan_path, profile_path = tmp_path / "plan.json", tmp_path / "profile.json"
    plan_path.write_text(json.dumps(plan(op_env).to_payload()), encoding="utf-8")
    profile_path.write_text(json.dumps(op_env.profile.to_payload()), encoding="utf-8")

    async def failed_capture(*args, **kwargs):
        return {
            "status": "capture_failed",
            "evidence": None,
            "capture_error": "TimeoutError",
        }

    monkeypatch.setattr(module, "capture", failed_capture)
    code = module.main(
        [
            "--execute",
            "--plan-file",
            str(plan_path),
            "--profile-file",
            str(profile_path),
        ],
        dependencies=(op_env.runtime, None),
    )
    assert code == 1
    assert json.loads(capsys.readouterr().out)["status"] == "capture_failed"
