from __future__ import annotations

from jarvis.capabilities.models import CapabilityRequest, CapabilityStatus
from jarvis.capabilities.system_reads import SystemReadExecutor


def _request(executor: SystemReadExecutor, operation: str, parameters: dict) -> CapabilityRequest:
    return CapabilityRequest(
        session_id="system-read-verification",
        capability_key=executor.capability_key,
        operation=operation,
        parameters=parameters,
    )


def test_system_status_emits_positive_verification_marker() -> None:
    executor = SystemReadExecutor()

    result = executor.execute(executor.prepare(_request(executor, "system_status", {})))

    assert result.status is CapabilityStatus.SUCCEEDED
    assert result.data["verification_passed"] is True


def test_process_listing_emits_positive_verification_marker() -> None:
    executor = SystemReadExecutor()

    result = executor.execute(
        executor.prepare(_request(executor, "list_processes", {"max_results": 1}))
    )

    assert result.status is CapabilityStatus.SUCCEEDED
    assert result.data["verification_passed"] is True
