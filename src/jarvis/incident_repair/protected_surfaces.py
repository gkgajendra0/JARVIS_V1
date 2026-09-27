"""Versioned protected-surface classification for governed source repair."""

from __future__ import annotations

import pathlib
from dataclasses import dataclass
from typing import ClassVar

from .models import ProtectedSurfaceVerdict


class ProtectedSurfacePolicyError(ValueError):
    """A changed path cannot be classified safely."""


@dataclass(frozen=True, slots=True)
class ProtectedPathFinding:
    path: str
    category: str

    def to_payload(self) -> dict[str, str]:
        return {"path": self.path, "category": self.category}


@dataclass(frozen=True, slots=True)
class ProtectedSurfaceAssessment:
    policy_id: str
    policy_version: int
    verdict: ProtectedSurfaceVerdict
    protected: tuple[ProtectedPathFinding, ...]
    unknown_paths: tuple[str, ...]
    clear_paths: tuple[str, ...]

    def to_payload(self) -> dict[str, object]:
        return {
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "verdict": self.verdict.value,
            "protected": [item.to_payload() for item in self.protected],
            "unknown_paths": list(self.unknown_paths),
            "clear_paths": list(self.clear_paths),
        }


class RepairProtectedSurfacePolicy:
    """Deterministic v5 classifier; ambiguous repository surfaces fail closed."""

    policy_id = "repair.protected_surfaces"
    policy_version = 5

    _EXACT_PROTECTED: ClassVar[dict[str, str]] = {
        "pyproject.toml": "repository_build_and_dependency_policy",
        "policies/step3_authority.rego": "authority_policy",
        "src/jarvis/capabilities/authority_bridge.py": "authority_boundary",
        "src/jarvis/capabilities/runtime.py": "capability_lifecycle_governance",
        "src/jarvis/engineering_substrate/sandbox.py": "sandbox_policy",
        "src/jarvis/incident_repair/protected_surfaces.py": "protected_surface_policy",
        "src/jarvis/dev_supervisor.py": "production_deployment_boundary",
        "src/jarvis/runtime_supervisor.py": "production_deployment_boundary",
        "src/jarvis/self_repair/windows_guardian.py": "production_deployment_boundary",
        "src/jarvis/work/dbos_backend.py": "durable_workflow_boundary",
        "src/jarvis/work/store.py": "durable_state_schema_boundary",
        "src/jarvis/incidents/migration_runner.py": "durable_state_schema_boundary",
        "src/jarvis/memory/migration_runner.py": "durable_state_schema_boundary",
        "tools/development-sandbox/dockerfile": "sandbox_policy",
    }
    _PREFIX_PROTECTED = (
        (".github/", "repository_governance_ci"),
        ("policies/", "authority_policy"),
        ("src/jarvis/authority/", "authority_boundary"),
        ("src/jarvis/engineering_change/", "engineering_governance"),
        ("src/jarvis/capability_registry/", "capability_lifecycle_governance"),
        ("src/jarvis/capability_acquisition/", "capability_acquisition_governance"),
        ("src/jarvis/promotion/", "promotion_and_deployment_governance"),
        ("src/jarvis/incidents/migrations/", "durable_state_schema_boundary"),
        ("src/jarvis/memory/migrations/", "durable_state_schema_boundary"),
        ("src/jarvis/engineering_substrate/secrets/", "secret_policy"),
    )
    _PROTECTED_TEST_PREFIXES = (
        "tests/test_authority",
        "tests/test_windows_authority",
        "tests/test_hands_authority",
        "tests/test_memory_service_authority",
        "tests/test_opa_policy",
        "tests/test_engineering_change",
        "tests/test_capability_registry_",
        "tests/test_capability_acquisition_",
        "tests/test_engineering_substrate_sandbox",
        "tests/test_engineering_substrate_secrets",
        "tests/test_phase5_acceptance",
        "tests/test_self_repair_phase5_acceptance",
        "tests/test_phase7_",
        "tests/test_promotion",
    )
    _KNOWN_CLEAR_PREFIXES = (
        "src/jarvis/",
        "tests/",
    )

    @staticmethod
    def normalize_path(value: object) -> str:
        raw = str(value or "").replace("\\", "/").strip()
        pure = pathlib.PurePosixPath(raw)
        windows = pathlib.PureWindowsPath(raw)
        if (
            not raw
            or pure.is_absolute()
            or windows.is_absolute()
            or bool(windows.root)
            or bool(windows.drive)
            or ".." in pure.parts
            or "." in pure.parts
            or raw.startswith("-")
        ):
            raise ProtectedSurfacePolicyError(
                "changed path must be a normalized repository-relative path"
            )
        normalized = pure.as_posix()
        if normalized.startswith("./"):
            normalized = normalized.removeprefix("./")
        return normalized

    @classmethod
    def _protected_category(cls, path: str) -> str | None:
        folded = path.casefold()
        exact = cls._EXACT_PROTECTED.get(folded)
        if exact is not None:
            return exact
        for prefix, category in cls._PREFIX_PROTECTED:
            if folded.startswith(prefix):
                return category

        name = pathlib.PurePosixPath(folded).name
        if folded.startswith("src/jarvis/") and (
            "acceptance" in name or "evaluation" in name
        ):
            return "self_acceptance_or_evaluator"
        if folded.startswith(
            "src/jarvis/engineering_substrate/dependency/"
        ) and name == ("policy.py"):
            return "dependency_policy"
        if folded.startswith("tests/") and (
            "acceptance" in name or "evaluation" in name
        ):
            return "self_acceptance_or_evaluator"
        if any(folded.startswith(prefix) for prefix in cls._PROTECTED_TEST_PREFIXES):
            return "protected_boundary_verifier"
        return None

    @classmethod
    def _known_clear(cls, path: str) -> bool:
        folded = path.casefold()
        return any(folded.startswith(prefix) for prefix in cls._KNOWN_CLEAR_PREFIXES)

    def assess(
        self,
        changed_paths: tuple[str, ...] | list[str],
    ) -> ProtectedSurfaceAssessment:
        normalized = tuple(
            dict.fromkeys(self.normalize_path(item) for item in changed_paths)
        )
        if not normalized:
            raise ProtectedSurfacePolicyError(
                "protected-surface assessment requires changed paths"
            )

        protected: list[ProtectedPathFinding] = []
        unknown: list[str] = []
        clear: list[str] = []
        for path in normalized:
            category = self._protected_category(path)
            if category is not None:
                protected.append(ProtectedPathFinding(path=path, category=category))
            elif self._known_clear(path):
                clear.append(path)
            else:
                unknown.append(path)

        if protected:
            verdict = ProtectedSurfaceVerdict.PROTECTED_CHANGE_REQUIRED
        elif unknown:
            verdict = ProtectedSurfaceVerdict.UNKNOWN
        else:
            verdict = ProtectedSurfaceVerdict.CLEAR
        return ProtectedSurfaceAssessment(
            policy_id=self.policy_id,
            policy_version=self.policy_version,
            verdict=verdict,
            protected=tuple(protected),
            unknown_paths=tuple(unknown),
            clear_paths=tuple(clear),
        )
