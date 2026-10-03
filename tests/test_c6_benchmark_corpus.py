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

from jarvis.engineering_substrate.canonical import canonical_digest
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
    assert "--fixture-stability-preflight" in completed.stdout
    assert "--fixture-stability-benchmark" in completed.stdout
    assert "--fixture-first-pair-preflight" in completed.stdout
    assert "--fixture-first-pair-benchmark" in completed.stdout
    assert "--fixture-remaining-preflight" in completed.stdout
    assert "--fixture-remaining-benchmark" in completed.stdout
    assert "--llmlingua-fixture-preflight" in completed.stdout
    assert "--llmlingua-fixture-benchmark" in completed.stdout


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
    assert "test(c6): repair bounded normalization" in first[0].request.work.request
    assert "test(c6): finalize reviewed change" in first[1].request.work.request

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
        message = (
            "test(c6): repair bounded normalization"
            if request.context_mode is WorkContextMode.SHADOW
            else "test(c6): repair normalization"
        )
        return (
            BrainDecision(
                action="dev_commit",
                summary="Intentional C6 parameter mismatch",
                parameters={"message": message},
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
    case = result["cases"][0]
    assert case["action_equal"] is True
    assert case["parameters_equal"] is False
    assert case["legacy_action"] == "dev_commit"
    assert case["optimized_action"] == "dev_commit"
    assert case["legacy_parameters"] == {
        "message": "test(c6): repair bounded normalization",
    }
    assert case["optimized_parameters"] == {
        "message": "test(c6): repair normalization",
    }
    assert case["legacy_parameters_digest"] == canonical_digest(
        case["legacy_parameters"]
    )
    assert case["optimized_parameters_digest"] == canonical_digest(
        case["optimized_parameters"]
    )
    assert result["c6_apply_decision_equivalence_proven"] is False
    assert result["actions_executed"] is False
    assert result["provider_circuit_updated"] is False


@pytest.mark.asyncio
async def test_c6_fixture_stability_preflight_uses_no_provider_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _forbidden_provider():
        raise AssertionError("stability preflight must not initialize provider state")

    monkeypatch.setattr(c6, "BackgroundProviderCircuitRegistry", _forbidden_provider)
    monkeypatch.setattr(c6, "ChatGPTPlanSessionManager", _forbidden_provider)

    result = await c6._run_fixture_stability_benchmark(
        model="reviewed-model",
        preflight_only=True,
    )

    assert result["fixture_stability_ready"] is True
    assert result["model_calls"] == 0
    assert result["same_context_stable"] is None
    assert result["case"]["case_id"] == "development_repair_after_failure"
    assert result["case"]["same_context_request_digest"]
    assert result["case"]["reasoning_contract_digest"]
    assert result["c6_apply_decision_equivalence_proven"] is False
    assert result["actions_executed"] is False
    assert result["provider_circuit_updated"] is False


@pytest.mark.asyncio
async def test_c6_fixture_stability_benchmark_reports_same_context_variance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Circuit:
        remaining_seconds = 0.0

        def allow_request(self) -> bool:
            return True

        def record_failure(self, _error):
            raise AssertionError("stability benchmark must not mutate provider circuit")

        def record_success(self):
            raise AssertionError("stability benchmark must not mutate provider circuit")

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
    request_digests: list[str] = []

    async def _evaluate(_client, request):
        nonlocal calls
        calls += 1
        assert request.context_mode is WorkContextMode.SHADOW
        request_digests.append(canonical_digest(_work_input_payload(request)))
        message = (
            "test(c6): repair bounded normalization"
            if calls == 1
            else "test(c6): repair normalization"
        )
        return (
            BrainDecision(
                action="dev_commit",
                summary="Same-context stability probe",
                parameters={"message": message},
            ),
            SimpleNamespace(
                usage={"input_tokens": calls},
                usage_observed=True,
                latency_ms=float(calls),
            ),
        )

    monkeypatch.setattr(c6, "evaluate_structured_work_request", _evaluate)

    result = await c6._run_fixture_stability_benchmark(model="reviewed-model")

    assert calls == 2
    assert request_digests[0] == request_digests[1]
    assert request_digests[0] == result["case"]["same_context_request_digest"]
    assert result["model_calls"] == 2
    assert result["same_context_stable"] is False
    assert result["case"]["action_equal"] is True
    assert result["case"]["parameters_equal"] is False
    assert result["case"]["first_parameters"] == {
        "message": "test(c6): repair bounded normalization"
    }
    assert result["case"]["second_parameters"] == {
        "message": "test(c6): repair normalization"
    }
    assert result["c6_apply_decision_equivalence_proven"] is False
    assert result["actions_executed"] is False
    assert result["provider_circuit_updated"] is False


@pytest.mark.asyncio
async def test_c6_fixture_stability_does_not_promote_apply_when_stable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Circuit:
        remaining_seconds = 0.0

        def allow_request(self) -> bool:
            return True

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

    async def _evaluate(_client, request):
        assert request.context_mode is WorkContextMode.SHADOW
        return (
            BrainDecision(
                action="dev_commit",
                summary="Stable same-context decision",
                parameters={"message": "test(c6): repair bounded normalization"},
            ),
            SimpleNamespace(
                usage={"input_tokens": 1},
                usage_observed=True,
                latency_ms=1.0,
            ),
        )

    monkeypatch.setattr(c6, "evaluate_structured_work_request", _evaluate)

    result = await c6._run_fixture_stability_benchmark(model="reviewed-model")

    assert result["model_calls"] == 2
    assert result["same_context_stable"] is True
    assert result["case"]["parameters_equal"] is True
    assert result["c6_apply_decision_equivalence_proven"] is False


@pytest.mark.asyncio
async def test_c6_fixture_first_pair_preflight_uses_no_provider_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _forbidden_provider():
        raise AssertionError("first-pair preflight must not initialize provider state")

    monkeypatch.setattr(c6, "BackgroundProviderCircuitRegistry", _forbidden_provider)
    monkeypatch.setattr(c6, "ChatGPTPlanSessionManager", _forbidden_provider)

    result = await c6._run_fixture_first_pair_benchmark(
        model="reviewed-model",
        preflight_only=True,
    )

    assert result["fixture_first_pair_ready"] is True
    assert result["model_calls"] == 0
    assert result["pair_equivalent"] is None
    assert result["case"]["case_id"] == "development_repair_after_failure"
    assert result["case"]["legacy_request_digest"]
    assert result["case"]["optimized_request_digest"]
    assert (
        result["case"]["legacy_request_digest"]
        != result["case"]["optimized_request_digest"]
    )
    assert result["case"]["optimized_chars"] < result["case"]["legacy_chars"]
    assert result["c6_apply_decision_equivalence_proven"] is False
    assert result["actions_executed"] is False


@pytest.mark.asyncio
async def test_c6_fixture_first_pair_reports_equivalence_without_promoting_apply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Circuit:
        remaining_seconds = 0.0

        def allow_request(self) -> bool:
            return True

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

    calls: list[WorkContextMode] = []

    async def _evaluate(_client, request):
        calls.append(request.context_mode)
        return (
            BrainDecision(
                action="dev_commit",
                summary="Equivalent corrected fixture decision",
                parameters={"message": "test(c6): repair bounded normalization"},
            ),
            SimpleNamespace(
                usage={"input_tokens": len(calls)},
                usage_observed=True,
                latency_ms=float(len(calls)),
            ),
        )

    monkeypatch.setattr(c6, "evaluate_structured_work_request", _evaluate)

    result = await c6._run_fixture_first_pair_benchmark(model="reviewed-model")

    assert calls == [WorkContextMode.SHADOW, WorkContextMode.APPLY]
    assert result["model_calls"] == 2
    assert result["pair_equivalent"] is True
    assert result["case"]["action_equal"] is True
    assert result["case"]["parameters_equal"] is True
    assert result["case"]["legacy_parameters"] == {
        "message": "test(c6): repair bounded normalization"
    }
    assert result["case"]["optimized_parameters"] == result["case"]["legacy_parameters"]
    assert result["c6_apply_decision_equivalence_proven"] is False
    assert result["production_routing_mutated"] is False
    assert result["actions_executed"] is False
    assert result["provider_circuit_updated"] is False


@pytest.mark.asyncio
async def test_c6_fixture_first_pair_reports_parameter_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Circuit:
        remaining_seconds = 0.0

        def allow_request(self) -> bool:
            return True

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
        message = (
            "test(c6): repair bounded normalization"
            if request.context_mode is WorkContextMode.SHADOW
            else "test(c6): repair normalization"
        )
        return (
            BrainDecision(
                action="dev_commit",
                summary="Intentional first-pair mismatch",
                parameters={"message": message},
            ),
            SimpleNamespace(
                usage={"input_tokens": calls},
                usage_observed=True,
                latency_ms=float(calls),
            ),
        )

    monkeypatch.setattr(c6, "evaluate_structured_work_request", _evaluate)

    result = await c6._run_fixture_first_pair_benchmark(model="reviewed-model")

    assert calls == 2
    assert result["pair_equivalent"] is False
    assert result["case"]["action_equal"] is True
    assert result["case"]["parameters_equal"] is False
    assert result["c6_apply_decision_equivalence_proven"] is False


@pytest.mark.asyncio
async def test_c6_fixture_remaining_preflight_selects_only_uncovered_pairs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _forbidden_provider():
        raise AssertionError("remaining-pairs preflight must not initialize provider")

    monkeypatch.setattr(c6, "BackgroundProviderCircuitRegistry", _forbidden_provider)
    monkeypatch.setattr(c6, "ChatGPTPlanSessionManager", _forbidden_provider)

    result = await c6._run_fixture_decision_benchmark(
        model="reviewed-model",
        max_cases=2,
        min_equivalent_cases=2,
        preflight_only=True,
        case_ids=(
            "development_ready_for_local_commit",
            "research_requires_reresolution_after_new_evidence",
        ),
    )

    assert result["fixture_preflight_ready"] is True
    assert result["subset_mode"] is True
    assert result["fixture_cases"] == 0
    assert [case["case_id"] for case in result["planned_cases"]] == [
        "development_ready_for_local_commit",
        "research_requires_reresolution_after_new_evidence",
    ]
    assert result["c6_apply_decision_equivalence_proven"] is False


@pytest.mark.asyncio
async def test_c6_fixture_remaining_pairs_pass_but_do_not_promote_apply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Circuit:
        remaining_seconds = 0.0

        def allow_request(self) -> bool:
            return True

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

    calls: list[tuple[str, WorkContextMode]] = []

    async def _evaluate(_client, request):
        calls.append((request.work.work_id, request.context_mode))
        if request.work.work_type is WorkType.DEVELOPMENT:
            decision = BrainDecision(
                action="dev_commit",
                summary="Equivalent development decision",
                parameters={"message": "test(c6): finalize reviewed change"},
            )
        else:
            decision = BrainDecision(
                action="acquisition_resolve",
                summary="Equivalent research decision",
                parameters={},
            )
        return (
            decision,
            SimpleNamespace(
                usage={"input_tokens": len(calls)},
                usage_observed=True,
                latency_ms=float(len(calls)),
            ),
        )

    monkeypatch.setattr(c6, "evaluate_structured_work_request", _evaluate)

    result = await c6._run_fixture_decision_benchmark(
        model="reviewed-model",
        max_cases=2,
        min_equivalent_cases=2,
        case_ids=(
            "development_ready_for_local_commit",
            "research_requires_reresolution_after_new_evidence",
        ),
    )

    assert len(calls) == 4
    assert result["fixture_cases"] == 2
    assert result["equivalent_cases"] == 2
    assert result["mismatch_cases"] == 0
    assert result["all_fixture_cases_equivalent"] is True
    assert result["c6_apply_decision_equivalence_proven"] is False


@pytest.mark.asyncio
async def test_c6_fixture_remaining_pairs_stop_on_first_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Circuit:
        remaining_seconds = 0.0

        def allow_request(self) -> bool:
            return True

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
        message = (
            "test(c6): finalize reviewed change"
            if request.context_mode is WorkContextMode.SHADOW
            else "test(c6): finalize change"
        )
        return (
            BrainDecision(
                action="dev_commit",
                summary="Intentional remaining-pair mismatch",
                parameters={"message": message},
            ),
            SimpleNamespace(
                usage={"input_tokens": calls},
                usage_observed=True,
                latency_ms=float(calls),
            ),
        )

    monkeypatch.setattr(c6, "evaluate_structured_work_request", _evaluate)

    result = await c6._run_fixture_decision_benchmark(
        model="reviewed-model",
        max_cases=2,
        min_equivalent_cases=2,
        case_ids=(
            "development_ready_for_local_commit",
            "research_requires_reresolution_after_new_evidence",
        ),
    )

    assert calls == 2
    assert result["fixture_cases"] == 1
    assert result["mismatch_cases"] == 1
    assert result["cases"][0]["parameters_equal"] is False
    assert result["c6_apply_decision_equivalence_proven"] is False



class _FakeCompressionResult:
    def __init__(self, payload):
        import copy

        self.payload = copy.deepcopy(payload)
        changed = False
        for step in self.payload.get("recent_steps", []):
            observation = step.get("observation")
            if not isinstance(observation, dict):
                continue
            summary = observation.get("summary")
            if isinstance(summary, str) and len(summary) > 200:
                observation["summary"] = "compressed authoritative evidence"
                changed = True
        self.provider = "llmlingua2"
        self.model = "fake-compressor"
        self.rate = 0.5
        self.candidate_strings = 1 if changed else 0
        self.compressed_strings = 1 if changed else 0
        self.original_chars = _chars(payload)
        self.compressed_chars = _chars(self.payload)
        self.estimated_original_tokens = max(1, self.original_chars // 4)
        self.estimated_compressed_tokens = max(1, self.compressed_chars // 4)
        self.llmlingua_origin_tokens = 100
        self.llmlingua_compressed_tokens = 40
        self.latency_ms = 2.0
        self.changed_paths = (
            ("recent_steps[0].observation.summary",) if changed else ()
        )

    @property
    def reduced(self):
        return self.compressed_chars < self.original_chars


class _FakeCompressor:
    def compress_payload(self, payload):
        return _FakeCompressionResult(payload)


@pytest.mark.asyncio
async def test_c6_llmlingua_preflight_uses_no_chatgpt_plan_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _forbidden():
        raise AssertionError("LLMLingua preflight must not initialize ChatGPT-plan")

    monkeypatch.setattr(c6, "ChatGPTPlanSessionManager", _forbidden)
    result = await c6._run_llmlingua_fixture_benchmark(
        model=None,
        compressor_model="fake-compressor",
        compression_rate=0.5,
        device_map="cpu",
        case_ids=("research_requires_reresolution_after_new_evidence",),
        preflight_only=True,
        compressor_factory=_FakeCompressor,
    )

    assert result["preflight_ready"] is True
    assert result["model_calls"] == 0
    assert result["all_fixture_cases_reduced"] is True
    assert result["c6_apply_decision_equivalence_proven"] is False
    assert len(result["planned_cases"]) == 1


@pytest.mark.asyncio
async def test_c6_llmlingua_live_pair_preserves_strict_decision_equivalence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Circuit:
        remaining_seconds = 0.0

        def allow_request(self):
            return True

    class _CircuitRegistry:
        def circuit(self, _key):
            return _Circuit()

    class _Plan:
        def is_connected(self):
            return True

        def list_models(self):
            return (SimpleNamespace(slug="reviewed-model"),)

    monkeypatch.setattr(c6, "BackgroundProviderCircuitRegistry", _CircuitRegistry)
    monkeypatch.setattr(c6, "ChatGPTPlanSessionManager", _Plan)
    monkeypatch.setattr(
        c6,
        "build_chatgpt_plan_structured_output_client",
        lambda **_kwargs: object(),
    )

    calls: list[bool] = []

    async def _evaluate(_client, _request, *, provider_payload_override=None):
        calls.append(provider_payload_override is not None)
        return (
            BrainDecision(
                action="acq_record_candidate",
                summary="Equivalent research decision",
                parameters={
                    "source_kind": "sdk_library",
                    "source_identity": "example-device-sdk",
                    "source_version": "2.4.1",
                    "supported_operations": ["pair", "launch", "key_input"],
                    "evidence_refs": [
                        "evidence-2",
                        "evidence-4",
                        "evidence-new-authoritative",
                    ],
                    "verification_requirements": ["verify exact artifact"],
                },
            ),
            SimpleNamespace(
                usage={"input_tokens": 100 if provider_payload_override is None else 45},
                usage_observed=True,
                latency_ms=10.0,
            ),
        )

    monkeypatch.setattr(c6, "evaluate_structured_work_request", _evaluate)

    result = await c6._run_llmlingua_fixture_benchmark(
        model="reviewed-model",
        compressor_model="fake-compressor",
        compression_rate=0.5,
        device_map="cpu",
        case_ids=("research_requires_reresolution_after_new_evidence",),
        preflight_only=False,
        compressor_factory=_FakeCompressor,
    )

    assert calls == [False, True]
    assert result["model_calls"] == 2
    assert result["fixture_cases"] == 1
    assert result["equivalent_cases"] == 1
    assert result["mismatch_cases"] == 0
    assert result["all_fixture_cases_equivalent"] is True
    assert result["c6_apply_decision_equivalence_proven"] is False
    assert result["cases"][0]["parameters_equal"] is True
