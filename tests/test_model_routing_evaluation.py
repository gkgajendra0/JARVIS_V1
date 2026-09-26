import json
from pathlib import Path

import pytest

from jarvis.model_routing.evaluation import (
    BenchmarkBaseline,
    RoutingEvaluationConfig,
    TargetReplayObservation,
    benchmark_fixture_digest,
    evaluate_routing_replay,
    load_routing_benchmark_fixture,
)
from jarvis.model_routing.models import BenchmarkStatus, ModelLocality, ModelTarget
from jarvis.model_routing.strategy import EngineeringStageStrategy

_FIXTURE = Path(__file__).parent / "fixtures" / "model_routing_benchmark_v1.json"


def _target(target_id: str, *, roles: tuple[str, ...]) -> ModelTarget:
    return ModelTarget(
        target_id=target_id,
        adapter_id="fixture",
        provider_id="fixture",
        model_id=f"fixture-{target_id}",
        locality=ModelLocality.LOCAL,
        capabilities=("engineering_reasoning", "structured_output"),
        roles=roles,
        max_context_tokens=64_000,
        supports_structured_output=True,
        supports_tools=False,
        supports_streaming=False,
        latency_class="fixture",
        benchmark_status=BenchmarkStatus.ACCEPTED,
        registry_version=1,
        credential_ref=None,
    )


def _targets() -> tuple[ModelTarget, ...]:
    return (
        _target("current-a", roles=("current",)),
        _target("efficient-a", roles=("efficient",)),
        _target("capable-a", roles=("capable",)),
    )


def _load():
    fixture_id, source_revision, cases = load_routing_benchmark_fixture(_FIXTURE)
    config = RoutingEvaluationConfig(
        fixture_id=fixture_id,
        source_revision=source_revision,
        registry_digest="c" * 64,
        current_target_id="current-a",
        capable_target_id="capable-a",
        efficient_target_id="efficient-a",
        engineering_fallback_budget=1,
    )
    return cases, config


def test_fixture_is_versioned_bounded_and_digest_is_deterministic() -> None:
    cases, config = _load()

    assert config.fixture_id == "phase4-routing-benchmark-v1"
    assert config.source_revision == "phase4h-replay-fixture-v1"
    assert len(cases) == 6
    first = benchmark_fixture_digest(cases)
    second = benchmark_fixture_digest(tuple(reversed(cases)))
    assert first == second
    assert len(first) == 64


def test_stage_router_reports_quality_cost_latency_and_category_metrics() -> None:
    cases, config = _load()

    report = evaluate_routing_replay(
        cases=cases,
        targets=_targets(),
        config=config,
    )

    assert report.fixture_id == config.fixture_id
    assert report.source_revision == config.source_revision
    assert report.registry_digest == "c" * 64
    assert report.strategy_digest == EngineeringStageStrategy.strategy_digest
    assert len(report.fixture_digest) == 64
    assert set(report.overall) == {baseline.value for baseline in BenchmarkBaseline}
    assert set(report.by_category) == {
        "development",
        "diagnostics",
        "provider_pressure",
        "research",
        "verification",
    }

    stage = report.overall[BenchmarkBaseline.ENGINEERING_STAGE_V1.value]
    assert stage.cases == 6
    assert stage.verified_successes == 6
    assert stage.verified_success_rate == 1.0
    assert stage.structured_output_valid_cases == 6
    assert stage.fallback_opportunities == 1
    assert stage.fallback_recoveries == 1
    assert stage.fallback_recovery_rate == 1.0
    assert stage.wrong_routes == 0
    assert stage.wrong_route_rate == 0.0
    assert stage.unnecessary_escalations == 0
    assert stage.model_calls == 7
    assert stage.route_churn == 1
    assert stage.total_latency_ms > 0
    assert stage.input_tokens > 0
    assert stage.output_tokens > 0
    assert stage.estimated_cost_usd > 0


