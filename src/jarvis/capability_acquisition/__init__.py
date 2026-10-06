from .hardening import (
    CapabilitySystemInvariantCode,
    CapabilitySystemInvariantFindingV1,
    CapabilitySystemInvariantReportV1,
    assert_capability_system_invariants,
    inspect_capability_system_invariants,
)
"""Phase-9 owner-requested capability acquisition contracts."""

from .activation import (
    CapabilityAcquisitionLifecycleCoordinator,
    CapabilityAcquisitionLifecycleError,
    CapabilityAcquisitionLifecycleResult,
)
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
from .evaluation import (
    Phase9ReplayCase,
    Phase9ReplayReport,
    RealCapabilityEvidenceError,
    build_real_capability_evidence,
    validate_real_capability_evidence,
)
from .evaluation import run_replay_suite as run_phase9_replay_suite
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
from .promotion import (
    CapabilityAcquisitionReleaseBridge,
    CapabilityAcquisitionReleaseBridgeError,
    CapabilityAcquisitionReleaseBridgeResult,
    CapabilityLifecycleProposalV1,
    ensure_capability_release_bridge_current,
)
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
from .target_compatibility import (
    CandidateTargetCompatibilityV1,
    TargetCompatibilityVerdict,
    evaluate_candidate_target_compatibility,
)
from .verification import (
    CapabilityAcquisitionDevelopmentCompletionHandler,
    CapabilityCandidateError,
    CapabilityCandidateEvidenceV1,
    CapabilityCandidateVerification,
    CapabilityCandidateVerifier,
    ensure_capability_candidate_acceptance_current,
    ensure_capability_substrate_requirements_current,
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
    "CandidateTargetCompatibilityV1",
    "CapabilityAcquisitionAdmission",
    "CapabilityAcquisitionAdmissionDisposition",
    "CapabilityAcquisitionArchitectureError",
    "CapabilityAcquisitionCoordinator",
    "CapabilityAcquisitionDevelopmentCompletionHandler",
    "CapabilityAcquisitionDevelopmentRevisionResolver",
    "CapabilityAcquisitionLifecycleCoordinator",
    "CapabilityAcquisitionLifecycleError",
    "CapabilityAcquisitionLifecycleResult",
    "CapabilityAcquisitionPlanV1",
    "CapabilityAcquisitionReleaseBridge",
    "CapabilityAcquisitionReleaseBridgeError",
    "CapabilityAcquisitionReleaseBridgeResult",
    "CapabilityAcquisitionResolver",
    "CapabilityAcquisitionSourceCompletionHandler",
    "CapabilityCandidateError",
    "CapabilityCandidateEvidenceV1",
    "CapabilityCandidateVerification",
    "CapabilityCandidateVerifier",
    "CapabilityLifecycleProposalV1",
    "CapabilityRuntimeAcquisitionContextProvider",
    "CapabilitySourceAdapter",
    "CapabilitySourceRegistry",
    "CustomBuildCapabilitySourceAdapter",
    "ExistingCapabilitySourceAdapter",
    "McpCapabilitySourceAdapter",
    "OpenApiCapabilitySourceAdapter",
    "OwnerCapabilityGoalV1",
    "OwnerConfiguredCapabilitySourceAdapter",
    "Phase9ReplayCase",
    "Phase9ReplayReport",
    "RealCapabilityEvidenceError",
    "SdkLibraryCapabilitySourceAdapter",
    "SourceEvidenceError",
    "StandardSourceEvidenceV1",
    "StaticAcquisitionContextProvider",
    "TargetCompatibilityVerdict",
    "acquisition_completion_guard",
    "asyncapi_contract_evidence",
    "build_acquisition_protocol_executors",
    "build_real_capability_evidence",
    "ensure_capability_acquisition_architecture_current",
    "ensure_capability_candidate_acceptance_current",
    "ensure_capability_release_bridge_current",
    "ensure_capability_substrate_requirements_current",
    "evaluate_candidate_target_compatibility",
    "mcp_server_evidence",
    "openapi_contract_evidence",
    "owner_configured_evidence",
    "run_phase9_replay_suite",
    "sdk_library_evidence",
    "validate_real_capability_evidence",
]
