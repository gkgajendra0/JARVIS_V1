"""Plan-only by default. A real capture needs an exact, fresh financial approval."""

import argparse
import asyncio
import json
from pathlib import Path

from jarvis.model_routing.budget import PaidBudgetDenied
from jarvis.model_routing.live_policy import LiveUsageProfile, digest
from jarvis.voice.gemini_live_diagnostics import load_live_diagnostic_plan

FIXTURE = "Fictional fact: the imaginary object's colour is blue. Say blue once."


def build_parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--execute", action="store_true")
    p.add_argument("--plan-file", type=Path)
    p.add_argument("--profile-file", type=Path)
    p.add_argument("--output", type=Path)
    return p


async def capture(runtime, plan, profile, *, broker):
    from jarvis.config import JarvisConfig
    from jarvis.model_routing.live_budget_admin import _profile_sources
    from jarvis.provider_resilience import ProviderFailure, ProviderFailureKind
    from jarvis.voice.gemini_live_diagnostics import authorize_live_experiment
    from jarvis.voice.gemini_operational_budget import (
        OperationalLiveAdmission,
        operational_live_policy,
    )
    from jarvis.voice.gemini_transport import GeminiTransportState
    from jarvis.voice.livekit_session import _create_realtime_model

    policy = operational_live_policy()
    if (
        plan.scope != "qualification_capture"
        or plan.fixture_ref != digest(FIXTURE)
        or plan.policy_ref != policy.fingerprint
        or plan.profile_ref != profile.fingerprint
    ):
        raise PaidBudgetDenied(
            "Exact fictional capture policy/profile/fixture required"
        )
    free, target = runtime.targets_for("voice.live", policy.model_id)
    price = runtime.pricing_for(target)
    if (
        target.target_id != plan.target_id
        or price is None
        or digest(price.to_payload()) != plan.price_ref
    ):
        raise PaidBudgetDenied("Exact current capture target/price required")
    price.validate_at(float(runtime.clock()))
    _profile_sources(profile, price)
    auth = authorize_live_experiment(
        runtime, plan, broker=broker, session_id="live-qualification-" + plan.nonce
    )
    # Explicit injected quota under the approved experiment; never exhaust real Free quota.
    runtime.store.record_pressure(
        target=free,
        failure=ProviderFailure("gemini", ProviderFailureKind.QUOTA_EXHAUSTED),
        config=runtime.config,
        now_epoch=float(runtime.clock()),
    )
    admission = OperationalLiveAdmission(
        runtime,
        session_id=auth.session_id,
        authorize=lambda: runtime.validate_live_experiment(auth),
        policy=policy,
        profile=profile,
        capture_only=True,
        experiment_authorization=auth,
    )
    state = GeminiTransportState(
        epoch=0,
        current_epoch=lambda: 0,
        authorize=lambda: runtime.validate_live_experiment(auth),
        controlled_admission=admission,
    )
    model = _create_realtime_model(
        JarvisConfig(ai_provider="gemini", gemini_realtime_model=policy.model_id),
        target=target,
        transport_state=state,
    )
    capture_error = teardown_error = None
    cancelled = None
    try:
        session = model.session(turn_detection_disabled=True)
        await session.update_instructions(FIXTURE)
        await session.update_tools([])
        from livekit.agents import llm

        context = llm.ChatContext.empty()
        context.add_message(role="user", content=FIXTURE)
        await session.update_chat_ctx(context)
        response = await asyncio.wait_for(session.generate_reply(), timeout=12)

        # Drain audio in memory, never play or persist raw output/transcripts.
        async def drain():
            async for message in response.message_stream:
                async for _ in message.text_stream:
                    pass
                async for _ in message.audio_stream:
                    pass
            async for _ in response.function_stream:
                raise PaidBudgetDenied("Qualification has no action tools")

        await asyncio.wait_for(drain(), timeout=12)
        # Stream completion precedes terminal accounting for supported profiles.
        # The transport's original 15s watchdog still bounds physical lifetime.
        await asyncio.wait_for(session.inner.wait_for_finalization(), timeout=3)
    except asyncio.CancelledError as exc:
        capture_error, cancelled = "CancelledError", exc
    except Exception as exc:  # noqa: BLE001 - preserve fixed diagnostics after teardown
        capture_error = _failure_code(exc)
    finally:
        try:
            await asyncio.wait_for(model.aclose(), timeout=3)
        except asyncio.CancelledError as exc:
            teardown_error, cancelled = "CancelledError", exc
        except Exception as exc:  # noqa: BLE001 - never infer successful teardown
            teardown_error = _failure_code(exc)
    result = capture_result(
        runtime, plan, capture_error=capture_error, teardown_error=teardown_error
    )
    if cancelled is not None:
        # Preserve cancellation while leaving an actionable, numeric-only record.
        import sys

        print(json.dumps(result, sort_keys=True), file=sys.stderr)
        raise cancelled
    return result


