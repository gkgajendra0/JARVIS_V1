"""Non-destructive owner-machine preflight for C5 local-brain benchmarking."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import psutil

DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"


def _run(
    command: list[str],
    *,
    timeout: float = 15.0,
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


def _get_json(url: str, *, timeout: float = 3.0) -> dict[str, Any] | None:
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _nvidia_snapshot() -> list[dict[str, Any]]:
    executable = shutil.which("nvidia-smi")
    if executable is None:
        return []
    result = _run(
        [
            executable,
            "--query-gpu=index,name,driver_version,memory.total,memory.used,"
            "memory.free,utilization.gpu",
            "--format=csv,noheader,nounits",
        ]
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
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return matches


def _ollama_cli_version(executable: str | None) -> str | None:
    if executable is None:
        return None
    result = _run([executable, "--version"])
    if result.returncode != 0:
        return None
    combined = (result.stdout or result.stderr).strip()
    return combined or None


def _ollama_models(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    raw = payload.get("models")
    if not isinstance(raw, list):
        return []
    result: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        details = item.get("details") if isinstance(item.get("details"), dict) else {}
        result.append(
            {
                "name": item.get("name") or item.get("model"),
                "size_bytes": item.get("size"),
                "size_vram_bytes": item.get("size_vram"),
                "context_length": item.get("context_length"),
                "parameter_size": details.get("parameter_size"),
                "quantization_level": details.get("quantization_level"),
                "family": details.get("family"),
                "processor": item.get("processor"),
                "expires_at": item.get("expires_at"),
            }
        )
    return result


def build_report(*, ollama_host: str) -> dict[str, Any]:
    host = ollama_host.rstrip("/")
    executable = shutil.which("ollama")
    version_payload = _get_json(f"{host}/api/version")
    tags_payload = _get_json(f"{host}/api/tags")
    ps_payload = _get_json(f"{host}/api/ps")

    return {
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "jarvis_processes": _jarvis_processes(),
        "gpu": _nvidia_snapshot(),
        "ollama": {
            "executable": executable,
            "cli_version": _ollama_cli_version(executable),
            "host": host,
            "server_reachable": version_payload is not None,
            "server_version": (
                version_payload.get("version")
                if isinstance(version_payload, dict)
                else None
            ),
            "installed_models": _ollama_models(tags_payload),
            "loaded_models": _ollama_models(ps_payload),
        },
        "ready_for_model_pull": (
            executable is not None
            and version_payload is not None
            and bool(_nvidia_snapshot())
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect owner-machine readiness for C5 local-brain benchmarks."
    )
    parser.add_argument("--ollama-host", default=DEFAULT_OLLAMA_HOST)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--require-ready",
        action="store_true",
        help="return nonzero unless Ollama server and NVIDIA GPU are visible",
    )
    args = parser.parse_args(argv)

    report = build_report(ollama_host=args.ollama_host)
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    print(encoded, end="")
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")

    if args.require_ready and not report["ready_for_model_pull"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
