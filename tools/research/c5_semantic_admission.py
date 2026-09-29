"""Final C5 semantic-admission comparison for production-like local profiles.

Compares:
- Phi-4-mini in its normal Ollama mode;
- Qwen3.5 4B with thinking explicitly disabled.

Uses the frozen C4/C5 corpus and scorer. This tool does not mutate production routing.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BENCHMARK = _REPO_ROOT / "tools" / "research" / "c4_c5_benchmark.py"
_CASES = _REPO_ROOT / "tools" / "research" / "c4_c5_benchmark_cases.json"


@dataclass(frozen=True, slots=True)
class AdmissionProfile:
    name: str
    model: str
    ollama_think: str


PROFILES = (
    AdmissionProfile("phi4-mini-default", "phi4-mini", "default"),
    AdmissionProfile("qwen3.5-4b-think-off", "qwen3.5:4b", "off"),
)


def _load_benchmark_module():
    name = "jarvis_c5_semantic_admission_benchmark_module"
    spec = importlib.util.spec_from_file_location(name, _BENCHMARK)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load C4/C5 benchmark module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


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


def _run_profile(
    profile: AdmissionProfile,
    *,
    output_dir: Path,
    num_ctx: int,
    num_predict: int,
    timeout: float,
) -> dict[str, Any]:
    output = output_dir / f"{profile.name}.json"
    command = [
        sys.executable,
        str(_BENCHMARK),
        "--runner",
        "ollama",
        "--model",
        profile.model,
        "--ollama-think",
        profile.ollama_think,
        "--num-ctx",
        str(num_ctx),
        "--num-predict",
        str(num_predict),
        "--repeat",
        "1",
        "--timeout",
        str(timeout),
        "--output",
        str(output),
        "--quiet",
    ]

    print(
        f"[semantic] {profile.name}: model={profile.model} "
        f"think={profile.ollama_think}",
        flush=True,
    )
    started = time.perf_counter()
    result = subprocess.run(
        command,
        check=False,
        timeout=max(3600.0, timeout * 20),
        shell=False,
    )
    elapsed = time.perf_counter() - started
    if result.returncode != 0:
        raise RuntimeError(
            f"Semantic benchmark failed for {profile.name} "
            f"with return code {result.returncode}"
        )
    report = json.loads(output.read_text(encoding="utf-8"))
    if not isinstance(report, dict):
        raise TypeError(f"{profile.name}: benchmark report is not an object")
    return {
        "elapsed_seconds": elapsed,
        "output": str(output),
        "report": report,
    }


def _task_class_for_case(case: Any) -> str:
    question = next(
        (item for item in case.questions if item.name == "task_class"),
        None,
    )
    if question is None:
        return "unknown"
    return question.expected


def _task_class_summaries(
    module: Any,
    cases: tuple[Any, ...],
    raw_results: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[Any]] = {}
    for case in cases:
        groups.setdefault(_task_class_for_case(case), []).append(case)

    by_case_id: dict[str, list[dict[str, Any]]] = {}
    for result in raw_results:
        by_case_id.setdefault(str(result["case_id"]), []).append(result)

    summaries: dict[str, dict[str, Any]] = {}
    for task_class, group_cases in sorted(groups.items()):
        group_results: list[dict[str, Any]] = []
        for case in group_cases:
            group_results.extend(by_case_id.get(case.case_id, []))
        score = module._score(
            tuple(group_cases),
            group_results,
            confidence_threshold=0.0,
        )
        summaries[task_class] = {
            "case_count": len(group_cases),
            "accuracy_over_covered": score["accuracy_over_covered"],
            "coverage": score["coverage"],
            "structured_output_failures": score["structured_output_failures"],
            "unsafe_downgrades": score["unsafe_downgrades"],
            "conservative_escalations": score["conservative_escalations"],
            "latency_ms_p50": score["latency_ms_p50"],
            "latency_ms_p95": score["latency_ms_p95"],
            "questions": score["questions"],
            "exact": score["exact"],
        }
    return summaries


def _clean_task_classes(
    summaries: dict[str, dict[str, Any]],
) -> list[str]:
    clean: list[str] = []
    for task_class, summary in summaries.items():
        if (
            summary["coverage"] == 1.0
            and summary["accuracy_over_covered"] == 1.0
            and summary["structured_output_failures"] == 0
            and summary["unsafe_downgrades"] == 0
        ):
            clean.append(task_class)
    return clean


def _comparison_row(
    profile: AdmissionProfile,
    run: dict[str, Any],
    task_classes: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    report = run["report"]
    summaries = report.get("summaries")
    summary = summaries[0] if isinstance(summaries, list) and summaries else {}
    return {
        "profile": profile.name,
        "model": profile.model,
        "ollama_think": profile.ollama_think,
        "accuracy_over_covered": summary.get("accuracy_over_covered"),
        "coverage": summary.get("coverage"),
        "structured_output_failures": summary.get("structured_output_failures"),
        "unsafe_downgrades": summary.get("unsafe_downgrades"),
        "conservative_escalations": summary.get("conservative_escalations"),
        "latency_ms_p50": summary.get("latency_ms_p50"),
        "latency_ms_p95": summary.get("latency_ms_p95"),
        "input_tokens": summary.get("input_tokens"),
        "output_tokens": summary.get("output_tokens"),
        "clean_task_classes": _clean_task_classes(task_classes),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare final production-like Tier-A C5 semantic profiles."
    )
    parser.add_argument("--num-ctx", type=int, default=4096)
    parser.add_argument("--num-predict", type=int, default=256)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.num_ctx <= 0:
        parser.error("--num-ctx must be positive")
    if args.num_predict <= 0:
        parser.error("--num-predict must be positive")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")

    module = _load_benchmark_module()
    suite, cases = module._load_cases(_CASES)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    final: dict[str, Any] = {
        "suite": suite,
        "num_ctx": args.num_ctx,
        "num_predict": args.num_predict,
        "profiles": [],
        "comparison": [],
        "cloud_model_api_called": False,
        "production_routing_mutated": False,
    }

    for index, profile in enumerate(PROFILES, start=1):
        print(
            f"[semantic] Profile {index}/{len(PROFILES)}: {profile.name}",
            flush=True,
        )
        _stop_model(profile.model)
        try:
            run = _run_profile(
                profile,
                output_dir=args.output_dir,
                num_ctx=args.num_ctx,
                num_predict=args.num_predict,
                timeout=args.timeout,
            )
            raw_results = run["report"].get("results")
            if not isinstance(raw_results, list):
                raise TypeError(f"{profile.name}: results are missing")
            task_classes = _task_class_summaries(module, cases, raw_results)
            entry = {
                "profile": profile.name,
                "model": profile.model,
                "ollama_think": profile.ollama_think,
                "elapsed_seconds": run["elapsed_seconds"],
                "benchmark_output": run["output"],
                "overall": run["report"].get("summaries", [None])[0],
                "task_classes": task_classes,
            }
            final["profiles"].append(entry)
            final["comparison"].append(_comparison_row(profile, run, task_classes))
        finally:
            print(f"[semantic] Unloading {profile.model}...", flush=True)
            _stop_model(profile.model)

    final["status"] = "PASS"
    output = args.output_dir / "c5-semantic-admission-summary.json"
    output.write_text(
        json.dumps(final, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print("\n=== C5 SEMANTIC ADMISSION COMPARISON ===")
    for row in final["comparison"]:
        print(
            f"{row['profile']}: "
            f"accuracy={row['accuracy_over_covered']}, "
            f"coverage={row['coverage']}, "
            f"structured_failures={row['structured_output_failures']}, "
            f"unsafe={row['unsafe_downgrades']}, "
            f"p50={row['latency_ms_p50']}ms, "
            f"clean_classes={','.join(row['clean_task_classes']) or 'none'}"
        )
    print(f"\nFull report: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
