import importlib.util
import json
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


def _write_valid_report(path: Path) -> Path:
    corpus = json.loads(
        (
            _REPO_ROOT
            / "tools"
            / "research"
            / "jev_phase9_candidate_benchmark_cases.json"
        ).read_text(encoding="utf-8")
    )
    case_ids = [str(item["id"]) for item in corpus["cases"]]
    results = [
        {
            "case_id": case_id,
            "repetition": repetition,
            "runner": "jev",
            "model": "jev-latest",
            "latency_ms": 1.0,
            "usage": {"input_tokens": 1, "output_tokens": 0, "total_tokens": 1},
            "api_cost_usd": None,
            "predictions": {
                "candidate": {
                    "value": "candidate_a",
                    "confidence": 0.99,
                    "probabilities": {"candidate_a": 0.99, "candidate_b": 0.01},
                }
            },
            "raw_metadata": {},
        }
        for repetition in range(1, 4)
        for case_id in case_ids
    ]
    path.write_text(
        json.dumps(
            {
                "suite": "jarvis-jev-phase9-candidate-selection-v1",
                "runner": "jev",
                "requested_model": "jev-latest",
                "case_count": 8,
                "repeat": 3,
                "summaries": [
                    {
                        "confidence_threshold": 0.95,
                        "questions": 24,
                        "covered": 24,
                        "coverage": 1.0,
                        "abstained": 0,
                        "structured_output_failures": 0,
                        "exact": 24,
                        "accuracy_over_covered": 1.0,
                        "unsafe_downgrades": 0,
                    }
                ],
                "results": results,
            }
        ),
        encoding="utf-8",
    )
    return path


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


def test_phase9_threshold_selection_requires_perfect_evidence_then_confidence() -> None:
    module = _load_module()
    report = {
        "summaries": [
            {
                "confidence_threshold": 0.80,
                "covered": 8,
                "coverage": 1.0,
                "accuracy_over_covered": 1.0,
                "unsafe_downgrades": 1,
                "structured_output_failures": 0,
            },
            {
                "confidence_threshold": 0.85,
                "covered": 7,
                "coverage": 0.875,
                "accuracy_over_covered": 1.0,
                "unsafe_downgrades": 0,
                "structured_output_failures": 0,
            },
            {
                "confidence_threshold": 0.90,
                "covered": 8,
                "coverage": 1.0,
                "accuracy_over_covered": 1.0,
                "unsafe_downgrades": 0,
                "structured_output_failures": 0,
            },
            {
                "confidence_threshold": 0.95,
                "covered": 8,
                "coverage": 1.0,
                "accuracy_over_covered": 1.0,
                "unsafe_downgrades": 0,
                "structured_output_failures": 0,
            },
        ]
    }

    assert module._select_admitted_threshold(report) == pytest.approx(0.95)


def test_phase9_threshold_selection_rejects_imperfect_evidence() -> None:
    module = _load_module()
    report = {
        "summaries": [
            {
                "confidence_threshold": 0.85,
                "covered": 8,
                "coverage": 1.0,
                "accuracy_over_covered": 0.875,
                "unsafe_downgrades": 0,
                "structured_output_failures": 0,
            },
            {
                "confidence_threshold": 0.90,
                "covered": 7,
                "coverage": 0.875,
                "accuracy_over_covered": 1.0,
                "unsafe_downgrades": 0,
                "structured_output_failures": 0,
            },
            {
                "confidence_threshold": 0.95,
                "covered": 8,
                "coverage": 1.0,
                "accuracy_over_covered": 1.0,
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


def test_phase9_owner_acceptance_apply_persists_text_settings_only(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    machine_path = tmp_path / "machine.json"
    monkeypatch.setenv("JARVIS_MACHINE_CONFIG", str(machine_path))

    after = module._apply_machine_settings(
        report_path=tmp_path / "report.json",
        model="jev-latest",
        endpoint="https://api.typesafe.ai/v1/systemone",
        threshold=0.95,
    )

    assert after["jev_bounded_decisions_enabled"] == "true"
    assert after["jev_benchmark_admitted"] == "true"
    assert after["jev_min_confidence"] == "0.95"
    assert after["jev_model"] == "jev-latest"
    assert "JEV_API_KEY" not in machine_path.read_text(encoding="utf-8")


def test_phase9_existing_report_admission_reuses_evidence_without_credential(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    source = _write_valid_report(tmp_path / "existing.json")
    durable = tmp_path / "JARVIS" / "acceptance" / "jev-phase9.json"
    machine = tmp_path / "machine.json"

    monkeypatch.delenv("JEV_API_KEY", raising=False)
    monkeypatch.setenv("JARVIS_MACHINE_CONFIG", str(machine))

    result = module._finalize_report_admission(
        source_report=source,
        durable_output=durable,
        model="jev-latest",
        endpoint="https://api.typesafe.ai/v1/systemone",
        apply=True,
    )

    assert result["status"] == "PASS"
    assert result["selected_confidence_threshold"] == pytest.approx(0.95)
    assert result["coverage"] == pytest.approx(1.0)
    assert result["accuracy_over_covered"] == pytest.approx(1.0)
    assert result["unsafe_downgrades"] == 0
    assert result["structured_output_failures"] == 0
    assert result["machine_settings_applied"] is True
    assert durable.read_bytes() == source.read_bytes()
    assert result["machine_after"]["jev_min_confidence"] == "0.95"
    assert result["machine_after"]["jev_benchmark_report_path"] == str(
        durable.resolve()
    )


def test_phase9_existing_report_admission_requires_three_full_repeats(
    tmp_path: Path,
) -> None:
    module = _load_module()
    source = _write_valid_report(tmp_path / "shallow.json")
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["repeat"] = 2
    payload["results"] = payload["results"][:16]
    source.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RuntimeError, match="at least 3 benchmark repeats"):
        module._finalize_report_admission(
            source_report=source,
            durable_output=tmp_path / "durable.json",
            model="jev-latest",
            endpoint="https://api.typesafe.ai/v1/systemone",
            apply=False,
        )


def test_phase9_existing_report_admission_requires_all_results(
    tmp_path: Path,
) -> None:
    module = _load_module()
    source = _write_valid_report(tmp_path / "incomplete.json")
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["results"] = payload["results"][:-1]
    source.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RuntimeError, match="every case/repetition result"):
        module._finalize_report_admission(
            source_report=source,
            durable_output=tmp_path / "durable.json",
            model="jev-latest",
            endpoint="https://api.typesafe.ai/v1/systemone",
            apply=False,
        )



def test_phase9_existing_report_rejects_duplicate_case_repetition(
    tmp_path: Path,
) -> None:
    module = _load_module()
    source = _write_valid_report(tmp_path / "duplicate.json")
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["results"][-1] = dict(payload["results"][0])
    source.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RuntimeError, match="duplicates a case/repetition"):
        module._finalize_report_admission(
            source_report=source,
            durable_output=tmp_path / "durable.json",
            model="jev-latest",
            endpoint="https://api.typesafe.ai/v1/systemone",
            apply=False,
        )
