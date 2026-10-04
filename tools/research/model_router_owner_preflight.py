"""Owner-machine preflight for JARVIS model-tier routing.

This probe performs no model inference. It reads the connected ChatGPT-plan model
catalog, builds the same Work target pool used by production, and exercises the
deterministic EngineeringStageStrategy for routine, capable, and frontier cases.
"""

from __future__ import annotations

import json
from jarvis.chatgpt_plan import ChatGPTPlanSessionManager
from jarvis.config import JarvisConfig
from jarvis.model_routing.invoker import build_default_model_adapter_registry
from jarvis.model_routing.models import (
    EvidenceSizeClass,
    LocalityRequirement,
    PrivacyClass,
    RoutingRequest,
)
from jarvis.model_routing.router import build_default_work_targets
from jarvis.model_routing.strategy import EngineeringStageStrategy


def _request(
    *,
    request_id: str,
    quality_failures: int,
    evidence_size: EvidenceSizeClass = EvidenceSizeClass.SMALL,
) -> RoutingRequest:
    failures = ("quality_failure",) if quality_failures else ()
    return RoutingRequest(
        routing_request_id=request_id,
        work_id=f"preflight-{request_id}",
        task_kind="research",
        strategy_key="engineering_stage",
        strategy_version=2,
        required_capabilities=("engineering_reasoning", "structured_output"),
        privacy_class=PrivacyClass.STANDARD,
        locality_requirement=LocalityRequirement.ANY,
        estimated_context_tokens=2_000,
        evidence_size_class=evidence_size,
        recent_progress_signals=(),
        recent_failure_signals=failures,
        latency_preference="balanced",
        cost_preference="balanced",
        routing_features={"quality_failure_count": quality_failures},
    )


def _selection(strategy, targets, request: RoutingRequest) -> dict[str, object]:
    try:
        ranked = strategy.rank(
            request=request,
            eligible_targets=targets,
            history=None,
        )
    except Exception as exc:  # noqa: BLE001 - probe reports fail-closed outcome
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    by_id = {target.target_id: target for target in targets}
    selected = by_id[ranked.ordered_target_ids[0]]
    return {
        "ok": True,
        "selected_role": ranked.selected_role,
        "selected_target_id": selected.target_id,
        "selected_model": selected.model_id,
        "ordered_targets": list(ranked.ordered_target_ids),
        "reason_codes": list(ranked.reason_codes),
    }


def main() -> int:
    config = JarvisConfig.from_environment()
    plan = ChatGPTPlanSessionManager()
    connected = plan.is_connected()
    catalog: tuple[str, ...] = ()
    catalog_error: str | None = None
    if connected:
        try:
            catalog = tuple(model.slug for model in plan.list_models())
        except Exception as exc:  # noqa: BLE001 - probe reports provider readiness
            catalog_error = f"{type(exc).__name__}: {exc}"

    adapters = build_default_model_adapter_registry(
        chatgpt_plan_session_manager=plan if connected else None,
    )
    targets = build_default_work_targets(
        configured_provider=config.ai_provider,
        configured_model=config.work_orchestration_model,
        adapter_registry=adapters,
        chatgpt_plan_enabled=config.chatgpt_plan_enabled,
        chatgpt_plan_model=config.chatgpt_plan_model,
        chatgpt_plan_available_models=catalog,
        paid_fallback_enabled=config.work_paid_fallback_enabled,
    )
    target_values = targets.registry.all()
    strategy = EngineeringStageStrategy()

    development_override = str(config.development_engine_model or "").strip()
    capable_plan_targets = tuple(
        target
        for target in targets.registry.for_role("capable")
        if target.provider_id == "chatgpt_plan"
    )
    if development_override:
        effective_development_model = development_override
        development_model_source = "explicit_override"
    elif capable_plan_targets:
        effective_development_model = capable_plan_targets[0].model_id
        development_model_source = "capable_tier"
    else:
        primary = targets.registry.require(targets.primary_target_id)
        effective_development_model = primary.model_id
        development_model_source = "primary_fallback"

    report = {
        "schema": "jarvis.model_router_owner_preflight.v1",
        "chatgpt_plan_enabled": config.chatgpt_plan_enabled,
        "chatgpt_plan_connected": connected,
        "catalog_error": catalog_error,
        "catalog_models": list(catalog),
        "registered_targets": [
            {
                "target_id": target.target_id,
                "provider_id": target.provider_id,
                "model_id": target.model_id,
                "roles": list(target.roles),
            }
            for target in target_values
        ],
        "primary_target_id": targets.primary_target_id,
        "development_engine": {
            "configured_override": development_override or None,
            "effective_model": effective_development_model,
            "selection_source": development_model_source,
            "warning": (
                "DevelopmentEngine is explicitly pinned to Astra; clear "
                "JARVIS_DEVELOPMENT_ENGINE_MODEL to use automatic capable-tier routing."
                if development_override.casefold().endswith("astra")
                else None
            ),
        },
        "cases": {
            "routine": _selection(
                strategy,
                target_values,
                _request(request_id="routine", quality_failures=0),
            ),
            "capable": _selection(
                strategy,
                target_values,
                _request(request_id="capable", quality_failures=2),
            ),
            "frontier": _selection(
                strategy,
                target_values,
                _request(request_id="frontier", quality_failures=3),
            ),
        },
        "inference_calls": 0,
        "quota_consumed_by_inference": False,
    }
    print(json.dumps(report, indent=2, sort_keys=True))

    cases = report["cases"]
    assert isinstance(cases, dict)
    passed = (
        config.chatgpt_plan_enabled
        and connected
        and catalog_error is None
        and all(
            isinstance(cases[name], dict) and cases[name].get("ok") is True
            for name in ("routine", "capable", "frontier")
        )
    )
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
