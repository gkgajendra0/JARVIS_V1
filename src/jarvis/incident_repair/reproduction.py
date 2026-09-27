"""Network-disabled diagnostic reproduction and coverage evidence for Phase 6."""

from __future__ import annotations

import asyncio
import hashlib
import json
import pathlib
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Any, Protocol

from jarvis.capabilities.local_reads import default_project_root
from jarvis.engineering_knowledge.security import (
    EngineeringEvidenceAdmissionGate,
    EvidenceAdmissionRequest,
)
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.engineering_substrate.contracts import (
    DependencyEcosystem,
    DependencyRequirement,
)
from jarvis.engineering_substrate.sandbox import (
    SandboxMountBinding,
    SandboxPolicyError,
    SandboxResourceUnavailable,
    default_sandbox_registry,
)
from jarvis.incident_repair.models import ReproductionState
from jarvis.observability.redaction import redact_data
from jarvis.work.brain import BrainAction
from jarvis.work.engine import WorkOwnerInputRequired
from jarvis.work.models import WorkItem, WorkType

from .workspace import DiagnosticWorkspaceError, DiagnosticWorkspaceManager

COVERAGE_PACKAGE = "coverage"
COVERAGE_VERSION = "7.16.1"
PYRIGHT_PACKAGE = "pyright"
PYRIGHT_VERSION = "1.1.414"
_MAX_TARGETS = 20
_MAX_TIMEOUT_SECONDS = 300.0
_MAX_OUTPUT_CHARS = 20_000
_MAX_COVERAGE_FILES = 100
_MAX_LINES_PER_FILE = 1000
_MAX_BRANCHES_PER_FILE = 1000


def diagnostic_verifier_requirements(
    *,
    change_id: str | None = None,
    work_id: str | None = None,
) -> tuple[DependencyRequirement, ...]:
    return (
        DependencyRequirement(
            requirement_id="phase6.coverage.v1",
            ecosystem=DependencyEcosystem.PYTHON,
            package_name=COVERAGE_PACKAGE,
            version_constraint=f"=={COVERAGE_VERSION}",
            purpose="Phase-6 statement and branch reproduction evidence",
            registered_source_ids=("pypi.public.v1",),
            change_id=change_id,
            work_id=work_id,
        ),
        DependencyRequirement(
            requirement_id="phase6.pyright.v1",
            ecosystem=DependencyEcosystem.PYTHON,
            package_name=PYRIGHT_PACKAGE,
            version_constraint=f"=={PYRIGHT_VERSION}",
            purpose="Phase-6 optional deterministic Python static diagnostics",
            registered_source_ids=("pypi.public.v1",),
            change_id=change_id,
            work_id=work_id,
        ),
    )


@dataclass(frozen=True, slots=True)
class CoverageFileEvidence:
    path: str
    executed_lines: tuple[int, ...]
    missing_lines: tuple[int, ...]
    executed_branches: tuple[tuple[int, int], ...]
    missing_branches: tuple[tuple[int, int], ...]
    percent_covered: float

    def to_payload(self) -> dict[str, object]:
        return {
            "path": self.path,
            "executed_lines": list(self.executed_lines),
            "missing_lines": list(self.missing_lines),
            "executed_branches": [list(item) for item in self.executed_branches],
            "missing_branches": [list(item) for item in self.missing_branches],
            "percent_covered": self.percent_covered,
        }


