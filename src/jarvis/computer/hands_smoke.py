"""Owner-machine acceptance smoke for governed JARVIS hands."""

from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from jarvis.authority.tooling import authority_tool_readiness
from jarvis.capabilities.runtime import (
    CapabilityRuntime,
    build_default_capability_runtime,
)
from jarvis.computer.structured_windows import StructuredWindowsError, WinAppCliBackend
from jarvis.config import JarvisConfig

_EXPECTED_TEXT = "JARVIS governed hands acceptance"
_CLIPBOARD_MARKER = "JARVIS native clipboard acceptance"
_REQUIRED_NATIVE_MODULES = {
    "pycaw": "Windows Core Audio",
    "win32clipboard": "Win32 clipboard",
    "win32gui": "Win32 window management",
    "winrt.windows.foundation": "Windows Runtime Foundation",
    "winrt.windows.media.control": "Windows media sessions",
}
_H1_OPERATIONS = (
    "get_master_volume",
    "set_master_volume",
    "mute_master_volume",
    "unmute_master_volume",
    "get_current_media",
    "play_media",
    "pause_media",
    "toggle_media_playback",
    "next_media",
    "previous_media",
    "stop_media",
    "get_clipboard_text",
    "set_clipboard_text",
    "clear_clipboard",
    "list_windows",
    "focus_window",
    "maximize_window",
    "minimize_window",
    "restore_window",
    "move_window_to_next_monitor",
    "open_app",
    "execute_windows_plan",
)


@dataclass(frozen=True, slots=True)
class ReadinessCheck:
    name: str
    ok: bool
    detail: str


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _native_dependency_checks(
    finder: Callable[[str], bool] = _module_available,
) -> tuple[ReadinessCheck, ...]:
    checks: list[ReadinessCheck] = []
    for module, label in _REQUIRED_NATIVE_MODULES.items():
        available = finder(module)
        checks.append(
            ReadinessCheck(
                name=f"Native dependency: {label}",
                ok=available,
                detail=(
                    module
                    if available
                    else f"missing {module}; install jarvis[windows-hands]"
                ),
            )
        )
    return tuple(checks)


def _operation_resolution_checks(
    runtime: CapabilityRuntime,
) -> tuple[ReadinessCheck, ...]:
    checks: list[ReadinessCheck] = []
    for operation in _H1_OPERATIONS:
        capability = runtime.capability_for_operation(operation)
        checks.append(
            ReadinessCheck(
                name=f"Operation: {operation}",
                ok=capability is not None,
                detail=capability or "did not resolve to exactly one governed executor",
            )
        )
    return tuple(checks)


def collect_readiness() -> tuple[ReadinessCheck, ...]:
    checks: list[ReadinessCheck] = []
    for item in authority_tool_readiness():
        detail = item.detail
        if item.path is not None:
            detail = f"{item.path} | {detail}"
        checks.append(ReadinessCheck(item.label, item.ok, detail))

    checks.extend(_native_dependency_checks())

    try:
        ui = WinAppCliBackend()
        probe = ui.probe()
        checks.append(
            ReadinessCheck(
                "Microsoft winapp",
                True,
                f"{ui.executable} | probe {probe.elapsed_ms:.1f} ms",
            )
        )
    except (StructuredWindowsError, OSError, RuntimeError) as exc:
        checks.append(ReadinessCheck("Microsoft winapp", False, str(exc)))

    runtime: CapabilityRuntime | None = None
    try:
        runtime = build_default_capability_runtime(
            ai_provider=JarvisConfig.from_environment().ai_provider
        )
        checks.extend(_operation_resolution_checks(runtime))
    except Exception as exc:  # noqa: BLE001 - readiness must report optional boundary failures.
        checks.append(
            ReadinessCheck(
                "Governed Hands runtime",
                False,
                f"{type(exc).__name__}: {exc}",
            )
        )
    finally:
        if runtime is not None:
            runtime.close()
    return tuple(checks)


def _readiness_payload(checks: tuple[ReadinessCheck, ...]) -> dict[str, Any]:
    return {
        "ok": all(check.ok for check in checks),
        "operation": "governed_hands_readiness",
        "read_only": True,
        "mutations_performed": 0,
        "cloud_model_calls": 0,
        "checks": [
            {"name": check.name, "ok": check.ok, "detail": check.detail}
            for check in checks
        ],
    }


def _readiness_or_exit() -> tuple[bool, tuple[ReadinessCheck, ...]]:
    readiness = collect_readiness()
    payload = _readiness_payload(readiness)
    print(json.dumps(payload, indent=2))
    if payload["ok"] is not True:
        print(
            "PRECHECK FAILED: fix readiness failures before governed mutation testing.",
            file=sys.stderr,
        )
        return False, readiness
    return True, readiness