def test_baselines_make_tradeoffs_visible_without_ranking_or_self_promotion() -> None:
    cases, config = _load()

    report = evaluate_routing_replay(
        cases=cases,
        targets=_targets(),
        config=config,
    )

    efficient = report.overall[BenchmarkBaseline.ALWAYS_EFFICIENT.value]
    capable = report.overall[BenchmarkBaseline.ALWAYS_CAPABLE.value]
    stage = report.overall[BenchmarkBaseline.ENGINEERING_STAGE_V1.value]

    assert efficient.verified_successes == 2
    assert capable.verified_successes == 6
    assert capable.unnecessary_escalations == 3
    assert stage.verified_successes == 6
    assert stage.unnecessary_escalations == 0
    assert stage.estimated_cost_usd < capable.estimated_cost_usd

    # The evaluator only reports evidence. It does not select or promote a
    # production winner and repeated evaluation is deterministic.
    repeated = evaluate_routing_replay(
        cases=cases,
        targets=_targets(),
        config=config,
    )
    assert repeated == report


def test_provider_pressure_case_remains_efficient_then_recovers_by_fallback() -> None:
    cases, config = _load()

    report = evaluate_routing_replay(
        cases=cases,
        targets=_targets(),
        config=config,
    )
    result = next(
        item
        for item in report.results
        if item.baseline is BenchmarkBaseline.ENGINEERING_STAGE_V1
        and item.case_id == "provider-pressure-fallback"
    )

    assert result.selected_role == "efficient"
    assert result.attempted_target_ids == ("efficient-a", "capable-a")
    assert result.final_target_id == "capable-a"
    assert result.fallback_recovered is True
    assert result.verified_success is True
    assert result.wrong_route is False


def test_category_metrics_do_not_hide_diagnostic_regressions() -> None:
    cases, config = _load()

    report = evaluate_routing_replay(
        cases=cases,
        targets=_targets(),
        config=config,
    )

    diagnostics = report.by_category["diagnostics"]
    efficient = diagnostics[BenchmarkBaseline.ALWAYS_EFFICIENT.value]
    stage = diagnostics[BenchmarkBaseline.ENGINEERING_STAGE_V1.value]

    assert efficient.cases == 2
    assert efficient.verified_successes == 1
    assert stage.cases == 2
    assert stage.verified_successes == 2


def test_replay_observation_requires_independent_verifier_reference() -> None:
    with pytest.raises(ValueError, match="verifier_reference"):
        TargetReplayObservation(
            target_id="efficient-a",
            invocation_succeeded=True,
            structured_output_valid=True,
            verified_success=True,
            verifier_reference="",
            latency_ms=1.0,
            input_tokens=1,
            output_tokens=1,
            estimated_cost_usd=0.0,
        )


def test_failed_invocation_requires_failure_class() -> None:
    with pytest.raises(ValueError, match="failure_class"):
        TargetReplayObservation(
            target_id="efficient-a",
            invocation_succeeded=False,
            structured_output_valid=False,
            verified_success=False,
            verifier_reference="fixture:test",
            latency_ms=1.0,
            input_tokens=0,
            output_tokens=0,
            estimated_cost_usd=0.0,
        )


def test_unknown_baseline_target_fails_closed() -> None:
    cases, config = _load()
    broken = RoutingEvaluationConfig(
        fixture_id=config.fixture_id,
        source_revision=config.source_revision,
        registry_digest=config.registry_digest,
        current_target_id="missing-target",
        capable_target_id=config.capable_target_id,
        efficient_target_id=config.efficient_target_id,
        engineering_fallback_budget=1,
    )

    with pytest.raises(ValueError, match="unknown target"):
        evaluate_routing_replay(
            cases=cases,
            targets=_targets(),
            config=broken,
        )


def test_fixture_loader_rejects_string_boolean_coercion(tmp_path: Path) -> None:
    payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    payload["cases"][0]["observations"][0]["verified_success"] = "false"
    path = tmp_path / "bad-bool.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(TypeError, match="verified_success"):
        load_routing_benchmark_fixture(path)


def test_fixture_loader_rejects_string_numeric_coercion(tmp_path: Path) -> None:
    payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    payload["cases"][0]["request"]["estimated_context_tokens"] = "1800"
    path = tmp_path / "bad-number.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(TypeError, match="estimated_context_tokens"):
        load_routing_benchmark_fixture(path)
