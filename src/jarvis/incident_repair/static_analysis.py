"""Optional Pyright static diagnostic evidence for Phase 6."""

from __future__ import annotations

import asyncio
import json
import pathlib
import subprocess
from dataclasses import dataclass
from typing import Any, Protocol

from jarvis.engineering_knowledge.security import (
    EngineeringEvidenceAdmissionGate,
    EvidenceAdmissionRequest,
)
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.engineering_substrate.sandbox import (
    SandboxMountBinding,
    SandboxPolicyError,
    SandboxResourceUnavailable,
    default_sandbox_registry,
)
from jarvis.observability.redaction import redact_data
from jarvis.work.brain import BrainAction
from jarvis.work.models import WorkItem, WorkType

from .reproduction import diagnostic_verifier_requirements
from .workspace import DiagnosticWorkspaceError, DiagnosticWorkspaceManager

_MAX_DIAGNOSTICS = 100
_MAX_OUTPUT_CHARS = 20_000


@dataclass(frozen=True, slots=True)
class StaticDiagnosticEvidence:
    available: bool
    returncode: int | None
    version: str | None
    diagnostics: tuple[dict[str, object], ...]
    summary: dict[str, object]
    reason_codes: tuple[str, ...]
    output: str
    sandbox_profile: str | None
    sandbox_profile_version: int | None

    def to_payload(self) -> dict[str, object]:
        return {
            "available": self.available,
            "returncode": self.returncode,
            "version": self.version,
            "diagnostics": list(self.diagnostics),
            "summary": self.summary,
            "reason_codes": list(self.reason_codes),
            "output": self.output,
            "sandbox_profile": self.sandbox_profile,
            "sandbox_profile_version": self.sandbox_profile_version,
        }


class DiagnosticStaticRunner(Protocol):
    async def run(
        self,
        workspace: pathlib.Path,
        *,
        targets: tuple[str, ...],
        timeout_seconds: float,
    ) -> StaticDiagnosticEvidence: ...


def _normalize_target(value: object) -> str:
    text = str(value or "").strip()
    posix = pathlib.PurePosixPath(text)
    windows = pathlib.PureWindowsPath(text)
    if (
        not text
        or posix.is_absolute()
        or windows.is_absolute()
        or bool(windows.root)
        or bool(windows.drive)
        or ".." in posix.parts
        or ".." in windows.parts
        or text.startswith("-")
    ):
        raise DiagnosticWorkspaceError(
            "static-check target must remain a relative non-option path"
        )
    return text


def _normalize_file(value: object) -> str | None:
    text = str(value or "").replace("\\", "/").strip()
    if text.startswith("/workspace/"):
        text = text[len("/workspace/") :]
    pure = pathlib.PurePosixPath(text)
    if not text or pure.is_absolute() or ".." in pure.parts:
        return None
    return pure.as_posix()


