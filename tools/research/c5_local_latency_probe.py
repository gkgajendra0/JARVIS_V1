"""Short owner-machine latency probe for C5 local-brain candidates.

Measures cold and warm latency for:
- Qwen3.5 4B with thinking enabled;
- Qwen3.5 4B with thinking disabled;
- Phi-4-mini.

This is research scaffolding only. It does not mutate production routing.
"""

from __future__ import annotations

import argparse
import json
import shutil
import statistics
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_HOST = "http://127.0.0.1:11434"


@dataclass(frozen=True, slots=True)
class Profile:
    name: str
    model: str
    think: bool | None


PROFILES = (
    Profile("qwen-thinking-on", "qwen3.5:4b", True),
    Profile("qwen-thinking-off", "qwen3.5:4b", False),
    Profile("phi4-mini", "phi4-mini", None),
)

SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {
            "type": "string",
            "enum": ["local_sufficient", "cloud_required"],
        }
    },
    "required": ["decision"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "You are a bounded JARVIS routing classifier. Return only the requested "
    "structured decision. Do not add prose."
)

USER_PROMPT = (
    "A local deterministic command has already been recognized and requires no "
    "fresh external information. Decide whether local handling is sufficient "
    "or cloud reasoning is required."
)


def _ns_to_ms(value: Any) -> float | None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        return None
    return value / 1_000_000.0


def _post_streaming_json(
    url: str,
    payload: dict[str, Any],
    *,
    timeout: float,
) -> tuple[list[dict[str, Any]], float, float | None, float | None]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    started = time.perf_counter()
    first_any_ms: float | None = None
    first_content_ms: float | None = None
    chunks: list[dict[str, Any]] = []

    with urllib.request.urlopen(request, timeout=timeout) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8").strip()
            if not line:
                continue
            chunk = json.loads(line)
            if not isinstance(chunk, dict):
                continue
            chunks.append(chunk)

            message = chunk.get("message")
            if not isinstance(message, dict):
                continue

            content = message.get("content")
            thinking = message.get("thinking")
            now_ms = (time.perf_counter() - started) * 1000.0

            if first_any_ms is None and (
                (isinstance(content, str) and content)
                or (isinstance(thinking, str) and thinking)
            ):
                first_any_ms = now_ms

            if (
                first_content_ms is None
                and isinstance(content, str)
                and content
            ):
                first_content_ms = now_ms

    wall_ms = (time.perf_counter() - started) * 1000.0
    return chunks, wall_ms, first_any_ms, first_content_ms


