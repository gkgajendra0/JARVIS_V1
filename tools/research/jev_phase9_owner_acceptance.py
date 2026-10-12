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
import shutil
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
        if float(summary.get("coverage") or 0.0) != 1.0:
            continue
        if float(summary.get("accuracy_over_covered") or 0.0) != 1.0:
            continue
        threshold = summary.get("confidence_threshold")
        if not isinstance(threshold, (int, float)):
            continue
        eligible.append(summary)

    if not eligible:
        raise RuntimeError(
            "JEV Phase-9 admission failed: no tested confidence threshold had "
            "zero unsafe downgrades, zero structured-output failures, "
            "full coverage, and perfect covered accuracy"
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
    settings[_SETTING_ENABLED] = "true"
    settings[_SETTING_ADMITTED] = "true"
    settings[_SETTING_REPORT] = str(report_path.resolve())
    settings[_SETTING_MODEL] = model
    settings[_SETTING_ENDPOINT] = endpoint
    settings[_SETTING_THRESHOLD] = f"{threshold:.2f}"
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


def _validate_owner_benchmark_depth(report: dict[str, Any]) -> None:
    repeat = report.get("repeat")
    case_count = report.get("case_count")
    results = report.get("results")
    if not isinstance(repeat, int) or isinstance(repeat, bool) or repeat < 3:
        raise RuntimeError("JEV owner admission requires at least 3 benchmark repeats")
    if case_count != 8:
        raise RuntimeError("JEV owner admission requires all 8 Phase-9 cases")
    if not isinstance(results, list) or len(results) != case_count * repeat:
        raise RuntimeError(
            "JEV owner admission report does not contain every case/repetition result"
        )

    corpus = json.loads(_CASES.read_text(encoding="utf-8"))
    raw_cases = corpus.get("cases") if isinstance(corpus, dict) else None
    if not isinstance(raw_cases, list) or len(raw_cases) != case_count:
        raise RuntimeError("JEV Phase-9 frozen corpus is unreadable or incomplete")
    expected_case_ids = {
        str(item.get("id") or "").strip()
        for item in raw_cases
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }
    if len(expected_case_ids) != case_count:
        raise RuntimeError("JEV Phase-9 frozen corpus case identities are invalid")

    observed: set[tuple[str, int]] = set()
    for item in results:
        if not isinstance(item, dict):
            raise TypeError("JEV owner admission result entry is invalid")
        case_id = str(item.get("case_id") or "").strip()
        repetition = item.get("repetition")
        if case_id not in expected_case_ids:
            raise RuntimeError("JEV owner admission report contains an unknown case")
        if (
            not isinstance(repetition, int)
            or isinstance(repetition, bool)
            or not 1 <= repetition <= repeat
        ):
            raise RuntimeError(
                "JEV owner admission report contains an invalid repetition"
            )
        key = (case_id, repetition)
        if key in observed:
            raise RuntimeError(
                "JEV owner admission report duplicates a case/repetition"
            )
        observed.add(key)

    expected = {
        (case_id, repetition)
        for case_id in expected_case_ids
        for repetition in range(1, repeat + 1)
    }
    if observed != expected:
        raise RuntimeError(
            "JEV owner admission report does not cover the exact case/repetition matrix"
        )


def _finalize_report_admission(
    *,
    source_report: Path,
    durable_output: Path,
    model: str,
    endpoint: str,
    apply: bool,
) -> dict[str, Any]:
    source = source_report.expanduser().resolve()
    report = _load_report(source)
    _validate_owner_benchmark_depth(report)
    threshold = _select_admitted_threshold(report)
    _validate_jev_benchmark_report(
        report_path=str(source),
        minimum_confidence=threshold,
        model=model,
    )

    durable = durable_output.expanduser().resolve()
    if source != durable:
        durable.parent.mkdir(parents=True, exist_ok=True)
        temporary = durable.with_suffix(durable.suffix + ".tmp")
        shutil.copyfile(source, temporary)
        os.replace(temporary, durable)
    else:
        durable.parent.mkdir(parents=True, exist_ok=True)

    # Re-read and revalidate the exact durable bytes before machine admission.
    durable_report = _load_report(durable)
    _validate_owner_benchmark_depth(durable_report)
    durable_threshold = _select_admitted_threshold(durable_report)
    if durable_threshold != threshold:
        raise RuntimeError("durable JEV benchmark threshold changed during persistence")
    _validate_jev_benchmark_report(
        report_path=str(durable),
        minimum_confidence=durable_threshold,
        model=model,
    )

    before = _machine_before()
    after = before
    if apply:
        after = _apply_machine_settings(
            report_path=durable,
            model=model,
            endpoint=endpoint,
            threshold=durable_threshold,
        )

    selected = next(
        item
        for item in durable_report["summaries"]
        if float(item["confidence_threshold"]) == durable_threshold
    )
    return {
        "status": "PASS",
        "decision_family": "capability_acquisition.candidate_selection",
        "suite": durable_report.get("suite"),
        "model": model,
        "case_count": durable_report.get("case_count"),
        "repeat": durable_report.get("repeat"),
        "selected_confidence_threshold": durable_threshold,
        "coverage": selected.get("coverage"),
        "accuracy_over_covered": selected.get("accuracy_over_covered"),
        "covered": selected.get("covered"),
        "abstained": selected.get("abstained"),
        "unsafe_downgrades": selected.get("unsafe_downgrades"),
        "structured_output_failures": selected.get("structured_output_failures"),
        "benchmark_report_path": str(durable),
        "machine_before": before,
        "machine_after": after,
        "machine_settings_applied": apply,
        "credential_persisted": False,
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

    return _finalize_report_admission(
        source_report=output,
        durable_output=output,
        model=model,
        endpoint=endpoint,
        apply=apply,
    )


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
    parser.add_argument(
        "--existing-report",
        type=Path,
        help=(
            "reuse an already-produced Phase-9 JEV benchmark report instead of "
            "calling JEV again; the report is revalidated and copied to --output"
        ),
    )
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
        if args.existing_report is not None:
            report = _finalize_report_admission(
                source_report=args.existing_report,
                durable_output=args.output,
                model=args.model.strip(),
                endpoint=args.jev_endpoint.strip(),
                apply=args.apply,
            )
        else:
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
