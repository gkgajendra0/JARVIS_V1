"""Deterministic cloud-reasoning admission for governed development."""

from __future__ import annotations

from collections.abc import Iterable

from jarvis.engineering_substrate.canonical import canonical_digest

from .contracts import DevelopmentTicketV1

DEVELOPMENT_REASONING_POLICY_VERSION = 1


def _refs(values: Iterable[str], *, field: str) -> list[str]:
    normalized = [str(value).strip() for value in values]
    if any(not value for value in normalized):
        raise ValueError(f"{field} values must not be empty")
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field} values must be unique")
    return sorted(normalized)


def build_development_reasoning_fingerprint(
    ticket: DevelopmentTicketV1,
    *,
    evidence_refs: Iterable[str] = (),
    failure_refs: Iterable[str] = (),
    progress_digest: str | None = None,
    tool_contract_version: int = 1,
) -> str:
    """Hash every fact that may justify a new expensive engineering turn.

    The fingerprint is intentionally provider-neutral. If it is unchanged and a
    reusable DevelopmentResult already exists, JARVIS can reuse that durable result
    instead of spending another cloud reasoning turn.
    """

    if not isinstance(ticket, DevelopmentTicketV1):
        raise TypeError("ticket must be DevelopmentTicketV1")
    if type(tool_contract_version) is not int or tool_contract_version < 1:
        raise ValueError("tool_contract_version must be a positive integer")
    normalized_progress = None
    if progress_digest is not None:
        normalized_progress = str(progress_digest).strip().casefold()
        if len(normalized_progress) != 64 or any(
            char not in "0123456789abcdef" for char in normalized_progress
        ):
            raise ValueError("progress_digest must be a lowercase SHA-256 digest")
    return canonical_digest(
        {
            "policy_version": DEVELOPMENT_REASONING_POLICY_VERSION,
            "ticket_digest": ticket.digest,
            "evidence_refs": _refs(evidence_refs, field="evidence_ref"),
            "failure_refs": _refs(failure_refs, field="failure_ref"),
            "progress_digest": normalized_progress,
            "tool_contract_version": tool_contract_version,
        }
    )
