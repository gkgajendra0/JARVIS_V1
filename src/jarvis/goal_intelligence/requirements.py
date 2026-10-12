"""Semantic capability requirement derivation and deterministic validation."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from jarvis.hands.provider_adapters import StructuredOutputClient

from .models import (
    CapabilityRequirementGraphV1,
    CapabilityRequirementV1,
    GoalInterpretationCandidateV1,
    OwnerGoalV2,
)
from .world import canonical_world_entity_type

_FAMILY_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
_OPERATION_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class RequirementDerivationError(RuntimeError):
    pass


class CapabilityRequirementProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    semantic_capability: str = Field(min_length=3, max_length=120)
    operation: str = Field(min_length=1, max_length=120)
    target_entity_id: str | None = Field(default=None, max_length=180)
    target_entity_type: str | None = Field(default=None, max_length=80)
    required_parameters_json: str = Field(default="{}", min_length=2, max_length=16_000)
    preconditions: list[str] = Field(default_factory=list, max_length=16)
    expected_postconditions: list[str] = Field(default_factory=list, max_length=16)
    observation_requirements: list[str] = Field(default_factory=list, max_length=16)
    reason: str = Field(min_length=1, max_length=480)
    depends_on_indexes: list[int] = Field(default_factory=list, max_length=20)

    @model_validator(mode="before")
    @classmethod
    def _legacy_parameter_schema_input(cls, value):
        if not isinstance(value, dict):
            return value
        if (
            "required_parameters_schema" not in value
            or "required_parameters_json" in value
        ):
            return value
        normalized = dict(value)
        legacy = normalized.pop("required_parameters_schema")
        normalized["required_parameters_json"] = json.dumps(
            legacy,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        return normalized

    @field_validator("required_parameters_json")
    @classmethod
    def _parameters_json(cls, value: str) -> str:
        raw = str(value).strip()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("required_parameters_json must be valid JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError(  # noqa: TRY004 - Pydantic validator contract
                "required_parameters_json must encode a JSON object"
            )
        encoded = json.dumps(
            parsed,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        if len(encoded) > 16_000:
            raise ValueError("required_parameters_json exceeds bounded size")
        return encoded

    @property
    def required_parameters_schema(self) -> dict[str, object]:
        parsed = json.loads(self.required_parameters_json)
        if not isinstance(parsed, dict):
            raise RequirementDerivationError(
                "required parameter contract is not a JSON object"
            )
        return parsed

    @field_validator("semantic_capability")
    @classmethod
    def _family(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if not _FAMILY_RE.fullmatch(normalized):
            raise ValueError("semantic_capability must be a reusable dotted family")
        return normalized

    @field_validator("operation")
    @classmethod
    def _operation(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if not _OPERATION_RE.fullmatch(normalized):
            raise ValueError("operation must be a semantic identifier")
        return normalized

    @field_validator("target_entity_id", "target_entity_type")
    @classmethod
    def _optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().casefold()
        return normalized or None

    @field_validator(
        "preconditions",
        "expected_postconditions",
        "observation_requirements",
    )
    @classmethod
    def _unique_text(cls, value: list[str]) -> list[str]:
        return sorted({str(item).strip() for item in value if str(item).strip()})

    @field_validator("depends_on_indexes")
    @classmethod
    def _dependencies(cls, value: list[int]) -> list[int]:
        if any(isinstance(item, bool) or item < 0 for item in value):
            raise ValueError("depends_on_indexes must contain non-negative integers")
        return sorted(set(value))


class CapabilityRequirementProposalSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirements: list[CapabilityRequirementProposal] = Field(
        min_length=1,
        max_length=40,
    )


@dataclass(frozen=True, slots=True)
class RequirementDerivationResult:
    graph: CapabilityRequirementGraphV1
    requirements: tuple[CapabilityRequirementV1, ...]
    provider_name: str
    model_name: str


_SYSTEM_PROMPT = """
You derive semantic capability requirements for JARVIS GICC.
Return reusable capability families and generic operations only.

Permanent rules:
- owner task parameters are not capability identity;
- providers, devices/resources and Authority are separate from capability identity;
- canonical world target types are camera, computer, display, entrance, media_player,
  room and generic_external_resource; normalize TV/television to media_player;
- use reusable dotted families such as media_player.control, camera.observe,
  vision.perceive, notification.owner, computer.application;
- do not put movie titles, filenames, people, search terms, brands or resource names
  into capability family or operation identifiers;
- target_entity_id may only use an ID supplied by JARVIS;
- every consequential requirement must include a postcondition or observation requirement;
- required_parameters_json must be a compact JSON object string describing only
  task parameters required by the generic operation; use "{}" when none are needed;
