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
from .standard_sources import (
    AsyncApiCapabilitySourceAdapter,
    CustomBuildCapabilitySourceAdapter,
    McpCapabilitySourceAdapter,
    OpenApiCapabilitySourceAdapter,
    OwnerConfiguredCapabilitySourceAdapter,
    SdkLibraryCapabilitySourceAdapter,
    SourceEvidenceError,
    StandardSourceEvidenceV1,
    asyncapi_contract_evidence,
    mcp_server_evidence,
    openapi_contract_evidence,
    owner_configured_evidence,
    sdk_library_evidence,
)

__all__ = [
    "OWNER_CAPABILITY_ACQUISITION_PROCESS",
    "AcquisitionCandidateEvaluationV1",
    "AcquisitionCandidateV1",
    "AcquisitionContextV1",
    "AcquisitionDisposition",
    "AcquisitionResolutionError",
    "AcquisitionResolutionResult",
    "AcquisitionSourceKind",
    "AcquisitionStrategy",
    "AcquisitionTrustClass",
    "AsyncApiCapabilitySourceAdapter",
    "CapabilityAcquisitionPlanV1",
    "CapabilityAcquisitionResolver",
    "CapabilitySourceAdapter",
    "CapabilitySourceRegistry",
    "CustomBuildCapabilitySourceAdapter",
    "ExistingCapabilitySourceAdapter",
    "McpCapabilitySourceAdapter",
    "OpenApiCapabilitySourceAdapter",
    "OwnerCapabilityGoalV1",
    "OwnerConfiguredCapabilitySourceAdapter",
    "SdkLibraryCapabilitySourceAdapter",
    "SourceEvidenceError",
    "StandardSourceEvidenceV1",
    "asyncapi_contract_evidence",
    "mcp_server_evidence",
    "openapi_contract_evidence",
    "owner_configured_evidence",
    "sdk_library_evidence",
]
