"""Registered EngineeringChange process for Phase-9 capability acquisition."""

from jarvis.engineering_change.models import (
    ProcessContract,
    ProcessStageContract,
    ProcessStageRole,
)
from jarvis.work.models import WorkType

OWNER_CAPABILITY_ACQUISITION_PROCESS = ProcessContract(
    key="owner_capability_acquisition",
    version=1,
    stages=(
        ProcessStageContract(
            stage_key="acquisition",
            work_type=WorkType.RESEARCH,
            role=ProcessStageRole.ARCHITECTURE_SOURCE,
        ),
        ProcessStageContract(
            stage_key="development",
            work_type=WorkType.DEVELOPMENT,
            role=ProcessStageRole.DEVELOPMENT,
        ),
    ),
)
