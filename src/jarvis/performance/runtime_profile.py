from __future__ import annotations

import argparse
import json
import math
import os
import platform
import shutil
import subprocess
import sys
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psutil

_PROCESS_TOKENS = ("jarvis-voice", "jarvis.voice.production_runtime")
_METRICS = (
    "process_cpu_raw_percent",
    "process_cpu_task_manager_percent",
    "system_cpu_percent",
    "rss_mb",
    "vms_mb",
    "num_threads",
    "child_process_count",
    "num_handles",
    "gpu_util_percent",
    "gpu_memory_used_mb",
)


@dataclass(frozen=True, slots=True)
class Phase:
    name: str
    duration_seconds: float
    instruction: str


_DEFAULT_PHASES = (
    Phase(
        "idle_background",
        20.0,
        "Stay silent and, if practical, remain outside the camera view.",
    ),
    Phase(
        "owner_visible_idle",
        20.0,
        "Sit normally in the camera view and remain silent.",
    ),
    Phase(
        "conversation",
        30.0,
        "Use the wake word and have a short, normal conversation with JARVIS.",
    ),
    Phase(
        "post_conversation_idle",
        20.0,
        "Remain visible and silent after the conversation ends.",
    ),
)


def find_jarvis_process() -> psutil.Process:
    current_pid = os.getpid()
    candidates: list[psutil.Process] = []
    for process in psutil.process_iter(["pid", "cmdline"]):
        if process.pid == current_pid:
            continue
        try:
            command = " ".join(process.info.get("cmdline") or []).lower()
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
        if any(token in command for token in _PROCESS_TOKENS):
            candidates.append(process)

    if not candidates:
        raise RuntimeError(
            "Could not find jarvis-voice. Start it first or pass --pid explicitly."
        )
    if len(candidates) > 1:
        pids = ", ".join(str(process.pid) for process in candidates)
        raise RuntimeError(
            f"Found multiple jarvis-voice candidates ({pids}); pass --pid."
        )
    return candidates[0]


def percentile(values: list[float], probability: float) -> float:
    if not values:
        raise ValueError("cannot compute percentile of empty values")
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    weight = position - lower
    return float(ordered[lower] * (1.0 - weight) + ordered[upper] * weight)


def metric_summary(
    samples: Iterable[dict[str, Any]], key: str
) -> dict[str, float] | None:
    values = [float(sample[key]) for sample in samples if sample.get(key) is not None]
    if not values:
        return None
    return {
        "mean": sum(values) / len(values),
        "median": percentile(values, 0.50),
        "p95": percentile(values, 0.95),
        "max": max(values),
    }