def _failure_code(exc):
    name = type(exc).__name__
    allowed = {
        "TimeoutError",
        "RuntimeError",
        "ValueError",
        "OSError",
        "APIConnectionError",
        "APIStatusError",
        "RealtimeError",
        "PaidBudgetDenied",
        "PaidOutcomeUnknown",
        "ConnectionClosedError",
    }
    return name if name in allowed else "provider_or_capture_error"


def capture_result(runtime, plan, *, capture_error=None, teardown_error=None):
    """Return actionable rejection evidence after teardown, without inference."""
    from jarvis.model_routing.live_budget_admin import (
        export_capture_diagnostics,
        export_reconciliation_evidence,
    )

    evidence_error = None
    reservation_id = getattr(runtime.live_diagnostics, "reservation_id", None)
    diagnostics = {
        "reservation_id": reservation_id,
        "state": "unavailable",
        "raw_numeric_metadata_available": False,
    }
    try:
        if reservation_id is None:
            raise PaidBudgetDenied("No bound capture reservation is available")
        evidence = export_reconciliation_evidence(
            runtime, reservation_id=reservation_id
        ).to_payload()
    except (PaidBudgetDenied, ValueError) as exc:
        evidence = None  # unknown is retained; no fabricated reconciliation file
        evidence_error = str(exc)[:256]
    if reservation_id is not None:
        diagnostics = export_capture_diagnostics(runtime, reservation_id=reservation_id)
    return {
        "status": "capture_failed"
        if capture_error or teardown_error
        else "capture_requires_reconciliation",
        "capture_error": capture_error,
        "teardown_error": teardown_error,
        "plan_ref": plan.fingerprint,
        "evidence": evidence,
        "evidence_error": evidence_error,
        "diagnostics": diagnostics,
        "known_and_held": __import__("dataclasses").asdict(
            runtime.paid_budget.status()
        ),
    }


def main(argv=None, *, dependencies=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.execute:
        print(
            json.dumps(
                {
                    "status": "plan-only",
                    "max_connections": 1,
                    "max_generations": 1,
                    "max_seconds": 15,
                    "allowance_minor": 1000,
                    "soft_stop_minor": 800,
                    "fixture_ref": digest(FIXTURE),
                    "requires": "reviewed price/FX, candidate reporting profile, exact financial approval",
                }
            )
        )
        return 0
    if args.plan_file is None or args.profile_file is None:
        parser.error("--execute requires --plan-file and --profile-file")
    plan = load_live_diagnostic_plan(args.plan_file)
    profile = LiveUsageProfile.from_payload(
        json.loads(args.profile_file.read_text(encoding="utf-8"))
    )
    owned = dependencies is None
    if owned:
        from jarvis.capabilities.authority_bridge import CapabilityAuthorityBroker
        from jarvis.config import JarvisConfig
        from jarvis.model_routing.runtime import build_production_routing_runtime

        runtime = build_production_routing_runtime(JarvisConfig.from_environment())
        if runtime is None:
            raise PaidBudgetDenied("Explicit configured Paid fallback runtime required")
        dependencies = (runtime, CapabilityAuthorityBroker())
    runtime, broker = dependencies
    try:
        result = asyncio.run(capture(runtime, plan, profile, broker=broker))
        text = json.dumps(result, sort_keys=True)
        if args.output and result["evidence"] is not None:
            args.output.write_text(
                json.dumps(result["evidence"], sort_keys=True) + "\n", encoding="utf-8"
            )
        print(text)
        return 1 if result["status"] == "capture_failed" else 0
    finally:
        if owned:
            broker.close()
            asyncio.run(runtime.aclose())


if __name__ == "__main__":
    raise SystemExit(main())
