"""Production entry point for the local-only JARVIS runtime supervisor."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import replace

from jarvis.dev_supervisor import (
    _runtime_supervisor_config_from_environment,
    run_supervisor,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the local-only JARVIS production runtime supervisor."
    )
    parser.add_argument(
        "--branch",
        default="",
        help="Explicit local Git branch identity; defaults to configured/main.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config = _runtime_supervisor_config_from_environment()
    if args.branch:
        config = replace(config, branch=str(args.branch).strip())
    return run_supervisor(config)


if __name__ == "__main__":
    raise SystemExit(main())
