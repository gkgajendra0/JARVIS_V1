"""Stable CLI dispatcher for governed JARVIS Hands acceptance and diagnostics."""

from __future__ import annotations

import argparse

from jarvis.computer.hands_integrated_acceptance import (
    run_integrated_acceptance,
    run_integrated_readiness,
)
from jarvis.computer.hands_smoke import (
    run_media_acceptance,
    run_native_core_acceptance,
    run_notepad_acceptance,
)
from jarvis.config import JarvisConfig
from jarvis.machine_config import load_machine_settings, save_machine_settings

_VISUAL_SETTING = "JARVIS_VISUAL_COMPUTER_USE_ENABLED"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and configure governed JARVIS Hands on the owner Windows machine"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--readiness",
        action="store_true",
        help="probe complete H1-H5 Hands readiness without authorizing mutations",
    )
    mode.add_argument(
        "--integrated",
        action="store_true",
        help="run the consolidated representative H1-H5 owner acceptance session",
    )
    mode.add_argument(
        "--native",
        action="store_true",
        help="run the legacy governed native H1 diagnostic",
    )
    mode.add_argument(
        "--media",
        action="store_true",
        help="run the legacy governed Windows media-session diagnostic",
    )
    mode.add_argument(
        "--enable-visual",
        action="store_true",
        help=(
            "persist opt-in for window-scoped provider-backed visual desktop fallback"
        ),
    )
    mode.add_argument(
        "--disable-visual",
        action="store_true",
        help="persistently disable provider-backed visual desktop fallback",
    )
    mode.add_argument(
        "--show-visual",
        action="store_true",
        help="show whether window-scoped visual desktop fallback is enabled",
    )
    parser.add_argument(
        "--volume",
        type=float,
        default=30.0,
        help="final master-volume percentage for --native (safe diagnostic range: 5-80)",
    )
    return parser


def _set_visual_enabled(enabled: bool) -> int:
    settings = load_machine_settings()
    settings[_VISUAL_SETTING] = "true" if enabled else "false"
    path = save_machine_settings(settings)
    print(
        "JARVIS window-scoped visual desktop fallback: "
        f"{'enabled' if enabled else 'disabled'}"
    )
    print(f"Machine profile: {path}")
    print("Restart any running JARVIS voice session for the change to take effect.")
    return 0


def _show_visual_enabled() -> int:
    config = JarvisConfig.from_environment()
    print(
        "JARVIS window-scoped visual desktop fallback: "
        f"{'enabled' if config.visual_computer_use_enabled else 'disabled'}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.readiness:
        return run_integrated_readiness()
    if args.integrated:
        return run_integrated_acceptance()
    if args.native:
        return run_native_core_acceptance(args.volume)
    if args.media:
        return run_media_acceptance()
    if args.enable_visual:
        return _set_visual_enabled(True)
    if args.disable_visual:
        return _set_visual_enabled(False)
    if args.show_visual:
        return _show_visual_enabled()
    return run_notepad_acceptance()


if __name__ == "__main__":
    raise SystemExit(main())
