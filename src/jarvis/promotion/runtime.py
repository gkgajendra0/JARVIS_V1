"""Production composition for owner-driven Phase-7 promotion from JARVIS voice."""

from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass
from typing import Mapping

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
from jarvis.dev_control import RuntimeReleaseIdentity
from jarvis.engineering_change.gates import GateDecision, GateService
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
from jarvis.promotion.authority import PromotionAuthorityBridge
from jarvis.promotion.coordinator import PreparedPromotionReview, PromotionCoordinator
from jarvis.promotion.github import GitHubPromotionAdapter, GitHubPromotionPolicy
from jarvis.promotion.github_app import BrokeredGitHubAppClient, GitHubAppConfig
from jarvis.promotion.merge import PromotionMerger
from jarvis.promotion.release import DeploymentMetadataStore
from jarvis.promotion.service import PromotionExecutionResult, PromotionSessionService
from jarvis.promotion.store import PromotionStore
from jarvis.work.development import DevelopmentWorkspaceManager

_GITHUB_CONSUMER = "github.promotion.v1"
_GITHUB_SCOPE = "repository.promotion"


class PromotionRuntimeError(ChangeConflict):
    """Production promotion runtime is unavailable or cannot authorize exact work."""


@dataclass(frozen=True, slots=True)
class PromotionRuntimeConfig:
    client_id: str
    installation_id: int
    repository_full_name: str
    private_key_secret_id: str
    base_branch: str = "main"
    workflow_file: str = "code-quality.yml"
    deployment_environment: str = "owner-windows"

    def __post_init__(self) -> None:
        if not str(self.private_key_secret_id).strip():
            raise ValueError("private_key_secret_id must not be empty")
        if not str(self.deployment_environment).strip():
            raise ValueError("deployment_environment must not be empty")
        GitHubAppConfig(
            client_id=self.client_id,
            installation_id=self.installation_id,
            repository_full_name=self.repository_full_name,
            base_branch=self.base_branch,
            workflow_file=self.workflow_file,
        )

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> PromotionRuntimeConfig | None:
        env = os.environ if environment is None else environment
        keys = {
            "client_id": str(env.get("JARVIS_GITHUB_APP_CLIENT_ID", "")).strip(),
            "installation_id": str(
                env.get("JARVIS_GITHUB_APP_INSTALLATION_ID", "")
            ).strip(),
            "repository_full_name": str(
                env.get("JARVIS_GITHUB_REPOSITORY", "")
            ).strip(),
            "private_key_secret_id": str(
                env.get("JARVIS_GITHUB_APP_SECRET_ID", "")
            ).strip(),
        }
        configured = tuple(bool(value) for value in keys.values())
        if not any(configured):
            return None
        if not all(configured):
            missing = ", ".join(name for name, value in keys.items() if not value)
            raise PromotionRuntimeError(
                "partial GitHub promotion configuration; missing " + missing
            )
        try:
            installation_id = int(keys["installation_id"])
        except ValueError as exc:
            raise PromotionRuntimeError(
                "JARVIS_GITHUB_APP_INSTALLATION_ID must be an integer"
            ) from exc
        return cls(
            client_id=keys["client_id"],
            installation_id=installation_id,
            repository_full_name=keys["repository_full_name"],
            private_key_secret_id=keys["private_key_secret_id"],
            base_branch=str(env.get("JARVIS_GITHUB_BASE_BRANCH", "main")).strip()
            or "main",
            workflow_file=str(
                env.get("JARVIS_GITHUB_WORKFLOW_FILE", "code-quality.yml")
            ).strip()
            or "code-quality.yml",
            deployment_environment=str(
                env.get("JARVIS_DEPLOYMENT_ENVIRONMENT", "owner-windows")
            ).strip()
            or "owner-windows",
        )

    def github(self) -> GitHubAppConfig:
        return GitHubAppConfig(
            client_id=self.client_id,
            installation_id=self.installation_id,
            repository_full_name=self.repository_full_name,
            base_branch=self.base_branch,
            workflow_file=self.workflow_file,
        )


