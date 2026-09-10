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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate governed JARVIS Hands on the owner Windows machine"
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
    parser.add_argument(
        "--volume",
        type=float,
        default=30.0,
        help="final master-volume percentage for --native (safe diagnostic range: 5-80)",
    )
    return parser


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
    return run_notepad_acceptance()


if __name__ == "__main__":
    raise SystemExit(main())
