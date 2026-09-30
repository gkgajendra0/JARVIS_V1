"""Owner-machine acceptance probe for ChatGPT-plan primary intelligence."""

from __future__ import annotations

import json
import sys

from jarvis.ai_provider import configured_ai_provider
from jarvis.chatgpt_plan import (
    CHATGPT_PLAN_TARGET_ID,
    ChatGPTPlanSessionManager,
)
from jarvis.machine_config import load_machine_settings
from jarvis.model_routing.invoker import build_default_model_adapter_registry
from jarvis.model_routing.router import build_default_work_targets


def main() -> int:
    settings = load_machine_settings()
    enabled = settings.get("JARVIS_CHATGPT_PLAN_ENABLED", "false").strip().casefold()
    model = settings.get("JARVIS_CHATGPT_PLAN_MODEL", "").strip()
    if enabled != "true" or not model:
        print(
            "FAIL: run python -m jarvis.chatgpt_plan_cli signin first.",
            file=sys.stderr,
        )
        return 2

    manager = ChatGPTPlanSessionManager()
    if not manager.is_connected():
        print("FAIL: ChatGPT-plan credentials are not connected.", file=sys.stderr)
        return 2

    models = manager.list_models()
    visible = {item.slug for item in models}
    if model not in visible:
        print(
            f"FAIL: configured model is no longer visible: {model}",
            file=sys.stderr,
        )
        return 2

    response = manager.invoke_structured(
        model=model,
        instructions=(
            "JARVIS owner acceptance. Return the requested JSON with ok=true, "
            "route='chatgpt_plan', and a concise confirmation."
        ),
        input_payload={"probe": "owner_acceptance"},
        schema_name="ChatGPTPlanOwnerAcceptance",
        schema={
            "type": "object",
            "properties": {
                "ok": {"type": "boolean"},
                "route": {"type": "string"},
                "message": {"type": "string"},
            },
            "required": ["ok", "route", "message"],
            "additionalProperties": False,
        },
    )
    payload = json.loads(response.output_text)
    if payload.get("ok") is not True or payload.get("route") != "chatgpt_plan":
        print("FAIL: live inference did not return the acceptance contract.", file=sys.stderr)
        return 2

    adapters = build_default_model_adapter_registry(
        chatgpt_plan_session_manager=manager,
    )
    paid_provider = configured_ai_provider(settings)
    targets = build_default_work_targets(
        configured_provider=paid_provider,
        configured_model=settings.get("JARVIS_WORK_ORCHESTRATION_MODEL"),
        adapter_registry=adapters,
        chatgpt_plan_enabled=True,
        chatgpt_plan_model=model,
    )
    target_ids = tuple(item.target_id for item in targets.registry.all())
    expected_paid = f"work.{paid_provider}.default"
    if targets.primary_target_id != CHATGPT_PLAN_TARGET_ID:
        print("FAIL: ChatGPT plan is not the Work primary target.", file=sys.stderr)
        return 2
    if target_ids != (CHATGPT_PLAN_TARGET_ID, expected_paid):
        print(f"FAIL: unexpected Work target pool: {target_ids}", file=sys.stderr)
        return 2
    if any(item.locality.value == "local" for item in targets.registry.all()):
        print("FAIL: a local LLM is still present in the production Work pool.", file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "accepted": True,
                "chatgpt_plan_connected": True,
                "model": model,
                "work_primary": targets.primary_target_id,
                "paid_fallback": expected_paid,
                "local_llm_in_work_pool": False,
                "usage_observed": response.usage_observed,
                "usage": response.usage,
                "next": "restart JARVIS and run live Hands/Work acceptance",
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
