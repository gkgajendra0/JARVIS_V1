"""Owner-machine smoke for the low-latency structured Windows path."""

from __future__ import annotations

import argparse
import platform
import sys
import time

from .structured_windows import (
    AllowlistedWindowsLauncher,
    StructuredWindowsError,
    WinAppCliBackend,
)

_EXPECTED_TEXT = "JARVIS structured automation smoke test"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Benchmark JARVIS structured Windows automation without an LLM loop."
    )
    parser.add_argument(
        "scenario",
        choices=("notepad-type",),
        help="Fixed non-consequential structured automation scenario.",
    )
    return parser


def _extract_text(payload: dict[str, object]) -> str:
    for key in ("text", "value"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
    return ""


def _run_notepad_type() -> int:
    if platform.system() != "Windows":
        print("This smoke requires Windows.", file=sys.stderr)
        return 2

    try:
        ui = WinAppCliBackend()
        launcher = AllowlistedWindowsLauncher()
    except StructuredWindowsError as exc:
        print(f"PRECHECK FAILED: {exc}", file=sys.stderr)
        return 2

    print("JARVIS structured Windows owner smoke")
    print("backend=Microsoft winapp UI Automation + native allow-listed app launch")
    print(f"winapp={ui.executable}")
    print("scenario=notepad-type")
    print("No Gemini/OpenAI computer-use calls will be made.")
    print("The test leaves Notepad open and does not save anything.")

    existing = ui.status("notepad", check=False)
    if int(existing.payload.get("exit_code", 1)) == 0:
        print(
            "PRECHECK FAILED: Notepad is already running. Close all Notepad windows "
            "first so this smoke cannot type into an existing document.",
            file=sys.stderr,
        )
        return 2

    confirmation = input("Type RUN exactly to start the fixed smoke task: ").strip()
    if confirmation != "RUN":
        print("Smoke canceled; no desktop action executed.")
        return 2

    total_started = time.perf_counter()
    try:
        launch = launcher.launch("notepad")
        print(f"[launch] request returned in {launch.elapsed_ms:.1f} ms")

        ready = ui.wait_until_running("notepad", timeout_seconds=6.0)
        print(f"[ready] winapp attached in {ready.elapsed_ms:.1f} ms")

        initial = ui.get_value("notepad", "Text editor")
        initial_text = _extract_text(initial.payload)
        print(f"[inspect] editor read in {initial.elapsed_ms:.1f} ms")
        if initial_text:
            print(
                "SAFETY STOP: Notepad opened with existing text/session content; "
                "nothing was typed.",
                file=sys.stderr,
            )
            return 3

        typed = ui.send_text(
            "notepad",
            _EXPECTED_TEXT,
            target_selector="Text editor",
        )
        print(f"[type] winapp delivered text in {typed.elapsed_ms:.1f} ms")

        verified = ui.get_value("notepad", "Text editor")
        actual = _extract_text(verified.payload)
        print(f"[verify] editor read in {verified.elapsed_ms:.1f} ms")
    except StructuredWindowsError as exc:
        print(f"SMOKE FAILED: {exc}", file=sys.stderr)
        return 3

    total_ms = (time.perf_counter() - total_started) * 1000
    ok = actual == _EXPECTED_TEXT
    print(
        {
            "ok": ok,
            "operation": "structured_windows_smoke",
            "backend": "winapp-ui",
            "scenario": "notepad-type",
            "expected": _EXPECTED_TEXT,
            "actual": actual,
            "total_ms": round(total_ms, 1),
            "launch_ms": round(launch.elapsed_ms, 1),
            "ready_ms": round(ready.elapsed_ms, 1),
            "type_ms": round(typed.elapsed_ms, 1),
            "verify_ms": round(verified.elapsed_ms, 1),
            "cloud_model_calls": 0,
        }
    )
    return 0 if ok else 3


def main() -> int:
    args = _parser().parse_args()
    if args.scenario == "notepad-type":
        return _run_notepad_type()
    raise AssertionError(f"unsupported scenario: {args.scenario}")


if __name__ == "__main__":
    raise SystemExit(main())
