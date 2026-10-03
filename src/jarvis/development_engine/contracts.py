"""Canonical provider-neutral contracts for governed engineering development."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from jarvis.engineering_substrate.canonical import canonical_digest

DEVELOPMENT_ENGINE_CONTRACT_VERSION = 1

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA1 = re.compile(r"^[0-9a-f]{40}$")


def _text(value: object, *, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


def _optional_text(value: object | None, *, field: str) -> str | None:
    if value is None:
        return None
    return _text(value, field=field)


def _digest(value: object, *, field: str) -> str:
    normalized = _text(value, field=field).casefold()
    if _SHA256.fullmatch(normalized) is None:
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return normalized


def _git_revision(value: object, *, field: str) -> str:
    normalized = _text(value, field=field).casefold()
    if _GIT_SHA1.fullmatch(normalized) is None:
        raise ValueError(f"{field} must be a full lowercase Git SHA-1")
    return normalized


def _optional_git_revision(value: object | None, *, field: str) -> str | None:
    if value is None:
        return None
    return _git_revision(value, field=field)


def _tokens(
    values: tuple[str, ...] | list[str],
    *,
    field: str,
    require_nonempty: bool = False,
    normalize: bool = False,
) -> tuple[str, ...]:
    normalized = tuple(
        (
            _text(value, field=field).casefold()
            if normalize
            else _text(value, field=field)
        )
        for value in values
    )
    if require_nonempty and not normalized:
        raise ValueError(f"{field} requires at least one value")
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field} values must be unique")
    return tuple(sorted(normalized))


class DevelopmentDisposition(StrEnum):
    """Typed outcome from an engineering specialist.

    JARVIS maps these outcomes into canonical lifecycle transitions. The
    DevelopmentEngine itself owns no EngineeringChange state transition.
    """

    COMPLETED = "completed"
    NEEDS_RESEARCH = "needs_research"
    NEEDS_ARCHITECTURE_REVISION = "needs_architecture_revision"
    NEEDS_DEPENDENCY = "needs_dependency"
    BLOCKED_RESOURCE = "blocked_resource"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class DevelopmentUsageV1:
    """Observed provider usage for one development result when available."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    def __post_init__(self) -> None:
        for field_name in ("input_tokens", "output_tokens", "total_tokens"):
            value = getattr(self, field_name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        if self.total_tokens and self.total_tokens < self.input_tokens + self.output_tokens:
            raise ValueError(
                "total_tokens cannot be smaller than input_tokens + output_tokens"
            )

    def canonical_payload(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass(frozen=True, slots=True)
class DevelopmentTicketV1:
    """Immutable engineering assignment admitted by the JARVIS control plane."""

    ticket_id: str
    request: str
    work_id: str
    engineering_change_id: str
    goal_id: str
    goal_digest: str
    architecture_artifact_id: str
    architecture_digest: str
    base_revision: str
    workspace_id: str
    required_operations: tuple[str, ...]
    dependency_refs: tuple[str, ...]
    secret_scopes: tuple[str, ...]
    discovery_scopes: tuple[str, ...]
    research_evidence_refs: tuple[str, ...]
    repository_context_refs: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    attempt: int
    contract_version: int
    digest: str

    @classmethod
    def create(
        cls,
        *,
        request: str,
        work_id: str,
        engineering_change_id: str,
        goal_id: str,
        goal_digest: str,
        architecture_artifact_id: str,
        architecture_digest: str,
        base_revision: str,
        workspace_id: str,
        required_operations: tuple[str, ...] | list[str],
        acceptance_criteria: tuple[str, ...] | list[str],
        allowed_tools: tuple[str, ...] | list[str],
        dependency_refs: tuple[str, ...] | list[str] = (),
        secret_scopes: tuple[str, ...] | list[str] = (),
        discovery_scopes: tuple[str, ...] | list[str] = (),
        research_evidence_refs: tuple[str, ...] | list[str] = (),
        repository_context_refs: tuple[str, ...] | list[str] = (),
        attempt: int = 1,
    ) -> DevelopmentTicketV1:
        if type(attempt) is not int or attempt < 1:
            raise ValueError("attempt must be a positive integer")
        payload: dict[str, object] = {
            "request": _text(request, field="request"),
            "work_id": _text(work_id, field="work_id"),
            "engineering_change_id": _text(
                engineering_change_id,
                field="engineering_change_id",
            ),
            "goal_id": _text(goal_id, field="goal_id"),
            "goal_digest": _digest(goal_digest, field="goal_digest"),
            "architecture_artifact_id": _text(
                architecture_artifact_id,
                field="architecture_artifact_id",
            ),
            "architecture_digest": _digest(
                architecture_digest,
                field="architecture_digest",
            ),
            "base_revision": _git_revision(
                base_revision,
                field="base_revision",
            ),
            "workspace_id": _text(workspace_id, field="workspace_id"),
            "required_operations": list(
                _tokens(
                    tuple(required_operations),
                    field="required_operation",
                    require_nonempty=True,
                    normalize=True,
                )
            ),
            "dependency_refs": list(
                _tokens(tuple(dependency_refs), field="dependency_ref")
            ),
            "secret_scopes": list(
                _tokens(
                    tuple(secret_scopes),
                    field="secret_scope",
                    normalize=True,
                )
            ),
            "discovery_scopes": list(
                _tokens(
                    tuple(discovery_scopes),
                    field="discovery_scope",
                    normalize=True,
                )
            ),
            "research_evidence_refs": list(
                _tokens(
                    tuple(research_evidence_refs),
                    field="research_evidence_ref",
                )
            ),
            "repository_context_refs": list(
                _tokens(
                    tuple(repository_context_refs),
                    field="repository_context_ref",
                )
            ),
            "acceptance_criteria": list(
                _tokens(
                    tuple(acceptance_criteria),
                    field="acceptance_criterion",
                    require_nonempty=True,
                )
            ),
            "allowed_tools": list(
                _tokens(
                    tuple(allowed_tools),
                    field="allowed_tool",
                    require_nonempty=True,
                    normalize=True,
                )
            ),
            "attempt": attempt,
            "contract_version": DEVELOPMENT_ENGINE_CONTRACT_VERSION,
        }
        digest = canonical_digest(payload)
        return cls(
            ticket_id=f"dev_ticket_{digest[:16]}",
            request=str(payload["request"]),
            work_id=str(payload["work_id"]),
            engineering_change_id=str(payload["engineering_change_id"]),
            goal_id=str(payload["goal_id"]),
            goal_digest=str(payload["goal_digest"]),
            architecture_artifact_id=str(payload["architecture_artifact_id"]),
            architecture_digest=str(payload["architecture_digest"]),
            base_revision=str(payload["base_revision"]),
            workspace_id=str(payload["workspace_id"]),
            required_operations=tuple(payload["required_operations"]),  # type: ignore[arg-type]
            dependency_refs=tuple(payload["dependency_refs"]),  # type: ignore[arg-type]
            secret_scopes=tuple(payload["secret_scopes"]),  # type: ignore[arg-type]
            discovery_scopes=tuple(payload["discovery_scopes"]),  # type: ignore[arg-type]
            research_evidence_refs=tuple(  # type: ignore[arg-type]
                payload["research_evidence_refs"]
            ),
            repository_context_refs=tuple(  # type: ignore[arg-type]
                payload["repository_context_refs"]
            ),
            acceptance_criteria=tuple(payload["acceptance_criteria"]),  # type: ignore[arg-type]
            allowed_tools=tuple(payload["allowed_tools"]),  # type: ignore[arg-type]
            attempt=attempt,
            contract_version=DEVELOPMENT_ENGINE_CONTRACT_VERSION,
            digest=digest,
        )

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, object],
        *,
        expected_digest: str | None = None,
    ) -> DevelopmentTicketV1:
        """Rebuild and verify a ticket from canonical durable payload."""

        ticket = cls.create(
            request=str(payload["request"]),
            work_id=str(payload["work_id"]),
            engineering_change_id=str(payload["engineering_change_id"]),
            goal_id=str(payload["goal_id"]),
            goal_digest=str(payload["goal_digest"]),
            architecture_artifact_id=str(payload["architecture_artifact_id"]),
            architecture_digest=str(payload["architecture_digest"]),
            base_revision=str(payload["base_revision"]),
            workspace_id=str(payload["workspace_id"]),
            required_operations=tuple(payload["required_operations"]),  # type: ignore[arg-type]
            dependency_refs=tuple(payload["dependency_refs"]),  # type: ignore[arg-type]
            secret_scopes=tuple(payload["secret_scopes"]),  # type: ignore[arg-type]
            discovery_scopes=tuple(payload["discovery_scopes"]),  # type: ignore[arg-type]
            research_evidence_refs=tuple(  # type: ignore[arg-type]
                payload["research_evidence_refs"]
            ),
            repository_context_refs=tuple(  # type: ignore[arg-type]
                payload["repository_context_refs"]
            ),
            acceptance_criteria=tuple(payload["acceptance_criteria"]),  # type: ignore[arg-type]
            allowed_tools=tuple(payload["allowed_tools"]),  # type: ignore[arg-type]
            attempt=int(payload["attempt"]),
        )
        version = int(payload["contract_version"])
        if version != DEVELOPMENT_ENGINE_CONTRACT_VERSION:
            raise ValueError("unsupported durable development ticket version")
        if expected_digest is not None:
            expected = _digest(expected_digest, field="expected ticket digest")
            if ticket.digest != expected:
                raise ValueError("durable development ticket digest mismatch")
        return ticket

    def canonical_payload(self) -> dict[str, object]:
        return {
            "request": self.request,
            "work_id": self.work_id,
            "engineering_change_id": self.engineering_change_id,
            "goal_id": self.goal_id,
            "goal_digest": self.goal_digest,
            "architecture_artifact_id": self.architecture_artifact_id,
            "architecture_digest": self.architecture_digest,
            "base_revision": self.base_revision,
            "workspace_id": self.workspace_id,
            "required_operations": list(self.required_operations),
            "dependency_refs": list(self.dependency_refs),
            "secret_scopes": list(self.secret_scopes),
            "discovery_scopes": list(self.discovery_scopes),
            "research_evidence_refs": list(self.research_evidence_refs),
            "repository_context_refs": list(self.repository_context_refs),
            "acceptance_criteria": list(self.acceptance_criteria),
            "allowed_tools": list(self.allowed_tools),
            "attempt": self.attempt,
            "contract_version": self.contract_version,
        }

    def __post_init__(self) -> None:
        if self.contract_version != DEVELOPMENT_ENGINE_CONTRACT_VERSION:
            raise ValueError("unsupported development ticket contract version")
        _digest(self.digest, field="ticket digest")
        if self.ticket_id != f"dev_ticket_{self.digest[:16]}":
            raise ValueError("ticket_id must be derived from ticket digest")
        if canonical_digest(self.canonical_payload()) != self.digest:
            raise ValueError("development ticket digest mismatch")


