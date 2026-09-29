"""Versioned deterministic resolvers for C3 global brain routing."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from jarvis.brain_routing.models import GlobalBrainRouteFacts
from jarvis.work.brain import BrainDecision, BrainRequest
from jarvis.work.models import WorkStep, WorkStepState, WorkType


class DeterministicResolutionStatus(StrEnum):
    MATCH = "match"
    ABSTAIN = "abstain"


@dataclass(frozen=True, slots=True)
class DeterministicResolution:
    status: DeterministicResolutionStatus
    resolver_id: str
    resolver_version: int
    reason_codes: tuple[str, ...]
    decision: BrainDecision | None = None

    @property
    def matched(self) -> bool:
        return self.status is DeterministicResolutionStatus.MATCH


class DeterministicBrainResolver(Protocol):
    resolver_id: str
    resolver_version: int

    def resolve(
        self,
        *,
        facts: GlobalBrainRouteFacts,
        request: BrainRequest,
        all_steps: tuple[WorkStep, ...],
    ) -> DeterministicResolution: ...


def _allowed(request: BrainRequest, action: str) -> bool:
    return any(item.name == action for item in request.allowed_actions)


def _abstain(
    resolver: DeterministicBrainResolver,
    reason: str,
) -> DeterministicResolution:
    return DeterministicResolution(
        status=DeterministicResolutionStatus.ABSTAIN,
        resolver_id=resolver.resolver_id,
        resolver_version=resolver.resolver_version,
        reason_codes=(reason,),
    )


def _match(
    resolver: DeterministicBrainResolver,
    *,
    action: str,
    summary: str,
    reason: str,
) -> DeterministicResolution:
    return DeterministicResolution(
        status=DeterministicResolutionStatus.MATCH,
        resolver_id=resolver.resolver_id,
        resolver_version=resolver.resolver_version,
        reason_codes=(reason,),
        decision=BrainDecision(
            action=action,
            summary=summary,
            parameters={},
        ),
    )


class InitialDevelopmentWorkspaceResolver:
    resolver_id = "work.development.initial_workspace"
    resolver_version = 1

    def resolve(
        self,
        *,
        facts: GlobalBrainRouteFacts,
        request: BrainRequest,
        all_steps: tuple[WorkStep, ...],
    ) -> DeterministicResolution:
        del facts
        if request.work.work_type is not WorkType.DEVELOPMENT:
            return _abstain(self, "work_type_mismatch")
        action = "dev_prepare_workspace"
        if not _allowed(request, action):
            return _abstain(self, "action_unavailable")
        if any(step.kind == action for step in all_steps):
            return _abstain(self, "workspace_action_already_attempted")
        return _match(
            self,
            action=action,
            summary="Prepare the isolated development workspace.",
            reason="initial_workspace_required",
        )


class InitialDiagnosticIncidentResolver:
    resolver_id = "work.diagnostics.initial_incident"
    resolver_version = 1

    def resolve(
        self,
        *,
        facts: GlobalBrainRouteFacts,
        request: BrainRequest,
        all_steps: tuple[WorkStep, ...],
    ) -> DeterministicResolution:
        del facts
        if request.work.work_type is not WorkType.DIAGNOSTICS:
            return _abstain(self, "work_type_mismatch")
        action = "diag_get_incident"
        if not _allowed(request, action):
            return _abstain(self, "action_unavailable")
        if any(step.kind == action for step in all_steps):
            return _abstain(self, "incident_action_already_attempted")
        return _match(
            self,
            action=action,
            summary="Inspect the canonical incident evidence before reasoning.",
            reason="initial_incident_inspection_required",
        )


class PostTestDevelopmentDiffResolver:
    resolver_id = "work.development.post_test_diff"
    resolver_version = 1

    def resolve(
        self,
        *,
        facts: GlobalBrainRouteFacts,
        request: BrainRequest,
        all_steps: tuple[WorkStep, ...],
    ) -> DeterministicResolution:
        del facts
        if request.work.work_type is not WorkType.DEVELOPMENT:
            return _abstain(self, "work_type_mismatch")
        action = "dev_diff"
        if not _allowed(request, action):
            return _abstain(self, "action_unavailable")

        last_write = -1
        last_test = -1
        last_passing_test = -1
        last_diff_attempt = -1
        last_commit = -1
        for index, step in enumerate(all_steps):
            if step.kind == "dev_write_file" and step.state is WorkStepState.COMPLETED:
                last_write = index
            elif step.kind == "dev_run_tests":
                last_test = index
                if (
                    step.state is WorkStepState.COMPLETED
                    and step.observation.get("passed") is True
                ):
                    last_passing_test = index
            elif step.kind == "dev_diff":
                last_diff_attempt = index
            elif step.kind == "dev_commit" and step.state is WorkStepState.COMPLETED:
                last_commit = index

        if last_write < 0:
            return _abstain(self, "no_completed_write")
        if last_test < 0 or last_test != last_passing_test:
            return _abstain(self, "latest_test_not_verified_passing")
        if last_passing_test <= last_write:
            return _abstain(self, "passing_test_precedes_latest_write")
        if last_diff_attempt > last_passing_test:
            return _abstain(self, "post_test_diff_already_attempted")
        if last_commit > last_passing_test:
            return _abstain(self, "post_test_commit_already_completed")
        return _match(
            self,
            action=action,
            summary="Inspect the final diff after the verified passing test.",
            reason="verified_test_requires_final_diff",
        )


class DeterministicResolverRegistry:
    """Fail-closed versioned resolver registry with ambiguity detection."""

    policy_version = 1

    def __init__(
        self,
        resolvers: tuple[DeterministicBrainResolver, ...] = (),
    ) -> None:
        seen: set[tuple[str, int]] = set()
        normalized: list[DeterministicBrainResolver] = []
        for resolver in resolvers:
            resolver_id = str(getattr(resolver, "resolver_id", "")).strip().casefold()
            version = getattr(resolver, "resolver_version", None)
            if not resolver_id:
                raise ValueError("resolver_id must not be empty")
            if (
                isinstance(version, bool)
                or not isinstance(version, int)
                or version <= 0
            ):
                raise ValueError("resolver_version must be a positive integer")
            key = (resolver_id, version)
            if key in seen:
                raise ValueError(
                    f"duplicate deterministic resolver: {resolver_id}.v{version}"
                )
            seen.add(key)
            normalized.append(resolver)
        self._resolvers = tuple(normalized)

    def digest(self) -> str:
        payload = [
            {
                "resolver_id": str(resolver.resolver_id).strip().casefold(),
                "resolver_version": int(resolver.resolver_version),
            }
            for resolver in self._resolvers
        ]
        return hashlib.sha256(
            json.dumps(
                {
                    "policy_version": self.policy_version,
                    "resolvers": payload,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    def candidate_count(
        self,
        *,
        facts: GlobalBrainRouteFacts,
        request: BrainRequest,
        all_steps: tuple[WorkStep, ...],
    ) -> int:
        return sum(
            resolver.resolve(
                facts=facts,
                request=request,
                all_steps=all_steps,
            ).matched
            for resolver in self._resolvers
        )

    def resolve(
        self,
        *,
        facts: GlobalBrainRouteFacts,
        request: BrainRequest,
        all_steps: tuple[WorkStep, ...],
    ) -> DeterministicResolution:
        matches = tuple(
            result
            for resolver in self._resolvers
            if (
                result := resolver.resolve(
                    facts=facts,
                    request=request,
                    all_steps=all_steps,
                )
            ).matched
        )
        if not matches:
            return DeterministicResolution(
                status=DeterministicResolutionStatus.ABSTAIN,
                resolver_id="registry",
                resolver_version=self.policy_version,
                reason_codes=("no_deterministic_match",),
            )
        if len(matches) > 1:
            return DeterministicResolution(
                status=DeterministicResolutionStatus.ABSTAIN,
                resolver_id="registry",
                resolver_version=self.policy_version,
                reason_codes=("ambiguous_multiple_matches",),
            )
        return matches[0]


def default_work_deterministic_resolvers() -> DeterministicResolverRegistry:
    return DeterministicResolverRegistry(
        (
            InitialDevelopmentWorkspaceResolver(),
            InitialDiagnosticIncidentResolver(),
            PostTestDevelopmentDiffResolver(),
        )
    )