def _nvidia_snapshot() -> dict[str, Any]:
    executable = shutil.which("nvidia-smi")
    if executable is None:
        return {}
    result = subprocess.run(
        [
            executable,
            "--query-gpu=memory.total,memory.used,memory.free,utilization.gpu",
            "--format=csv,noheader,nounits",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=15.0,
    )
    if result.returncode != 0:
        return {}
    first = result.stdout.strip().splitlines()
    if not first:
        return {}
    parts = [part.strip() for part in first[0].split(",")]
    if len(parts) != 4:
        return {}
    try:
        return {
            "memory_total_mib": int(parts[0]),
            "memory_used_mib": int(parts[1]),
            "memory_free_mib": int(parts[2]),
            "utilization_gpu_percent": int(parts[3]),
        }
    except ValueError:
        return {}


def _ollama_loaded(host: str, model: str) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(
            f"{host.rstrip('/')}/api/ps",
            timeout=5.0,
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None

    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        return None

    requested = model.casefold()
    aliases = {requested, f"{requested}:latest"}
    for item in models:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("model") or "").casefold()
        if name in aliases:
            return {
                "name": item.get("name") or item.get("model"),
                "size_vram_bytes": item.get("size_vram"),
                "context_length": item.get("context_length"),
                "processor": item.get("processor"),
            }
    return None


def _stop_model(model: str) -> None:
    executable = shutil.which("ollama")
    if executable is None:
        raise RuntimeError("ollama CLI is not available on PATH")
    subprocess.run(
        [executable, "stop", model],
        check=False,
        capture_output=True,
        text=True,
        timeout=30.0,
    )
    time.sleep(1.0)


def _run_request(
    *,
    profile: Profile,
    host: str,
    num_ctx: int,
    num_predict: int,
    timeout: float,
    run_kind: str,
    ordinal: int,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": profile.model,
        "stream": True,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_PROMPT},
        ],
        "format": SCHEMA,
        "options": {
            "temperature": 0,
            "num_ctx": num_ctx,
            "num_predict": num_predict,
        },
        "keep_alive": "5m",
    }
    if profile.think is not None:
        payload["think"] = profile.think

    chunks, wall_ms, first_any_ms, first_content_ms = _post_streaming_json(
        f"{host.rstrip('/')}/api/chat",
        payload,
        timeout=timeout,
    )
    if not chunks:
        raise RuntimeError(f"{profile.name}: Ollama returned no streaming chunks")

    content_parts: list[str] = []
    thinking_parts: list[str] = []
    for chunk in chunks:
        message = chunk.get("message")
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        thinking = message.get("thinking")
        if isinstance(content, str):
            content_parts.append(content)
        if isinstance(thinking, str):
            thinking_parts.append(thinking)

    final = chunks[-1]
    content = "".join(content_parts)
    thinking = "".join(thinking_parts)

    structured_valid = False
    decision = None
    try:
        decoded = json.loads(content)
        if isinstance(decoded, dict):
            decision = decoded.get("decision")
            structured_valid = decision in {"local_sufficient", "cloud_required"}
    except json.JSONDecodeError:
        pass

    eval_count = final.get("eval_count")
    eval_duration = final.get("eval_duration")
    eval_tokens_per_second = None
    if (
        isinstance(eval_count, int)
        and isinstance(eval_duration, int)
        and eval_duration > 0
    ):
        eval_tokens_per_second = eval_count / (eval_duration / 1_000_000_000.0)

    return {
        "profile": profile.name,
        "model": profile.model,
        "think": profile.think,
        "run_kind": run_kind,
        "ordinal": ordinal,
        "wall_ms": wall_ms,
        "first_any_token_ms": first_any_ms,
        "first_content_token_ms": first_content_ms,
        "total_duration_ms": _ns_to_ms(final.get("total_duration")),
        "load_duration_ms": _ns_to_ms(final.get("load_duration")),
        "prompt_eval_duration_ms": _ns_to_ms(final.get("prompt_eval_duration")),
        "eval_duration_ms": _ns_to_ms(eval_duration),
        "prompt_eval_count": final.get("prompt_eval_count"),
        "eval_count": eval_count,
        "eval_tokens_per_second": eval_tokens_per_second,
        "done_reason": final.get("done_reason"),
        "content_chars": len(content),
        "thinking_chars": len(thinking),
        "structured_valid": structured_valid,
        "decision": decision,
        "loaded_model": _ollama_loaded(host, profile.model),
        "gpu_after_request": _nvidia_snapshot(),
    }


def _median(values: list[float | None]) -> float | None:
    present = [float(value) for value in values if value is not None]
    return statistics.median(present) if present else None