@dataclass(frozen=True, slots=True)
class DiagnosticReproductionEvidence:
    evidence_id: str
    reproduction_state: ReproductionState
    pytest_returncode: int
    coverage_returncode: int | None
    targets: tuple[str, ...]
    coverage_files: tuple[CoverageFileEvidence, ...]
    output: str
    output_sha256: str
    sandbox_profile: str
    sandbox_profile_version: int
    network: str
    workspace_mode: str
    reason_codes: tuple[str, ...]
    digest: str

    @classmethod
    def create(
        cls,
        *,
        reproduction_state: ReproductionState,
        pytest_returncode: int,
        coverage_returncode: int | None,
        targets: tuple[str, ...],
        coverage_files: tuple[CoverageFileEvidence, ...],
        output: str,
        sandbox_profile: str,
        sandbox_profile_version: int,
        reason_codes: tuple[str, ...],
    ) -> DiagnosticReproductionEvidence:
        payload = {
            "reproduction_state": reproduction_state.value,
            "pytest_returncode": int(pytest_returncode),
            "coverage_returncode": (
                None if coverage_returncode is None else int(coverage_returncode)
            ),
            "targets": list(targets),
            "coverage_files": [item.to_payload() for item in coverage_files],
            "output": output,
            "output_sha256": hashlib.sha256(output.encode("utf-8")).hexdigest(),
            "sandbox_profile": sandbox_profile,
            "sandbox_profile_version": int(sandbox_profile_version),
            "network": "disabled",
            "workspace_mode": "read_only",
            "reason_codes": list(reason_codes),
        }
        digest = canonical_digest(payload)
        return cls(
            evidence_id=f"reproduction_{digest[:16]}",
            reproduction_state=reproduction_state,
            pytest_returncode=int(pytest_returncode),
            coverage_returncode=(
                None if coverage_returncode is None else int(coverage_returncode)
            ),
            targets=targets,
            coverage_files=coverage_files,
            output=output,
            output_sha256=str(payload["output_sha256"]),
            sandbox_profile=sandbox_profile,
            sandbox_profile_version=int(sandbox_profile_version),
            network="disabled",
            workspace_mode="read_only",
            reason_codes=reason_codes,
            digest=digest,
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "evidence_id": self.evidence_id,
            "reproduction_state": self.reproduction_state.value,
            "pytest_returncode": self.pytest_returncode,
            "coverage_returncode": self.coverage_returncode,
            "targets": list(self.targets),
            "coverage_files": [item.to_payload() for item in self.coverage_files],
            "output": self.output,
            "output_sha256": self.output_sha256,
            "sandbox_profile": self.sandbox_profile,
            "sandbox_profile_version": self.sandbox_profile_version,
            "network": self.network,
            "workspace_mode": self.workspace_mode,
            "reason_codes": list(self.reason_codes),
            "digest": self.digest,
        }


def _normalize_target(value: object) -> str:
    text = str(value or "").strip()
    path_token = text.split("::", 1)[0]
    posix = pathlib.PurePosixPath(path_token)
    windows = pathlib.PureWindowsPath(path_token)
    if (
        not text
        or not path_token
        or posix.is_absolute()
        or windows.is_absolute()
        or bool(windows.root)
        or bool(windows.drive)
        or ".." in posix.parts
        or ".." in windows.parts
        or text.startswith("-")
    ):
        raise DiagnosticWorkspaceError(
            "reproduction target must remain a relative non-option path"
        )
    return text


def _normalize_coverage_path(value: object) -> str | None:
    text = str(value or "").replace("\\", "/").strip()
    if not text:
        return None
    if text.startswith("/workspace/"):
        text = text[len("/workspace/") :]
    pure = pathlib.PurePosixPath(text)
    if pure.is_absolute() or ".." in pure.parts:
        return None
    if not pure.parts or pure.parts[0] not in {"src", "tests"}:
        return None
    return pure.as_posix()


def _bounded_ints(values: object, *, limit: int) -> tuple[int, ...]:
    if not isinstance(values, list):
        return ()
    output: list[int] = []
    for raw in values:
        if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
            continue
        if raw not in output:
            output.append(raw)
        if len(output) >= limit:
            break
    return tuple(output)


def _bounded_branches(
    values: object,
    *,
    limit: int,
) -> tuple[tuple[int, int], ...]:
    if not isinstance(values, list):
        return ()
    output: list[tuple[int, int]] = []
    for raw in values:
        if (
            not isinstance(raw, list)
            or len(raw) != 2
            or any(isinstance(item, bool) or not isinstance(item, int) for item in raw)
        ):
            continue
        pair = (int(raw[0]), int(raw[1]))
        if pair not in output:
            output.append(pair)
        if len(output) >= limit:
            break
    return tuple(output)


