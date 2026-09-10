"""Owner-machine acceptance smoke for governed JARVIS hands."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from jarvis.authority.tooling import authority_tool_readiness
from jarvis.capabilities.runtime import CapabilityRuntime, build_default_capability_runtime
from jarvis.computer.structured_windows import StructuredWindowsError, WinAppCliBackend

_EXPECTED_TEXT = "JARVIS governed hands acceptance"
_REQUIRED_NATIVE_MODULES = {
    "pycaw": "Windows Core Audio",
    "win32clipboard": "Win32 clipboard",
    "win32gui": "Win32 window management",
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
    return tuple(
        ReadinessCheck(
            name=f"Native dependency: {label}",
            ok=finder(module),
            detail=(
                module
                if finder(module)
                else f"missing {module}; install jarvis[windows-hands]"
            ),
        )
        for module, label in _REQUIRED_NATIVE_MODULES.items()
    )


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
            ai_provider=os.getenv("JARVIS_AI_PROVIDER", "gemini")
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

    readiness = collect_readiness()
    readiness_payload = _readiness_payload(readiness)
    print(json.dumps(readiness_payload, indent=2))
    if readiness_payload["ok"] is not True:
        print(
            "PRECHECK FAILED: fix readiness failures before governed mutation testing.",
            file=sys.stderr,
        )
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
        ai_provider=os.getenv("JARVIS_AI_PROVIDER", "gemini")
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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate governed JARVIS Hands on the owner Windows machine"
    )
    parser.add_argument(
        "--readiness",
        action="store_true",
        help="probe dependencies and operation resolution without authorizing mutations",
    )
    args = parser.parse_args()
    return run_readiness() if args.readiness else run_notepad_acceptance()


if __name__ == "__main__":
    raise SystemExit(main())
