from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from jarvis.brain_routing.jev import (
    JevAdmissionPolicy,
    JevChoiceDecision,
    JevDecisionResult,
)
from jarvis.capabilities.models import CapabilityCatalog
from jarvis.capability_acquisition.jev import (
    JevAcquisitionCandidateAdvisor,
    build_jev_acquisition_candidate_advisor,
)
from jarvis.capability_acquisition.models import (
    AcquisitionCandidateV1,
    AcquisitionSourceKind,
    AcquisitionStrategy,
    AcquisitionTrustClass,
    OwnerCapabilityGoalV1,
)
from jarvis.capability_acquisition.resolver import (
    AcquisitionResolutionError,
    CapabilityAcquisitionResolver,
)
from jarvis.capability_acquisition.source import (
    AcquisitionContextV1,
    CapabilitySourceRegistry,
)


def _goal() -> OwnerCapabilityGoalV1:
    return OwnerCapabilityGoalV1.create(
        request="Get TV control capability",
        requested_capability="TV control",
        required_operations=("power", "volume"),
        source_session_id="session-jev",
        source_turn_id="turn-jev",
        now_epoch=100.0,
    )


def _context() -> AcquisitionContextV1:
    return AcquisitionContextV1(
        catalog=CapabilityCatalog(sources=(), capabilities=()),
        inventory=(),
    )


def _candidate(
    identity: str,
    digest_char: str,
    *,
    strategy: AcquisitionStrategy = AcquisitionStrategy.WRAP,
) -> AcquisitionCandidateV1:
    return AcquisitionCandidateV1.create(
        source_kind=AcquisitionSourceKind.MCP,
        source_identity=identity,
        source_digest=digest_char * 64,
        trust_class=AcquisitionTrustClass.VERIFIED_OFFICIAL_REMOTE,
        supported_operations=("power", "volume"),
        strategy=strategy,
        evidence_refs=(f"evidence:{identity}",),
        verification_requirements=("contract-test",),
        external_acceptance_requirements=("owner-observe-tv",),
    )




def _write_benchmark_report(tmp_path, *, threshold: float = 0.85, model: str = "jev-latest"):
    path = tmp_path / "jev-benchmark.json"
    path.write_text(
        json.dumps(
            {
                "suite": "jarvis-c4-c5-bounded-decision-v1",
                "runner": "jev",
                "requested_model": model,
                "case_count": 18,
                "repeat": 1,
                "summaries": [
                    {
                        "confidence_threshold": threshold,
                        "structured_output_failures": 0,
                        "unsafe_downgrades": 0,
                        "covered": 12,
                    }
                ],
                "results": [],
            }
        ),
        encoding="utf-8",
    )
    return path


@dataclass
class FakeJevClient:
    selected: str
    confidence: float
    calls: int = 0

    def decide(self, request):
        self.calls += 1
        choices = request.questions[0].choices
        probabilities = {
            key: (
                self.confidence
                if key == self.selected
                else (1.0 - self.confidence) / (len(choices) - 1)
            )
            for key in choices
        }
        return JevDecisionResult(
            decision_family=request.decision_family,
            requested_model="jev-latest",
            resolved_model="jev-test",
            answers=(
                JevChoiceDecision(
                    question_name="candidate",
                    choice=self.selected,
                    confidence=self.confidence,
                    probabilities=probabilities,
                ),
            ),
        )


def _advisor(client: FakeJevClient, *, threshold: float = 0.8):
    return JevAcquisitionCandidateAdvisor(
        client,
        admission=JevAdmissionPolicy(
            admitted_families=frozenset({"capability_acquisition.candidate_selection"}),
            minimum_confidence=threshold,
        ),
    )


def test_jev_selects_only_within_equivalent_safe_tier() -> None:
    first = _candidate("mcp:vendor-a", "a")
    second = _candidate("mcp:vendor-b", "b")
    client = FakeJevClient(selected=second.candidate_id, confidence=0.93)

    resolver = CapabilityAcquisitionResolver(
        CapabilitySourceRegistry(),
        advisor=_advisor(client),
    )
    result = resolver.resolve_candidates(_goal(), (first, second), _context())

    assert client.calls == 1
    assert result.selected_candidate_id == second.candidate_id


