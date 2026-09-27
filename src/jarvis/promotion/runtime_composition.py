"""Production composition for owner-grounded Phase-7 promotion operations."""

from __future__ import annotations

import pathlib
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from jarvis.authority.approval import ApprovalService
from jarvis.authority.audit import SqliteAuditEventStore
from jarvis.authority.local_opa import ManagedOpaServer
from jarvis.authority.permit import PermitRegistry
from jarvis.authority.policy import OpaPolicyEngine
from jarvis.authority.risk import RiskClassifier
from jarvis.authority.service import AuthorityService
from jarvis.authority.strong_approval import StrongApprovalService
from jarvis.authority.types import (
    ActionOrigin,
    AttentionState,
    AuthorityEffect,
    InteractionContext,
    TrustTier,
)
from jarvis.authority.verifier import WindowsHelloVerifier
from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.engineering_change.models import ChangeConflict
from jarvis.engineering_change.store import ChangeStore
from jarvis.engineering_substrate.secrets import (
    CanonicalAuthoritySecretGate,
    SecretBroker,
    SecretLeaseRequest,
    SecretStore,
    build_secret_lease_proposal,
    default_secret_consumer_registry,
)
from jarvis.work.development import DevelopmentWorkspaceManager

from .authority import PromotionAuthorityBridge
from .coordinator import PreparedPromotionReview, PromotionCoordinator
from .github import GitHubPromotionAdapter, GitHubPromotionPolicy
from .github_app import BrokeredGitHubAppClient, GitHubAppConfig
from .merge import PromotionMerger
from .release import DeploymentMetadataStore
from .service import PromotionExecutionResult, PromotionSessionService
from .store import PromotionStore

_GITHUB_CONSUMER = "github.promotion.v1"
_GITHUB_SCOPE = "repository.promotion"


class PromotionRuntimeError(ChangeConflict):
    """Live promotion composition is unavailable or not safely authorized."""


@dataclass(frozen=True, slots=True)
class PromotionRuntimeConfig:
    client_id: str
    installation_id: int
    repository_full_name: str
    secret_id: str
    base_branch: str = "main"
    workflow_file: str = "code-quality.yml"
    expected_ci_app_id: int | None = 15368
    deployment_environment: str = "owner-windows"

    def __post_init__(self) -> None:
        client_id = str(self.client_id).strip()
        repository = str(self.repository_full_name).strip()
        secret_id = str(self.secret_id).strip()
        environment = str(self.deployment_environment).strip()
        if not client_id:
            raise ValueError("promotion GitHub App client_id must not be empty")
        if type(self.installation_id) is not int or self.installation_id <= 0:
            raise ValueError("promotion GitHub App installation_id must be positive")
        if not repository:
            raise ValueError("promotion repository_full_name must not be empty")
        if not secret_id:
            raise ValueError("promotion GitHub App secret_id must not be empty")
        if not environment:
            raise ValueError("promotion deployment_environment must not be empty")
        if self.expected_ci_app_id is not None and (
            type(self.expected_ci_app_id) is not int
            or self.expected_ci_app_id <= 0
        ):
            raise ValueError("expected_ci_app_id must be positive")
        object.__setattr__(self, "client_id", client_id)
        object.__setattr__(self, "repository_full_name", repository)
        object.__setattr__(self, "secret_id", secret_id)
        object.__setattr__(self, "deployment_environment", environment)


@dataclass(slots=True)
class _AuthorityBundle:
    approvals: ApprovalService
    authority: AuthorityService
    verifier: WindowsHelloVerifier
    opa: ManagedOpaServer
    audit: SqliteAuditEventStore

    def close(self) -> None:
        self.opa.close()
        self.audit.close()


