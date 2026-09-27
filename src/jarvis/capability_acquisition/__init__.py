"""Phase-9 owner-requested capability acquisition contracts."""

from .models import (
    AcquisitionCandidateEvaluationV1,
    AcquisitionCandidateV1,
    AcquisitionDisposition,
    AcquisitionSourceKind,
    AcquisitionStrategy,
    AcquisitionTrustClass,
    CapabilityAcquisitionPlanV1,
    OwnerCapabilityGoalV1,
)
from .process import OWNER_CAPABILITY_ACQUISITION_PROCESS
from .resolver import (
    AcquisitionResolutionError,
    AcquisitionResolutionResult,
    CapabilityAcquisitionResolver,
)
from .source import (
    AcquisitionContextV1,
    CapabilitySourceAdapter,
    CapabilitySourceRegistry,
    ExistingCapabilitySourceAdapter,
)

__all__ = [
    "OWNER_CAPABILITY_ACQUISITION_PROCESS",
    "AcquisitionCandidateEvaluationV1",
    "AcquisitionCandidateV1",
    "AcquisitionDisposition",
    "AcquisitionSourceKind",
    "AcquisitionStrategy",
    "AcquisitionTrustClass",
    "CapabilityAcquisitionPlanV1",
    "OwnerCapabilityGoalV1",
    "AcquisitionContextV1",
    "AcquisitionResolutionError",
    "AcquisitionResolutionResult",
    "CapabilityAcquisitionResolver",
    "CapabilitySourceAdapter",
    "CapabilitySourceRegistry",
    "ExistingCapabilitySourceAdapter",
]
