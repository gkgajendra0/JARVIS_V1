"""Owner-facing setup and acceptance CLI for ChatGPT-plan intelligence."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from jarvis.chatgpt_plan import (
    ChatGPTPlanError,
    ChatGPTPlanSessionManager,
    utc_saved_at,
)
from jarvis.machine_config import load_machine_settings, save_machine_settings

_ENABLED_KEY = "JARVIS_CHATGPT_PLAN_ENABLED"
_MODEL_KEY = "JARVIS_CHATGPT_PLAN_MODEL"


def _persist_plan(*, enabled: bool, model: str | None = None) -> None:
    settings = load_machine_settings()
    settings[_ENABLED_KEY] = "true" if enabled else "false"
    if model is not None:
        normalized = str(model).strip()
        if not normalized:
            raise ValueError("ChatGPT-plan model must not be empty")
        settings[_MODEL_KEY] = normalized
    save_machine_settings(settings)


def _configured_model() -> str | None:
    value = load_machine_settings().get(_MODEL_KEY)
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _select_model(
    manager: ChatGPTPlanSessionManager,
    requested: str | None,
) -> str:
    models = manager.list_models()
    slugs = tuple(model.slug for model in models)
    requested_model = str(requested or "").strip() or None
    current = _configured_model()

    if requested_model is not None:
        if requested_model not in slugs:
            raise ChatGPTPlanError(
                "Requested model is not visible to this ChatGPT account: "
                f"{requested_model}"
            )
        selected = requested_model
    elif current in slugs:
        selected = current
    else:
        selected = slugs[0]

    print("Available ChatGPT-plan models:")
    for model in models:
        marker = "*" if model.slug == selected else " "
        print(f"  {marker} {model.slug} - {model.display_name}")
    return selected


def _cmd_signin(args: argparse.Namespace) -> int:
    manager = ChatGPTPlanSessionManager()
    print("Opening ChatGPT authorization in your browser...")
    credentials = manager.sign_in(timeout_seconds=float(args.timeout))
    selected = _select_model(manager, args.model)
    _persist_plan(enabled=True, model=selected)
    identity = credentials.email or credentials.subject
    print(f"Connected ChatGPT account: {identity}")
    print(f"ChatGPT-plan model: {selected}")
    print("ChatGPT-plan intelligence: ENABLED")
    print("Paid API provider remains configured as fallback/realtime.")
    return 0


def _cmd_status(_args: argparse.Namespace) -> int:
    manager = ChatGPTPlanSessionManager()
    credentials = manager.current_credentials()
    settings = load_machine_settings()
    enabled = settings.get(_ENABLED_KEY, "false").strip().casefold() == "true"
    model = settings.get(_MODEL_KEY, "").strip() or None
    payload = {
        "connected": bool(credentials and credentials.plan_usage_enabled),
        "enabled": enabled,
        "model": model,
        "account": (
            None
            if credentials is None
            else credentials.email or credentials.subject
        ),
        "saved_at_utc": (
            None if credentials is None else utc_saved_at(credentials)
        ),
        "plan_usage_scope": bool(
            credentials and credentials.plan_usage_enabled
        ),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["connected"] else 2


def _cmd_models(_args: argparse.Namespace) -> int:
    manager = ChatGPTPlanSessionManager()
    for model in manager.list_models():
        print(f"{model.slug}\t{model.display_name}")
    return 0


def _cmd_set_model(args: argparse.Namespace) -> int:
    manager = ChatGPTPlanSessionManager()
    requested = str(args.model).strip()
    visible = {model.slug for model in manager.list_models()}
    if requested not in visible:
        raise ChatGPTPlanError(
            f"Model is not visible to this ChatGPT account: {requested}"
        )
    _persist_plan(enabled=True, model=requested)
    print(f"ChatGPT-plan model: {requested}")
    print("ChatGPT-plan intelligence: ENABLED")
    return 0


def _cmd_disable(_args: argparse.Namespace) -> int:
    _persist_plan(enabled=False)
    print("ChatGPT-plan intelligence: DISABLED")
    print("Saved OAuth credentials were retained for later re-enable/reauthorization.")
    return 0


def _cmd_smoke(_args: argparse.Namespace) -> int:
    settings = load_machine_settings()
    enabled = settings.get(_ENABLED_KEY, "false").strip().casefold() == "true"
    model = settings.get(_MODEL_KEY, "").strip()
    if not enabled or not model:
        raise ChatGPTPlanError(
            "ChatGPT-plan intelligence is not enabled with a selected model"
        )
    manager = ChatGPTPlanSessionManager()
    response = manager.invoke_structured(
        model=model,
        instructions=(
            "This is a JARVIS owner-acceptance probe. Return the requested JSON "
            "with ok=true and a short message confirming ChatGPT-plan inference."
        ),
        input_payload={"probe": "chatgpt_plan_owner_acceptance"},
        schema_name="ChatGPTPlanSmoke",
        schema={
            "type": "object",
            "properties": {
                "ok": {"type": "boolean"},
                "message": {"type": "string"},
            },
            "required": ["ok", "message"],
            "additionalProperties": False,
        },
    )
    try:
        payload = json.loads(response.output_text)
    except json.JSONDecodeError as exc:
        raise ChatGPTPlanError(
            "ChatGPT-plan smoke response was not valid JSON"
        ) from exc
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise ChatGPTPlanError("ChatGPT-plan smoke probe did not return ok=true")
    print(
        json.dumps(
            {
                "ok": True,
                "model": model,
                "message": payload.get("message"),
                "usage_observed": response.usage_observed,
                "usage": response.usage,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jarvis-chatgpt-plan",
        description="Manage JARVIS ChatGPT-plan primary intelligence.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    signin = commands.add_parser("signin", help="Authorize ChatGPT plan usage.")
    signin.add_argument(
        "--model",
        default=None,
        help="Select one visible model slug after authorization.",
    )
    signin.add_argument(
        "--timeout",
        type=float,
        default=300.0,
        help="Seconds to wait for browser authorization.",
    )
    signin.set_defaults(handler=_cmd_signin)

    status = commands.add_parser("status", help="Show connection state without tokens.")
    status.set_defaults(handler=_cmd_status)

    models = commands.add_parser("models", help="List plan-visible model slugs.")
    models.set_defaults(handler=_cmd_models)

    model = commands.add_parser("set-model", help="Select and enable one visible model.")
    model.add_argument("model")
    model.set_defaults(handler=_cmd_set_model)

    disable = commands.add_parser(
        "disable",
        help="Disable plan routing while retaining encrypted credentials.",
    )
    disable.set_defaults(handler=_cmd_disable)

    smoke = commands.add_parser(
        "smoke",
        help="Run one minimal plan-backed structured inference.",
    )
    smoke.set_defaults(handler=_cmd_smoke)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except (ChatGPTPlanError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
