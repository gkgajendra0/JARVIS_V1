from __future__ import annotations

import pytest

from jarvis.incident_repair.models import ProtectedSurfaceVerdict
from jarvis.incident_repair.protected_surfaces import (
    ProtectedSurfacePolicyError,
    RepairProtectedSurfacePolicy,
)


def test_ordinary_source_and_test_paths_are_clear() -> None:
    result = RepairProtectedSurfacePolicy().assess(
        (
            "src/jarvis/voice/runtime.py",
            "tests/test_voice_runtime.py",
        )
    )

    assert result.verdict is ProtectedSurfaceVerdict.CLEAR
    assert result.protected == ()
    assert result.unknown_paths == ()


@pytest.mark.parametrize(
    ("path", "category"),
    [
        ("src/jarvis/authority/service.py", "authority_boundary"),
        ("policies/step3_authority.rego", "authority_policy"),
        ("src/jarvis/engineering_change/gates.py", "engineering_governance"),
        (
            "src/jarvis/engineering_substrate/secrets/broker.py",
            "secret_policy",
        ),
        (
            "src/jarvis/engineering_substrate/sandbox.py",
            "sandbox_policy",
        ),
        (
            "src/jarvis/model_routing/acceptance.py",
            "self_acceptance_or_evaluator",
        ),
        (
            "tests/test_phase5_acceptance_harness.py",
            "self_acceptance_or_evaluator",
        ),
        (".github/workflows/code-quality.yml", "repository_governance_ci"),
    ],
)
def test_protected_paths_require_separate_change(path: str, category: str) -> None:
    result = RepairProtectedSurfacePolicy().assess((path,))

    assert result.verdict is ProtectedSurfaceVerdict.PROTECTED_CHANGE_REQUIRED
    assert result.protected[0].category == category


def test_unclassified_repository_surface_fails_closed() -> None:
    result = RepairProtectedSurfacePolicy().assess(("scripts/release.py",))

    assert result.verdict is ProtectedSurfaceVerdict.UNKNOWN
    assert result.unknown_paths == ("scripts/release.py",)


@pytest.mark.parametrize(
    "path",
    [
        "../outside.py",
        "/absolute.py",
        r"C:\absolute.py",
    ],
)
def test_protected_surface_policy_rejects_non_relative_paths(path: str) -> None:
    with pytest.raises(ProtectedSurfacePolicyError):
        RepairProtectedSurfacePolicy().assess((path,))