@dataclass(frozen=True, slots=True)
class DevelopmentResultV1:
    """Typed engineering outcome; lifecycle authority remains with JARVIS."""

    result_id: str
    ticket_id: str
    ticket_digest: str
    disposition: DevelopmentDisposition
    engine_id: str
    engine_version: str
    summary: str
    reason: str | None
    thread_id: str | None
    candidate_revision: str | None
    changed_files: tuple[str, ...]
    test_evidence_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    requested_dependencies: tuple[str, ...]
    blocker_code: str | None
    usage: DevelopmentUsageV1 | None
    contract_version: int
    digest: str

    @classmethod
    def create(
        cls,
        *,
        ticket: DevelopmentTicketV1,
        disposition: DevelopmentDisposition,
        engine_id: str,
        engine_version: str,
        summary: str,
        reason: str | None = None,
        thread_id: str | None = None,
        candidate_revision: str | None = None,
        changed_files: tuple[str, ...] | list[str] = (),
        test_evidence_refs: tuple[str, ...] | list[str] = (),
        evidence_refs: tuple[str, ...] | list[str] = (),
        requested_dependencies: tuple[str, ...] | list[str] = (),
        blocker_code: str | None = None,
        usage: DevelopmentUsageV1 | None = None,
    ) -> DevelopmentResultV1:
        if not isinstance(ticket, DevelopmentTicketV1):
            raise TypeError("ticket must be DevelopmentTicketV1")
        if not isinstance(disposition, DevelopmentDisposition):
            raise TypeError("disposition must be DevelopmentDisposition")
        reason_text = _optional_text(reason, field="reason")
        candidate = _optional_git_revision(
            candidate_revision,
            field="candidate_revision",
        )
        tests = _tokens(tuple(test_evidence_refs), field="test_evidence_ref")
        evidence = _tokens(tuple(evidence_refs), field="evidence_ref")
        dependencies = _tokens(
            tuple(requested_dependencies),
            field="requested_dependency",
        )
        blocker = _optional_text(blocker_code, field="blocker_code")
        if usage is not None and not isinstance(usage, DevelopmentUsageV1):
            raise TypeError("usage must be DevelopmentUsageV1")

        if disposition is DevelopmentDisposition.COMPLETED:
            if candidate is None:
                raise ValueError("completed development requires candidate_revision")
            if not tests:
                raise ValueError("completed development requires test evidence")
            if reason_text is not None or blocker is not None or dependencies:
                raise ValueError(
                    "completed development cannot carry blocker/dependency fields"
                )
        else:
            if not reason_text:
                raise ValueError("non-completed development requires a reason")
            if disposition is DevelopmentDisposition.NEEDS_ARCHITECTURE_REVISION:
                if not evidence:
                    raise ValueError(
                        "architecture revision requires exact evidence references"
                    )
            if disposition is DevelopmentDisposition.NEEDS_DEPENDENCY:
                if not dependencies:
                    raise ValueError(
                        "dependency disposition requires requested_dependencies"
                    )
            if disposition is DevelopmentDisposition.BLOCKED_RESOURCE:
                if blocker is None:
                    raise ValueError(
                        "blocked-resource disposition requires blocker_code"
                    )

        payload: dict[str, object] = {
            "ticket_id": ticket.ticket_id,
            "ticket_digest": ticket.digest,
            "disposition": disposition.value,
            "engine_id": _text(engine_id, field="engine_id").casefold(),
            "engine_version": _text(engine_version, field="engine_version"),
            "summary": _text(summary, field="summary"),
            "reason": reason_text,
            "thread_id": _optional_text(thread_id, field="thread_id"),
            "candidate_revision": candidate,
            "changed_files": list(
                _tokens(tuple(changed_files), field="changed_file")
            ),
            "test_evidence_refs": list(tests),
            "evidence_refs": list(evidence),
            "requested_dependencies": list(dependencies),
            "blocker_code": blocker,
            "usage": None if usage is None else usage.canonical_payload(),
            "contract_version": DEVELOPMENT_ENGINE_CONTRACT_VERSION,
        }
        digest = canonical_digest(payload)
        return cls(
            result_id=f"dev_result_{digest[:16]}",
            ticket_id=ticket.ticket_id,
            ticket_digest=ticket.digest,
            disposition=disposition,
            engine_id=str(payload["engine_id"]),
            engine_version=str(payload["engine_version"]),
            summary=str(payload["summary"]),
            reason=reason_text,
            thread_id=payload["thread_id"] if isinstance(payload["thread_id"], str) else None,
            candidate_revision=candidate,
            changed_files=tuple(payload["changed_files"]),  # type: ignore[arg-type]
            test_evidence_refs=tests,
            evidence_refs=evidence,
            requested_dependencies=dependencies,
            blocker_code=blocker,
            usage=usage,
            contract_version=DEVELOPMENT_ENGINE_CONTRACT_VERSION,
            digest=digest,
        )

    @classmethod
    def from_payload(
        cls,
        *,
        ticket: DevelopmentTicketV1,
        payload: dict[str, object],
        expected_digest: str | None = None,
    ) -> DevelopmentResultV1:
        """Rebuild and verify one durable DevelopmentResult."""

        raw_usage = payload.get("usage")
        usage = None
        if raw_usage is not None:
            if not isinstance(raw_usage, dict):
                raise TypeError("durable development usage must be an object")
            usage = DevelopmentUsageV1(
                input_tokens=int(raw_usage.get("input_tokens", 0)),
                output_tokens=int(raw_usage.get("output_tokens", 0)),
                total_tokens=int(raw_usage.get("total_tokens", 0)),
            )
        result = cls.create(
            ticket=ticket,
            disposition=DevelopmentDisposition(str(payload["disposition"])),
            engine_id=str(payload["engine_id"]),
            engine_version=str(payload["engine_version"]),
            summary=str(payload["summary"]),
            reason=(
                None
                if payload.get("reason") is None
                else str(payload["reason"])
            ),
            thread_id=(
                None
                if payload.get("thread_id") is None
                else str(payload["thread_id"])
            ),
            candidate_revision=(
                None
                if payload.get("candidate_revision") is None
                else str(payload["candidate_revision"])
            ),
            changed_files=tuple(payload.get("changed_files") or ()),  # type: ignore[arg-type]
            test_evidence_refs=tuple(  # type: ignore[arg-type]
                payload.get("test_evidence_refs") or ()
            ),
            evidence_refs=tuple(payload.get("evidence_refs") or ()),  # type: ignore[arg-type]
            requested_dependencies=tuple(  # type: ignore[arg-type]
                payload.get("requested_dependencies") or ()
            ),
            blocker_code=(
                None
                if payload.get("blocker_code") is None
                else str(payload["blocker_code"])
            ),
            usage=usage,
        )
        if str(payload.get("ticket_id") or "") != ticket.ticket_id:
            raise ValueError("durable result ticket_id mismatch")
        if str(payload.get("ticket_digest") or "") != ticket.digest:
            raise ValueError("durable result ticket_digest mismatch")
        version = int(payload["contract_version"])
        if version != DEVELOPMENT_ENGINE_CONTRACT_VERSION:
            raise ValueError("unsupported durable development result version")
        if expected_digest is not None:
            expected = _digest(expected_digest, field="expected result digest")
            if result.digest != expected:
                raise ValueError("durable development result digest mismatch")
        return result

    def canonical_payload(self) -> dict[str, object]:
        return {
            "ticket_id": self.ticket_id,
            "ticket_digest": self.ticket_digest,
            "disposition": self.disposition.value,
            "engine_id": self.engine_id,
            "engine_version": self.engine_version,
            "summary": self.summary,
            "reason": self.reason,
            "thread_id": self.thread_id,
            "candidate_revision": self.candidate_revision,
            "changed_files": list(self.changed_files),
            "test_evidence_refs": list(self.test_evidence_refs),
            "evidence_refs": list(self.evidence_refs),
            "requested_dependencies": list(self.requested_dependencies),
            "blocker_code": self.blocker_code,
            "usage": None if self.usage is None else self.usage.canonical_payload(),
            "contract_version": self.contract_version,
        }

    def __post_init__(self) -> None:
        if self.contract_version != DEVELOPMENT_ENGINE_CONTRACT_VERSION:
            raise ValueError("unsupported development result contract version")
        _digest(self.ticket_digest, field="ticket_digest")
        _digest(self.digest, field="result digest")
        if self.result_id != f"dev_result_{self.digest[:16]}":
            raise ValueError("result_id must be derived from result digest")
        if canonical_digest(self.canonical_payload()) != self.digest:
            raise ValueError("development result digest mismatch")