def _result_payload(label: str, result) -> dict[str, Any]:
    return {
        "label": label,
        "ok": result.ok,
        "operation": result.operation,
        "capability": result.capability_key,
        "status": result.status.value,
        "verification_passed": result.data.get("verification_passed", False),
        "reason": result.reason,
        "elapsed_ms": round(result.elapsed_ms, 1),
        "provenance": list(result.provenance),
    }


def _native_core_actions(
    volume_percent: float,
) -> tuple[tuple[str, str, dict[str, object]], ...]:
    if not 5.0 <= float(volume_percent) <= 80.0:
        raise ValueError("native acceptance volume must be between 5 and 80 percent")
    return (
        ("open_calculator", "open_app", {"app": "calculator"}),
        ("maximize_calculator", "maximize_window", {"app": "calculator"}),
        ("set_master_volume", "set_master_volume", {"percent": float(volume_percent)}),
        (
            "set_clipboard_marker",
            "set_clipboard_text",
            {"text": _CLIPBOARD_MARKER},
        ),
    )


def _media_transition_plan(status: str) -> tuple[str, str] | None:
    normalized = str(status).strip().casefold()
    if "playing" in normalized:
        return ("pause_media", "play_media")
    if "paused" in normalized:
        return ("play_media", "pause_media")
    if "stopped" in normalized:
        return ("play_media", "stop_media")
    return None


def run_readiness() -> int:
    if platform.system() != "Windows":
        print("JARVIS hands readiness requires Windows.", file=sys.stderr)
        return 2
    payload = _readiness_payload(collect_readiness())
    print(json.dumps(payload, indent=2))
    return 0 if payload["ok"] is True else 2


def run_notepad_acceptance() -> int:
    if platform.system() != "Windows":
        print("JARVIS hands smoke requires Windows.", file=sys.stderr)
        return 2

    ready, _ = _readiness_or_exit()
    if not ready:
        return 2

    try:
        ui = WinAppCliBackend()
        existing = ui.status("notepad", check=False)
    except StructuredWindowsError as exc:
        print(f"PRECHECK FAILED: {exc}", file=sys.stderr)
        return 2

    if int(existing.payload.get("exit_code", 1)) == 0:
        print(
            "PRECHECK FAILED: Close all Notepad windows first. The acceptance smoke "
            "will never type into a pre-existing document.",
            file=sys.stderr,
        )
        return 2

    print("JARVIS governed hands owner acceptance")
    print("target=Notepad")
    print("strategy=Microsoft winapp structured UI Automation")
    print("authority=canonical ActionProposal + OPA + Windows Hello + one-time permit")
    print("browser_control=False raw_shell=False file_save=False cloud_model_calls=0")
    print("Windows Hello should authorize the exact bounded Notepad task once.")

    runtime = build_default_capability_runtime(
        ai_provider=JarvisConfig.from_environment().ai_provider
    )
    try:
        result = runtime.execute_operation(
            session_id="governed-hands-owner-acceptance",
            operation="execute_windows_plan",
            parameters={
                "app": "notepad",
                "task": f"Open Notepad and type exactly: {_EXPECTED_TEXT}",
                "allow_existing_app": False,
                "plan": [
                    {"action": "launch"},
                    {"action": "wait_until_running", "timeout_seconds": 6.0},
                    {
                        "action": "send_text",
                        "selector": "Text editor",
                        "text": _EXPECTED_TEXT,
                    },
                    {
                        "action": "verify_value",
                        "selector": "Text editor",
                        "expected": _EXPECTED_TEXT,
                        "comparison": "equals",
                    },
                ],
            },
        )
    finally:
        runtime.close()

    payload = {
        "ok": result.ok,
        "operation": "governed_hands_owner_acceptance",
        "status": result.status.value,
        "capability": result.capability_key,
        "strategy": result.data.get("strategy"),
        "verification_passed": result.data.get("verification_passed", False),
        "expected": _EXPECTED_TEXT,
        "reason": result.reason,
        "elapsed_ms": round(result.elapsed_ms, 1),
        "provenance": list(result.provenance),
        "cloud_model_calls": 0,
        "browser_control": False,
        "raw_shell": False,
        "file_saved": False,
    }
    print(json.dumps(payload, indent=2))
    print("Notepad is intentionally left open and unsaved for owner inspection.")
    return 0 if result.ok and payload["verification_passed"] is True else 3