def git_metadata() -> dict[str, Any]:
    def run(*args: str) -> str | None:
        try:
            result = subprocess.run(
                ["git", *args],
                check=False,
                capture_output=True,
                text=True,
                timeout=2.0,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return result.stdout.strip() if result.returncode == 0 else None

    status = run("status", "--porcelain")
    return {
        "head": run("rev-parse", "HEAD"),
        "branch": run("branch", "--show-current"),
        "dirty": bool(status) if status is not None else None,
    }


class NvidiaSmiProbe:
    def __init__(self) -> None:
        self.executable = shutil.which("nvidia-smi")
        self.disabled_reason: str | None = None

    @property
    def available(self) -> bool:
        return self.executable is not None and self.disabled_reason is None

    def sample(self) -> dict[str, float | int] | None:
        if not self.available or self.executable is None:
            return None
        command = [
            self.executable,
            "--query-gpu=index,utilization.gpu,memory.used,memory.total",
            "--format=csv,noheader,nounits",
        ]
        creationflags = 0
        if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
            creationflags = subprocess.CREATE_NO_WINDOW
        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=2.0,
                creationflags=creationflags,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            self.disabled_reason = str(exc)
            return None
        if result.returncode != 0:
            self.disabled_reason = result.stderr.strip() or "nvidia-smi failed"
            return None
        row = next((line for line in result.stdout.splitlines() if line.strip()), None)
        if row is None:
            self.disabled_reason = "nvidia-smi returned no GPU rows"
            return None
        fields = [field.strip() for field in row.split(",")]
        if len(fields) != 4:
            self.disabled_reason = f"unexpected nvidia-smi row: {row}"
            return None
        try:
            return {
                "gpu_index": int(fields[0]),
                "gpu_util_percent": float(fields[1]),
                "gpu_memory_used_mb": float(fields[2]),
                "gpu_memory_total_mb": float(fields[3]),
            }
        except ValueError:
            self.disabled_reason = f"could not parse nvidia-smi row: {row}"
            return None


def sample_process(
    process: psutil.Process,
    *,
    phase: str,
    logical_cpu_count: int,
    gpu_probe: NvidiaSmiProbe,
) -> dict[str, Any]:
    raw_cpu = process.cpu_percent(interval=None)
    memory = process.memory_info()
    sample: dict[str, Any] = {
        "captured_at": datetime.now(UTC).isoformat(),
        "phase": phase,
        "process_cpu_raw_percent": raw_cpu,
        "process_cpu_task_manager_percent": raw_cpu / max(logical_cpu_count, 1),
        "system_cpu_percent": psutil.cpu_percent(interval=None),
        "rss_mb": memory.rss / (1024 * 1024),
        "vms_mb": memory.vms / (1024 * 1024),
        "num_threads": process.num_threads(),
        "child_process_count": len(process.children(recursive=True)),
    }
    if hasattr(process, "num_handles"):
        try:
            sample["num_handles"] = process.num_handles()
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            sample["num_handles"] = None

    gpu = gpu_probe.sample()
    sample.update(
        gpu
        or {
            "gpu_index": None,
            "gpu_util_percent": None,
            "gpu_memory_used_mb": None,
            "gpu_memory_total_mb": None,
        }
    )
    return sample


def collect_phase(
    process: psutil.Process,
    phase: Phase,
    *,
    interval_seconds: float,
    logical_cpu_count: int,
    gpu_probe: NvidiaSmiProbe,
) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    started = time.monotonic()
    while True:
        elapsed = time.monotonic() - started
        if elapsed >= phase.duration_seconds:
            return samples
        time.sleep(min(interval_seconds, phase.duration_seconds - elapsed))
        try:
            samples.append(
                sample_process(
                    process,
                    phase=phase.name,
                    logical_cpu_count=logical_cpu_count,
                    gpu_probe=gpu_probe,
                )
            )
        except (psutil.NoSuchProcess, psutil.ZombieProcess) as exc:
            raise RuntimeError("jarvis-voice exited during profiling") from exc


def build_summary(samples: list[dict[str, Any]]) -> dict[str, Any]:
    overall = {key: metric_summary(samples, key) for key in _METRICS}
    phase_names = list(dict.fromkeys(sample["phase"] for sample in samples))
    by_phase: dict[str, Any] = {}
    for phase_name in phase_names:
        phase_samples = [sample for sample in samples if sample["phase"] == phase_name]
        by_phase[phase_name] = {
            key: metric_summary(phase_samples, key) for key in _METRICS
        }
    return {"overall": overall, "by_phase": by_phase}


def run_profile(
    *,
    pid: int | None,
    label: str,
    output_path: Path,
    interval_seconds: float,
    phases: tuple[Phase, ...],
    prompt: bool,
) -> int:
    if interval_seconds < 0.1:
        raise ValueError("sample interval must be at least 0.1 seconds")
    if any(phase.duration_seconds <= 0 for phase in phases):
        raise ValueError("phase durations must be positive")

    process = psutil.Process(pid) if pid is not None else find_jarvis_process()
    logical_cpu_count = psutil.cpu_count(logical=True) or 1
    physical_cpu_count = psutil.cpu_count(logical=False)
    gpu_probe = NvidiaSmiProbe()
    started_at = datetime.now(UTC)

    print("JARVIS runtime baseline profiler")
    print("--------------------------------")
    print(f"target_pid = {process.pid}")
    print(f"logical_cpus = {logical_cpu_count}")
    print(f"sample_interval_seconds = {interval_seconds:.2f}")
    print(f"nvidia_smi_available = {gpu_probe.available}")
    print("JARVIS behavior is not modified by this profiler.")

    samples: list[dict[str, Any]] = []
    for phase in phases:
        print()
        print(f"NEXT PHASE: {phase.name} ({phase.duration_seconds:.0f}s)")
        print(phase.instruction)
        if prompt:
            input("Press Enter when ready to start this phase... ")
        # Reset non-blocking CPU counters only after the operator is ready, so the
        # first sample cannot include time spent waiting at the phase prompt.
        process.cpu_percent(interval=None)
        psutil.cpu_percent(interval=None)
        phase_samples = collect_phase(
            process,
            phase,
            interval_seconds=interval_seconds,
            logical_cpu_count=logical_cpu_count,
            gpu_probe=gpu_probe,
        )
        samples.extend(phase_samples)
        cpu_values = [
            sample["process_cpu_task_manager_percent"] for sample in phase_samples
        ]
        if cpu_values:
            print(
                "phase_cpu_task_manager = "
                f"median {percentile(cpu_values, 0.50):.1f}% | "
                f"p95 {percentile(cpu_values, 0.95):.1f}% | "
                f"max {max(cpu_values):.1f}%"
            )

    try:
        target_name = process.name()
        target_cmdline = process.cmdline()
    except (psutil.AccessDenied, psutil.NoSuchProcess):
        target_name = "unknown"
        target_cmdline = []

    report = {
        "schema_version": 1,
        "label": label,
        "started_at": started_at.isoformat(),
        "completed_at": datetime.now(UTC).isoformat(),
        "host": {
            "platform": platform.platform(),
            "python": sys.version,
            "logical_cpu_count": logical_cpu_count,
            "physical_cpu_count": physical_cpu_count,
        },
        "git": git_metadata(),
        "target": {
            "pid": process.pid,
            "name": target_name,
            "cmdline": target_cmdline,
        },
        "profiler": {
            "interval_seconds": interval_seconds,
            "nvidia_smi_available": gpu_probe.available,
            "nvidia_smi_disabled_reason": gpu_probe.disabled_reason,
            "phase_plan": [
                {
                    "name": phase.name,
                    "duration_seconds": phase.duration_seconds,
                    "instruction": phase.instruction,
                }
                for phase in phases
            ],
        },
        "samples": samples,
        "summary": build_summary(samples),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print()
    print(f"PROFILE_COMPLETE = {output_path}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Profile a running JARVIS runtime without changing its behavior."
    )
    parser.add_argument("--pid", type=int, default=None)
    parser.add_argument("--label", default="baseline-owner-pc")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/performance/baseline-owner-pc.json"),
    )
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--idle-seconds", type=float, default=20.0)
    parser.add_argument("--visible-seconds", type=float, default=20.0)
    parser.add_argument("--conversation-seconds", type=float, default=30.0)
    parser.add_argument("--post-seconds", type=float, default=20.0)
    parser.add_argument("--no-prompt", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    phases = (
        Phase("idle_background", args.idle_seconds, _DEFAULT_PHASES[0].instruction),
        Phase(
            "owner_visible_idle",
            args.visible_seconds,
            _DEFAULT_PHASES[1].instruction,
        ),
        Phase(
            "conversation",
            args.conversation_seconds,
            _DEFAULT_PHASES[2].instruction,
        ),
        Phase(
            "post_conversation_idle",
            args.post_seconds,
            _DEFAULT_PHASES[3].instruction,
        ),
    )
    try:
        code = run_profile(
            pid=args.pid,
            label=args.label,
            output_path=args.output,
            interval_seconds=args.interval,
            phases=phases,
            prompt=not args.no_prompt,
        )
    except (RuntimeError, ValueError, psutil.Error) as exc:
        print(f"PROFILE_FAILED: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    raise SystemExit(code)


if __name__ == "__main__":
    main()
