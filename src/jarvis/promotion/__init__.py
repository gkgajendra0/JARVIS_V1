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
from .merge import MergeResult, PromotionMergeError, PromotionMerger
from .models import (
    CheckEvidence,
    CompatibilityEvidence,
    CompatibilityVerdict,
    PromotionAttempt,
    PromotionAttemptState,
    PromotionEvidenceV1,
)
from .store import PromotionStore

__all__ = [
    "AuthorizedPromotion",
    "CheckEvidence",
    "CompatibilityAssessment",
    "CompatibilityEvidence",
    "CompatibilityVerdict",
    "GitHubPromotionAdapter",
    "GitHubPromotionError",
    "GitHubPromotionPolicy",
    "GitHubPullRequestSnapshot",
    "GitHubWorkflowSnapshot",
    "MergeResult",
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
    "StalePromotionCandidate",
    "VerifiedGitHubEvidence",
    "VerifiedPromotionCandidate",
    "assess_ordinary_compatibility",
]