def _audit_path() -> pathlib.Path:
    path = (
        pathlib.Path.home()
        / ".jarvis"
        / "authority"
        / "promotion_runtime_audit.sqlite3"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


class PromotionRuntime:
    """Short-lived secure GitHub sessions over canonical Phase-7 state."""

    def __init__(
        self,
        changes: ChangeStore,
        workspace_manager: DevelopmentWorkspaceManager,
        deployment_metadata: DeploymentMetadataStore,
        config: PromotionRuntimeConfig,
        *,
        secret_store: SecretStore | None = None,
    ) -> None:
        if not isinstance(changes, ChangeStore):
            raise TypeError("changes must be ChangeStore")
        if not isinstance(workspace_manager, DevelopmentWorkspaceManager):
            raise TypeError("workspace_manager must be DevelopmentWorkspaceManager")
        if not isinstance(deployment_metadata, DeploymentMetadataStore):
            raise TypeError("deployment_metadata must be DeploymentMetadataStore")
        if not isinstance(config, PromotionRuntimeConfig):
            raise TypeError("config must be PromotionRuntimeConfig")
        self._changes = changes
        self._promotions = PromotionStore(changes)
        self._workspace = workspace_manager
        self._deployment = deployment_metadata
        self._config = config
        self._secret_store = secret_store

    @staticmethod
    def _latest_owner_turn(session: ConversationSession):
        if not isinstance(session, ConversationSession):
            raise TypeError("session must be ConversationSession")
        turn = next(
            (
                item
                for item in reversed(session.turns)
                if item.role is ConversationRole.USER
            ),
            None,
        )
        if turn is None or not any(item is turn for item in session.turns):
            raise PromotionRuntimeError("promotion requires a canonical owner turn")
        return turn

    @contextmanager
    def _authority_bundle(self) -> Iterator[_AuthorityBundle]:
        audit = SqliteAuditEventStore(_audit_path())
        opa = ManagedOpaServer()
        bundle: _AuthorityBundle | None = None
        try:
            opa.start()
            approvals = ApprovalService()
            authority = AuthorityService(
                risk_classifier=RiskClassifier(),
                policy_engine=OpaPolicyEngine(endpoint=opa.endpoint),
                approvals=approvals,
                audit_store=audit,
                permits=PermitRegistry(),
            )
            bundle = _AuthorityBundle(
                approvals=approvals,
                authority=authority,
                verifier=WindowsHelloVerifier(),
                opa=opa,
                audit=audit,
            )
            yield bundle
        finally:
            if bundle is None:
                opa.close()
                audit.close()
            else:
                bundle.close()

    @staticmethod
    def _context(session_id: str) -> InteractionContext:
        return InteractionContext(
            session_id=session_id,
            trust_tier=TrustTier.VERIFIED_OWNER,
            attention_state=AttentionState.ATTENTIVE,
            actor_unambiguous=True,
            windows_session_valid=True,
        )

    def _candidate_work_id(self, change_id: str) -> str:
        change = self._changes.require(change_id)
        kind = (
            "capability_candidate"
            if change.process_key == "owner_capability_acquisition"
            else "source_repair_candidate"
        )
        candidate = self._changes.latest_artifact(change_id, kind)
        if candidate is None:
            raise PromotionRuntimeError("verified promotion candidate is unavailable")
        work_id = str(candidate.payload.get("development_work_id") or "").strip()
        if not work_id:
            raise PromotionRuntimeError("promotion candidate has no development work")
        return work_id

    def _secret_store_instance(self) -> SecretStore:
        if self._secret_store is None:
            self._secret_store = SecretStore()
        return self._secret_store

    def _issue_github_lease(
        self,
        *,
        bundle: _AuthorityBundle,
        session: ConversationSession,
        change_id: str,
    ) -> tuple[SecretBroker, str]:
        turn = self._latest_owner_turn(session)
        work_id = self._candidate_work_id(change_id)
        request = SecretLeaseRequest(
            secret_id=self._config.secret_id,
            consumer_id=_GITHUB_CONSUMER,
            scopes=(_GITHUB_SCOPE,),
            ttl_seconds=300.0,
            use_budget=1,
            change_id=change_id,
            work_id=work_id,
        )
        proposal = build_secret_lease_proposal(
            request,
            session_id=session.session_id,
            origin=ActionOrigin.DIRECT_USER,
        )
        strong = StrongApprovalService(
            approvals=bundle.approvals,
            verifier=bundle.verifier,
        ).verify_and_resolve(
            proposal=proposal,
            session_id=session.session_id,
        )
        if not strong.granted or not strong.verification.is_bound_to(
            proposal=proposal,
            session_id=session.session_id,
        ):
            raise PromotionRuntimeError(
                "strong owner verification required for GitHub credential use"
            )
        context = self._context(session.session_id)
        decision = bundle.authority.evaluate(
            proposal=proposal,
            context=context,
            approval_id=strong.approval.approval_id,
        )
        if decision.effect is not AuthorityEffect.ALLOW:
            raise PromotionRuntimeError(
                "Authority rejected GitHub promotion credential use"
            )
        if decision.execution_permit is None:
            raise PromotionRuntimeError(
                "GitHub promotion credential authorization has no execution permit"
            )
        broker = SecretBroker(
            store=self._secret_store_instance(),
            consumers=default_secret_consumer_registry(),
            authority_gate=CanonicalAuthoritySecretGate(bundle.authority),
        )
        lease = broker.issue_lease(
            request,
            proposal=proposal,
            context=context,
            permit_id=decision.execution_permit.permit_id,
        )
        if lease.change_id != change_id or lease.work_id != work_id:
            raise PromotionRuntimeError("GitHub secret lease binding changed")
        if turn is not self._latest_owner_turn(session):
            raise PromotionRuntimeError("owner turn changed during GitHub authorization")
        return broker, lease.lease_id

    @contextmanager
    def _github_session(
        self,
        *,
        session: ConversationSession,
        change_id: str,
    ):
        active = self._deployment.active()
        if active is None:
            raise PromotionRuntimeError(
                "promotion requires an active verified Phase-7 release"
            )
        with self._authority_bundle() as bundle:
            broker, lease_id = self._issue_github_lease(
                bundle=bundle,
                session=session,
                change_id=change_id,
            )
            app_config = GitHubAppConfig(
                client_id=self._config.client_id,
                installation_id=self._config.installation_id,
                repository_full_name=self._config.repository_full_name,
                base_branch=self._config.base_branch,
                workflow_file=self._config.workflow_file,
            )
            with BrokeredGitHubAppClient(
                broker=broker,
                lease_id=lease_id,
                config=app_config,
                release_identity=active.runtime_identity(),
            ) as client:
                yield bundle, GitHubPromotionAdapter(client), active

    def prepare_review(
        self,
        change_id: str,
        *,
        session: ConversationSession,
    ) -> PreparedPromotionReview:
        self._latest_owner_turn(session)
        with self._github_session(session=session, change_id=change_id) as (
            _bundle,
            github,
            active,
        ):
            coordinator = PromotionCoordinator(
                self._changes,
                self._promotions,
                github=github,
                workspace_manager=self._workspace,
                deployment_metadata=self._deployment,
                policy=GitHubPromotionPolicy(
                    expected_app_id=self._config.expected_ci_app_id
                ),
            )
            change = self._changes.require(change_id)
            return coordinator.prepare_review(
                change_id,
                config_digest=active.config_digest,
                deployment_environment=self._config.deployment_environment,
                title=f"JARVIS governed change {change_id}",
                body=(
                    "Exact JARVIS governed candidate for "
                    f"{change.process_key}. Change: {change_id}."
                ),
            )

    def authorize_and_merge(
        self,
        gate_id: str,
        *,
        session: ConversationSession,
    ) -> PromotionExecutionResult:
        turn = self._latest_owner_turn(session)
        from jarvis.engineering_change.gates import GateDecision, GateService

        resolved = GateService(
            self._changes,
            verify_owner=lambda *_: False,
        ).get(gate_id)
        if resolved is None:
            raise PromotionRuntimeError("unknown promotion gate")
        challenge = resolved.challenge if isinstance(resolved, GateDecision) else resolved
        change_id = challenge.change_id
        with self._github_session(session=session, change_id=change_id) as (
            bundle,
            github,
            _active,
        ):
            authority = PromotionAuthorityBridge(
                self._changes,
                self._promotions,
                approvals=bundle.approvals,
                authority=bundle.authority,
                verifier=bundle.verifier,
            )
            merger = PromotionMerger(
                self._changes,
                self._promotions,
                github=github,
                policy=GitHubPromotionPolicy(
                    expected_app_id=self._config.expected_ci_app_id
                ),
                authority=authority,
            )
            service = PromotionSessionService(
                self._changes,
                self._promotions,
                session=session,
                authority=authority,
                merger=merger,
                repository_full_name=self._config.repository_full_name,
            )
            result = service.authorize_and_merge(gate_id)
            if result.gate_decision.source_turn_id != turn.turn_id:
                raise PromotionRuntimeError("promotion approval used a stale owner turn")
            return result
