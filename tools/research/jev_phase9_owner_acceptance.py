"""Owner-machine admission harness for bounded Phase-9 JEV decisions.

The harness reuses the generic frozen benchmark runner but fixes the corpus to the
only live JEV decision family currently admitted by production JARVIS:
capability_acquisition.candidate_selection.

By default it only benchmarks and reports.  With --apply it persists the selected
benchmark evidence and bounded JEV runtime settings only after admission passes.
The JEV credential remains environment-only and is never written to machine config.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from jarvis.capability_acquisition.jev import _validate_jev_benchmark_report
from jarvis.machine_config import (
    default_machine_config_path,
    load_machine_settings,
    save_machine_settings,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BENCHMARK = Path(__file__).with_name("c4_c5_benchmark.py")
_CASES = Path(__file__).with_name("jev_phase9_candidate_benchmark_cases.json")
_DEFAULT_OUTPUT = (
    Path(os.getenv("LOCALAPPDATA", str(Path.home())))
    / "JARVIS"
    / "acceptance"
    / "jev-phase9-candidate-benchmark.json"
)
_DEFAULT_MODEL = "jev-latest"
_DEFAULT_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
_DEFAULT_THRESHOLDS = (0.70, 0.75, 0.80, 0.85, 0.90, 0.95)

_SETTING_ENABLED = "JARVIS_JEV_BOUNDED_DECISIONS_ENABLED"
_SETTING_ADMITTED = "JARVIS_JEV_BENCHMARK_ADMITTED"
_SETTING_REPORT = "JARVIS_JEV_BENCHMARK_REPORT_PATH"
_SETTING_MODEL = "JARVIS_JEV_MODEL"
_SETTING_ENDPOINT = "JARVIS_JEV_ENDPOINT"
_SETTING_THRESHOLD = "JARVIS_JEV_MIN_CONFIDENCE"


def _load_benchmark_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "jarvis_jev_phase9_benchmark",
        _BENCHMARK,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load JARVIS benchmark runner")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _benchmark_argv(
    *,
    model: str,
    endpoint: str,
    api_key_env: str,
    output: Path,
    repeat: int,
    timeout: float,
    thresholds: tuple[float, ...],
) -> list[str]:
    argv = [
        "--cases",
        str(_CASES),
        "--runner",
        "jev",
        "--model",
        model,
        "--jev-endpoint",
        endpoint,
        "--jev-api-key-env",
        api_key_env,
        "--repeat",
        str(repeat),
        "--timeout",
        str(timeout),
        "--output",
        str(output),
        "--quiet",
    ]
    for threshold in thresholds:
        argv.extend(("--confidence-threshold", str(threshold)))
    return argv


def _load_report(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("JEV Phase-9 benchmark report is unreadable") from exc
    if not isinstance(payload, dict):
        raise TypeError("JEV Phase-9 benchmark report must be a JSON object")
    return payload


def _select_admitted_threshold(report: dict[str, Any]) -> float:
    summaries = report.get("summaries")
    if not isinstance(summaries, list) or not summaries:
        raise RuntimeError("JEV Phase-9 benchmark report has no threshold summaries")

    eligible: list[dict[str, Any]] = []
    for summary in summaries:
        if not isinstance(summary, dict):
            continue
        if int(summary.get("structured_output_failures") or 0) != 0:
            continue
        if int(summary.get("unsafe_downgrades") or 0) != 0:
            continue
        if int(summary.get("covered") or 0) <= 0:
            continue
        threshold = summary.get("confidence_threshold")
        if not isinstance(threshold, (int, float)):
            continue
        eligible.append(summary)

    if not eligible:
        raise RuntimeError(
            "JEV Phase-9 admission failed: no tested confidence threshold had "
            "zero unsafe downgrades, zero structured-output failures, and "
            "non-zero decision coverage"
        )

    # Prefer maximum decision coverage first.  If several tested thresholds cover
    # the same number of decisions safely, choose the higher threshold as the more
    # conservative production gate.
    selected = max(
        eligible,
        key=lambda item: (
            int(item.get("covered") or 0),
            float(item["confidence_threshold"]),
        ),
    )
    return float(selected["confidence_threshold"])


def _machine_before() -> dict[str, Any]:
    path = default_machine_config_path()
    settings = load_machine_settings(path)
    return {
        "path": str(path),
        "jev_bounded_decisions_enabled": settings.get(_SETTING_ENABLED),
        "jev_benchmark_admitted": settings.get(_SETTING_ADMITTED),
        "jev_benchmark_report_path": settings.get(_SETTING_REPORT),
        "jev_model": settings.get(_SETTING_MODEL),
        "jev_endpoint": settings.get(_SETTING_ENDPOINT),
        "jev_min_confidence": settings.get(_SETTING_THRESHOLD),
    }


def _apply_machine_settings(
    *,
    report_path: Path,
    model: str,
    endpoint: str,
    threshold: float,
) -> dict[str, Any]:
    path = default_machine_config_path()
    settings = load_machine_settings(path)
    settings[_SETTING_ENABLED] = True
    settings[_SETTING_ADMITTED] = True
    settings[_SETTING_REPORT] = str(report_path.resolve())
    settings[_SETTING_MODEL] = model
    settings[_SETTING_ENDPOINT] = endpoint
    settings[_SETTING_THRESHOLD] = threshold
    save_machine_settings(settings, path)

    reloaded = load_machine_settings(path)
    return {
        "path": str(path),
        "jev_bounded_decisions_enabled": reloaded.get(_SETTING_ENABLED),
        "jev_benchmark_admitted": reloaded.get(_SETTING_ADMITTED),
        "jev_benchmark_report_path": reloaded.get(_SETTING_REPORT),
        "jev_model": reloaded.get(_SETTING_MODEL),
        "jev_endpoint": reloaded.get(_SETTING_ENDPOINT),
        "jev_min_confidence": reloaded.get(_SETTING_THRESHOLD),
    }


def _run(
    *,
    model: str,
    endpoint: str,
    api_key_env: str,
    output: Path,
    repeat: int,
    timeout: float,
    thresholds: tuple[float, ...],
    apply: bool,
) -> dict[str, Any]:
    key_name = api_key_env.strip()
    if not key_name:
        raise ValueError("api_key_env must not be empty")
    if not os.getenv(key_name, "").strip():
        raise RuntimeError(
            f"JEV credential missing from environment variable {key_name}"
        )

    before = _machine_before()
    output = output.expanduser().resolve()
    module = _load_benchmark_module()
    rc = module.main(
        _benchmark_argv(
            model=model,
            endpoint=endpoint,
            api_key_env=key_name,
            output=output,
            repeat=repeat,
            timeout=timeout,
            thresholds=thresholds,
        )
    )
    if rc != 0:
        raise RuntimeError(f"JEV benchmark runner exited with status {rc}")

    report = _load_report(output)
    threshold = _select_admitted_threshold(report)
    _validate_jev_benchmark_report(
        report_path=str(output),
        minimum_confidence=threshold,
        model=model,
    )

    after = before
    if apply:
        after = _apply_machine_settings(
            report_path=output,
            model=model,
            endpoint=endpoint,
            threshold=threshold,
        )

    selected = next(
        item
        for item in report["summaries"]
        if float(item["confidence_threshold"]) == threshold
    )
    return {
        "status": "PASS",
        "decision_family": "capability_acquisition.candidate_selection",
        "suite": report.get("suite"),
        "model": model,
        "case_count": report.get("case_count"),
        "repeat": report.get("repeat"),
        "selected_confidence_threshold": threshold,
        "covered": selected.get("covered"),
        "abstained": selected.get("abstained"),
        "unsafe_downgrades": selected.get("unsafe_downgrades"),
        "structured_output_failures": selected.get("structured_output_failures"),
        "benchmark_report_path": str(output),
        "machine_before": before,
        "machine_after": after,
        "machine_settings_applied": apply,
        "credential_persisted": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark and optionally enable JARVIS's bounded Phase-9 JEV "
            "candidate-selection advisor."
        )
    )
    parser.add_argument("--model", default=_DEFAULT_MODEL)
    parser.add_argument("--jev-endpoint", default=_DEFAULT_ENDPOINT)
    parser.add_argument("--jev-api-key-env", default="JEV_API_KEY")
    parser.add_argument("--output", type=Path, default=_DEFAULT_OUTPUT)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument(
        "--confidence-threshold",
        type=float,
        action="append",
        default=[],
        help=(
            "tested threshold; may be repeated. Defaults to the bounded "
            "0.70/0.75/0.80/0.85/0.90/0.95 grid."
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="persist JEV runtime settings only after the benchmark passes",
    )
    args = parser.parse_args(argv)

    if args.repeat <= 0:
        parser.error("--repeat must be positive")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    thresholds = tuple(args.confidence_threshold) or _DEFAULT_THRESHOLDS
    for threshold in thresholds:
        if not 0.0 < threshold <= 1.0:
            parser.error("--confidence-threshold must be in (0, 1]")

    try:
        report = _run(
            model=args.model.strip(),
            endpoint=args.jev_endpoint.strip(),
            api_key_env=args.jev_api_key_env,
            output=args.output,
            repeat=args.repeat,
            timeout=args.timeout,
            thresholds=thresholds,
            apply=args.apply,
        )
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001 - owner acceptance boundary
        print(
            json.dumps(
                {
                    "status": "FAIL",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