class DockerPyrightDiagnosticRunner:
    def __init__(
        self,
        image: str,
        *,
        protected_main_root: str | pathlib.Path,
    ) -> None:
        normalized = str(image or "").strip()
        if not normalized:
            raise ValueError("Pyright diagnostic image must not be empty")
        self.image = normalized
        self._registry = default_sandbox_registry(
            protected_main_root=pathlib.Path(protected_main_root).resolve(),
        )
        self._gate = EngineeringEvidenceAdmissionGate()

    async def run(
        self,
        workspace: pathlib.Path,
        *,
        targets: tuple[str, ...],
        timeout_seconds: float,
    ) -> StaticDiagnosticEvidence:
        normalized_targets = tuple(_normalize_target(item) for item in targets)
        if not normalized_targets:
            raise DiagnosticWorkspaceError("static check requires at least one target")
        try:
            launch = self._registry.build_launch(
                profile_id="diagnostic.static.v1",
                image=self.image,
                mounts=(SandboxMountBinding("workspace_ro", workspace),),
                trusted_suffix=normalized_targets,
                requested_timeout_seconds=max(
                    1.0,
                    min(float(timeout_seconds), 300.0),
                ),
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
            return StaticDiagnosticEvidence(
                available=True,
                returncode=124,
                version=None,
                diagnostics=(),
                summary={},
                reason_codes=("static_check_timeout",),
                output="Pyright static diagnostic timed out",
                sandbox_profile=launch.profile_id,
                sandbox_profile_version=launch.profile_version,
            )

        combined = (completed.stdout + "\n" + completed.stderr).strip()
        lowered = combined.casefold()
        if "no module named pyright" in lowered:
            return StaticDiagnosticEvidence(
                available=False,
                returncode=completed.returncode,
                version=None,
                diagnostics=(),
                summary={},
                reason_codes=("pyright_not_provisioned",),
                output="Pyright is not provisioned in the approved diagnostic image",
                sandbox_profile=launch.profile_id,
                sandbox_profile_version=launch.profile_version,
            )

        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            payload = {}
        raw_diagnostics = payload.get("generalDiagnostics")
        diagnostics: list[dict[str, object]] = []
        if isinstance(raw_diagnostics, list):
            for raw in raw_diagnostics:
                if not isinstance(raw, dict):
                    continue
                path = _normalize_file(raw.get("file"))
                if path is None:
                    continue
                message = str(raw.get("message") or "").strip()
                decision = self._gate.assess(
                    EvidenceAdmissionRequest(
                        source_class="deterministic_test",
                        content=message or "empty diagnostic",
                    )
                )
                if not decision.admissible:
                    continue
                row = {
                    "file": path,
                    "severity": str(raw.get("severity") or "").strip(),
                    "message": str(redact_data(message))[:2000],
                    "range": raw.get("range"),
                    "rule": raw.get("rule"),
                }
                diagnostics.append(row)
                if len(diagnostics) >= _MAX_DIAGNOSTICS:
                    break

        raw_summary = payload.get("summary")
        summary = dict(raw_summary) if isinstance(raw_summary, dict) else {}
        version = str(payload.get("version") or "").strip() or None
        safe_output = combined[-_MAX_OUTPUT_CHARS:]
        decision = self._gate.assess(
            EvidenceAdmissionRequest(
                source_class="deterministic_test",
                content=safe_output or "empty Pyright output",
            )
        )
        if decision.admissible:
            safe_output = str(redact_data(safe_output))
            reasons = ("static_check_completed",)
        else:
            safe_output = "[BLOCKED_UNSAFE_STATIC_OUTPUT]"
            reasons = tuple(decision.reason_codes)

        return StaticDiagnosticEvidence(
            available=True,
            returncode=completed.returncode,
            version=version,
            diagnostics=tuple(diagnostics),
            summary=summary,
            reason_codes=reasons,
            output=safe_output,
            sandbox_profile=launch.profile_id,
            sandbox_profile_version=launch.profile_version,
        )


def build_diagnostic_static_runner(
    image: str | None,
    *,
    protected_main_root: str | pathlib.Path,
) -> DiagnosticStaticRunner | None:
    normalized = str(image or "").strip()
    if not normalized:
        return None
    return DockerPyrightDiagnosticRunner(
        normalized,
        protected_main_root=protected_main_root,
    )


class DiagnosticStaticCheckExecutor:
    descriptor = BrainAction(
        name="diag_static_check",
        description=(
            "Run optional Pyright JSON diagnostics inside the approved "
            "network-disabled read-only sandbox."
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
        runner: DiagnosticStaticRunner | None,
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
            raise DiagnosticWorkspaceError("static-check targets must be an array")
        targets = tuple(_normalize_target(item) for item in raw_targets)
        runner = self._runner
        if runner is None:
            pyright_requirement = diagnostic_verifier_requirements(
                work_id=work.work_id
            )[1]
            return {
                "available": False,
                "reason_codes": ["diagnostic_image_not_configured"],
                "requirement_id": pyright_requirement.requirement_id,
                "diagnostics": [],
            }
        result = await runner.run(
            workspace.path,
            targets=targets,
            timeout_seconds=float(parameters.get("timeout_seconds", 120.0)),
        )
        self._manager.assert_pristine(work.work_id)
        payload = result.to_payload()
        digest = canonical_digest(payload)
        payload["evidence_id"] = f"pyright_{digest[:16]}"
        payload["digest"] = digest
        return payload
