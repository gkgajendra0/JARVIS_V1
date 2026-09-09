"""Owner-machine acceptance smoke for governed JARVIS hands."""

from __future__ import annotations

import json
import os
import platform
import sys

from jarvis.capabilities.runtime import build_default_capability_runtime
from jarvis.computer.structured_windows import StructuredWindowsError, WinAppCliBackend

_EXPECTED_TEXT = "JARVIS governed hands acceptance"


def main() -> int:
    if platform.system() != "Windows":
        print("JARVIS hands smoke requires Windows.", file=sys.stderr)
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


if __name__ == "__main__":
    raise SystemExit(main())
