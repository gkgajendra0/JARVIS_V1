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
    "acquisition_completion_guard",
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
    "asyncapi_contract_evidence",
    "AsyncApiCapabilitySourceAdapter",
    "build_acquisition_protocol_executors",
    "build_capability_candidate_executors",
    "capability_candidate_completion_guard",
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
    "ensure_capability_acquisition_architecture_current",
    "ensure_capability_acquisition_candidate_current",
    "ExistingCapabilitySourceAdapter",
    "mcp_server_evidence",
    "McpCapabilitySourceAdapter",
    "openapi_contract_evidence",
    "OpenApiCapabilitySourceAdapter",
    "OWNER_CAPABILITY_ACQUISITION_PROCESS",
    "owner_configured_evidence",
    "OwnerCapabilityGoalV1",
    "OwnerConfiguredCapabilitySourceAdapter",
    "sdk_library_evidence",
    "SdkLibraryCapabilitySourceAdapter",
    "SourceEvidenceError",
    "StandardSourceEvidenceV1",
    "StaticAcquisitionContextProvider",
    ]
]