"""Governed Phase-7 promotion, deployment, observation, and rollback."""

from .authority import (
    AuthorizedPromotion,
    PromotionAuthorizationError,
    PromotionAuthorityBridge,
)
from .candidate import (
    PromotionCandidateError,
    PromotionCandidateVerifier,
    StalePromotionCandidate,
    VerifiedPromotionCandidate,
)
from .compatibility import CompatibilityAssessment, assess_ordinary_compatibility
from .evidence import PreparedPromotionEvidence, PromotionEvidenceBuilder
from .github import (
    GitHubPromotionAdapter,
    GitHubPromotionError,
    GitHubPromotionPolicy,
    GitHubPullRequestSnapshot,
    GitHubWorkflowSnapshot,
    VerifiedGitHubEvidence,
)
from .deployment import (
    DeploymentCoordinator,
    DeploymentError,
    DeploymentResult,
    RuntimeDeploymentDriver,
)
from .merge import MergeResult, PromotionMergeError, PromotionMerger
from .observation import (
    FailureAttribution,
    ObservationAssessment,
    ObservationController,
    ObservationDisposition,
)
from .models import (
    CheckEvidence,
    CompatibilityEvidence,
    CompatibilityVerdict,
    PromotionAttempt,
    PromotionAttemptState,
    PromotionEvidenceV1,
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
from .store import PromotionStore

__all__ = [
    "AuthorizedPromotion",
    "CheckEvidence",
    "CompatibilityAssessment",
    "CompatibilityEvidence",
    "CompatibilityVerdict",
    "DeploymentCoordinator",
    "DeploymentError",
    "DeploymentMetadataStore",
    "DeploymentResult",
    "GitHubPromotionAdapter",
    "GitHubPromotionError",
    "GitHubPromotionPolicy",
    "GitHubPullRequestSnapshot",
    "GitHubWorkflowSnapshot",
    "GitReleaseStager",
    "FailureAttribution",
    "MergeResult",
    "ObservationAssessment",
    "ObservationController",
    "ObservationDisposition",
    "PreparedPromotionEvidence",
    "PromotionAttempt",
    "PromotionAttemptState",
    "PromotionAuthorizationError",
    "PromotionAuthorityBridge",
    "PromotionCandidateError",
    "PromotionCandidateVerifier",
    "PromotionEvidenceBuilder",
    "PromotionMergeError",
    "PromotionMerger",
    "PromotionEvidenceV1",
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
