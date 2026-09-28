"""Durable post-activation external acceptance for acquired capabilities."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Protocol

from jarvis.authority.types import ActionOrigin
from jarvis.capabilities.models import CapabilityStatus
from jarvis.capabilities.runtime import CapabilityRuntime
from jarvis.capability_acquisition.artifacts import goal_from_payload
from jarvis.capability_acquisition.process import OWNER_CAPABILITY_ACQUISITION_PROCESS
from jarvis.capability_acquisition.workflow import (
    PHASE9_REAL_EXTERNAL_ACCEPTANCE_CONTRACT,
)
from jarvis.engineering_change.models import ChangeArtifact, ChangeConflict
from jarvis.engineering_change.store import ChangeStore
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.engineering_substrate.change_integration import MANIFEST_KIND
from jarvis.engineering_substrate.contracts import HardwareAcceptanceVerdict
from jarvis.engineering_substrate.hardware_acceptance import HardwareAcceptanceService
from jarvis.work.brain import BrainAction
from jarvis.work.engine import WorkOwnerInputRequired
from jarvis.work.models import (
    DeliveryPolicy,
    WorkItem,
    WorkPriority,
    WorkState,
    WorkStep,
    WorkType,
)
from jarvis.work.store import SQLiteWorkStore, WorkStoreError

EXTERNAL_ACCEPTANCE_BINDING_KIND = "capability_external_acceptance_binding"
EXTERNAL_ACCEPTANCE_RESULT_KIND = "capability_external_acceptance"
_OWNER_INPUT_REQUEST_KEY = "owner_input_request"
_ACCEPTANCE_OBSERVATION_KEY = "acceptance_observation"
_PARAMETER = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_AFFIRMATIVE = frozenset(
    {
        "yes",
        "y",
        "approve",
        "approved",
        "continue",
        "run",
        "go ahead",
        "okay",
        "ok",
        "do it",
        "done",
    }
)
_NEGATIVE = frozenset({"no", "n", "reject", "decline", "cancel", "stop"})


class ExternalAcceptanceError(ChangeConflict):
    pass


class ExternalAcceptanceBackend(Protocol):
    def submit(self, work_id: str, *, priority: WorkPriority) -> str: ...


@dataclass(frozen=True, slots=True)
class ExternalAcceptanceContext:
    change_id: str
    work_id: str
    binding: ChangeArtifact
    candidate: ChangeArtifact
    activation: ChangeArtifact
    architecture: ChangeArtifact
    manifest: ChangeArtifact
    goal: ChangeArtifact


def _bounded_text(value: object, *, field: str, limit: int = 1000) -> str:
    text = " ".join(str(value or "").split())
    if not text or len(text) > limit:
        raise ExternalAcceptanceError(
            f"{field} must be between 1 and {limit} characters"
        )
    if any(ord(character) < 32 for character in text):
        raise ExternalAcceptanceError(f"{field} contains control characters")
    return text


def _normalize_owner_reply(value: str) -> str:
    return " ".join(value.strip().casefold().rstrip(".!?").split())


def _owner_reply(
    steps: tuple[WorkStep, ...],
    *,
    input_key: str,
) -> tuple[str, str] | None:
    key = str(input_key).strip().casefold()
    for step in reversed(steps):
        if (
            step.kind == "owner_input"
            and step.state.value == "completed"
            and str(step.observation.get("input_key") or "").strip().casefold() == key
            and isinstance(step.observation.get("response"), str)
        ):
            return str(step.observation["response"]), step.step_id
    return None


def _latest_step(
    steps: tuple[WorkStep, ...],
    kind: str,
    *,
    predicate=None,
) -> WorkStep | None:
    for step in reversed(steps):
        if step.kind != kind or step.state.value != "completed":
            continue
        if predicate is None or predicate(step):
            return step
    return None


class ExternalAcceptanceContextResolver:
    def __init__(self, store: ChangeStore) -> None:
        self._store = store

    @property
    def store(self) -> ChangeStore:
        return self._store

    def context_for(self, work_id: str) -> ExternalAcceptanceContext:
        work = self._store.work.require(str(work_id).strip())
        prefix = "phase9-external:"
        if (
            work.work_type is not WorkType.EXTERNAL_ACCEPTANCE
            or not work.source_session_id.startswith(prefix)
        ):
            raise ExternalAcceptanceError(
                "work is not a Phase-9 external acceptance mission"
            )
        change_id = work.source_session_id[len(prefix) :]
        change = self._store.require(change_id)
        if (
            change.process_key != OWNER_CAPABILITY_ACQUISITION_PROCESS.key
            or change.process_version != OWNER_CAPABILITY_ACQUISITION_PROCESS.version
        ):
            raise ExternalAcceptanceError(
                "external acceptance belongs to the wrong EngineeringChange process"
            )
        binding = next(
            (
                artifact
                for artifact in reversed(
                    self._store.list_artifacts(
                        change_id,
                        kind=EXTERNAL_ACCEPTANCE_BINDING_KIND,
                    )
                )
                if artifact.payload.get("work_id") == work.work_id
            ),
            None,
        )
        if binding is None:
            raise ExternalAcceptanceError(
                "external acceptance work has no canonical binding"
            )
        candidate = self._store.get_artifact(
            str(binding.payload.get("candidate_artifact_id") or "")
        )
        activation = self._store.get_artifact(
            str(binding.payload.get("activation_artifact_id") or "")
        )
        architecture = self._store.get_artifact(
            str(binding.payload.get("architecture_artifact_id") or "")
        )
        manifest = self._store.get_artifact(
            str(binding.payload.get("manifest_artifact_id") or "")
        )
        goal = self._store.get_artifact(
            str(binding.payload.get("goal_artifact_id") or "")
        )
        if any(
            item is None
            for item in (candidate, activation, architecture, manifest, goal)
        ):
            raise ExternalAcceptanceError(
                "external acceptance binding references missing evidence"
            )
        assert candidate is not None
        assert activation is not None
        assert architecture is not None
        assert manifest is not None
        assert goal is not None
        checks = (
            (
                candidate,
                "candidate_artifact_digest",
            ),
            (
                activation,
                "activation_artifact_digest",
            ),
            (
                architecture,
                "architecture_artifact_digest",
            ),
            (
                manifest,
                "manifest_artifact_digest",
            ),
            (
                goal,
                "goal_artifact_digest",
            ),
        )
        for artifact, digest_field in checks:
            if binding.payload.get(digest_field) != artifact.digest:
                raise ExternalAcceptanceError(
                    "external acceptance evidence digest is stale"
                )
        latest_candidate = self._store.latest_artifact(
            change_id,
            "capability_candidate",
        )
        latest_activation = self._store.latest_artifact(
            change_id,
            "capability_lifecycle_activation",
        )
        latest_architecture = self._store.latest_artifact(change_id, "architecture")
        latest_manifest = self._store.latest_artifact(change_id, MANIFEST_KIND)
        if (
            latest_candidate is None
            or latest_candidate.artifact_id != candidate.artifact_id
            or latest_activation is None
            or latest_activation.artifact_id != activation.artifact_id
            or latest_architecture is None
            or latest_architecture.artifact_id != architecture.artifact_id
            or latest_manifest is None
            or latest_manifest.artifact_id != manifest.artifact_id
        ):
            raise ExternalAcceptanceError(
                "external acceptance binding no longer points at current evidence"
            )
        if activation.payload.get("effective_enabled") is not True:
            raise ExternalAcceptanceError(
                "external acceptance requires an effectively enabled capability"
            )
        disabled = self._store.latest_artifact(
            change_id,
            "capability_lifecycle_disable",
        )
        if (
            disabled is not None
            and disabled.payload.get("candidate_artifact_id") == candidate.artifact_id
            and disabled.created_at >= activation.created_at
            and disabled.payload.get("effective_enabled") is False
        ):
            raise ExternalAcceptanceError(
                "external acceptance stopped because the capability was disabled"
            )
        contracts = {
            str(item).strip().casefold()
            for item in architecture.payload.get("owner_acceptance_contract_ids", ())
            if str(item).strip()
        }
        if PHASE9_REAL_EXTERNAL_ACCEPTANCE_CONTRACT not in contracts:
            raise ExternalAcceptanceError(
                "current architecture has no real-external-effect acceptance contract"
            )
        return ExternalAcceptanceContext(
            change_id=change_id,
            work_id=work.work_id,
            binding=binding,
            candidate=candidate,
            activation=activation,
            architecture=architecture,
            manifest=manifest,
            goal=goal,
        )


class ExternalAcceptanceCoordinator:
    """Create/recover one durable acceptance WorkItem for an exact activation."""

    def __init__(
        self,
        changes: ChangeStore,
        backend: ExternalAcceptanceBackend,
    ) -> None:
        self._changes = changes
        self._backend = backend

    def start(
        self,
        change_id: str,
        *,
        activation_artifact_id: str,
        authority_session_id: str,
        source_turn_id: str,
    ) -> WorkItem:
        change = self._changes.require(str(change_id).strip())
        if (
            change.process_key != OWNER_CAPABILITY_ACQUISITION_PROCESS.key
            or change.process_version != OWNER_CAPABILITY_ACQUISITION_PROCESS.version
        ):
            raise ExternalAcceptanceError(
                "external acceptance requires Phase-9 capability acquisition"
            )
        candidate = self._changes.latest_artifact(
            change.change_id,
            "capability_candidate",
        )
        activation = self._changes.get_artifact(str(activation_artifact_id).strip())
        architecture = self._changes.latest_artifact(change.change_id, "architecture")
        manifest = self._changes.latest_artifact(change.change_id, MANIFEST_KIND)
        goal_artifact = self._changes.latest_artifact(
            change.change_id,
            "capability_goal",
        )
        if any(
            item is None
            for item in (candidate, activation, architecture, manifest, goal_artifact)
        ):
            raise ExternalAcceptanceError(
                "external acceptance prerequisites are incomplete"
            )
        assert candidate is not None
        assert activation is not None
        assert architecture is not None
        assert manifest is not None
        assert goal_artifact is not None
        latest_activation = self._changes.latest_artifact(
            change.change_id,
            "capability_lifecycle_activation",
        )
        if (
            latest_activation is None
            or latest_activation.artifact_id != activation.artifact_id
            or activation.payload.get("effective_enabled") is not True
        ):
            raise ExternalAcceptanceError(
                "external acceptance requires the current effective activation"
            )
        if (
            activation.payload.get("candidate_artifact_id") != candidate.artifact_id
            or activation.payload.get("candidate_artifact_digest") != candidate.digest
        ):
            raise ExternalAcceptanceError(
                "activation is not bound to the current capability candidate"
            )
        contracts = tuple(
            str(item).strip().casefold()
            for item in architecture.payload.get("owner_acceptance_contract_ids", ())
            if str(item).strip()
        )
        if PHASE9_REAL_EXTERNAL_ACCEPTANCE_CONTRACT not in set(contracts):
            raise ExternalAcceptanceError(
                "activated capability has no required external acceptance contract"
            )

        source_session = f"phase9-external:{change.change_id}"
        existing = self._changes.work.find_by_source_turn(
            source_session_id=source_session,
            source_turn_id=activation.artifact_id,
            work_type=WorkType.EXTERNAL_ACCEPTANCE,
        )
        if existing is not None:
            if not existing.state.terminal:
                execution_id = self._backend.submit(
                    existing.work_id,
                    priority=existing.priority,
                )
                if execution_id != existing.work_id:
                    raise ExternalAcceptanceError(
                        "external acceptance backend returned mismatched identity"
                    )
            return existing

        goal = goal_from_payload(goal_artifact.payload)
        development_work_id = str(
            candidate.payload.get("development_work_id") or ""
        ).strip()
        if not development_work_id:
            raise ExternalAcceptanceError(
                "capability candidate has no DEVELOPMENT work identity"
            )
        item = WorkItem(
            request=(
                "Validate the activated acquired capability against the real external "
                f"target. Original owner goal: {goal.request}"
            ),
            work_type=WorkType.EXTERNAL_ACCEPTANCE,
            source_session_id=source_session,
            source_turn_id=activation.artifact_id,
            priority=WorkPriority.NORMAL,
            delivery_policy=DeliveryPolicy.WHEN_IDLE,
            dependencies=(development_work_id,),
        )
        self._changes.work.create(item)
        target_hints = tuple(goal.target_hints)
        device_identity = (
            " | ".join(target_hints)
            if target_hints
            else str(candidate.payload.get("capability_id") or "external-target")
        )
        self._changes.add_artifact(
            change.change_id,
            kind=EXTERNAL_ACCEPTANCE_BINDING_KIND,
            payload={
                "schema": "capability_external_acceptance_binding.v1",
                "work_id": item.work_id,
                "activation_artifact_id": activation.artifact_id,
                "activation_artifact_digest": activation.digest,
                "candidate_artifact_id": candidate.artifact_id,
                "candidate_artifact_digest": candidate.digest,
                "architecture_artifact_id": architecture.artifact_id,
                "architecture_artifact_digest": architecture.digest,
                "manifest_artifact_id": manifest.artifact_id,
                "manifest_artifact_digest": manifest.digest,
                "goal_artifact_id": goal_artifact.artifact_id,
                "goal_artifact_digest": goal_artifact.digest,
                "capability_id": candidate.payload.get("capability_id"),
                "package_id": candidate.payload.get("package_id"),
                "package_version": candidate.payload.get("package_version"),
                "requested_operations": list(
                    architecture.payload.get("requested_operations", ())
                ),
                "acceptance_contract_id": (PHASE9_REAL_EXTERNAL_ACCEPTANCE_CONTRACT),
                "device_identity": device_identity,
                "target_hints": list(target_hints),
                "authority_session_id": _bounded_text(
                    authority_session_id,
                    field="authority_session_id",
                    limit=180,
                ),
                "source_turn_id": _bounded_text(
                    source_turn_id,
                    field="source_turn_id",
                    limit=180,
                ),
            },
        )
        execution_id = self._backend.submit(item.work_id, priority=item.priority)
        if execution_id != item.work_id:
            failed = item.transition(
                WorkState.FAILED,
                status_detail="external acceptance backend returned mismatched identity",
            )
            self._changes.work.save(failed, expected_version=item.version)
            raise ExternalAcceptanceError(
                "external acceptance backend returned mismatched identity"
            )
        return item


class ExternalAcceptanceInspectExecutor:
    descriptor = BrainAction(
        name="external_acceptance_inspect",
        description=(
            "Inspect the exact activated capability, owner goal, target hints and "
            "allowed operations for this post-activation acceptance mission."
        ),
        parameter_schema={"type": "object", "additionalProperties": False},
    )
    work_types = frozenset({WorkType.EXTERNAL_ACCEPTANCE})

    def __init__(self, resolver: ExternalAcceptanceContextResolver) -> None:
        self._resolver = resolver

    def resource_keys(
        self, work: WorkItem, parameters: dict[str, Any]
    ) -> tuple[str, ...]:
        del work, parameters
        return ()

    async def execute(
        self,
        *,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        del parameters
        context = self._resolver.context_for(work.work_id)
        goal = goal_from_payload(context.goal.payload)
        return {
            "inspected": True,
            "change_id": context.change_id,
            "capability_id": context.binding.payload.get("capability_id"),
            "requested_operations": list(
                context.binding.payload.get("requested_operations", ())
            ),
            "target_hints": list(context.binding.payload.get("target_hints", ())),
            "device_identity": context.binding.payload.get("device_identity"),
            "owner_goal": goal.request,
            "acceptance_contract_id": (PHASE9_REAL_EXTERNAL_ACCEPTANCE_CONTRACT),
        }


class ExternalAcceptancePrepareExecutor:
    descriptor = BrainAction(
        name="external_acceptance_prepare",
        description=(
            "Prepare one exact real-world acceptance request for an allowed operation. "
            "This creates evidence only and performs no external action."
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 120,
                },
                "expected_observation": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 500,
                },
            },
            "required": ["operation", "expected_observation"],
            "additionalProperties": False,
        },
    )
    work_types = frozenset({WorkType.EXTERNAL_ACCEPTANCE})

    def __init__(self, resolver: ExternalAcceptanceContextResolver) -> None:
        self._resolver = resolver

    def resource_keys(
        self, work: WorkItem, parameters: dict[str, Any]
    ) -> tuple[str, ...]:
        del work, parameters
        return ("device_acceptance",)

    async def execute(
        self,
        *,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        context = self._resolver.context_for(work.work_id)
        operation = _bounded_text(
            parameters.get("operation"),
            field="operation",
            limit=120,
        ).casefold()
        allowed = {
            str(item).strip().casefold()
            for item in context.binding.payload.get("requested_operations", ())
            if str(item).strip()
        }
        if operation not in allowed:
            raise ExternalAcceptanceError(
                "acceptance operation is outside the owner-approved architecture"
            )
        expected = _bounded_text(
            parameters.get("expected_observation"),
            field="expected_observation",
            limit=500,
        )
        manifest_id = _bounded_text(
            context.manifest.payload.get("manifest_id"),
            field="manifest_id",
            limit=300,
        )
        manifest_digest = _bounded_text(
            context.manifest.payload.get("manifest_digest"),
            field="manifest_digest",
            limit=64,
        ).casefold()
        request_id = (
            "hwreq_phase9_"
            + canonical_digest(
                {
                    "binding_digest": context.binding.digest,
                    "operation": operation,
                }
            )[:20]
        )
        request = HardwareAcceptanceService(
            self._resolver.store
        ).create_post_activation_request(
            change_id=context.change_id,
            manifest_id=manifest_id,
            manifest_digest=manifest_digest,
            declared_operations=tuple(sorted(allowed)),
            acceptance_contract_id=PHASE9_REAL_EXTERNAL_ACCEPTANCE_CONTRACT,
            device_identity=_bounded_text(
                context.binding.payload.get("device_identity"),
                field="device_identity",
            ),
            operation=operation,
            expected_observation=expected,
            request_id=request_id,
        )
        return {
            "prepared": True,
            "request_id": request.request_id,
            "request_digest": canonical_digest(request),
            "manifest_digest": request.manifest_digest,
            "operation": operation,
            "expected_observation": request.expected_observation,
            "device_identity": request.device_identity,
        }


def _validate_parameters(value: object) -> dict[str, object]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ExternalAcceptanceError("capability parameters must be an object")
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    if len(encoded.encode("utf-8")) > 8192:
        raise ExternalAcceptanceError("capability parameters exceed 8 KiB")
    if any(len(str(key)) > 120 for key in value):
        raise ExternalAcceptanceError("capability parameter name is too long")
    return dict(value)


def _waiting_resume_step(
    steps: tuple[WorkStep, ...],
    *,
    request_id: str,
) -> WorkStep | None:
    return _latest_step(
        steps,
        "external_acceptance_invoke",
        predicate=lambda step: (
            step.observation.get("needs_owner") is True
            and isinstance(step.observation.get("resume_context"), dict)
            and step.observation["resume_context"].get("request_id") == request_id
            and step.observation["resume_context"].get("kind")
            in {"pin", "confirmation"}
        ),
    )


class ExternalAcceptanceInvokeExecutor:
    descriptor = BrainAction(
        name="external_acceptance_invoke",
        description=(
            "Invoke one prepared owner-approved capability operation against the live "
            "external target. The first live effect requires explicit owner confirmation. "
            "Pairing PIN/confirmation requests pause and resume the same WorkItem."
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 120,
                },
                "parameters": {
                    "type": "object",
                    "additionalProperties": True,
                },
            },
            "required": ["operation"],
            "additionalProperties": False,
        },
    )
    work_types = frozenset({WorkType.EXTERNAL_ACCEPTANCE})

    def __init__(
        self,
        resolver: ExternalAcceptanceContextResolver,
        runtime: CapabilityRuntime,
    ) -> None:
        self._resolver = resolver
        self._runtime = runtime

    def resource_keys(
        self, work: WorkItem, parameters: dict[str, Any]
    ) -> tuple[str, ...]:
        del work, parameters
        return ("device_acceptance", "network")

    async def execute(
        self,
        *,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        context = self._resolver.context_for(work.work_id)
        operation = _bounded_text(
            parameters.get("operation"),
            field="operation",
            limit=120,
        ).casefold()
        steps = self._resolver.store.work.list_steps(work.work_id)
        prepared = _latest_step(
            steps,
            "external_acceptance_prepare",
            predicate=lambda step: (
                step.observation.get("prepared") is True
                and step.observation.get("operation") == operation
            ),
        )
        if prepared is None:
            raise ExternalAcceptanceError(
                "live invocation requires an exact prepared acceptance request"
            )
        request_id = str(prepared.observation["request_id"])
        request_digest = str(prepared.observation["request_digest"])
        authority_key = f"external_acceptance_authorize:{request_id}".casefold()
        authority_reply = _owner_reply(steps, input_key=authority_key)
        if authority_reply is None:
            raise WorkOwnerInputRequired(
                (
                    "The acquired capability is ready for a real external test of "
                    f"'{operation}' on {prepared.observation.get('device_identity')}. "
                    "Reply yes to run this test, or no to decline."
                ),
                input_key=authority_key,
                resume_context={
                    "kind": "live_acceptance_authorization",
                    "request_id": request_id,
                    "operation": operation,
                },
            )
        decision = _normalize_owner_reply(authority_reply[0])
        if decision in _NEGATIVE:
            return {
                "invoked": False,
                "owner_declined": True,
                "request_id": request_id,
                "request_digest": request_digest,
                "operation": operation,
                "owner_input_step_id": authority_reply[1],
            }
        if decision not in _AFFIRMATIVE:
            raise WorkOwnerInputRequired(
                "Please reply yes to run the real external test, or no to decline.",
                input_key=authority_key,
                resume_context={
                    "kind": "live_acceptance_authorization",
                    "request_id": request_id,
                    "operation": operation,
                },
            )

        invoke_parameters = _validate_parameters(parameters.get("parameters"))
        resume = _waiting_resume_step(steps, request_id=request_id)
        if resume is not None:
            resume_context = dict(resume.observation.get("resume_context") or {})
            input_key = (
                str(resume.observation.get("input_key") or "").strip().casefold()
            )
            kind = str(resume_context.get("kind") or "").strip().casefold()
            parameter = str(resume_context.get("parameter") or "").strip().casefold()
            if parameter and _PARAMETER.fullmatch(parameter) is None:
                raise ExternalAcceptanceError("pairing resume parameter is invalid")
            if resume.observation.get("sensitive") is True:
                owner_value = self._resolver.store.work.pop_sensitive_input(
                    work.work_id,
                    input_key,
                )
                if owner_value is None:
                    raise WorkOwnerInputRequired(
                        str(
                            resume.observation.get("question")
                            or "Pairing input required."
                        ),
                        sensitive=True,
                        input_key=input_key,
                        resume_context=resume_context,
                    )
            else:
                response = _owner_reply(steps, input_key=input_key)
                if response is None:
                    raise WorkOwnerInputRequired(
                        str(
                            resume.observation.get("question")
                            or "Owner input required."
                        ),
                        input_key=input_key,
                        resume_context=resume_context,
                    )
                owner_value = response[0]
                if kind == "confirmation":
                    normalized = _normalize_owner_reply(owner_value)
                    if normalized in _NEGATIVE:
                        return {
                            "invoked": False,
                            "owner_declined": True,
                            "request_id": request_id,
                            "operation": operation,
                            "pairing_declined": True,
                        }
                    if normalized not in _AFFIRMATIVE:
                        raise WorkOwnerInputRequired(
                            str(
                                resume.observation.get("question")
                                or "Confirm the requested pairing step."
                            ),
                            input_key=input_key,
                            resume_context=resume_context,
                        )
            if parameter:
                invoke_parameters[parameter] = owner_value

        authority_session_id = _bounded_text(
            context.binding.payload.get("authority_session_id"),
            field="authority_session_id",
            limit=180,
        )
        result = self._runtime.execute_operation(
            session_id=authority_session_id,
            operation=operation,
            parameters=invoke_parameters,
            origin=ActionOrigin.DIRECT_USER,
        )
        owner_request = result.data.get(_OWNER_INPUT_REQUEST_KEY)
        if result.status is CapabilityStatus.PARTIAL and isinstance(
            owner_request, dict
        ):
            kind = str(owner_request.get("kind") or "").strip().casefold()
            if kind not in {"pin", "confirmation"}:
                raise ExternalAcceptanceError(
                    "capability requested an unsupported owner-input kind"
                )
            prompt = _bounded_text(
                owner_request.get("prompt"),
                field="owner_input_request.prompt",
                limit=500,
            )
            parameter = str(owner_request.get("parameter") or "").strip().casefold()
            if parameter and _PARAMETER.fullmatch(parameter) is None:
                raise ExternalAcceptanceError(
                    "capability owner-input parameter is invalid"
                )
            input_key = (
                "external_capability_input:"
                + canonical_digest(
                    {
                        "work_id": work.work_id,
                        "request_id": request_id,
                        "operation": operation,
                        "kind": kind,
                        "parameter": parameter,
                        "prompt": prompt,
                    }
                )[:24]
            )
            sensitive = kind == "pin"
            raise WorkOwnerInputRequired(
                "The activated capability needs owner input to continue: " + prompt,
                sensitive=sensitive,
                input_key=input_key,
                resume_context={
                    "kind": kind,
                    "parameter": parameter,
                    "request_id": request_id,
                    "operation": operation,
                },
            )

        observation = result.data.get(_ACCEPTANCE_OBSERVATION_KEY)
        accepted_observation: dict[str, object] | None = None
        if isinstance(observation, dict):
            method = str(observation.get("method") or "").strip().casefold()
            observed = observation.get("observed") is True
            summary = str(observation.get("summary") or "").strip()
            refs = observation.get("evidence_refs") or ()
            if (
                observed
                and method in {"device_state_readback", "external_system_readback"}
                and summary
                and isinstance(refs, (list, tuple))
            ):
                accepted_observation = {
                    "observed": True,
                    "method": method,
                    "summary": summary[:1000],
                    "evidence_refs": [
                        str(item)[:1000] for item in refs if str(item).strip()
                    ][:20],
                }

        succeeded = result.status is CapabilityStatus.SUCCEEDED
        return {
            "invoked": succeeded,
            "request_id": request_id,
            "request_digest": request_digest,
            "operation": operation,
            "capability_key": result.capability_key,
            "status": result.status.value,
            "reason": result.reason,
            "provenance": list(result.provenance[:20]),
            "acceptance_observation": accepted_observation,
        }


class ExternalAcceptanceRecordExecutor:
    descriptor = BrainAction(
        name="external_acceptance_record",
        description=(
            "Resolve the prepared post-activation hardware acceptance from a successful "
            "live capability invocation. Use device/system readback when available; "
            "otherwise ask the owner to confirm the physical effect."
        ),
        parameter_schema={"type": "object", "additionalProperties": False},
    )
    work_types = frozenset({WorkType.EXTERNAL_ACCEPTANCE})

    def __init__(self, resolver: ExternalAcceptanceContextResolver) -> None:
        self._resolver = resolver

    def resource_keys(
        self, work: WorkItem, parameters: dict[str, Any]
    ) -> tuple[str, ...]:
        del work, parameters
        return ("device_acceptance",)

    async def execute(
        self,
        *,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        del parameters
        context = self._resolver.context_for(work.work_id)
        steps = self._resolver.store.work.list_steps(work.work_id)
        invoked = _latest_step(
            steps,
            "external_acceptance_invoke",
            predicate=lambda step: step.observation.get("invoked") is True,
        )
        if invoked is None:
            raise ExternalAcceptanceError(
                "external acceptance record requires a successful live invocation"
            )
        request_id = str(invoked.observation.get("request_id") or "")
        hardware = HardwareAcceptanceService(self._resolver.store)
        request = hardware.get_request(request_id)
        if canonical_digest(request) != invoked.observation.get("request_digest"):
            raise ExternalAcceptanceError(
                "live invocation request digest differs from hardware evidence"
            )
        observation = invoked.observation.get("acceptance_observation")
        owner_ref: str | None = None
        telemetry_refs: tuple[str, ...] = ()
        verifier_refs: tuple[str, ...] = ()
        verdict = HardwareAcceptanceVerdict.PASS
        observation_method = "owner_observed"

        if isinstance(observation, dict) and observation.get("observed") is True:
            observation_method = str(observation.get("method") or "")
            verifier_refs = tuple(
                str(item)
                for item in observation.get("evidence_refs") or ()
                if str(item).strip()
            )
            if not verifier_refs:
                verifier_refs = (
                    "capability-runtime-result:"
                    + canonical_digest(invoked.observation),
                )
        else:
            input_key = f"external_effect_confirmation:{request_id}".casefold()
            response = _owner_reply(steps, input_key=input_key)
            if response is None:
                raise WorkOwnerInputRequired(
                    (
                        "The live capability operation completed, but JARVIS has no "
                        "independent device-state readback. "
                        f"Expected observation: {request.expected_observation}. "
                        "Reply yes if you observed it, or no if you did not."
                    ),
                    input_key=input_key,
                    resume_context={
                        "kind": "external_effect_confirmation",
                        "request_id": request_id,
                        "operation": request.operation,
                    },
                )
            normalized = _normalize_owner_reply(response[0])
            if normalized in _AFFIRMATIVE:
                verdict = HardwareAcceptanceVerdict.PASS
            elif normalized in _NEGATIVE:
                verdict = HardwareAcceptanceVerdict.FAIL
            else:
                raise WorkOwnerInputRequired(
                    "Please reply yes if you observed the expected effect, or no if not.",
                    input_key=input_key,
                    resume_context={
                        "kind": "external_effect_confirmation",
                        "request_id": request_id,
                        "operation": request.operation,
                    },
                )
            owner_ref = f"work-owner-observation:{response[1]}"

        evidence = hardware.resolve(
            request_id=request.request_id,
            request_digest=canonical_digest(request),
            manifest_digest=request.manifest_digest,
            device_identity=request.device_identity,
            operation=request.operation,
            verdict=verdict,
            resolution_key=(
                "phase9-external:"
                + canonical_digest(
                    {
                        "binding_digest": context.binding.digest,
                        "request_digest": canonical_digest(request),
                        "invoke_step_id": invoked.step_id,
                        "verdict": verdict.value,
                    }
                )
            ),
            owner_observation_ref=owner_ref,
            telemetry_refs=telemetry_refs,
            verifier_refs=verifier_refs,
        )
        payload = {
            "schema": "capability_external_acceptance.v1",
            "work_id": work.work_id,
            "binding_artifact_id": context.binding.artifact_id,
            "binding_artifact_digest": context.binding.digest,
            "candidate_artifact_id": context.candidate.artifact_id,
            "candidate_artifact_digest": context.candidate.digest,
            "activation_artifact_id": context.activation.artifact_id,
            "activation_artifact_digest": context.activation.digest,
            "request_id": request.request_id,
            "request_digest": canonical_digest(request),
            "evidence_id": evidence.evidence_id,
            "evidence_digest": canonical_digest(evidence),
            "operation": request.operation,
            "device_identity": request.device_identity,
            "verdict": verdict.value,
            "observation_method": observation_method,
        }
        latest = self._resolver.store.latest_artifact(
            context.change_id,
            EXTERNAL_ACCEPTANCE_RESULT_KIND,
        )
        artifact = (
            latest
            if latest is not None and latest.payload == payload
            else self._resolver.store.add_artifact(
                context.change_id,
                kind=EXTERNAL_ACCEPTANCE_RESULT_KIND,
                payload=payload,
            )
        )
        return {
            "acceptance_recorded": True,
            "verdict": verdict.value,
            "operation": request.operation,
            "request_id": request.request_id,
            "evidence_id": evidence.evidence_id,
            "acceptance_artifact_id": artifact.artifact_id,
            "acceptance_artifact_digest": artifact.digest,
            "observation_method": observation_method,
        }


def external_acceptance_completion_guard(
    steps: tuple[WorkStep, ...],
) -> tuple[bool, str | None]:
    inspected = _latest_step(
        steps,
        "external_acceptance_inspect",
        predicate=lambda step: step.observation.get("inspected") is True,
    )
    if inspected is None:
        return False, "external acceptance must inspect its exact activation binding"
    prepared = _latest_step(
        steps,
        "external_acceptance_prepare",
        predicate=lambda step: step.observation.get("prepared") is True,
    )
    if prepared is None:
        return False, "external acceptance requires an exact hardware request"
    invoked = _latest_step(steps, "external_acceptance_invoke")
    if invoked is None:
        return False, "external acceptance requires a live capability invocation"
    if invoked.observation.get("owner_declined") is True:
        return True, None
    if invoked.observation.get("invoked") is not True:
        return False, "external acceptance live invocation has not succeeded"
    recorded = _latest_step(
        steps,
        "external_acceptance_record",
        predicate=lambda step: step.observation.get("acceptance_recorded") is True,
    )
    if recorded is None:
        return False, "external acceptance requires durable real-world evidence"
    return True, None


def build_external_acceptance_executors(
    store: ChangeStore,
    *,
    capability_runtime: CapabilityRuntime,
) -> tuple[object, ...]:
    resolver = ExternalAcceptanceContextResolver(store)
    return (
        ExternalAcceptanceInspectExecutor(resolver),
        ExternalAcceptancePrepareExecutor(resolver),
        ExternalAcceptanceInvokeExecutor(resolver, capability_runtime),
        ExternalAcceptanceRecordExecutor(resolver),
    )