- do not grant permission and do not claim execution succeeded;
- keep acquisition requirements to the minimum operations needed by the current goal.
""".strip()


def _identifier_terms(value: str) -> set[str]:
    return {
        token for token in re.split(r"[._:-]+", str(value).strip().casefold()) if token
    }


class RequirementValidator:
    """Fail closed around a reasoning worker's requirement proposal."""

    def validate(
        self,
        *,
        goal: OwnerGoalV2,
        proposals: tuple[CapabilityRequirementProposal, ...]
        | list[CapabilityRequirementProposal],
        known_entity_ids: tuple[str, ...] | list[str] = (),
        task_specific_terms: tuple[str, ...] | list[str] = (),
    ) -> CapabilityRequirementGraphV1:
        if not isinstance(goal, OwnerGoalV2):
            raise TypeError("goal must be OwnerGoalV2")
        proposal_values = tuple(proposals)
        if not proposal_values:
            raise RequirementDerivationError("at least one requirement is required")
        known = {
            str(item).strip().casefold()
            for item in known_entity_ids
            if str(item).strip()
        }
        forbidden = {
            str(item).strip().casefold()
            for item in task_specific_terms
            if len(str(item).strip()) >= 3
        }
        requirements: list[CapabilityRequirementV1] = []
        for proposal in proposal_values:
            if not isinstance(proposal, CapabilityRequirementProposal):
                raise TypeError(
                    "proposals must contain CapabilityRequirementProposal values"
                )
            identity_terms = _identifier_terms(proposal.semantic_capability) | {
                proposal.operation
            }
            leaked = forbidden & identity_terms
            if leaked:
                raise RequirementDerivationError(
                    "task-specific parameter leaked into capability identity: "
                    + ",".join(sorted(leaked))
                )
            if (
                proposal.target_entity_id is not None
                and proposal.target_entity_id not in known
            ):
                raise RequirementDerivationError(
                    "requirement target entity is not bound to canonical world state"
                )
            if not (
                proposal.expected_postconditions or proposal.observation_requirements
            ):
                raise RequirementDerivationError(
                    "requirement lacks completion/observation evidence"
                )
            requirements.append(
                CapabilityRequirementV1.create(
                    goal_id=goal.goal_id,
                    semantic_capability=proposal.semantic_capability,
                    operation=proposal.operation,
                    target_entity_id=proposal.target_entity_id,
                    target_entity_type=(
                        None
                        if proposal.target_entity_type is None
                        else canonical_world_entity_type(proposal.target_entity_type)
                    ),
                    required_parameters_schema=proposal.required_parameters_schema,
                    preconditions=tuple(proposal.preconditions),
                    expected_postconditions=tuple(proposal.expected_postconditions),
                    observation_requirements=tuple(proposal.observation_requirements),
                    reason=proposal.reason,
                )
            )

        edges: list[tuple[str, str]] = []
        for index, proposal in enumerate(proposal_values):
            for dependency in proposal.depends_on_indexes:
                if dependency >= len(requirements):
                    raise RequirementDerivationError(
                        "requirement dependency references an unknown index"
                    )
                if dependency == index:
                    raise RequirementDerivationError(
                        "requirement cannot depend on itself"
                    )
                edges.append(
                    (
                        requirements[dependency].requirement_id,
                        requirements[index].requirement_id,
                    )
                )

        return CapabilityRequirementGraphV1.create(
            goal_id=goal.goal_id,
            requirements=tuple(requirements),
            edges=tuple(edges),
            completion_predicates=goal.completion_predicates,
        )


class RequirementDeriver:
    def __init__(
        self,
        *,
        client: StructuredOutputClient,
        validator: RequirementValidator | None = None,
    ) -> None:
        self._client = client
        self._validator = validator or RequirementValidator()

    @property
    def provider_name(self) -> str:
        return str(self._client.provider_name)

    @property
    def model_name(self) -> str:
        return str(self._client.model_name)

    async def derive(
        self,
        *,
        goal: OwnerGoalV2,
        interpretation: GoalInterpretationCandidateV1,
        known_entity_ids: tuple[str, ...] | list[str] = (),
        task_specific_terms: tuple[str, ...] | list[str] = (),
    ) -> RequirementDerivationResult:
        if not isinstance(interpretation, GoalInterpretationCandidateV1):
            raise TypeError("interpretation must be GoalInterpretationCandidateV1")
        input_payload = {
            "goal": {
                "goal_id": goal.goal_id,
                "goal_kind": goal.goal_kind.value,
                "desired_outcome": goal.desired_outcome,
                "completion_predicates": list(goal.completion_predicates),
                "referenced_entity_ids": list(goal.referenced_entity_ids),
            },
            "interpretation": interpretation.canonical_payload(),
            "known_entity_ids": sorted(
                {
                    str(item).strip().casefold()
                    for item in known_entity_ids
                    if str(item).strip()
                }
            ),
        }
        telemetry = await self._client.parse_with_telemetry(
            system_prompt=_SYSTEM_PROMPT,
            input_payload=input_payload,
            response_model=CapabilityRequirementProposalSet,
        )
        parsed = telemetry.parsed
        if not isinstance(parsed, CapabilityRequirementProposalSet):
            raise RequirementDerivationError(
                "requirement worker returned the wrong structured-output contract"
            )
        graph = self._validator.validate(
            goal=goal,
            proposals=tuple(parsed.requirements),
            known_entity_ids=known_entity_ids,
            task_specific_terms=task_specific_terms,
        )
        return RequirementDerivationResult(
            graph=graph,
            requirements=graph.requirements,
            provider_name=self.provider_name,
            model_name=self.model_name,
        )
