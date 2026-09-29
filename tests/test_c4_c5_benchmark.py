from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO_ROOT / "tools" / "research" / "c4_c5_benchmark.py"
_CASES = _REPO_ROOT / "tools" / "research" / "c4_c5_benchmark_cases.json"


def _load_module():
    name = "jarvis_c4_c5_benchmark_test_module"
    spec = importlib.util.spec_from_file_location(name, _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_frozen_corpus_loads_and_has_expected_size() -> None:
    module = _load_module()

    suite, cases = module._load_cases(_CASES)

    assert suite == "jarvis-c4-c5-bounded-decision-v1"
    assert len(cases) == 18
    assert len({case.case_id for case in cases}) == 18
    assert all(case.questions for case in cases)


def test_abstain_baseline_has_zero_semantic_coverage() -> None:
    module = _load_module()
    _, cases = module._load_cases(_CASES)
    runner = module.AbstainRunner()

    results = []
    for case in cases[:2]:
        result = runner.run(case)
        results.append(
            {
                "case_id": case.case_id,
                "latency_ms": result.latency_ms,
                "usage": result.usage,
                "api_cost_usd": result.api_cost_usd,
                "predictions": {
                    name: module._prediction_payload(prediction)
                    for name, prediction in result.predictions.items()
                },
            }
        )

    summary = module._score(cases[:2], results, confidence_threshold=0.0)

    assert summary["coverage"] == 0.0
    assert summary["unsafe_downgrades"] == 0
    assert summary["known_api_cost_usd"] == 0.0
    assert summary["complete_api_cost_usd"] == 0.0


def test_scorer_separates_unsafe_downgrade_from_over_escalation() -> None:
    module = _load_module()
    _, cases = module._load_cases(_CASES)
    case = next(
        item for item in cases if item.case_id == "route-017-cross-cutting-refactor"
    )

    result = {
        "case_id": case.case_id,
        "latency_ms": 10.0,
        "usage": {},
        "api_cost_usd": 0.0,
        "predictions": {
            question.name: {
                "value": (
                    "local_sufficient"
                    if question.name == "reasoning_tier"
                    else (
                        "insufficient_state"
                        if question.name == "research_need"
                        else question.expected
                    )
                ),
                "confidence": None,
                "probabilities": None,
            }
            for question in case.questions
        },
    }

    summary = module._score((case,), [result], confidence_threshold=0.0)

    assert summary["unsafe_downgrades"] == 1
    assert summary["conservative_escalations"] == 1


def test_ollama_runner_validates_structured_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    _, cases = module._load_cases(_CASES)
    case = cases[0]

    def fake_json_request(url, payload, *, headers=None, timeout):
        assert url == "http://127.0.0.1:11434/api/chat"
        assert headers is None
        assert timeout == 15.0
        assert payload["model"] == "test-local"
        answers = {question.name: question.expected for question in case.questions}
        return (
            {
                "message": {"content": __import__("json").dumps({"answers": answers})},
                "prompt_eval_count": 100,
                "eval_count": 10,
                "total_duration": 1_000_000,
            },
            12.5,
        )

    monkeypatch.setattr(module, "_json_request", fake_json_request)
    runner = module.OllamaRunner(
        host="http://127.0.0.1:11434",
        model="test-local",
        num_ctx=4096,
        timeout=15.0,
    )

    result = runner.run(case)

    assert all(
        result.predictions[question.name].value == question.expected
        for question in case.questions
    )
    assert result.usage == {
        "input_tokens": 100,
        "output_tokens": 10,
        "total_tokens": 110,
    }
    assert result.api_cost_usd == 0.0


def test_jev_runner_keeps_confidence_probabilities_and_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    _, cases = module._load_cases(_CASES)
    case = cases[0]

    def fake_json_request(url, payload, *, headers=None, timeout):
        assert url == "https://api.typesafe.ai/v1/systemone"
        assert headers == {"Authorization": "Bearer test-key"}
        assert timeout == 20.0
        assert payload["model"] == "jev-test"
        answers = {}
        for question in case.questions:
            probabilities = {
                choice: (
                    0.9
                    if choice == question.expected
                    else 0.1 / (len(question.choices) - 1)
                )
                for choice in question.choices
            }
            answers[question.name] = {
                "type": "choice",
                "choice": question.expected,
                "confidence": 0.9,
                "probabilities": probabilities,
            }
        return (
            {
                "model": "jev-test-pinned",
                "answers": answers,
                "usage": {"input_tokens": 500, "output_tokens": 20},
            },
            90.0,
        )

    monkeypatch.setattr(module, "_json_request", fake_json_request)
    runner = module.JevRunner(
        endpoint="https://api.typesafe.ai/v1/systemone",
        model="jev-test",
        api_key="test-key",
        timeout=20.0,
        input_usd_per_million=0.042,
    )

    result = runner.run(case)

    assert result.model == "jev-test-pinned"
    assert result.usage["input_tokens"] == 500
    assert result.predictions["reasoning_tier"].confidence == 0.9
    assert result.api_cost_usd == pytest.approx(0.000021)


def test_confidence_threshold_turns_uncertain_jev_choice_into_abstain() -> None:
    module = _load_module()
    _, cases = module._load_cases(_CASES)
    case = cases[0]
    predictions = {}
    for question in case.questions:
        predictions[question.name] = {
            "value": question.expected,
            "confidence": 0.6,
            "probabilities": None,
        }
    result = {
        "case_id": case.case_id,
        "latency_ms": 50.0,
        "usage": {},
        "api_cost_usd": None,
        "predictions": predictions,
    }

    low = module._score((case,), [result], confidence_threshold=0.5)
    high = module._score((case,), [result], confidence_threshold=0.7)

    assert low["coverage"] == 1.0
    assert low["accuracy_over_covered"] == 1.0
    assert high["coverage"] == 0.0
    assert high["complete_api_cost_usd"] is None
