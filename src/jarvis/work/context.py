"""Deterministic bounded context assembly for JARVIS Work reasoning.

C6 keeps the WorkStore as canonical truth.  This module only projects a smaller,
recoverable reasoning view over that durable history.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from jarvis.work.models import WorkItem, WorkStep, WorkStepState, WorkType

_CONTEXT_VERSION = "c6.v1"
_DEFAULT_MAX_SELECTED_STEPS = 12
_DEFAULT_MANIFEST_LIMIT = 24
_DEFAULT_MAX_STRING_CHARS = 6000
_DEFAULT_MAX_LIST_ITEMS = 48


class WorkContextMode(StrEnum):
    """Rollout state for bounded Work context."""

    OFF = "off"
    SHADOW = "shadow"
    APPLY = "apply"


def normalize_work_context_mode(value: WorkContextMode | str) -> WorkContextMode:
    if isinstance(value, WorkContextMode):
        return value
    try:
        return WorkContextMode(str(value).strip().casefold())
    except ValueError as exc:
        raise ValueError("work context mode must be off, shadow, or apply") from exc


class WorkContextEvidenceProvider(Protocol):
    """Optional advisory evidence source for one WorkItem."""

    def for_work(self, work: WorkItem) -> tuple[dict[str, Any], ...]: ...


@dataclass(frozen=True, slots=True)
class WorkContextStep:
    step_id: str
    kind: str
    summary: str
    state: str
    input_data: dict[str, Any]
    observation: dict[str, Any]
    error: str | None

    def as_payload(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "kind": self.kind,
            "summary": self.summary,
            "state": self.state,
            "input": self.input_data,
            "observation": self.observation,
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class WorkContextManifestEntry:
    step_id: str
    kind: str
    summary: str
    state: str
    has_error: bool

    def as_payload(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "kind": self.kind,
            "summary": self.summary,
            "state": self.state,
            "has_error": self.has_error,
        }


@dataclass(frozen=True, slots=True)
class WorkContextPack:
    """Bounded reasoning projection. Full source history remains in WorkStore."""

    version: str
    full_history_step_count: int
    selected_steps: tuple[WorkContextStep, ...]
    omitted_step_count: int
    omitted_manifest: tuple[WorkContextManifestEntry, ...]
    evidence: tuple[dict[str, Any], ...]

    def recent_steps_payload(self) -> list[dict[str, Any]]:
        return [step.as_payload() for step in self.selected_steps]

    def history_manifest_payload(self) -> dict[str, Any]:
        return {
            "context_version": self.version,
            "full_history_step_count": self.full_history_step_count,
            "selected_step_count": len(self.selected_steps),
            "omitted_step_count": self.omitted_step_count,
            "omitted_steps": [item.as_payload() for item in self.omitted_manifest],
            "full_history_is_durable": True,
        }


@dataclass(frozen=True, slots=True)
class WorkContextShadowReport:
    legacy_chars: int
    optimized_chars: int
    legacy_estimated_tokens: int
    optimized_estimated_tokens: int
    reduction_percent: float
    selected_step_count: int
    omitted_step_count: int


def build_context_shadow_report(
    *,
    legacy_payload: dict[str, Any],
    optimized_payload: dict[str, Any],
    pack: WorkContextPack,
) -> WorkContextShadowReport:
    legacy_chars = _serialized_chars(legacy_payload)
    optimized_chars = _serialized_chars(optimized_payload)
    reduction = 0.0
    if legacy_chars > 0:
        reduction = max(
            0.0,
            (legacy_chars - optimized_chars) * 100.0 / legacy_chars,
        )
    return WorkContextShadowReport(
        legacy_chars=legacy_chars,
        optimized_chars=optimized_chars,
        legacy_estimated_tokens=_estimated_tokens(legacy_chars),
        optimized_estimated_tokens=_estimated_tokens(optimized_chars),
        reduction_percent=reduction,
        selected_step_count=len(pack.selected_steps),
        omitted_step_count=pack.omitted_step_count,
    )


class WorkContextAssembler:
    """Select high-signal Work history while retaining durable provenance."""

    def __init__(
        self,
        *,
        max_selected_steps: int = _DEFAULT_MAX_SELECTED_STEPS,
        manifest_limit: int = _DEFAULT_MANIFEST_LIMIT,
        max_string_chars: int = _DEFAULT_MAX_STRING_CHARS,
        max_list_items: int = _DEFAULT_MAX_LIST_ITEMS,
        evidence_provider: WorkContextEvidenceProvider | None = None,
    ) -> None:
        if max_selected_steps <= 0:
            raise ValueError("max_selected_steps must be positive")
        if manifest_limit < 0:
            raise ValueError("manifest_limit must not be negative")
        if max_string_chars < 1000:
            raise ValueError("max_string_chars must be at least 1000")
        if max_list_items < 8:
            raise ValueError("max_list_items must be at least 8")
        self._max_selected_steps = int(max_selected_steps)
        self._manifest_limit = int(manifest_limit)
        self._max_string_chars = int(max_string_chars)
        self._max_list_items = int(max_list_items)
        self._evidence_provider = evidence_provider

    def build(
        self,
        *,
        work: WorkItem,
        steps: tuple[WorkStep, ...],
        evidence: tuple[dict[str, Any], ...] = (),
    ) -> WorkContextPack:
        selected_indices = self._selected_indices(work.work_type, steps)
        selected = tuple(
            self._project_step(steps[index]) for index in selected_indices
        )
        selected_set = frozenset(selected_indices)
        omitted_indices = [
            index for index in range(len(steps)) if index not in selected_set
        ]
        manifest_indices = (
            omitted_indices[-self._manifest_limit :]
            if self._manifest_limit
            else []
        )
        manifest = tuple(
            WorkContextManifestEntry(
                step_id=steps[index].step_id,
                kind=steps[index].kind,
                summary=steps[index].summary,
                state=steps[index].state.value,
                has_error=bool(steps[index].error),
            )
            for index in manifest_indices
        )

        merged_evidence = list(evidence)
        if self._evidence_provider is not None:
            merged_evidence.extend(self._evidence_provider.for_work(work))
        compact_evidence = tuple(
            self._compact_value(item) for item in _deduplicate_evidence(merged_evidence)
        )

        return WorkContextPack(
            version=_CONTEXT_VERSION,
            full_history_step_count=len(steps),
            selected_steps=selected,
            omitted_step_count=len(omitted_indices),
            omitted_manifest=manifest,
            evidence=compact_evidence,
        )

    def _selected_indices(
        self,
        work_type: WorkType,
        steps: tuple[WorkStep, ...],
    ) -> tuple[int, ...]:
        if not steps:
            return ()

        candidates: set[int] = set(range(max(0, len(steps) - 3), len(steps)))
        candidates.update(self._latest_per_kind(steps))

        for index, step in enumerate(steps):
            if step.state in {WorkStepState.FAILED, WorkStepState.INTERRUPTED}:
                candidates.add(index)

        if work_type is WorkType.GENERIC:
            candidates.update(range(max(0, len(steps) - 6), len(steps)))
        elif work_type is WorkType.RESEARCH:
            candidates.update(self._latest_n(steps, "research_web", 2))
            candidates.update(self._latest_n(steps, "acq_record_candidate", 2))
        elif work_type is WorkType.DIAGNOSTICS:
            candidates.update(self._latest_n(steps, "diag_record_hypothesis", 2))
            candidates.update(self._latest_n(steps, "research_web", 2))
            candidates.update(self._latest_n(steps, "diag_run_reproduction", 2))
        elif work_type is WorkType.DEVELOPMENT:
            candidates.update(self._latest_n(steps, "dev_run_tests", 2))
            candidates.update(self._latest_n(steps, "dev_read_file", 2))
            candidates.update(self._latest_n(steps, "dev_search", 2))

        ranked = sorted(
            candidates,
            key=lambda index: (
                -self._priority(work_type, steps, index),
                -index,
            ),
        )
        chosen = sorted(ranked[: self._max_selected_steps])
        return tuple(chosen)

    @staticmethod
    def _latest_per_kind(steps: tuple[WorkStep, ...]) -> set[int]:
        latest: dict[str, int] = {}
        for index, step in enumerate(steps):
            latest[step.kind] = index
        return set(latest.values())

    @staticmethod
    def _latest_n(
        steps: tuple[WorkStep, ...],
        kind: str,
        limit: int,
    ) -> set[int]:
        matching = [
            index for index, step in enumerate(steps) if step.kind == kind
        ]
        return set(matching[-limit:])

    @staticmethod
    def _priority(
        work_type: WorkType,
        steps: tuple[WorkStep, ...],
        index: int,
    ) -> int:
        step = steps[index]
        if index >= len(steps) - 3:
            return 120
        if step.state in {WorkStepState.FAILED, WorkStepState.INTERRUPTED}:
            return 115
        if step.kind in {"owner_input", "completion_guard", "provider_pressure"}:
            return 110

        critical: set[str] = set()
        if work_type is WorkType.DEVELOPMENT:
            critical = {
                "dev_prepare_workspace",
                "dev_write_file",
                "dev_run_tests",
                "dev_diff",
                "dev_commit",
                "dev_status",
                "dev_resolve_python_dependency",
                "dev_bind_capability_manifest",
                "dev_verify_capability_substrate",
            }
        elif work_type is WorkType.DIAGNOSTICS:
            critical = {
                "diag_get_incident",
                "diag_retrieve_knowledge",
                "diag_prepare_workspace",
                "diag_run_reproduction",
                "diag_record_hypothesis",
                "diag_finalize",
            }
        elif work_type is WorkType.RESEARCH:
            critical = {
                "acq_inspect_goal",
                "acq_resolve",
                "acq_finalize",
                "research_web",
            }

        if step.kind in critical:
            return 100
        return 70

    def _project_step(self, step: WorkStep) -> WorkContextStep:
        compact_input = self._compact_value(step.input_data)
        compact_observation = self._compact_value(step.observation)
        if not isinstance(compact_input, dict):
            raise TypeError("compacted WorkStep input must remain an object")
        if not isinstance(compact_observation, dict):
            raise TypeError("compacted WorkStep observation must remain an object")
        return WorkContextStep(
            step_id=step.step_id,
            kind=step.kind,
            summary=step.summary,
            state=step.state.value,
            input_data=compact_input,
            observation=compact_observation,
            error=(
                None
                if step.error is None
                else self._compact_text(step.error)
            ),
        )

    def _compact_value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self._compact_text(value)
        if isinstance(value, dict):
            return {
                str(key): self._compact_value(item)
                for key, item in value.items()
            }
        if isinstance(value, tuple):
            value = list(value)
        if isinstance(value, list):
            if len(value) <= self._max_list_items:
                return [self._compact_value(item) for item in value]
            head_count = max(1, self._max_list_items - 9)
            head = [
                self._compact_value(item)
                for item in value[:head_count]
            ]
            tail = [
                self._compact_value(item)
                for item in value[-8:]
            ]
            omitted = len(value) - len(head) - len(tail)
            return [
                *head,
                {"c6_omitted_list_items": omitted},
                *tail,
            ]
        return value

    def _compact_text(self, value: str) -> str:
        if len(value) <= self._max_string_chars:
            return value
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
        marker = (
            "\n...[C6_CONTEXT_TRUNCATED "
            f"original_chars={len(value)} sha256={digest}]...\n"
        )
        available = max(1, self._max_string_chars - len(marker))
        head_chars = max(1, int(available * 0.67))
        tail_chars = max(1, available - head_chars)
        return value[:head_chars] + marker + value[-tail_chars:]


def _deduplicate_evidence(
    evidence: list[dict[str, Any]],
) -> tuple[dict[str, Any], ...]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in evidence:
        if not isinstance(item, dict):
            raise TypeError("context evidence items must be objects")
        encoded = json.dumps(
            item,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            default=str,
        )
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        output.append(dict(item))
    return tuple(output)


def _serialized_chars(payload: dict[str, Any]) -> int:
    return len(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            default=str,
        )
    )


def _estimated_tokens(char_count: int) -> int:
    return max(1, (int(char_count) + 3) // 4)
