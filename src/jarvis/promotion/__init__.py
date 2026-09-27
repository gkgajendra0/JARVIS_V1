"""Governed Phase-7 promotion, deployment, observation, and rollback."""

from .authority import (
    AuthorizedPromotion,
    PromotionAuthorityBridge,
    PromotionAuthorizationError,
)
from .candidate import (
    PromotionCandidateError,
    PromotionCandidateVerifier,
    StalePromotionCandidate,
    VerifiedPromotionCandidate,
)
from .compatibility import CompatibilityAssessment, assess_ordinary_compatibility
from .coordinator import (
    PreparedPromotionReview,
    PromotionCoordinator,
    PromotionPreparationError,
)
from .deployment import (
    DeploymentCoordinator,
    DeploymentError,
    DeploymentResult,
    RuntimeDeploymentDriver,
)
from .evidence import PreparedPromotionEvidence, PromotionEvidenceBuilder
from .github import (
    GitHubPromotionAdapter,
    GitHubPromotionError,
    GitHubPromotionPolicy,
    GitHubPullRequestSnapshot,
    GitHubWorkflowSnapshot,
    VerifiedGitHubEvidence,
)
from .github_app import BrokeredGitHubAppClient, GitHubAppConfig
from .merge import MergeResult, PromotionMergeError, PromotionMerger
from .models import (
    CheckEvidence,
    CompatibilityEvidence,
    CompatibilityVerdict,
    PromotionAttempt,
    PromotionAttemptState,
    PromotionEvidenceV1,
)
from .observation import (
    FailureAttribution,
    ObservationAssessment,
    ObservationController,
    ObservationDisposition,
)
from .release import (
    DeploymentMetadataStore,
    GitReleaseStager,
    RecoveryPhase,
    RecoveryRecord,
    ReleaseError,
    ReleaseRecord,
)
from .rollback import RollbackCoordinator, RollbackError, RollbackResult
from .service import PromotionExecutionResult, PromotionSessionError, PromotionSessionService
from .store import PromotionStore

__all__ = [
    "AuthorizedPromotion",
    "BrokeredGitHubAppClient",
    "CheckEvidence",
    "CompatibilityAssessment",
    "CompatibilityEvidence",
    "CompatibilityVerdict",
    "DeploymentCoordinator",
    "DeploymentError",
    "DeploymentMetadataStore",
    "DeploymentResult",
    "FailureAttribution",
    "GitHubAppConfig",
    "GitHubPromotionAdapter",
    "GitHubPromotionError",
    "GitHubPromotionPolicy",
    "GitHubPullRequestSnapshot",
    "GitHubWorkflowSnapshot",
    "GitReleaseStager",
    "MergeResult",
    "ObservationAssessment",
    "ObservationController",
    "ObservationDisposition",
    "PreparedPromotionEvidence",
    "PreparedPromotionReview",
    "PromotionAttempt",
    "PromotionAttemptState",
    "PromotionAuthorityBridge",
    "PromotionAuthorizationError",
    "PromotionCandidateError",
    "PromotionCandidateVerifier",
    "PromotionCoordinator",
    "PromotionEvidenceBuilder",
    "PromotionEvidenceV1",
    "PromotionExecutionResult",
    "PromotionMergeError",
    "PromotionMerger",
    "PromotionPreparationError",
    "PromotionSessionError",
    "PromotionSessionService",
    "PromotionStore",
    "RecoveryPhase",
    "RecoveryRecord",
    "ReleaseError",
    "ReleaseRecord",
    "RollbackCoordinator",
    "RollbackError",
    "RollbackResult",
    "RuntimeDeploymentDriver",
    "StalePromotionCandidate",
    "VerifiedGitHubEvidence",
    "VerifiedPromotionCandidate",
    "assess_ordinary_compatibility",
]
