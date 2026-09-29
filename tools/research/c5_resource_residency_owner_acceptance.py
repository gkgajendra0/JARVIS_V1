"""Owner-machine acceptance for C5 resource-aware local-model residency."""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import time
from dataclasses import asdict, replace
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from jarvis.model_routing.invoker import (
    ModelInvocationContext,
    ModelInvoker,
    build_default_model_adapter_registry,
)
from jarvis.model_routing.local_residency import (
    GpuResidencyState,
    LocalResidencyPolicy,
    NvidiaSmiResidencyProbe,
)
from jarvis.model_routing.ollama import (
    C5_LOCAL_TARGET_ID,
    build_c5_local_residency_manager,
    build_c5_local_target_registry,
)


class _AcceptanceOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["residency_ready"]


def _stop_model(model: str) -> None:
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
    if result.returncode != 0:
        raise RuntimeError("could not stop Ollama model before acceptance")
    time.sleep(1.0)


async def _invoke(
    *,
    invoker: ModelInvoker,
    target,
    ordinal: int,
) -> dict[str, object]:
    started = time.perf_counter()
    telemetry = await invoker.invoke_structured_with_telemetry(
        target=target,
        system_prompt=(
            "You are the localhost JARVIS residency acceptance probe. "
            "Return only the exact schema-valid status requested."
        ),
        input_payload={
            "required_status": "residency_ready",
            "ordinal": ordinal,
        },
        response_model=_AcceptanceOutput,
        request_context=ModelInvocationContext(
            work_id="c5-residency-owner-acceptance",
            routing_request_id=f"c5-residency-route-{ordinal}",
            decision_id=f"c5-residency-decision-{ordinal}",
            attempt_id=f"c5-residency-attempt-{ordinal}",
            correlation_key=f"c5-residency-{ordinal}",
        ),
    )
    wall_ms = (time.perf_counter() - started) * 1000.0
    if telemetry.parsed != _AcceptanceOutput(status="residency_ready"):
        raise RuntimeError("unexpected local residency acceptance output")
    return {
        "ordinal": ordinal,
        "wall_latency_ms": wall_ms,
        "adapter_latency_ms": telemetry.latency_ms,
        "usage_observed": telemetry.usage_observed,
        "usage": telemetry.usage,
    }


async def _run() -> dict[str, object]:
    production_policy = LocalResidencyPolicy()
    acceptance_policy = replace(
        production_policy,
        # Acceptance-only threshold deliberately sits above the known loaded
        # headroom so two manual polls force the real automatic-eviction path.
        pressure_free_mib=4000,
        sample_interval_seconds=60.0,
    )
    probe = NvidiaSmiResidencyProbe()
    if not probe.available:
        raise RuntimeError("nvidia-smi is unavailable")

    baseline = probe.sample()
    if baseline is None:
        raise RuntimeError("could not sample NVIDIA GPU state")
    if baseline.free_mib < production_policy.min_free_to_load_mib:
        raise RuntimeError(
            "owner GPU does not currently have production-safe cold-load headroom"
        )
    if baseline.utilization_percent > production_policy.max_util_to_load_percent:
        raise RuntimeError(
            "owner GPU is currently too busy for production-safe cold loading"
        )

    _stop_model("qwen3.5:4b")

    manager = build_c5_local_residency_manager(
        policy=acceptance_policy,
        probe=probe,
    )
    adapters = build_default_model_adapter_registry(
        ollama_residency_manager=manager,
    )
    target_registry = build_c5_local_target_registry(adapters)
    target = target_registry.require(C5_LOCAL_TARGET_ID)
    invoker = ModelInvoker(adapters)

    try:
        invocations = [
            await _invoke(invoker=invoker, target=target, ordinal=1),
            await _invoke(invoker=invoker, target=target, ordinal=2),
        ]
        loaded_snapshot = probe.sample()
        if loaded_snapshot is None:
            raise RuntimeError("could not sample loaded local-model GPU state")

        resident_status = manager.status()
        if resident_status.state is not GpuResidencyState.RESIDENT:
            raise RuntimeError("local model was not marked resident")

        first_pressure = manager.poll_once()
        second_pressure = manager.poll_once()
        if first_pressure.state is not GpuResidencyState.RESIDENT:
            raise RuntimeError("pressure hysteresis evicted before required samples")
        if second_pressure.state is not GpuResidencyState.PRESSURE_BLOCKED:
            raise RuntimeError("sustained acceptance pressure did not evict local model")
        if second_pressure.resident_model is not None:
            raise RuntimeError("evicted local model remained marked resident")

        recovery_trace: list[dict[str, object]] = []
        recovered = False
        for attempt in range(1, 13):
            time.sleep(1.0)
            status = manager.poll_once()
            snapshot = status.snapshot
            recovery_trace.append(
                {
                    "attempt": attempt,
                    "state": status.state.value,
                    "recovery_sample_count": status.recovery_sample_count,
                    "reason": status.last_reason,
                    "gpu": None if snapshot is None else asdict(snapshot),
                }
            )
            if status.state is GpuResidencyState.AVAILABLE:
                recovered = True
                break
        if not recovered:
            raise RuntimeError("local residency manager did not recover after unload")

        recovered_snapshot = probe.sample()
        if recovered_snapshot is None:
            raise RuntimeError("could not sample recovered GPU state")

        return {
            "status": "PASS",
            "cloud_model_api_called": False,
            "production_routing_mutated": False,
            "target": {
                "target_id": target.target_id,
                "model_id": target.model_id,
            },
            "production_policy": asdict(production_policy),
            "acceptance_pressure_override_mib": (
                acceptance_policy.pressure_free_mib
            ),
            "baseline_gpu": asdict(baseline),
            "loaded_gpu": asdict(loaded_snapshot),
            "recovered_gpu": asdict(recovered_snapshot),
            "invocations": invocations,
            "pressure": {
                "first_poll_state": first_pressure.state.value,
                "first_poll_count": first_pressure.pressure_sample_count,
                "second_poll_state": second_pressure.state.value,
                "second_poll_reason": second_pressure.last_reason,
            },
            "recovery_trace": recovery_trace,
        }
    finally:
        manager.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run C5 resource-aware residency owner acceptance."
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    report = asyncio.run(_run())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    print(f"\nFull report: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
