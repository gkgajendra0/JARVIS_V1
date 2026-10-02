"""Jev advisor for Phase-9 equivalent capability candidates.

Hard eligibility and ranking stay in CapabilityAcquisitionResolver.  This advisor is
consulted only when multiple selectable candidates share the same deterministic
strategy/trust/source rank.  Low-confidence or non-admitted Jev output abstains and
the resolver keeps its deterministic fallback.
"""

from __future__ import annotations

import os
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


def build_jev_acquisition_candidate_advisor(
    *,
    enabled: bool,
    benchmark_admitted: bool,
    minimum_confidence: float,
    model: str,
    endpoint: str,
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
    key_name = str(api_key_env).strip()
    if not key_name:
        raise ValueError("api_key_env must not be empty")
    api_key = os.getenv(key_name, "").strip()
    if not api_key:
        raise RuntimeError(\n            f"JEV credential missing from environment variable {key_name}"\n        )

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