def _coverage_evidence(path: pathlib.Path) -> tuple[CoverageFileEvidence, ...]:
    if not path.is_file() or path.stat().st_size > 5_000_000:
        return ()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return ()
    files = payload.get("files")
    if not isinstance(files, dict):
        return ()

    output: list[CoverageFileEvidence] = []
    for raw_path, raw in sorted(files.items(), key=lambda item: str(item[0])):
        normalized = _normalize_coverage_path(raw_path)
        if normalized is None or not isinstance(raw, dict):
            continue
        summary = raw.get("summary")
        percent = 0.0
        if isinstance(summary, dict):
            raw_percent = summary.get("percent_covered")
            if isinstance(raw_percent, int | float) and not isinstance(
                raw_percent, bool
            ):
                percent = float(raw_percent)
        output.append(
            CoverageFileEvidence(
                path=normalized,
                executed_lines=_bounded_ints(
                    raw.get("executed_lines"),
                    limit=_MAX_LINES_PER_FILE,
                ),
                missing_lines=_bounded_ints(
                    raw.get("missing_lines"),
                    limit=_MAX_LINES_PER_FILE,
                ),
                executed_branches=_bounded_branches(
                    raw.get("executed_branches"),
                    limit=_MAX_BRANCHES_PER_FILE,
                ),
                missing_branches=_bounded_branches(
                    raw.get("missing_branches"),
                    limit=_MAX_BRANCHES_PER_FILE,
                ),
                percent_covered=round(percent, 4),
            )
        )
        if len(output) >= _MAX_COVERAGE_FILES:
            break
    return tuple(output)


def _classify_pytest_returncode(returncode: int) -> ReproductionState:
    if returncode == 1:
        return ReproductionState.REPRODUCED
    if returncode == 0:
        return ReproductionState.NOT_REPRODUCED
    return ReproductionState.INCONCLUSIVE


class DiagnosticReproductionRunner(Protocol):
    async def run(
        self,
        workspace: pathlib.Path,
        *,
        targets: tuple[str, ...],
        timeout_seconds: float,
    ) -> DiagnosticReproductionEvidence: ...


class DockerDiagnosticReproductionRunner:
    """Run fixed pytest+Coverage.py inside diagnostic.reproduction.v1."""

    def __init__(
        self,
        image: str,
        *,
        protected_main_root: str | pathlib.Path | None = None,
    ) -> None:
        self.image = str(image or "").strip()
        if not self.image:
            raise ValueError("diagnostic reproduction image must not be empty")
        docker = shutil.which("docker")
        if docker is None:
            raise DiagnosticWorkspaceError("Docker executable is unavailable")
        self._sandbox_registry = default_sandbox_registry(
            docker_executable=docker,
            protected_main_root=pathlib.Path(
                protected_main_root or default_project_root()
            ).resolve(),
        )
        self._gate = EngineeringEvidenceAdmissionGate()

    async def run(
        self,
        workspace: pathlib.Path,
        *,
        targets: tuple[str, ...],
        timeout_seconds: float,
    ) -> DiagnosticReproductionEvidence:
        normalized_targets = tuple(_normalize_target(item) for item in targets)
        if not normalized_targets or len(normalized_targets) > _MAX_TARGETS:
            raise DiagnosticWorkspaceError(
                "diagnostic reproduction requires 1-20 pytest targets"
            )
        timeout = max(1.0, min(float(timeout_seconds), _MAX_TIMEOUT_SECONDS))

        with tempfile.TemporaryDirectory(
            prefix="jarvis-diagnostic-evidence-"
        ) as temporary:
            evidence_root = pathlib.Path(temporary).resolve()
            try:
                launch = self._sandbox_registry.build_launch(
                    profile_id="diagnostic.reproduction.v1",
                    image=self.image,
                    mounts=(
                        SandboxMountBinding("workspace_ro", workspace),
                        SandboxMountBinding("evidence_rw", evidence_root),
                    ),
                    trusted_suffix=normalized_targets,
                    requested_timeout_seconds=timeout,
                )
            except (SandboxPolicyError, SandboxResourceUnavailable) as exc:
                raise DiagnosticWorkspaceError(str(exc)) from exc

            try:
                completed = await asyncio.to_thread(
                    subprocess.run,
                    list(launch.command),
                    cwd=workspace,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=launch.timeout_seconds,
                    check=False,
                    shell=False,
                )
            except subprocess.TimeoutExpired:
                return DiagnosticReproductionEvidence.create(
                    reproduction_state=ReproductionState.INCONCLUSIVE,
                    pytest_returncode=124,
                    coverage_returncode=None,
                    targets=normalized_targets,
                    coverage_files=(),
                    output="diagnostic reproduction timed out",
                    sandbox_profile=launch.profile_id,
                    sandbox_profile_version=launch.profile_version,
                    reason_codes=("reproduction_timeout",),
                )

            combined = (completed.stdout + "\n" + completed.stderr).strip()
            coverage_files = _coverage_evidence(evidence_root / "coverage.json")
            coverage_returncode = None
            reason_codes: list[str] = []
            last_json = next(
                (
                    line
                    for line in reversed(completed.stdout.splitlines())
                    if line.strip().startswith("{") and "coverage_returncode" in line
                ),
                None,
            )
            if last_json is not None:
                try:
                    status = json.loads(last_json)
                    raw_coverage = status.get("coverage_returncode")
                    if isinstance(raw_coverage, int) and not isinstance(
                        raw_coverage,
                        bool,
                    ):
                        coverage_returncode = raw_coverage
                except json.JSONDecodeError:
                    reason_codes.append("sandbox_status_invalid")

            state = _classify_pytest_returncode(completed.returncode)
            if state is ReproductionState.REPRODUCED:
                reason_codes.append("pytest_failure_reproduced")
            elif state is ReproductionState.NOT_REPRODUCED:
                reason_codes.append("pytest_target_passed")
            else:
                reason_codes.append("pytest_infrastructure_inconclusive")
            if coverage_returncode not in {0, None}:
                reason_codes.append("coverage_export_failed")
            if not coverage_files:
                reason_codes.append("coverage_evidence_unavailable")

            decision = self._gate.assess(
                EvidenceAdmissionRequest(
                    source_class="deterministic_test",
                    content=combined or "pytest produced no output",
                )
            )
            if decision.admissible:
                safe_output = str(redact_data(combined))[-_MAX_OUTPUT_CHARS:]
            else:
                safe_output = "[BLOCKED_UNSAFE_REPRODUCTION_OUTPUT]"
                reason_codes.extend(decision.reason_codes)

            return DiagnosticReproductionEvidence.create(
                reproduction_state=state,
                pytest_returncode=completed.returncode,
                coverage_returncode=coverage_returncode,
                targets=normalized_targets,
                coverage_files=coverage_files,
                output=safe_output,
                sandbox_profile=launch.profile_id,
                sandbox_profile_version=launch.profile_version,
                reason_codes=tuple(dict.fromkeys(reason_codes)),
            )


