from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Protocol, TypeVar

from jarvis.authority import (
    ActionAttributes,
    ActionOrigin,
    ActionProposal,
    ApprovalStatus,
    AuthorityEffect,
    AuthorityService,
    InteractionContext,
    StrongApprovalService,
    TrustTier,
)
from jarvis.authority.session import AuthoritySession

from .store import OwnerProfileNotFound, SqliteOwnerProfileStore
from .types import OWNER_PROFILE_ID, OwnerProfile, TemplateInput

_T = TypeVar("_T")


class OwnerProfileLifecycleError(RuntimeError):
    pass


class OwnerProfileAuthorizationDenied(OwnerProfileLifecycleError):
    pass


class AuthoritySessionProvider(Protocol):
    def current_session(self) -> AuthoritySession: ...


@dataclass(frozen=True, slots=True)
class OwnerProfileMutationResult:
    operation: str
    proposal_id: str
    proposal_fingerprint: str
    profile: OwnerProfile | None


class OwnerProfileLifecycleService:
    """Strong-verifier-gated create/replace/delete OWNER lifecycle."""

    def __init__(
        self,
        *,
        store: SqliteOwnerProfileStore,
        strong_approval: StrongApprovalService,
        authority: AuthorityService,
        session_provider: AuthoritySessionProvider,
    ) -> None:
        self._store = store
        self._strong_approval = strong_approval
        self._authority = authority
        self._session_provider = session_provider

    def create_owner(
        self,
        templates: Iterable[TemplateInput],
    ) -> OwnerProfileMutationResult:
        items = tuple(templates)
        return self._execute(
            operation="create_owner",
            templates=items,
            mutation=lambda: self._store.create_owner(items),
        )

    def replace_owner(
        self,
        templates: Iterable[TemplateInput],
    ) -> OwnerProfileMutationResult:
        items = tuple(templates)
        return self._execute(
            operation="replace_owner",
            templates=items,
            mutation=lambda: self._store.replace_owner(items),
        )

    def delete_owner(self) -> OwnerProfileMutationResult:
        def delete() -> None:
            if not self._store.delete_owner():
                raise OwnerProfileNotFound("OWNER profile is not enrolled")

        return self._execute(
            operation="delete_owner",
            templates=(),
            mutation=delete,
        )

    def _execute(
        self,
        *,
        operation: str,
        templates: tuple[TemplateInput, ...],
        mutation: Callable[[], _T],
    ) -> OwnerProfileMutationResult:
        session = self._session_provider.current_session()
        if not session.active_unlocked:
            raise OwnerProfileAuthorizationDenied(
                "Windows session is not active/unlocked"
            )

        proposal = self._proposal(
            session_id=session.session_id,
            operation=operation,
            templates=templates,
        )
        outcome = self._strong_approval.verify_and_resolve(
            proposal=proposal,
            session_id=session.session_id,
        )
        if outcome.approval.status is not ApprovalStatus.GRANTED:
            raise OwnerProfileAuthorizationDenied(
                f"strong verification did not grant approval: "
                f"{outcome.approval.status.value}"
            )

        context = InteractionContext(
            session_id=session.session_id,
            trust_tier=TrustTier.VERIFIED_OWNER,
            actor_unambiguous=True,
            windows_session_valid=True,
        )
        decision = self._authority.evaluate(
            proposal=proposal,
            context=context,
            approval_id=outcome.approval.approval_id,
        )
        if (
            decision.effect is not AuthorityEffect.ALLOW
            or decision.execution_permit is None
        ):
            raise OwnerProfileAuthorizationDenied(
                f"authority denied OWNER profile mutation: {decision.reason_codes}"
            )

        current = self._session_provider.current_session()
        if current.session_id != session.session_id or not current.active_unlocked:
            self._authority.invalidate_session(session.session_id)
            raise OwnerProfileAuthorizationDenied(
                "Windows session changed before OWNER profile mutation"
            )

        self._authority.revalidate_and_consume(
            permit_id=decision.execution_permit.permit_id,
            proposal=proposal,
            context=context,
        )
        profile = mutation()
        return OwnerProfileMutationResult(
            operation=operation,
            proposal_id=proposal.proposal_id,
            proposal_fingerprint=proposal.fingerprint,
            profile=profile if isinstance(profile, OwnerProfile) else None,
        )

    @staticmethod
    def _proposal(
        *,
        session_id: str,
        operation: str,
        templates: tuple[TemplateInput, ...],
    ) -> ActionProposal:
        manifests = [item.metadata.manifest_view() for item in templates]
        commitments = [
            {
                "modality": item.metadata.modality.value,
                "sha256": hashlib.sha256(item.payload).hexdigest(),
            }
            for item in templates
        ]
        summary = {
            "create_owner": "Enroll this local biometric profile as JARVIS OWNER",
            "replace_owner": "Replace the enrolled JARVIS OWNER biometric profile",
            "delete_owner": "Delete the enrolled JARVIS OWNER biometric profile",
        }[operation]
        return ActionProposal.create(
            session_id=session_id,
            capability="identity_profile",
            operation=operation,
            target={"subject": OWNER_PROFILE_ID},
            parameters={
                "template_manifests": manifests,
                "template_commitments": commitments,
            },
            material_summary=summary,
            attributes=ActionAttributes(
                persistent_write=True,
                identity_profile_change=True,
            ),
            origin=ActionOrigin.DIRECT_USER,
            ttl_seconds=120.0,
        )
