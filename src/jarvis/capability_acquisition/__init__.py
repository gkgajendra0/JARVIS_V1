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
from .candidate_actions import (
    CapabilityBindSubstrateExecutor,
    CapabilityCandidateActionError,
    CapabilityManifestContextExecutor,
    build_capability_candidate_executors,
    capability_candidate_completion_guard,
)
from .candidate_models import CapabilityAcquisitionCandidateEvidenceV1
from .candidate_verification import (
    CapabilityAcquisitionCandidateError,
    CapabilityAcquisitionCandidateVerifier,
    CapabilityAcquisitionDevelopmentCompletionHandler,
    CapabilityAcquisitionProtectedSurfacePolicy,
    ensure_capability_acquisition_candidate_current,
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
    "CapabilityAcquisitionCandidateError",
    "CapabilityAcquisitionCandidateEvidenceV1",
    "CapabilityAcquisitionCandidateVerifier",
    "CapabilityAcquisitionCoordinator",
    "CapabilityAcquisitionDevelopmentCompletionHandler",
    "CapabilityAcquisitionDevelopmentRevisionResolver",
    "CapabilityAcquisitionPlanV1",
    "CapabilityAcquisitionProtectedSurfacePolicy",
    "CapabilityAcquisitionResolver",
    "CapabilityAcquisitionSourceCompletionHandler",
    "CapabilityBindSubstrateExecutor",
    "CapabilityCandidateActionError",
    "CapabilityManifestContextExecutor",
    "CapabilityRuntimeAcquisitionContextProvider",
    "CapabilitySourceAdapter",
    "CapabilitySourceRegistry",
    "CustomBuildCapabilitySourceAdapter",
    "ExistingCapabilitySourceAdapter",
    "McpCapabilitySourceAdapter",
    "OWNER_CAPABILITY_ACQUISITION_PROCESS",
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
    "build_capability_candidate_executors",
    "capability_candidate_completion_guard",
    "ensure_capability_acquisition_architecture_current",
    "ensure_capability_acquisition_candidate_current",
    "mcp_server_evidence",
    "openapi_contract_evidence",
    "owner_configured_evidence",
    "sdk_library_evidence",
]
