"""Owner-machine acceptance for the C5 production Ollama integration."""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from jarvis.model_routing.cost import estimate_usage_cost_usd
from jarvis.model_routing.invoker import (
    ModelInvocationContext,
    ModelInvoker,
    build_default_model_adapter_registry,
)
from jarvis.model_routing.models import ModelLocality
from jarvis.model_routing.router import build_default_work_targets


class _LocalAcceptanceOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["local_ready"]


def _gpu_snapshot() -> dict[str, int | str] | None:
    executable = shutil.which("nvidia-smi")
    if executable is None:
        return None
    result = subprocess.run(
        [
            executable,
            "--query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu",
            "--format=csv,noheader,nounits",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=15.0,
    )
    if result.returncode != 0:
        return None
    lines = result.stdout.strip().splitlines()
    if not lines:
        return None
    parts = [item.strip() for item in lines[0].split(",")]
    if len(parts) != 5:
        return None
    try:
        return {
            "name": parts[0],
            "memory_total_mib": int(parts[1]),
            "memory_used_mib": int(parts[2]),
            "memory_free_mib": int(parts[3]),
            "utilization_gpu_percent": int(parts[4]),
        }
    except ValueError:
        return None


def _stop_model(model: str) -> dict[str, object]:
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
    return {
        "returncode": result.returncode,
        "gpu_after_unload": _gpu_snapshot(),
    }


async def _run(provider: str) -> dict[str, object]:
    adapters = build_default_model_adapter_registry()
    targets = build_default_work_targets(
        configured_provider=provider,
        configured_model=None,
        adapter_registry=adapters,
    )
    target = targets.registry.require("local.ollama.qwen3_5_4b.c5")

    expected_capabilities = {
        "bounded_planning",
        "classification_extraction",
        "summarization",
        "structured_output",
    }
    if set(target.capabilities) != expected_capabilities:
        raise RuntimeError("C5 local target capability contract drifted")
    if "engineering_reasoning" in target.capabilities:
        raise RuntimeError("C5 local target was unsafely admitted for engineering")
    if target.locality is not ModelLocality.LOCAL:
        raise RuntimeError("C5 target locality is not local")
    if target.credential_ref is not None:
        raise RuntimeError("C5 local target unexpectedly requires a credential")

    invoker = ModelInvoker(adapters)
    gpu_before = _gpu_snapshot()
    started = time.perf_counter()
    invocation = await invoker.invoke_structured_with_telemetry(
        target=target,
        system_prompt=(
            "You are a localhost JARVIS acceptance probe. Return the exact "
            "schema-valid status requested by the user payload and no prose."
        ),
        input_payload={"required_status": "local_ready"},
        response_model=_LocalAcceptanceOutput,
        request_context=ModelInvocationContext(
            work_id="c5-owner-local-acceptance",
            routing_request_id="c5-owner-local-acceptance-route",
            decision_id="c5-owner-local-acceptance-decision",
            attempt_id="c5-owner-local-acceptance-attempt",
            correlation_key="c5-owner-local-acceptance",
        ),
    )
    wall_ms = (time.perf_counter() - started) * 1000.0
    if invocation.parsed != _LocalAcceptanceOutput(status="local_ready"):
        raise RuntimeError("C5 local target returned unexpected acceptance output")

    api_cost = (
        estimate_usage_cost_usd(target, invocation.usage)
        if invocation.usage_observed
        else None
    )
    if api_cost not in {0, 0.0}:
        raise RuntimeError("C5 local target API cost is not known zero")

    gpu_loaded = _gpu_snapshot()
    unload = _stop_model(target.model_id)

    return {
        "status": "PASS",
        "cloud_model_api_called": False,
        "production_routing_mutated": False,
        "target": {
            "target_id": target.target_id,
            "adapter_id": target.adapter_id,
            "provider_id": target.provider_id,
            "model_id": target.model_id,
            "locality": target.locality.value,
            "capabilities": list(target.capabilities),
            "benchmark_status": target.benchmark_status.value,
            "endpoint_ref": target.endpoint_ref,
            "credential_ref": target.credential_ref,
        },
        "invocation": {
            "parsed_status": invocation.parsed.status,
            "usage": invocation.usage,
            "usage_observed": invocation.usage_observed,
            "adapter_latency_ms": invocation.latency_ms,
            "wall_latency_ms": wall_ms,
            "estimated_api_cost_usd": api_cost,
        },
        "gpu_before": gpu_before,
        "gpu_loaded": gpu_loaded,
        "unload": unload,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run C5 production local-target owner acceptance."
    )
    parser.add_argument(
        "--configured-provider",
        choices=("gemini", "openai"),
        default="gemini",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    report = asyncio.run(_run(args.configured_provider))
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
