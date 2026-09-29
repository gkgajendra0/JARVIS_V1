"""Owner-machine orchestration for the C5 isolated local-model benchmark.

This tool does not call cloud model APIs and does not mutate production JARVIS routing.
It optionally pulls approved local Ollama models, runs the frozen C4/C5 benchmark against
each model one at a time, records GPU/Ollama residency, unloads each model, and writes a
single comparison report.

By default it requires the production JARVIS voice runtime to be stopped so the first
measurement is an isolated local-model ceiling. A later coexistence run should use the
same models and corpus with JARVIS explicitly running.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import psutil

DEFAULT_MODELS = ("phi4-mini", "qwen3.5:4b")
DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"
BENCHMARK_SCRIPT = Path(__file__).with_name("c4_c5_benchmark.py")


def _run(
    command: list[str],
    *,
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        shell=False,
    )


def _get_json(url: str, *, timeout: float = 5.0) -> dict[str, Any] | None:
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _jarvis_processes() -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for process in psutil.process_iter(["pid", "name", "cmdline", "create_time"]):
        try:
            info = process.info
            command = " ".join(info.get("cmdline") or [])
            if (
                "jarvis.voice.production_runtime" not in command
                and "jarvis-voice" not in command
            ):
                continue
            matches.append(
                {
                    "pid": int(info["pid"]),
                    "name": info.get("name"),
                    "cmdline": command,
                    "create_time_epoch": info.get("create_time"),
                }
            )
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
    return matches


def _nvidia_snapshot() -> list[dict[str, Any]]:
    executable = shutil.which("nvidia-smi")
    if executable is None:
        return []
    result = _run(
        [
            executable,
            (
                "--query-gpu=index,name,driver_version,memory.total,memory.used,"
                "memory.free,utilization.gpu"
            ),
            "--format=csv,noheader,nounits",
        ],
        timeout=15.0,
    )
    if result.returncode != 0:
        return []
    rows: list[dict[str, Any]] = []
    for line in result.stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 7:
            continue
        try:
            rows.append(
                {
                    "index": int(parts[0]),
                    "name": parts[1],
                    "driver_version": parts[2],
                    "memory_total_mib": int(parts[3]),
                    "memory_used_mib": int(parts[4]),
                    "memory_free_mib": int(parts[5]),
                    "utilization_gpu_percent": int(parts[6]),
                }
            )
        except ValueError:
            continue
    return rows


def _ollama_models(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    raw = payload.get("models")
    if not isinstance(raw, list):
        return []
    models: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        details = item.get("details") if isinstance(item.get("details"), dict) else {}
        models.append(
            {
                "name": item.get("name") or item.get("model"),
                "size_bytes": item.get("size"),
                "size_vram_bytes": item.get("size_vram"),
                "context_length": item.get("context_length"),
                "processor": item.get("processor"),
                "parameter_size": details.get("parameter_size"),
                "quantization_level": details.get("quantization_level"),
                "family": details.get("family"),
            }
        )
    return models


def _ollama_state(host: str) -> dict[str, Any]:
    normalized = host.rstrip("/")
    return {
        "version": _get_json(f"{normalized}/api/version"),
        "installed": _ollama_models(_get_json(f"{normalized}/api/tags")),
        "loaded": _ollama_models(_get_json(f"{normalized}/api/ps")),
    }


def _require_ollama(host: str) -> str:
    executable = shutil.which("ollama")
    if executable is None:
        raise RuntimeError(
            "Ollama CLI is not installed or not available on PATH. "
            "Install Ollama for Windows before running this benchmark."
        )
    version = _get_json(f"{host.rstrip('/')}/api/version")
    if version is None:
        raise RuntimeError(
            "Ollama CLI exists but the local server is not reachable on "
            f"{host}. Start Ollama and retry."
        )
    return executable


def _pull_model(executable: str, model: str) -> dict[str, Any]:
    started = time.perf_counter()
    result = _run([executable, "pull", model], timeout=3600.0)
    elapsed = time.perf_counter() - started
    if result.returncode != 0:
        raise RuntimeError(
            f"ollama pull {model} failed: {(result.stderr or result.stdout)[-4000:]}"
        )
    return {
        "elapsed_seconds": elapsed,
        "stdout_tail": result.stdout[-2000:],
        "stderr_tail": result.stderr[-2000:],
    }


def _stop_model(executable: str, model: str) -> dict[str, Any]:
    result = _run([executable, "stop", model], timeout=30.0)
    return {
        "returncode": result.returncode,
        "stdout_tail": result.stdout[-1000:],
        "stderr_tail": result.stderr[-1000:],
    }


def _run_benchmark(
    *,
    model: str,
    host: str,
    num_ctx: int,
    repeat: int,
    timeout: float,
    output: Path,
) -> dict[str, Any]:
    command = [
        sys.executable,
        str(BENCHMARK_SCRIPT),
        "--runner",
        "ollama",
        "--model",
        model,
        "--ollama-host",
        host,
        "--num-ctx",
        str(num_ctx),
        "--repeat",
        str(repeat),
        "--timeout",
        str(timeout),
        "--output",
        str(output),
    ]
    started = time.perf_counter()
    result = _run(command, timeout=max(3600.0, timeout * repeat * 20))
    elapsed = time.perf_counter() - started
    if result.returncode != 0:
        raise RuntimeError(
            f"C4/C5 benchmark failed for {model}: "
            f"{(result.stderr or result.stdout)[-8000:]}"
        )
    report = json.loads(output.read_text(encoding="utf-8"))
    if not isinstance(report, dict):
        raise TypeError(f"benchmark report for {model} is not an object")
    return {
        "elapsed_seconds": elapsed,
        "report": report,
    }


def _find_model(
    models: list[dict[str, Any]],
    requested: str,
) -> dict[str, Any] | None:
    normalized = requested.strip().casefold()
    aliases = {normalized, f"{normalized}:latest"}
    for model in models:
        name = str(model.get("name") or "").strip().casefold()
        if name in aliases:
            return model
    return None


def _comparison_row(
    model: str,
    benchmark: dict[str, Any],
    loaded_model: dict[str, Any] | None,
    gpu_after: list[dict[str, Any]],
) -> dict[str, Any]:
    report = benchmark["report"]
    summaries = report.get("summaries")
    summary = summaries[0] if isinstance(summaries, list) and summaries else {}
    gpu = gpu_after[0] if gpu_after else {}
    return {
        "model": model,
        "accuracy_over_covered": summary.get("accuracy_over_covered"),
        "coverage": summary.get("coverage"),
        "unsafe_downgrades": summary.get("unsafe_downgrades"),
        "conservative_escalations": summary.get("conservative_escalations"),
        "latency_ms_p50": summary.get("latency_ms_p50"),
        "latency_ms_p95": summary.get("latency_ms_p95"),
        "input_tokens": summary.get("input_tokens"),
        "output_tokens": summary.get("output_tokens"),
        "api_cost_usd": summary.get("complete_api_cost_usd"),
        "ollama_processor": (
            None if loaded_model is None else loaded_model.get("processor")
        ),
        "ollama_size_vram_bytes": (
            None if loaded_model is None else loaded_model.get("size_vram_bytes")
        ),
        "ollama_context_length": (
            None if loaded_model is None else loaded_model.get("context_length")
        ),
        "gpu_memory_used_mib": gpu.get("memory_used_mib"),
        "gpu_memory_free_mib": gpu.get("memory_free_mib"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Pull and benchmark approved C5 local Ollama models one at a time."
        )
    )
    parser.add_argument(
        "--model",
        action="append",
        default=[],
        help="model to benchmark; may be repeated",
    )
    parser.add_argument("--ollama-host", default=DEFAULT_OLLAMA_HOST)
    parser.add_argument("--num-ctx", type=int, default=4096)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument(
        "--pull",
        action="store_true",
        help="download/update each model before benchmarking",
    )
    parser.add_argument(
        "--allow-jarvis-running",
        action="store_true",
        help=(
            "allow production JARVIS voice runtime to be running; omit for the isolated "
            "baseline"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
    )
    args = parser.parse_args(argv)

    if args.num_ctx <= 0:
        parser.error("--num-ctx must be positive")
    if args.repeat <= 0:
        parser.error("--repeat must be positive")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")

    models = tuple(args.model) or DEFAULT_MODELS
    jarvis_before = _jarvis_processes()
    if jarvis_before and not args.allow_jarvis_running:
        raise RuntimeError(
            "Isolated C5 benchmark requires JARVIS production runtime to be stopped. "
            "Use --allow-jarvis-running only for the later coexistence benchmark."
        )

    executable = _require_ollama(args.ollama_host)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {
        "mode": "coexistence" if args.allow_jarvis_running else "isolated",
        "models": list(models),
        "num_ctx": args.num_ctx,
        "repeat": args.repeat,
        "jarvis_processes_before": jarvis_before,
        "gpu_before": _nvidia_snapshot(),
        "ollama_before": _ollama_state(args.ollama_host),
        "runs": [],
        "comparison": [],
        "cloud_model_api_called": False,
        "production_routing_mutated": False,
    }

    for index, model in enumerate(models, start=1):
        model_entry: dict[str, Any] = {
            "model": model,
            "ordinal": index,
            "pull": None,
            "gpu_before": _nvidia_snapshot(),
            "ollama_before": _ollama_state(args.ollama_host),
        }
        try:
            if args.pull:
                model_entry["pull"] = _pull_model(executable, model)

            benchmark_output = (
                args.output_dir
                / f"{index:02d}-{model.replace(':', '_')}-benchmark.json"
            )
            benchmark = _run_benchmark(
                model=model,
                host=args.ollama_host,
                num_ctx=args.num_ctx,
                repeat=args.repeat,
                timeout=args.timeout,
                output=benchmark_output,
            )
            model_entry["benchmark_output"] = str(benchmark_output)
            model_entry["benchmark_elapsed_seconds"] = benchmark["elapsed_seconds"]
            model_entry["benchmark_summary"] = benchmark["report"].get("summaries")

            ollama_after = _ollama_state(args.ollama_host)
            gpu_after = _nvidia_snapshot()
            model_entry["ollama_after"] = ollama_after
            model_entry["gpu_after"] = gpu_after
            loaded = _find_model(ollama_after["loaded"], model)
            report["comparison"].append(
                _comparison_row(model, benchmark, loaded, gpu_after)
            )
        finally:
            model_entry["unload"] = _stop_model(executable, model)
            time.sleep(1.0)
            model_entry["gpu_after_unload"] = _nvidia_snapshot()
            model_entry["ollama_after_unload"] = _ollama_state(args.ollama_host)
            report["runs"].append(model_entry)

    report["jarvis_processes_after"] = _jarvis_processes()
    report["gpu_after"] = _nvidia_snapshot()
    report["ollama_after"] = _ollama_state(args.ollama_host)
    report["status"] = "PASS"

    output = args.output_dir / "c5-owner-local-benchmark-summary.json"
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
