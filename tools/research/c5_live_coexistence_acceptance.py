"""Owner-machine C5 live JARVIS + local-brain coexistence acceptance."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import psutil
from pydantic import BaseModel, ConfigDict

from jarvis.model_routing.invoker import (
    ModelInvocationContext,
    ModelInvoker,
    build_default_model_adapter_registry,
)
from jarvis.model_routing.ollama import (
    C5_LOCAL_TARGET_ID,
    build_c5_local_target_registry,
)
from jarvis.performance.runtime_profile import (
    NvidiaSmiProbe,
    metric_summary,
    sample_process,
)


class _ProbeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["coexistence_ready"]


@dataclass(frozen=True, slots=True)
class _PhaseResult:
    name: str
    samples: tuple[dict[str, object], ...]


def _stop_model(model: str) -> int:
    executable = shutil.which("ollama")
    if executable is None:
        raise RuntimeError("ollama CLI is not available on PATH")
    result = subprocess.run(
        [executable, "stop", model],
        check=False,
        capture_output=True,
        text=True,
        timeout=30.0,
    )
    time.sleep(1.0)
    return int(result.returncode)


def _jarvis_process_candidates() -> tuple[psutil.Process, ...]:
    """Return matching JARVIS voice launcher/runtime processes on Windows."""

    current_pid = os.getpid()
    matches: list[psutil.Process] = []
    for process in psutil.process_iter(["pid", "name", "cmdline", "create_time"]):
        if process.pid == current_pid:
            continue
        try:
            command = " ".join(process.info.get("cmdline") or []).casefold()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
        if (
            "jarvis-voice" not in command
            and "jarvis.voice.production_runtime" not in command
        ):
            continue
        matches.append(process)
    return tuple(matches)


def _select_jarvis_runtime_process() -> tuple[
    psutil.Process, tuple[dict[str, object], ...]
]:
    """Choose the newest Python runtime when Windows exposes launcher/shim peers."""

    candidates = _jarvis_process_candidates()
    if not candidates:
        raise RuntimeError(
            "Could not find jarvis-voice. Start production JARVIS first."
        )

    snapshots: list[dict[str, object]] = []
    ranked: list[tuple[int, float, int, psutil.Process]] = []
    for process in candidates:
        try:
            name = str(process.name() or "")
            command = " ".join(process.cmdline())
            created = float(process.create_time())
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

        is_python = 1 if name.casefold().startswith("python") else 0
        ranked.append((is_python, created, process.pid, process))
        snapshots.append(
            {
                "pid": process.pid,
                "name": name,
                "cmdline": command,
                "create_time_epoch": created,
                "python_runtime_candidate": bool(is_python),
            }
        )

    if not ranked:
        raise RuntimeError("Matching jarvis-voice processes disappeared")

    ranked.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    selected = ranked[0][3]
    return selected, tuple(sorted(snapshots, key=lambda item: int(item["pid"])))


def _process_alive(process: psutil.Process) -> bool:
    try:
        return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def _collect_samples(
    process: psutil.Process,
    *,
    name: str,
    duration_seconds: float,
    interval_seconds: float,
    gpu_probe: NvidiaSmiProbe,
) -> _PhaseResult:
    if duration_seconds <= 0:
        raise ValueError("phase duration must be positive")
    logical_cpus = psutil.cpu_count(logical=True) or 1
    samples: list[dict[str, object]] = []
    process.cpu_percent(interval=None)
    psutil.cpu_percent(interval=None)
    started = time.monotonic()
    while time.monotonic() - started < duration_seconds:
        time.sleep(
            min(interval_seconds, duration_seconds - (time.monotonic() - started))
        )
        if not _process_alive(process):
            raise RuntimeError("jarvis-voice exited during coexistence acceptance")
        samples.append(
            sample_process(
                process,
                phase=name,
                logical_cpu_count=logical_cpus,
                gpu_probe=gpu_probe,
            )
        )
    return _PhaseResult(name=name, samples=tuple(samples))


def _phase_summary(phase: _PhaseResult) -> dict[str, object]:
    samples = list(phase.samples)
    keys = (
        "process_cpu_task_manager_percent",
        "system_cpu_percent",
        "rss_mb",
        "gpu_util_percent",
        "gpu_memory_used_mb",
        "gpu_memory_total_mb",
    )
    return {
        "name": phase.name,
        "sample_count": len(samples),
        "metrics": {key: metric_summary(samples, key) for key in keys},
    }


async def _invoke_local(
    *,
    invoker: ModelInvoker,
    target,
    ordinal: int,
) -> dict[str, object]:
    started = time.perf_counter()
    telemetry = await invoker.invoke_structured_with_telemetry(
        target=target,
        system_prompt=(
            "You are the localhost JARVIS coexistence acceptance probe. "
            "Return only the exact schema-valid status requested."
        ),
        input_payload={"required_status": "coexistence_ready", "ordinal": ordinal},
        response_model=_ProbeOutput,
        request_context=ModelInvocationContext(
            work_id="c5-live-coexistence",
            routing_request_id=f"c5-live-route-{ordinal}",
            decision_id=f"c5-live-decision-{ordinal}",
            attempt_id=f"c5-live-attempt-{ordinal}",
            correlation_key=f"c5-live-{ordinal}",
        ),
    )
    wall_ms = (time.perf_counter() - started) * 1000.0
    if telemetry.parsed != _ProbeOutput(status="coexistence_ready"):
        raise RuntimeError("local coexistence probe returned unexpected output")
    return {
        "ordinal": ordinal,
        "adapter_latency_ms": telemetry.latency_ms,
        "wall_latency_ms": wall_ms,
        "usage_observed": telemetry.usage_observed,
        "usage": telemetry.usage,
    }


async def _run(args: argparse.Namespace) -> dict[str, object]:
    if args.pid is not None:
        process = psutil.Process(args.pid)
        process_candidates: tuple[dict[str, object], ...] = ()
    else:
        process, process_candidates = _select_jarvis_runtime_process()

    if not _process_alive(process):
        raise RuntimeError("jarvis-voice process is not running")

    gpu_probe = NvidiaSmiProbe()
    if not gpu_probe.available:
        raise RuntimeError("nvidia-smi GPU sampling is unavailable")

    adapters = build_default_model_adapter_registry()
    target_registry = build_c5_local_target_registry(adapters)
    target = target_registry.require(C5_LOCAL_TARGET_ID)
    invoker = ModelInvoker(adapters)

    _stop_model(target.model_id)

    baseline = _collect_samples(
        process,
        name="jarvis_baseline",
        duration_seconds=args.baseline_seconds,
        interval_seconds=args.interval,
        gpu_probe=gpu_probe,
    )

    invocations: list[dict[str, object]] = []
    for ordinal in range(1, args.warm_requests + 2):
        print(
            f"[coexistence] local request {ordinal}/{args.warm_requests + 1}",
            flush=True,
        )
        invocations.append(
            await _invoke_local(
                invoker=invoker,
                target=target,
                ordinal=ordinal,
            )
        )

    qwen_loaded = _collect_samples(
        process,
        name="jarvis_qwen_loaded_idle",
        duration_seconds=args.loaded_idle_seconds,
        interval_seconds=args.interval,
        gpu_probe=gpu_probe,
    )

    print()
    print("Qwen is now loaded and JARVIS should remain running.")
    print(
        "Use the wake word and have a short normal conversation with JARVIS "
        "during the next phase."
    )
    if not args.no_prompt:
        input("Press Enter when ready to start the live conversation phase... ")

    conversation = _collect_samples(
        process,
        name="jarvis_qwen_loaded_conversation",
        duration_seconds=args.conversation_seconds,
        interval_seconds=args.interval,
        gpu_probe=gpu_probe,
    )

    alive_after_conversation = _process_alive(process)
    unload_returncode = _stop_model(target.model_id)

    recovered = _collect_samples(
        process,
        name="jarvis_after_qwen_unload",
        duration_seconds=args.recovery_seconds,
        interval_seconds=args.interval,
        gpu_probe=gpu_probe,
    )

    return {
        "status": "PASS",
        "cloud_model_api_called": False,
        "production_routing_mutated": False,
        "jarvis": {
            "pid": process.pid,
            "alive_after_conversation": alive_after_conversation,
            "process_candidates": list(process_candidates),
        },
        "local_target": {
            "target_id": target.target_id,
            "model_id": target.model_id,
            "capabilities": list(target.capabilities),
        },
        "invocations": invocations,
        "phases": {
            "baseline": _phase_summary(baseline),
            "qwen_loaded_idle": _phase_summary(qwen_loaded),
            "qwen_loaded_conversation": _phase_summary(conversation),
            "after_unload": _phase_summary(recovered),
        },
        "unload_returncode": unload_returncode,
        "nvidia_smi_disabled_reason": gpu_probe.disabled_reason,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Measure live JARVIS voice/vision coexistence with C5 Qwen."
    )
    parser.add_argument("--pid", type=int)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--interval", type=float, default=0.5)
    parser.add_argument("--baseline-seconds", type=float, default=10.0)
    parser.add_argument("--loaded-idle-seconds", type=float, default=10.0)
    parser.add_argument("--conversation-seconds", type=float, default=20.0)
    parser.add_argument("--recovery-seconds", type=float, default=5.0)
    parser.add_argument("--warm-requests", type=int, default=2)
    parser.add_argument("--no-prompt", action="store_true")
    args = parser.parse_args(argv)

    if args.interval < 0.1:
        parser.error("--interval must be at least 0.1 seconds")
    for name in (
        "baseline_seconds",
        "loaded_idle_seconds",
        "conversation_seconds",
        "recovery_seconds",
    ):
        if getattr(args, name) <= 0:
            parser.error(f"--{name.replace('_', '-')} must be positive")
    if args.warm_requests < 0:
        parser.error("--warm-requests must be non-negative")

    report = asyncio.run(_run(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print()
    print(json.dumps(report, indent=2, sort_keys=True))
    print(f"\nFull report: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
