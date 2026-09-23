"""Owner-invoked fault injection for Self-Repair acceptance testing.

This module is deliberately outside the automatic repair authority path. It can only
act on one production runtime that is directly supervised by jarvis-dev.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import Enum

import psutil


class FaultKind(str, Enum):
    CRASH = "crash"
    HANG = "hang"
    RESUME = "resume"


@dataclass(frozen=True, slots=True)
class ProcessSnapshot:
    pid: int
    create_time: float
    cmdline: tuple[str, ...]
    parent_pid: int | None
    parent_cmdline: tuple[str, ...]


def _normalize_cmdline(parts: Sequence[object] | None) -> tuple[str, ...]:
    if not parts:
        return ()
    return tuple(str(part) for part in parts if str(part).strip())


def _looks_like_runtime(cmdline: Sequence[str]) -> bool:
    joined = " ".join(cmdline).lower()
    return "jarvis.voice.production_runtime" in joined


def _looks_like_supervisor(cmdline: Sequence[str]) -> bool:
    joined = " ".join(cmdline).lower()
    return "jarvis-dev" in joined or "jarvis.dev_supervisor" in joined


def select_supervised_runtime(
    snapshots: Iterable[ProcessSnapshot],
) -> ProcessSnapshot:
    candidates = tuple(
        snapshot
        for snapshot in snapshots
        if _looks_like_runtime(snapshot.cmdline)
        and _looks_like_supervisor(snapshot.parent_cmdline)
    )
    if not candidates:
        raise RuntimeError(
            "no production runtime directly supervised by jarvis-dev was found"
        )
    if len(candidates) != 1:
        pids = ", ".join(str(candidate.pid) for candidate in candidates)
        raise RuntimeError(
            "refusing fault injection because multiple supervised runtimes were "
            f"found: {pids}"
        )
    return candidates[0]


def discover_supervised_runtime() -> ProcessSnapshot:
    snapshots: list[ProcessSnapshot] = []
    for process in psutil.process_iter(
        attrs=["pid", "create_time", "cmdline", "ppid"]
    ):
        try:
            info = process.info
            cmdline = _normalize_cmdline(info.get("cmdline"))
            if not _looks_like_runtime(cmdline):
                continue

            parent = process.parent()
            parent_pid = None if parent is None else parent.pid
            parent_cmdline = (
                () if parent is None else _normalize_cmdline(parent.cmdline())
            )
            snapshots.append(
                ProcessSnapshot(
                    pid=int(info["pid"]),
                    create_time=float(info["create_time"]),
                    cmdline=cmdline,
                    parent_pid=parent_pid,
                    parent_cmdline=parent_cmdline,
                )
            )
        except (psutil.Error, KeyError, TypeError, ValueError):
            continue

    return select_supervised_runtime(snapshots)


def inject_fault(kind: FaultKind, target: ProcessSnapshot) -> None:
    process = psutil.Process(target.pid)
    if abs(float(process.create_time()) - target.create_time) > 0.001:
        raise RuntimeError(
            "target process identity changed before fault injection; refusing to act"
        )

    if kind is FaultKind.CRASH:
        process.kill()
        return
    if kind is FaultKind.HANG:
        process.suspend()
        return
    if kind is FaultKind.RESUME:
        process.resume()
        return
    raise RuntimeError(f"unsupported fault kind: {kind}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Inject one explicit fault into the production runtime currently "
            "supervised by jarvis-dev."
        )
    )
    parser.add_argument(
        "fault",
        choices=[kind.value for kind in FaultKind],
        help=(
            "crash abruptly kills the supervised runtime; hang suspends it so the "
            "watchdog must recover it; resume is an emergency manual undo for hang"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        target = discover_supervised_runtime()
        kind = FaultKind(args.fault)
        inject_fault(kind, target)
    except (RuntimeError, psutil.Error) as exc:
        print(f"self-repair fault injection refused: {exc}", file=sys.stderr)
        return 2

    if kind is FaultKind.CRASH:
        print(
            f"Injected abrupt crash into supervised JARVIS runtime pid={target.pid}. "
            "jarvis-dev should apply the registered bounded crash-recovery policy."
        )
    elif kind is FaultKind.HANG:
        print(
            f"Suspended supervised JARVIS runtime pid={target.pid}. "
            "jarvis-dev should require watchdog threshold + confirmation before "
            "bounded liveness recovery."
        )
    else:
        print(f"Resumed supervised JARVIS runtime pid={target.pid}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