def _audit_path() -> pathlib.Path:
    configured = os.getenv("JARVIS_AUTHORITY_AUDIT_DB", "").strip()
    if configured:
        base = pathlib.Path(configured).expanduser()
        return base.with_name(
            f"{base.stem}.promotion{base.suffix or '.sqlite3'}"
        )
    return (
        pathlib.Path.home()
        / ".jarvis"
        / "authority"
        / "promotion_audit.sqlite3"
    )


class _PromotionAuthorityRuntime:
    """Short-lived Authority/OPA/SecretBroker bundle for one owner action."""

    def __init__(self) -> None:
        audit_path = _audit_path()
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        self.audit = SqliteAuditEventStore(audit_path)
        self.opa = ManagedOpaServer()
        try:
            self.opa.start()
            self.approvals = ApprovalService()
            self.authority = AuthorityService(
                risk_classifier=RiskClassifier(),
                policy_engine=OpaPolicyEngine(endpoint=self.opa.endpoint),
                approvals=self.approvals,
                audit_store=self.audit,
                permits=PermitRegistry(),
            )
            self.verifier = WindowsHelloVerifier()
            self.strong = StrongApprovalService(
                approvals=self.approvals,
                verifier=self.verifier,
            )
            self.broker = SecretBroker(
                store=SecretStore(),
                consumers=default_secret_consumer_registry(),
                authority_gate=CanonicalAuthoritySecretGate(self.authority),
            )
        except Exception:
            self.opa.close()
            self.audit.close()
            raise

    def close(self) -> None:
        self.broker.invalidate_all()
        self.opa.close()
        self.audit.close()

    def issue_github_lease(
        self,
        config: PromotionRuntimeConfig,
        *,
        session: ConversationSession,
        change_id: str,
        work_id: str,
    ):
        turn = next(
            (
                item
                for item in reversed(session.turns)
                if item.role is ConversationRole.USER
            ),
            None,
        )
        if turn is None:
            raise PromotionRuntimeError("no canonical owner turn for GitHub lease")
        request = SecretLeaseRequest(
            secret_id=config.private_key_secret_id,
            consumer_id=_GITHUB_CONSUMER,
            scopes=(_GITHUB_SCOPE,),
            ttl_seconds=120.0,
            use_budget=1,
            change_id=change_id,
            work_id=work_id,
        )
        proposal = build_secret_lease_proposal(
            request,
            session_id=session.session_id,
            origin=ActionOrigin.DIRECT_USER,
        )
        outcome = self.strong.verify_and_resolve(
            proposal=proposal,
            session_id=session.session_id,
            ttl_seconds=60.0,
        )
        if not outcome.granted:
            raise PromotionRuntimeError(
                "strong owner verification required for GitHub App secret lease"
            )
        context = InteractionContext(
            session_id=session.session_id,
            trust_tier=TrustTier.VERIFIED_OWNER,
            attention_state=AttentionState.ATTENTIVE,
            actor_unambiguous=True,
        )
        decision = self.authority.evaluate(
            proposal=proposal,
            context=context,
            approval_id=outcome.approval.approval_id,
        )
        if decision.effect is not AuthorityEffect.ALLOW or decision.execution_permit is None:
            raise PromotionRuntimeError(
                "canonical Authority denied GitHub App secret lease"
            )
        return self.broker.issue_lease(
            request,
            proposal=proposal,
            context=context,
            permit_id=decision.execution_permit.permit_id,
        )


