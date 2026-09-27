from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from jarvis.incident_repair.models import ReproductionState
from jarvis.incident_repair.reproduction import (
    COVERAGE_VERSION,
    PYRIGHT_VERSION,
    DiagnosticReproductionEvidence,
    DiagnosticRunReproductionExecutor,
    _classify_pytest_returncode,
    diagnostic_verifier_requirements,
)
from jarvis.incident_repair.static_analysis import (
    DiagnosticStaticCheckExecutor,
    StaticDiagnosticEvidence,
)
from jarvis.work.engine import WorkOwnerInputRequired
from jarvis.work.models import WorkItem, WorkType


class FakeWorkspaceManager:
    def __init__(self, path) -> None:
        self.path = path

    def assert_pristine(self, work_id: str):
        assert work_id
        return SimpleNamespace(path=self.path, revision="a" * 40)


class FakeStaticRunner:
    async def run(self, workspace, *, targets, timeout_seconds):
        assert workspace.is_dir()
        assert targets == ("src/jarvis/example.py",)
        assert timeout_seconds == 42.0
        return StaticDiagnosticEvidence(
            available=True,
            returncode=1,
            version=PYRIGHT_VERSION,
            diagnostics=(
                {
                    "file": "src/jarvis/example.py",
                    "severity": "error",
                    "message": "typed error",
                    "range": None,
                    "rule": "reportAssignmentType",
                },
            ),
            summary={"errorCount": 1},
            reason_codes=("static_check_completed",),
            output='{"version":"test"}',
            sandbox_profile="diagnostic.static.v1",
            sandbox_profile_version=1,
        )


def _work() -> WorkItem:
    return WorkItem(
        request="diagnose incident",
        work_type=WorkType.DIAGNOSTICS,
        source_session_id="incident:1",
        source_turn_id="revision:a",
    )


def test_pytest_returncode_classification_is_truthful() -> None:
    assert _classify_pytest_returncode(1) is ReproductionState.REPRODUCED
    assert _classify_pytest_returncode(0) is ReproductionState.NOT_REPRODUCED
    assert _classify_pytest_returncode(2) is ReproductionState.INCONCLUSIVE
    assert _classify_pytest_returncode(5) is ReproductionState.INCONCLUSIVE


def test_reproduction_evidence_identity_is_canonical() -> None:
    first = DiagnosticReproductionEvidence.create(
        reproduction_state=ReproductionState.REPRODUCED,
        pytest_returncode=1,
        coverage_returncode=0,
        targets=("tests/test_fault.py::test_repro",),
        coverage_files=(),
        output="one failed",
        sandbox_profile="diagnostic.reproduction.v1",
        sandbox_profile_version=1,
        reason_codes=("pytest_failure_reproduced",),
    )
    second = DiagnosticReproductionEvidence.create(
        reproduction_state=ReproductionState.REPRODUCED,
        pytest_returncode=1,
        coverage_returncode=0,
        targets=("tests/test_fault.py::test_repro",),
        coverage_files=(),
        output="one failed",
        sandbox_profile="diagnostic.reproduction.v1",
        sandbox_profile_version=1,
        reason_codes=("pytest_failure_reproduced",),
    )

    assert first == second
    assert first.evidence_id == f"reproduction_{first.digest[:16]}"
    assert len(first.digest) == 64
    assert first.network == "disabled"
    assert first.workspace_mode == "read_only"


def test_verifier_requirements_are_exact_and_phase5_broker_compatible() -> None:
    requirements = diagnostic_verifier_requirements(
        change_id="change-1",
        work_id="work-1",
    )

    assert [item.package_name for item in requirements] == [
        "coverage",
        "pyright",
    ]
    assert requirements[0].version_constraint == f"=={COVERAGE_VERSION}"
    assert requirements[1].version_constraint == f"=={PYRIGHT_VERSION}"
    assert all(
        item.registered_source_ids == ("pypi.public.v1",)
        for item in requirements
    )
    assert all(item.change_id == "change-1" for item in requirements)
    assert all(item.work_id == "work-1" for item in requirements)


def test_reproduction_without_approved_runner_requires_owner_input(tmp_path) -> None:
    executor = DiagnosticRunReproductionExecutor(
        FakeWorkspaceManager(tmp_path),
        None,
    )

    with pytest.raises(
        WorkOwnerInputRequired,
        match="Safe diagnostic reproduction is not configured",
    ):
        asyncio.run(
            executor.execute(
                work=_work(),
                parameters={"targets": ["tests/test_fault.py"]},
            )
        )


def test_static_check_evidence_id_is_deterministic(tmp_path) -> None:
    executor = DiagnosticStaticCheckExecutor(
        FakeWorkspaceManager(tmp_path),
        FakeStaticRunner(),
    )
    parameters = {
        "targets": ["src/jarvis/example.py"],
        "timeout_seconds": 42,
    }

    first = asyncio.run(executor.execute(work=_work(), parameters=parameters))
    second = asyncio.run(executor.execute(work=_work(), parameters=parameters))

    assert first == second
    assert first["available"] is True
    assert first["evidence_id"].startswith("pyright_")
    assert len(first["digest"]) == 64
    assert first["diagnostics"][0]["rule"] == "reportAssignmentType"


def test_static_check_without_image_is_explicitly_unavailable(tmp_path) -> None:
    executor = DiagnosticStaticCheckExecutor(
        FakeWorkspaceManager(tmp_path),
        None,
    )
    result = asyncio.run(
        executor.execute(
            work=_work(),
            parameters={"targets": ["src/jarvis/example.py"]},
        )
    )

    assert result["available"] is False
    assert result["reason_codes"] == ["diagnostic_image_not_configured"]
    assert result["requirement_id"] == "phase6.pyright.v1"