def test_low_confidence_jev_abstains_to_deterministic_fallback() -> None:
    first = _candidate("mcp:vendor-a", "a")
    second = _candidate("mcp:vendor-b", "b")
    client = FakeJevClient(selected=second.candidate_id, confidence=0.6)

    resolver = CapabilityAcquisitionResolver(
        CapabilitySourceRegistry(),
        advisor=_advisor(client, threshold=0.8),
    )
    result = resolver.resolve_candidates(_goal(), (first, second), _context())

    expected = min(first.candidate_id, second.candidate_id)
    assert client.calls == 1
    assert result.selected_candidate_id == expected


def test_jev_is_not_called_when_deterministic_strategy_rank_has_a_winner() -> None:
    wrap = _candidate("mcp:wrap", "a", strategy=AcquisitionStrategy.WRAP)
    build = _candidate(
        "mcp:build",
        "b",
        strategy=AcquisitionStrategy.BUILD_CUSTOM,
    )
    client = FakeJevClient(selected=build.candidate_id, confidence=0.99)

    resolver = CapabilityAcquisitionResolver(
        CapabilitySourceRegistry(),
        advisor=_advisor(client),
    )
    result = resolver.resolve_candidates(_goal(), (build, wrap), _context())

    assert client.calls == 0
    assert result.selected_candidate_id == wrap.candidate_id


def test_advisor_cannot_select_outside_deterministic_safe_tier() -> None:
    first = _candidate("mcp:vendor-a", "a")
    second = _candidate("mcp:vendor-b", "b")
    outsider = _candidate(
        "mcp:custom",
        "c",
        strategy=AcquisitionStrategy.BUILD_CUSTOM,
    )

    class BadAdvisor:
        def select(self, **kwargs):
            del kwargs
            return outsider.candidate_id

    resolver = CapabilityAcquisitionResolver(
        CapabilitySourceRegistry(),
        advisor=BadAdvisor(),
    )

    with pytest.raises(AcquisitionResolutionError, match="outside deterministic"):
        resolver.resolve_candidates(
            _goal(),
            (first, second, outsider),
            _context(),
        )


def test_live_jev_factory_is_disabled_without_side_effects(monkeypatch) -> None:
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    assert (
        build_jev_acquisition_candidate_advisor(
            enabled=False,
            benchmark_admitted=False,
            minimum_confidence=0.0,
            model="jev-latest",
            endpoint="https://api.typesafe.ai/v1/systemone",
        )
        is None
    )


def test_live_jev_factory_requires_benchmark_admission(monkeypatch) -> None:
    monkeypatch.setenv("JEV_API_KEY", "secret")
    with pytest.raises(RuntimeError, match="benchmark admission"):
        build_jev_acquisition_candidate_advisor(
            enabled=True,
            benchmark_admitted=False,
            minimum_confidence=0.85,
            model="jev-latest",
            endpoint="https://api.typesafe.ai/v1/systemone",
        )


def test_live_jev_factory_requires_calibrated_threshold_and_secret(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("JEV_API_KEY", "secret")
    with pytest.raises(RuntimeError, match="calibrated confidence"):
        build_jev_acquisition_candidate_advisor(
            enabled=True,
            benchmark_admitted=True,
            minimum_confidence=0.0,
            model="jev-latest",
            endpoint="https://api.typesafe.ai/v1/systemone",
        )

    monkeypatch.delenv("JEV_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="credential missing"):
        build_jev_acquisition_candidate_advisor(
            enabled=True,
            benchmark_admitted=True,
            minimum_confidence=0.85,
            model="jev-latest",
            endpoint="https://api.typesafe.ai/v1/systemone",
        )


def test_live_jev_factory_builds_only_after_all_gates(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("JEV_API_KEY", "secret")
    advisor = build_jev_acquisition_candidate_advisor(
        enabled=True,
        benchmark_admitted=True,
        minimum_confidence=0.85,
        model="jev-latest",
        endpoint="https://api.typesafe.ai/v1/systemone",
        benchmark_report_path=str(_write_benchmark_report(tmp_path)),
    )
    assert isinstance(advisor, JevAcquisitionCandidateAdvisor)


def test_live_jev_factory_rejects_unsafe_benchmark_evidence(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("JEV_API_KEY", "secret")
    path = _write_benchmark_report(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["summaries"][0]["unsafe_downgrades"] = 1
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RuntimeError, match="zero unsafe downgrades"):
        build_jev_acquisition_candidate_advisor(
            enabled=True,
            benchmark_admitted=True,
            minimum_confidence=0.85,
            model="jev-latest",
            endpoint="https://api.typesafe.ai/v1/systemone",
            benchmark_report_path=str(path),
        )