class PromotionRuntimeService:
    """Thin production adapter over the accepted Phase-7 promotion domain."""

    def __init__(
        self,
        changes: ChangeStore,
        *,
        workspace_manager: DevelopmentWorkspaceManager,
        deployment_metadata: DeploymentMetadataStore,
        release_identity: RuntimeReleaseIdentity,
        config: PromotionRuntimeConfig,
    ) -> None:
        if not isinstance(changes, ChangeStore):
            raise TypeError("changes must be ChangeStore")
        if not isinstance(workspace_manager, DevelopmentWorkspaceManager):
            raise TypeError("workspace_manager must be DevelopmentWorkspaceManager")
        if not isinstance(deployment_metadata, DeploymentMetadataStore):
            raise TypeError("deployment_metadata must be DeploymentMetadataStore")
        if not isinstance(release_identity, RuntimeReleaseIdentity):
            raise TypeError("release_identity must be RuntimeReleaseIdentity")
        if not isinstance(config, PromotionRuntimeConfig):
            raise TypeError("config must be PromotionRuntimeConfig")
        self._changes = changes
        self._promotions = PromotionStore(changes)
        self._workspace = workspace_manager
        self._metadata = deployment_metadata
        self._release_identity = release_identity
        self.config = config

    @property
    def promotions(self) -> PromotionStore:
        return self._promotions

    def _development_work_id(self, change_id: str) -> str:
        change = self._changes.require(change_id)
        candidate_kind = (
            "capability_candidate"
            if change.process_key == "owner_capability_acquisition"
            else "source_repair_candidate"
        )
        candidate = self._changes.latest_artifact(change_id, candidate_kind)
        work_id = (
            "" if candidate is None else str(
                candidate.payload.get("development_work_id") or ""
            ).strip()
        )
        if not work_id:
            raise PromotionRuntimeError(
                "promotion requires current verified development candidate"
            )
        return work_id

    def prepare_review(
        self,
        change_id: str,
        *,
        session: ConversationSession,
        title: str,
        body: str,
    ) -> PreparedPromotionReview:
        work_id = self._development_work_id(change_id)
        runtime = _PromotionAuthorityRuntime()
        try:
            lease = runtime.issue_github_lease(
                self.config,
                session=session,
                change_id=change_id,
                work_id=work_id,
            )
            client = BrokeredGitHubAppClient(
                broker=runtime.broker,
                lease_id=lease.lease_id,
                config=self.config.github(),
                release_identity=self._release_identity,
            )
            with client:
                coordinator = PromotionCoordinator(
                    self._changes,
                    self._promotions,
                    github=GitHubPromotionAdapter(client),
                    workspace_manager=self._workspace,
                    deployment_metadata=self._metadata,
                )
                return coordinator.prepare_review(
                    change_id,
                    config_digest=self._release_identity.config_digest,
                    deployment_environment=self.config.deployment_environment,
                    title=title,
                    body=body,
                )
        finally:
            runtime.close()

    def authorize_and_merge(
        self,
        gate_id: str,
        *,
        session: ConversationSession,
    ) -> PromotionExecutionResult:
        gate = GateService(self._changes, verify_owner=lambda *_args: False).get(
            gate_id
        )
        challenge = gate.challenge if isinstance(gate, GateDecision) else gate
        if challenge is None:
            raise PromotionRuntimeError("unknown promotion gate")
        work_id = self._development_work_id(challenge.change_id)
        runtime = _PromotionAuthorityRuntime()
        try:
            lease = runtime.issue_github_lease(
                self.config,
                session=session,
                change_id=challenge.change_id,
                work_id=work_id,
            )
            client = BrokeredGitHubAppClient(
                broker=runtime.broker,
                lease_id=lease.lease_id,
                config=self.config.github(),
                release_identity=self._release_identity,
            )
            with client:
                github = GitHubPromotionAdapter(client)
                policy = GitHubPromotionPolicy()
                authority = PromotionAuthorityBridge(
                    self._changes,
                    self._promotions,
                    approvals=runtime.approvals,
                    authority=runtime.authority,
                    verifier=runtime.verifier,
                )
                merger = PromotionMerger(
                    self._changes,
                    self._promotions,
                    github=github,
                    policy=policy,
                    authority=authority,
                )
                service = PromotionSessionService(
                    self._changes,
                    self._promotions,
                    session=session,
                    authority=authority,
                    merger=merger,
                    repository_full_name=self.config.repository_full_name,
                )
                return service.authorize_and_merge(gate_id)
        finally:
            runtime.close()