def _summarize_profile(
    profile: Profile,
    runs: list[dict[str, Any]],
) -> dict[str, Any]:
    cold = next((run for run in runs if run["run_kind"] == "cold"), None)
    warm = [run for run in runs if run["run_kind"] == "warm"]
    return {
        "profile": profile.name,
        "model": profile.model,
        "think": profile.think,
        "cold_wall_ms": None if cold is None else cold.get("wall_ms"),
        "cold_first_content_ms": (
            None if cold is None else cold.get("first_content_token_ms")
        ),
        "cold_load_ms": None if cold is None else cold.get("load_duration_ms"),
        "warm_wall_ms_median": _median([run.get("wall_ms") for run in warm]),
        "warm_first_content_ms_median": _median(
            [run.get("first_content_token_ms") for run in warm]
        ),
        "warm_eval_tokens_per_second_median": _median(
            [run.get("eval_tokens_per_second") for run in warm]
        ),
        "structured_valid_runs": sum(
            1 for run in runs if run.get("structured_valid") is True
        ),
        "run_count": len(runs),
        "max_thinking_chars": max(
            (int(run.get("thinking_chars") or 0) for run in runs),
            default=0,
        ),
        "peak_gpu_used_mib": max(
            (
                int((run.get("gpu_after_request") or {}).get("memory_used_mib") or 0)
                for run in runs
            ),
            default=0,
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a short C5 local-model cold/warm latency probe."
    )
    parser.add_argument("--ollama-host", default=DEFAULT_HOST)
    parser.add_argument("--num-ctx", type=int, default=4096)
    parser.add_argument("--num-predict", type=int, default=96)
    parser.add_argument("--warm-repeats", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--profile",
        action="append",
        choices=tuple(profile.name for profile in PROFILES),
        default=[],
    )
    args = parser.parse_args(argv)

    if args.num_ctx <= 0 or args.num_predict <= 0 or args.warm_repeats <= 0:
        parser.error("num-ctx, num-predict and warm-repeats must be positive")
    if args.timeout <= 0:
        parser.error("timeout must be positive")

    selected_names = set(args.profile)
    profiles = tuple(
        profile
        for profile in PROFILES
        if not selected_names or profile.name in selected_names
    )

    report: dict[str, Any] = {
        "num_ctx": args.num_ctx,
        "num_predict": args.num_predict,
        "warm_repeats": args.warm_repeats,
        "gpu_before": _nvidia_snapshot(),
        "profiles": [],
        "comparison": [],
    }

    for profile_index, profile in enumerate(profiles, start=1):
        print(
            f"[latency] Profile {profile_index}/{len(profiles)}: {profile.name}",
            flush=True,
        )
        _stop_model(profile.model)
        runs: list[dict[str, Any]] = []

        print("[latency] cold request...", flush=True)
        cold = _run_request(
            profile=profile,
            host=args.ollama_host,
            num_ctx=args.num_ctx,
            num_predict=args.num_predict,
            timeout=args.timeout,
            run_kind="cold",
            ordinal=1,
        )
        runs.append(cold)
        print(
            f"[latency] cold wall={cold['wall_ms']:.0f} ms "
            f"first_content={cold['first_content_token_ms']} ms "
            f"eval_tps={cold['eval_tokens_per_second']}",
            flush=True,
        )

        for index in range(1, args.warm_repeats + 1):
            print(
                f"[latency] warm request {index}/{args.warm_repeats}...",
                flush=True,
            )
            warm = _run_request(
                profile=profile,
                host=args.ollama_host,
                num_ctx=args.num_ctx,
                num_predict=args.num_predict,
                timeout=args.timeout,
                run_kind="warm",
                ordinal=index,
            )
            runs.append(warm)
            print(
                f"[latency] warm wall={warm['wall_ms']:.0f} ms "
                f"first_content={warm['first_content_token_ms']} ms "
                f"eval_tps={warm['eval_tokens_per_second']}",
                flush=True,
            )

        loaded_before_unload = _ollama_loaded(args.ollama_host, profile.model)
        gpu_before_unload = _nvidia_snapshot()
        _stop_model(profile.model)
        gpu_after_unload = _nvidia_snapshot()

        entry = {
            "profile": profile.name,
            "model": profile.model,
            "think": profile.think,
            "runs": runs,
            "loaded_before_unload": loaded_before_unload,
            "gpu_before_unload": gpu_before_unload,
            "gpu_after_unload": gpu_after_unload,
        }
        report["profiles"].append(entry)
        report["comparison"].append(_summarize_profile(profile, runs))

    report["gpu_after"] = _nvidia_snapshot()
    report["status"] = "PASS"

    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")

    print("\n=== C5 LOCAL LATENCY COMPARISON ===")
    for row in report["comparison"]:
        print(
            f"{row['profile']}: "
            f"cold={row['cold_wall_ms']:.0f}ms, "
            f"warm_median={row['warm_wall_ms_median']:.0f}ms, "
            f"warm_first_content={row['warm_first_content_ms_median']}ms, "
            f"eval_tps={row['warm_eval_tokens_per_second_median']}, "
            f"valid={row['structured_valid_runs']}/{row['run_count']}, "
            f"peak_gpu={row['peak_gpu_used_mib']}MiB"
        )

    if args.output is not None:
        print(f"\nFull report: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
