import importlib.util
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_TOOL = _REPO_ROOT / "tools" / "research" / "jev_phase9_owner_acceptance.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "jarvis_test_jev_phase9_owner_acceptance",
        _TOOL,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load JEV Phase-9 owner acceptance module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_phase9_owner_acceptance_uses_dedicated_corpus_and_all_thresholds(
    tmp_path: Path,
) -> None:
    module = _load_module()
    argv = module._benchmark_argv(
        model="jev-test",
        endpoint="https://example.invalid/jev",
        api_key_env="JEV_TEST_KEY",
        output=tmp_path / "report.json",
        repeat=3,
        timeout=42.0,
        thresholds=(0.7, 0.85, 0.95),
    )

    assert argv[argv.index("--cases") + 1].endswith(
        "jev_phase9_candidate_benchmark_cases.json"
    )
    assert argv[argv.index("--runner") + 1] == "jev"
    assert argv[argv.index("--model") + 1] == "jev-test"
    assert argv.count("--confidence-threshold") == 3
    assert "--quiet" in argv


def test_phase9_threshold_selection_maximizes_safe_coverage_then_confidence() -> None:
    module = _load_module()
    report = {
        "summaries": [
            {
                "confidence_threshold": 0.70,
                "covered": 8,
                "unsafe_downgrades": 1,
                "structured_output_failures": 0,
            },
            {
                "confidence_threshold": 0.80,
                "covered": 7,
                "unsafe_downgrades": 0,
                "structured_output_failures": 0,
            },
            {
                "confidence_threshold": 0.85,
                "covered": 7,
                "unsafe_downgrades": 0,
                "structured_output_failures": 0,
            },
            {
                "confidence_threshold": 0.90,
                "covered": 5,
                "unsafe_downgrades": 0,
                "structured_output_failures": 0,
            },
        ]
    }

    assert module._select_admitted_threshold(report) == pytest.approx(0.85)


def test_phase9_threshold_selection_rejects_no_safe_coverage() -> None:
    module = _load_module()
    report = {
        "summaries": [
            {
                "confidence_threshold": 0.80,
                "covered": 8,
                "unsafe_downgrades": 1,
                "structured_output_failures": 0,
            },
            {
                "confidence_threshold": 0.90,
                "covered": 0,
                "unsafe_downgrades": 0,
                "structured_output_failures": 0,
            },
            {
                "confidence_threshold": 0.95,
                "covered": 4,
                "unsafe_downgrades": 0,
                "structured_output_failures": 1,
            },
        ]
    }

    with pytest.raises(RuntimeError, match="admission failed"):
        module._select_admitted_threshold(report)


def test_phase9_owner_acceptance_requires_environment_credential(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    monkeypatch.delenv("JEV_MISSING_KEY", raising=False)

    with pytest.raises(RuntimeError, match="credential missing"):
        module._run(
            model="jev-test",
            endpoint="https://example.invalid/jev",
            api_key_env="JEV_MISSING_KEY",
            output=tmp_path / "report.json",
            repeat=1,
            timeout=5.0,
            thresholds=(0.85,),
            apply=False,
        )
