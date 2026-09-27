"""Registered EngineeringChange process contract for Phase-6 incident repair."""

from jarvis.engineering_change.models import (
    ProcessContract,
    ProcessStageContract,
    ProcessStageRole,
)
from jarvis.work.models import WorkType

UNKNOWN_INCIDENT_REPAIR_PROCESS = ProcessContract(
    key="unknown_incident_repair",
    version=1,
    stages=(
        ProcessStageContract(
            stage_key="diagnostics",
            work_type=WorkType.DIAGNOSTICS,
            role=ProcessStageRole.ARCHITECTURE_SOURCE,
        ),
        ProcessStageContract(
            stage_key="development",
            work_type=WorkType.DEVELOPMENT,
            role=ProcessStageRole.DEVELOPMENT,
        ),
    ),
)
