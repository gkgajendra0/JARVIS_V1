from __future__ import annotations

import json
import pathlib
import subprocess
import sys
from dataclasses import replace
from types import SimpleNamespace

import pytest
from tools.research import c6_context_owner_acceptance as c6
from tools.research.c6_benchmark_corpus import build_c6_benchmark_cases

from jarvis.work.brain import BrainDecision
from jarvis.work.context import WorkContextMode
from jarvis.work.models import WorkType
from jarvis.work.reasoner import _work_input_payload


def _chars(value: object) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            default=str,
        )
    )


def test_c6_owner_harness_supports_direct_script_execution() -> None:
    repo_root = pathlib.Path(__file__).resolve().parents[1]
    script = repo_root / "tools" / "research" / "c6_context_owner_acceptance.py"
    completed = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "--fixture-decision-preflight" in completed.stdout


def test_c6_fixture_corpus_is_fixed_representative_and_reducing() -> None:
    first = build_c6_benchmark_cases()
    second = build_c6_benchmark_cases()

    assert [item.case_id for item in first] == [
        "development_repair_after_failure",
        "development_ready_for_local_commit",
        "research_requires_reresolution_after_new_evidence",
    ]
    assert [item.case_id for item in second] == [item.case_id for item in first]
    assert {item.request.work.work_type for item in first} == {
        WorkType.DEVELOPMENT,
        WorkType.RESEARCH,
    }

    first_step_ids = [
        [step.step_id for step in item.request.context_pack.selected_steps]
        for item in first
        if item.request.context_pack is not None
    ]
    second_step_ids = [
        [step.step_id for step in item.request.context_pack.selected_steps]
        for item in second
        if item.request.context_pack is not None
    ]
    assert first_step_ids == second_step_ids

    for item in first:
        legacy = replace(item.request, context_mode=WorkContextMode.SHADOW)
        legacy_chars = _chars(_work_input_payload(legacy))
        optimized_chars = _chars(_work_input_payload(item.request))
        assert optimized_chars < legacy_chars, (
            item.case_id,
            legacy_chars,
            optimized_chars,
        )


@pytest.mark.asyncio
async def test_c6_fixture_preflight_uses_no_provider_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _forbidden_provider():
        raise AssertionError("fixture preflight must not initialize provider state")

    monkeypatch.setattr(c6, "BackgroundProviderCircuitRegistry", _forbidden_provider)
    monkeypatch.setattr(c6, "ChatGPTPlanSessionManager", _forbidden_provider)

    result = await c6._run_fixture_decision_benchmark(
        model="reviewed-model",
        max_cases=3,
        min_equivalent_cases=3,
        preflight_only=True,
    )

    assert result["corpus_source"] == "checked_in_descriptor_fixture"
    assert result["fixture_preflight_ready"] is True
    assert result["fixture_cases"] == 0
    assert len(result["planned_cases"]) == 3
    assert result["candidate_stats"]["representative_corpus_covered"] is True
    assert result["candidate_stats"]["selected_work_types"] == [
        "development",
        "research",
    ]
    assert result["c6_apply_decision_equivalence_proven"] is False
    assert result["actions_executed"] is False
    assert result["provider_circuit_updated"] is False


@pytest.mark.asyncio
async def test_c6_fixture_benchmark_stops_on_first_mismatch_without_circuit_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Circuit:
        remaining_seconds = 0.0

        def allow_request(self) -> bool:
            return True

        def record_failure(self, _error):
            raise AssertionError(
                "fixture benchmark must not mutate the shared provider circuit"
            )

        def record_success(self):
            raise AssertionError(
                "fixture benchmark must not mutate the shared provider circuit"
            )

    class _CircuitRegistry:
        def circuit(self, _key):
            return _Circuit()

    class _Plan:
        def is_connected(self) -> bool:
            return True

        def list_models(self):
            return (SimpleNamespace(slug="reviewed-model"),)

    monkeypatch.setattr(c6, "BackgroundProviderCircuitRegistry", _CircuitRegistry)
    monkeypatch.setattr(c6, "ChatGPTPlanSessionManager", _Plan)
    monkeypatch.setattr(
        c6,
        "build_chatgpt_plan_structured_output_client",
        lambda **kwargs: object(),
    )

    calls = 0

    async def _evaluate(_client, request):
        nonlocal calls
        calls += 1
        action = (
            "dev_status"
            if request.context_mode is WorkContextMode.SHADOW
            else "dev_diff"
        )
        return (
            BrainDecision(
                action=action,
                summary="Intentional C6 fixture mismatch",
            ),
            SimpleNamespace(
                usage={"input_tokens": 1.0},
                usage_observed=True,
                latency_ms=1.0,
            ),
        )

    monkeypatch.setattr(c6, "evaluate_structured_work_request", _evaluate)

    result = await c6._run_fixture_decision_benchmark(
        model="reviewed-model",
        max_cases=3,
        min_equivalent_cases=3,
    )

    assert calls == 2
    assert result["fixture_cases"] == 1
    assert result["mismatch_cases"] == 1
    assert result["cases"][0]["action_equal"] is False
    assert result["c6_apply_decision_equivalence_proven"] is False
    assert result["actions_executed"] is False
    assert result["provider_circuit_updated"] is False
