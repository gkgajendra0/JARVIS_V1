"""Jev advisor for Phase-9 equivalent capability candidates.

Hard eligibility and ranking stay in CapabilityAcquisitionResolver.  This advisor is
consulted only when multiple selectable candidates share the same deterministic
strategy/trust/source rank.  Low-confidence or non-admitted Jev output abstains and
the resolver keeps its deterministic fallback.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Protocol

from jarvis.brain_routing.jev import (
    JevAdmissionPolicy,
    JevChoiceQuestion,
    JevDecisionRequest,
    JevDecisionResult,
    TypeSafeJevClient,
)
from jarvis.capability_acquisition.models import (
    AcquisitionCandidateEvaluationV1,
    AcquisitionCandidateV1,
    OwnerCapabilityGoalV1,
)


class JevDecisionClient(Protocol):
    def decide(self, request: JevDecisionRequest) -> JevDecisionResult: ...


class JevAcquisitionCandidateAdvisor:
    decision_family = "capability_acquisition.candidate_selection"

    def __init__(
        self,
        client: JevDecisionClient,
        *,
        admission: JevAdmissionPolicy,
    ) -> None:
        self._client = client
        self._admission = admission

    @staticmethod
    def _candidate_description(
        candidate: AcquisitionCandidateV1,
        evaluation: AcquisitionCandidateEvaluationV1,
    ) -> str:
        parts = [
            f"source={candidate.source_kind.value}",
            f"identity={candidate.source_identity}",
            f"strategy={candidate.strategy.value}",
            f"trust={candidate.trust_class.value}",
            "operations=" + ",".join(candidate.supported_operations),
            "verification=" + ",".join(candidate.verification_requirements),
        ]
        if candidate.source_version:
            parts.append(f"version={candidate.source_version}")
        if candidate.license_id:
            parts.append(f"license={candidate.license_id}")
        if evaluation.reason_codes:
            parts.append("reasons=" + ",".join(evaluation.reason_codes))
        if candidate.external_acceptance_requirements:
            parts.append(
                "external_acceptance="
                + ",".join(candidate.external_acceptance_requirements)
            )
        return "; ".join(parts)

    def select(
        self,
        *,
        goal: OwnerCapabilityGoalV1,
        candidates: tuple[AcquisitionCandidateV1, ...],
        evaluations: tuple[AcquisitionCandidateEvaluationV1, ...],
    ) -> str | None:
        if len(candidates) < 2 or len(candidates) != len(evaluations):
            return None

        by_id = {item.candidate_id: item for item in evaluations}
        if set(by_id) != {item.candidate_id for item in candidates}:
            raise ValueError("candidate/evaluation identity mismatch")

        choices = {
            candidate.candidate_id: self._candidate_description(
                candidate,
                by_id[candidate.candidate_id],
            )
            for candidate in candidates
        }
        result = self._client.decide(
            JevDecisionRequest(
                decision_family=self.decision_family,
                state={
                    "requested_capability": goal.requested_capability,
                    "required_operations": list(goal.required_operations),
                    "target_hints": list(goal.target_hints),
                    "decision_rule": (
                        "All supplied candidates already passed deterministic hard "
                        "eligibility and have equal strategy/trust/source rank. Choose "
                        "the candidate best aligned with the owner goal and lowest "
                        "remaining integration/verification burden. Do not infer "
                        "authority or bypass verification."
                    ),
                },
                questions=(
                    JevChoiceQuestion(
                        name="candidate",
                        instructions=(
                            "Choose exactly one of the equivalent safe candidates."
                        ),
                        choices=choices,
                    ),
                ),
            )
        )
        if not self._admission.permits(result):
            return None
        return result.answer("candidate").choice


def _validate_jev_benchmark_report(
    *,
    report_path: str,
    minimum_confidence: float,
    model: str,
) -> None:
    path = Path(str(report_path).strip()).expanduser()
    if not path.is_file():
        raise RuntimeError(f"JEV benchmark report is missing: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "JEV benchmark report is unreadable or invalid JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise RuntimeError("JEV benchmark report must be a JSON object")
    if payload.get("suite") != "jarvis-jev-phase9-candidate-selection-v1":
        raise RuntimeError(
            "JEV benchmark report uses the wrong Phase-9 decision corpus"
        )
    if payload.get("runner") != "jev":
        raise RuntimeError("JEV benchmark report was not produced by the Jev runner")
    if str(payload.get("requested_model") or "").strip() != str(model).strip():
        raise RuntimeError("JEV benchmark report model does not match runtime model")
    if payload.get("case_count") != 8:
        raise RuntimeError("JEV benchmark report does not cover all 8 Phase-9 cases")

    summaries = payload.get("summaries")
    if not isinstance(summaries, list):
        raise RuntimeError("JEV benchmark report is missing summaries")
    selected = next(
        (
            item
            for item in summaries
            if isinstance(item, dict)
            and isinstance(item.get("confidence_threshold"), (int, float))
            and abs(float(item["confidence_threshold"]) - float(minimum_confidence))
            <= 1e-9
        ),
        None,
    )
    if selected is None:
        raise RuntimeError(
            "JEV benchmark report does not contain the configured confidence threshold"
        )
    if int(selected.get("structured_output_failures") or 0) != 0:
        raise RuntimeError(
            "JEV benchmark admission requires zero structured-output failures"
        )
    if int(selected.get("unsafe_downgrades") or 0) != 0:
        raise RuntimeError("JEV benchmark admission requires zero unsafe downgrades")
    if int(selected.get("covered") or 0) <= 0:
        raise RuntimeError(
            "JEV benchmark admission requires non-zero covered decisions"
        )


def build_jev_acquisition_candidate_advisor(
    *,
    enabled: bool,
    benchmark_admitted: bool,
    minimum_confidence: float,
    model: str,
    endpoint: str,
    benchmark_report_path: str,
    api_key_env: str = "JEV_API_KEY",
) -> JevAcquisitionCandidateAdvisor | None:
    """Build the live Phase-9 JEV advisor only after benchmark admission."""

    if not enabled:
        return None
    if not benchmark_admitted:
        raise RuntimeError(
            "JEV runtime activation is blocked until owner-machine benchmark admission"
        )
    if not 0.0 < float(minimum_confidence) <= 1.0:
        raise RuntimeError(
            "JEV runtime activation requires a calibrated confidence threshold"
        )
    _validate_jev_benchmark_report(
        report_path=benchmark_report_path,
        minimum_confidence=minimum_confidence,
        model=model,
    )

    key_name = str(api_key_env).strip()
    if not key_name:
        raise ValueError("api_key_env must not be empty")
    api_key = os.getenv(key_name, "").strip()
    if not api_key:
        raise RuntimeError(
            f"JEV credential missing from environment variable {key_name}"
        )

    client = TypeSafeJevClient(
        api_key=api_key,
        endpoint=endpoint,
        model=model,
    )
    return JevAcquisitionCandidateAdvisor(
        client,
        admission=JevAdmissionPolicy(
            admitted_families=frozenset(
                {JevAcquisitionCandidateAdvisor.decision_family}
            ),
            minimum_confidence=float(minimum_confidence),
        ),
    )
