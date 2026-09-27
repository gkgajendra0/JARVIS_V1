"""Phase-9 owner-requested capability acquisition contracts."""

from .admission import (
    CapabilityAcquisitionAdmission,
    CapabilityAcquisitionAdmissionDisposition,
    CapabilityAcquisitionCoordinator,
)
from .architecture import (
    CapabilityAcquisitionArchitectureError,
    CapabilityAcquisitionDevelopmentRevisionResolver,
    CapabilityAcquisitionSourceCompletionHandler,
    ensure_capability_acquisition_architecture_current,
)
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
from .runtime_context import (
    AcquisitionContextProvider,
    CapabilityRuntimeAcquisitionContextProvider,
    StaticAcquisitionContextProvider,
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
from .workflow import (
    AcquisitionProtocolError,
    AcquisitionWorkContextResolver,
    acquisition_completion_guard,
    build_acquisition_protocol_executors,
)

__all__ = [
    "OWNER_CAPABILITY_ACQUISITION_PROCESS",
    "AcquisitionCandidateEvaluationV1",
    "AcquisitionCandidateV1",
    "AcquisitionContextProvider",
    "AcquisitionContextV1",
    "AcquisitionDisposition",
    "AcquisitionProtocolError",
    "AcquisitionResolutionError",
    "AcquisitionResolutionResult",
    "AcquisitionSourceKind",
    "AcquisitionStrategy",
    "AcquisitionTrustClass",
    "AcquisitionWorkContextResolver",
    "AsyncApiCapabilitySourceAdapter",
    "CapabilityAcquisitionAdmission",
    "CapabilityAcquisitionAdmissionDisposition",
    "CapabilityAcquisitionArchitectureError",
    "CapabilityAcquisitionCoordinator",
    "CapabilityAcquisitionDevelopmentRevisionResolver",
    "CapabilityAcquisitionPlanV1",
    "CapabilityAcquisitionResolver",
    "CapabilityAcquisitionSourceCompletionHandler",
    "CapabilityRuntimeAcquisitionContextProvider",
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
    "StaticAcquisitionContextProvider",
    "acquisition_completion_guard",
    "asyncapi_contract_evidence",
    "build_acquisition_protocol_executors",
    "ensure_capability_acquisition_architecture_current",
    "mcp_server_evidence",
    "openapi_contract_evidence",
    "owner_configured_evidence",
    "sdk_library_evidence",
]