def build_diagnostic_reproduction_runner(
    image: str | None,
    *,
    protected_main_root: str | pathlib.Path | None = None,
) -> DiagnosticReproductionRunner | None:
    normalized = str(image or "").strip()
    if not normalized:
        return None
    try:
        return DockerDiagnosticReproductionRunner(
            normalized,
            protected_main_root=protected_main_root,
        )
    except DiagnosticWorkspaceError:
        return None


class DiagnosticRunReproductionExecutor:
    descriptor = BrainAction(
        name="diag_run_reproduction",
        description=(
            "Run explicit pytest targets with Coverage.py inside the approved "
            "network-disabled read-only diagnostic sandbox."
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "targets": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 500,
                    },
                    "minItems": 1,
                    "maxItems": 20,
                },
                "timeout_seconds": {
                    "type": "number",
                    "minimum": 1,
                    "maximum": 300,
                },
            },
            "required": ["targets"],
            "additionalProperties": False,
        },
    )
    work_types = frozenset({WorkType.DIAGNOSTICS})

    def __init__(
        self,
        manager: DiagnosticWorkspaceManager,
        runner: DiagnosticReproductionRunner | None,
    ) -> None:
        self._manager = manager
        self._runner = runner

    def resource_keys(
        self,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> tuple[str, ...]:
        del work, parameters
        return ("cpu",)

    async def execute(
        self,
        *,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        workspace = self._manager.assert_pristine(work.work_id)
        raw_targets = parameters.get("targets")
        if not isinstance(raw_targets, list):
            raise DiagnosticWorkspaceError(
                "diagnostic reproduction targets must be an array"
            )
        targets = tuple(_normalize_target(item) for item in raw_targets)
        runner = self._runner
        if runner is None:
            requirement_ids = [
                item.requirement_id
                for item in diagnostic_verifier_requirements(work_id=work.work_id)
            ]
            raise WorkOwnerInputRequired(
                "Safe diagnostic reproduction is not configured. "
                "Configure an approved diagnostic Docker image containing the "
                "verified dependencies " + ", ".join(requirement_ids) + "."
            )
        result = await runner.run(
            workspace.path,
            targets=targets,
            timeout_seconds=float(parameters.get("timeout_seconds", 120.0)),
        )
        self._manager.assert_pristine(work.work_id)
        return result.to_payload()
