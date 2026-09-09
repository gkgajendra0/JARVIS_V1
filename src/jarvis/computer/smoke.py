"""Owner-machine technology smoke for bounded local computer use.

This is intentionally not wired into the production voice runtime. It exists only
to validate provider + screenshot + input mechanics before the existing Step-3
authority path is attached to live computer actions.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from jarvis.ai_provider import configured_ai_provider
from jarvis.computer import (
    ActionExecutionResult,
    ComputerAction,
    ComputerUseService,
    MssPyAutoGuiExecutor,
    ScreenFrame,
    build_computer_use_provider,
)
from jarvis.machine_config import load_machine_settings

_SMOKE_TASKS = {
    "notepad-type": (
        "Open Notepad. Type exactly 'JARVIS computer use smoke test'. "
        "Do not save, create, delete, download, install, send, purchase, or change "
        "any account or security setting. Stop after the text is visible."
    ),
    "settings-bluetooth-readonly": (
        "Open Windows Settings and navigate to Bluetooth & devices. "
        "Do not connect, disconnect, pair, remove, rename, or modify any device or "
        "setting. Stop when the Bluetooth & devices page is visible."
    ),
}


class _TracingExecutor:
    """Owner-smoke wrapper that exposes progress without changing production core."""

    def __init__(self, inner: MssPyAutoGuiExecutor) -> None:
        self._inner = inner
        self._capture_count = 0
        self._action_count = 0

    def capture_screen(self) -> ScreenFrame:
        self._capture_count += 1
        print(f"[capture {self._capture_count}] Capturing desktop state...", flush=True)
        frame = self._inner.capture_screen()
        print(
            "[capture "
            f"{self._capture_count}] OK {frame.width}x{frame.height} "
            f"at ({frame.left},{frame.top})",
            flush=True,
        )
        return frame

    def execute(self, action: ComputerAction) -> ActionExecutionResult:
        self._action_count += 1
        intent = f" intent={action.intent!r}" if action.intent else ""
        print(
            f"[action {self._action_count}] {action.name} "
            f"args={action.arguments!r}{intent}",
            flush=True,
        )
        result = self._inner.execute(action)
        print(f"[action {self._action_count}] {result.detail}", flush=True)
        return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a bounded owner-machine JARVIS computer-use smoke."
    )
    parser.add_argument(
        "scenario",
        choices=sorted(_SMOKE_TASKS),
        help="Fixed non-consequential scenario to run.",
    )
    parser.add_argument(
        "--provider",
        choices=("gemini", "openai"),
        default=None,
        help="Override the configured active provider for this smoke only.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Optional computer-use model override.",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=8,
        help="Maximum provider action-loop turns.",
    )
    return parser


async def _run(args: argparse.Namespace) -> int:
    provider_name = args.provider or configured_ai_provider(load_machine_settings())
    task = _SMOKE_TASKS[args.scenario]
    provider = build_computer_use_provider(
        provider_name,
        model=args.model or os.getenv("JARVIS_COMPUTER_USE_MODEL"),
    )

    print("JARVIS computer-use owner smoke")
    print(f"provider={provider.provider_name} model={provider.model_name}")
    print(f"scenario={args.scenario} max_steps={args.max_steps}")
    print("Production voice integration remains DISABLED.")
    print("PyAutoGUI emergency fail-safe remains enabled (move pointer to upper-left).")
    confirmation = input("Type RUN exactly to allow this fixed smoke task: ").strip()
    if confirmation != "RUN":
        print("Smoke canceled; no desktop action executed.")
        return 2

    executor = _TracingExecutor(MssPyAutoGuiExecutor())
    service = ComputerUseService(
        provider=provider,
        executor=executor,
        max_steps=args.max_steps,
    )
    print("[provider] Starting computer-use action loop...", flush=True)
    result = await service.execute(task)
    print("[provider] Action loop finished.", flush=True)
    print(result.to_tool_payload())
    return 0 if result.ok else 3


def main() -> int:
    args = _parser().parse_args()
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        print("\nComputer-use smoke interrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