def run_native_core_acceptance(volume_percent: float) -> int:
    if platform.system() != "Windows":
        print("JARVIS native hands smoke requires Windows.", file=sys.stderr)
        return 2
    try:
        actions = _native_core_actions(volume_percent)
    except ValueError as exc:
        print(f"PRECHECK FAILED: {exc}", file=sys.stderr)
        return 2

    ready, _ = _readiness_or_exit()
    if not ready:
        return 2

    print("JARVIS native H1 owner acceptance")
    print("actions=app lifecycle + window management + Core Audio + clipboard")
    print("authority=canonical ActionProposal + OPA + Windows Hello + one-time permit")
    print(f"final_volume_percent={float(volume_percent):g}")
    print(f"final_clipboard_text={_CLIPBOARD_MARKER!r}")
    print("Calculator is intentionally left open and maximized for owner inspection.")
    print("Expect one Windows Hello approval for each exact reversible action.")

    runtime = build_default_capability_runtime(
        ai_provider=JarvisConfig.from_environment().ai_provider
    )
    results: list[dict[str, Any]] = []
    try:
        for label, operation, parameters in actions:
            result = runtime.execute_operation(
                session_id="governed-hands-native-owner-acceptance",
                operation=operation,
                parameters=parameters,
            )
            payload = _result_payload(label, result)
            results.append(payload)
            print(json.dumps(payload, indent=2))
            if not result.ok or payload["verification_passed"] is not True:
                break
    finally:
        runtime.close()

    ok = len(results) == len(actions) and all(item["ok"] for item in results)
    summary = {
        "ok": ok,
        "operation": "governed_native_h1_owner_acceptance",
        "actions_completed": len(results),
        "actions_expected": len(actions),
        "verification_passed": ok
        and all(item["verification_passed"] is True for item in results),
        "cloud_model_calls": 0,
        "raw_shell": False,
        "final_side_effects": {
            "calculator": "open and maximized",
            "master_volume_percent": float(volume_percent),
            "clipboard_text": _CLIPBOARD_MARKER,
        },
        "results": results,
    }
    print(json.dumps(summary, indent=2))
    return 0 if summary["ok"] and summary["verification_passed"] else 3


def run_media_acceptance() -> int:
    if platform.system() != "Windows":
        print("JARVIS media hands smoke requires Windows.", file=sys.stderr)
        return 2

    ready, _ = _readiness_or_exit()
    if not ready:
        return 2

    print("JARVIS native media owner acceptance")
    print(
        "precondition=one Windows media session is active (playing, paused, or stopped)"
    )
    print("The test will read the session, change playback state, then restore it.")
    print(
        "Expect Windows Hello for the private read and for each exact media mutation."
    )

    runtime = build_default_capability_runtime(
        ai_provider=JarvisConfig.from_environment().ai_provider
    )
    results: list[dict[str, Any]] = []
    try:
        current = runtime.execute_operation(
            session_id="governed-hands-media-owner-acceptance",
            operation="get_current_media",
            parameters={},
        )
        current_payload = _result_payload("read_current_media", current)
        if current.ok:
            current_payload["state"] = current.data.get("state", {})
        results.append(current_payload)
        print(json.dumps(current_payload, indent=2))
        if not current.ok:
            return 3

        state = current.data.get("state", {})
        transition = _media_transition_plan(str(state.get("playback_status", "")))
        if transition is None:
            print(
                "MEDIA PRECONDITION FAILED: current playback state is not playing, paused, or stopped.",
                file=sys.stderr,
            )
            return 2

        for index, operation in enumerate(transition, start=1):
            result = runtime.execute_operation(
                session_id="governed-hands-media-owner-acceptance",
                operation=operation,
                parameters={},
            )
            payload = _result_payload(f"media_transition_{index}", result)
            if result.ok:
                payload["state"] = result.data.get("state", {})
            results.append(payload)
            print(json.dumps(payload, indent=2))
            if not result.ok or payload["verification_passed"] is not True:
                break
    finally:
        runtime.close()

    ok = len(results) == 3 and all(item["ok"] for item in results)
    summary = {
        "ok": ok,
        "operation": "governed_media_owner_acceptance",
        "verification_passed": ok
        and all(item["verification_passed"] is True for item in results),
        "final_playback_state_restored": ok,
        "cloud_model_calls": 0,
        "results": results,
    }
    print(json.dumps(summary, indent=2))
    return 0 if summary["ok"] and summary["verification_passed"] else 3


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate governed JARVIS Hands on the owner Windows machine"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--readiness",
        action="store_true",
        help="probe dependencies and operation resolution without authorizing mutations",
    )
    mode.add_argument(
        "--native",
        action="store_true",
        help="run governed native H1 acceptance for app/window/audio/clipboard",
    )
    mode.add_argument(
        "--media",
        action="store_true",
        help="run governed Windows media-session acceptance and restore playback state",
    )
    parser.add_argument(
        "--volume",
        type=float,
        default=30.0,
        help="final master-volume percentage for --native (safe acceptance range: 5-80)",
    )
    args = parser.parse_args()
    if args.readiness:
        return run_readiness()
    if args.native:
        return run_native_core_acceptance(args.volume)
    if args.media:
        return run_media_acceptance()
    return run_notepad_acceptance()


if __name__ == "__main__":
    raise SystemExit(main())
