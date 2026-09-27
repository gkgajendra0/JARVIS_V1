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
    "FailureAttribution",
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
    "PromotionAttempt",
    "PromotionAttemptState",
    "PromotionAuthorityBridge",
    "PromotionAuthorizationError",
    "PromotionCandidateError",
    "PromotionCandidateVerifier",
    "PromotionEvidenceBuilder",
    "PromotionEvidenceV1",
    "PromotionMergeError",
    "PromotionMerger",
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
