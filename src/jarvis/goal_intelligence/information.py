"""Typed information resolution and exact owner-input binding for GICC."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Protocol

from jarvis.conversation import ConversationRole, ConversationTurn

from .models import (
    InformationNeedCategory,
    InformationNeedState,
    InformationNeedV1,
)
from .store import GoalStore, GoalStoreConflict


class InformationResolutionState(str, Enum):
    RESOLVED = "resolved"
    NEEDS_OWNER = "needs_owner"
    UNRESOLVED = "unresolved"


class InformationResolutionStrategy(str, Enum):
    CONVERSATION_CONTEXT = "conversation_context"
    WORLD_REGISTRY = "world_registry"
    CURRENT_STATE_OBSERVATION = "current_state_observation"
    BOUNDED_LOCAL_DISCOVERY = "bounded_local_discovery"
    RESEARCH_RETRIEVAL = "research_retrieval"
    OWNER_INPUT = "owner_input"
    SECRET_FLOW = "secret_flow"


@dataclass(frozen=True, slots=True)
class InformationProbeResult:
    resolution_ref: str | None
    evidence_refs: tuple[str, ...] = ()
    reason: str = ""

    @property
    def resolved(self) -> bool:
        return bool(self.resolution_ref)


class InformationProbe(Protocol):
    strategy: InformationResolutionStrategy

    def resolve(self, need: InformationNeedV1) -> InformationProbeResult: ...


@dataclass(frozen=True, slots=True)
class InformationResolutionResult:
    state: InformationResolutionState
    need: InformationNeedV1
    attempted_strategies: tuple[InformationResolutionStrategy, ...]
    interaction: dict[str, object] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, InformationResolutionState):
            raise TypeError("state must be InformationResolutionState")
        if not isinstance(self.need, InformationNeedV1):
            raise TypeError("need must be InformationNeedV1")
        if (
            self.state is InformationResolutionState.NEEDS_OWNER
            and self.interaction is None
        ):
            raise ValueError("NEEDS_OWNER requires an exact interaction binding")


_DEFAULT_ORDER = (
    InformationResolutionStrategy.CONVERSATION_CONTEXT,
    InformationResolutionStrategy.WORLD_REGISTRY,
    InformationResolutionStrategy.CURRENT_STATE_OBSERVATION,
    InformationResolutionStrategy.BOUNDED_LOCAL_DISCOVERY,
    InformationResolutionStrategy.RESEARCH_RETRIEVAL,
)


class InformationResolver:
    """Try self-resolution in bounded order; owner input is always last."""

    def __init__(
        self,
        *,
        store: GoalStore,
        probes: tuple[InformationProbe, ...] | list[InformationProbe] = (),
    ) -> None:
        if not isinstance(store, GoalStore):
            raise TypeError("store must be GoalStore")
        self._store = store
        self._probes = {probe.strategy: probe for probe in probes}
        if len(self._probes) != len(tuple(probes)):
            raise ValueError("information resolution strategies must be unique")

    def resolve(
        self,
        need: InformationNeedV1,
        *,
        owner_question: str | None = None,
        created_at: str | None = None,
    ) -> InformationResolutionResult:
        if not isinstance(need, InformationNeedV1):
            raise TypeError("need must be InformationNeedV1")
        current = self._store.get_information_need(need.information_need_id)
        if current is None:
            current = self._store.create_information_need(need)
        if current.state is InformationNeedState.RESOLVED:
            return InformationResolutionResult(
                state=InformationResolutionState.RESOLVED,
                need=current,
                attempted_strategies=(),
            )

        allowed = {
            InformationResolutionStrategy(item)
            for item in current.allowed_resolution_sources
            if item in {strategy.value for strategy in InformationResolutionStrategy}
        }
        attempted: list[InformationResolutionStrategy] = []
        observed_evidence: set[str] = set()

        for strategy in _DEFAULT_ORDER:
            if strategy not in allowed:
                continue
            attempted.append(strategy)
            probe = self._probes.get(strategy)
            if probe is None:
                continue
            result = probe.resolve(current)
            observed_evidence.update(result.evidence_refs)
            if result.resolved:
                resolved = self._store.resolve_information_need(
                    current.information_need_id,
                    resolution_ref=str(result.resolution_ref),
                    evidence_refs=tuple(sorted(observed_evidence)),
                    expected_revision=current.revision,
                    resolved_at=datetime.now(UTC).isoformat(),
                )
                return InformationResolutionResult(
                    state=InformationResolutionState.RESOLVED,
                    need=resolved,
                    attempted_strategies=tuple(attempted),
                )

        attempt_values = tuple(strategy.value for strategy in attempted)
        owner_allowed = InformationResolutionStrategy.OWNER_INPUT in allowed
        secret_required = (
            current.category is InformationNeedCategory.OWNER_SECRET
            or InformationResolutionStrategy.SECRET_FLOW in allowed
        )
        if secret_required:
            # Secret collection must be performed by the dedicated secret flow, not
            # generic conversational owner input.
            updated = self._store.update_information_need_state(
                current.information_need_id,
                InformationNeedState.WAITING_FOR_OWNER,
                expected_revision=current.revision,
                self_resolution_attempts=(
                    *attempt_values,
                    InformationResolutionStrategy.SECRET_FLOW.value,
                ),
                owner_question=owner_question,
                evidence_refs=tuple(sorted(observed_evidence)),
            )
            interaction = self._store.begin_information_interaction(
                need_id=updated.information_need_id,
                created_at=created_at or datetime.now(UTC).isoformat(),
            )
            return InformationResolutionResult(
                state=InformationResolutionState.NEEDS_OWNER,
                need=updated,
                attempted_strategies=(
                    *attempted,
                    InformationResolutionStrategy.SECRET_FLOW,
                ),
                interaction=interaction,
            )

        if owner_allowed:
            updated = self._store.update_information_need_state(
                current.information_need_id,
                InformationNeedState.WAITING_FOR_OWNER,
                expected_revision=current.revision,
                self_resolution_attempts=attempt_values,
                owner_question=owner_question,
                evidence_refs=tuple(sorted(observed_evidence)),
            )
            interaction = self._store.begin_information_interaction(
                need_id=updated.information_need_id,
                created_at=created_at or datetime.now(UTC).isoformat(),
            )
            return InformationResolutionResult(
                state=InformationResolutionState.NEEDS_OWNER,
                need=updated,
                attempted_strategies=tuple(attempted),
                interaction=interaction,
            )

        updated = self._store.update_information_need_state(
            current.information_need_id,
            InformationNeedState.SELF_RESOLVING,
            expected_revision=current.revision,
            self_resolution_attempts=attempt_values,
            evidence_refs=tuple(sorted(observed_evidence)),
        )
        return InformationResolutionResult(
            state=InformationResolutionState.UNRESOLVED,
            need=updated,
            attempted_strategies=tuple(attempted),
        )


class BoundInformationInteraction:
    """One exact active GICC InformationNeed interaction.

    Ambient speech is never consumed by this object.  A caller must explicitly route
    a canonical USER turn to the exact interaction, goal and InformationNeed IDs.
    """

    def __init__(
        self,
        *,
        store: GoalStore,
        interaction_id: str,
        goal_id: str,
        information_need_id: str,
    ) -> None:
        if not isinstance(store, GoalStore):
            raise TypeError("store must be GoalStore")
        self._store = store
        self.interaction_id = str(interaction_id).strip()
        self.goal_id = str(goal_id).strip()
        self.information_need_id = str(information_need_id).strip()
        if not all((self.interaction_id, self.goal_id, self.information_need_id)):
            raise ValueError("bound interaction identifiers must not be empty")
        interaction = self._store.get_information_interaction(self.interaction_id)
        if interaction is None:
            raise GoalStoreConflict("bound information interaction does not exist")
        if (
            interaction["goal_id"] != self.goal_id
            or interaction["information_need_id"] != self.information_need_id
        ):
            raise GoalStoreConflict(
                "bound information interaction identifiers do not match"
            )

    @property
    def snapshot(self) -> dict[str, object]:
        interaction = self._store.get_information_interaction(self.interaction_id)
        if interaction is None:
            raise GoalStoreConflict("bound information interaction disappeared")
        return interaction

    def submit(
        self,
        turn: ConversationTurn,
        *,
        resolution_ref: str,
        resolved_at: str | None = None,
    ) -> InformationNeedV1:
        if not isinstance(turn, ConversationTurn):
            raise TypeError("turn must be ConversationTurn")
        if turn.role is not ConversationRole.USER:
            raise ValueError("only a canonical USER turn may resolve InformationNeed")
        return self._store.submit_information_interaction_reply(
            interaction_id=self.interaction_id,
            goal_id=self.goal_id,
            need_id=self.information_need_id,
            source_turn_id=turn.turn_id,
            resolution_ref=resolution_ref,
            resolved_at=resolved_at or datetime.now(UTC).isoformat(),
        )


def restore_bound_information_interaction(
    *,
    store: GoalStore,
    interaction_id: str,
) -> BoundInformationInteraction:
    interaction = store.get_information_interaction(interaction_id)
    if interaction is None:
        raise GoalStoreConflict("information interaction does not exist")
    if interaction["state"] not in {"active", "resolved"}:
        raise GoalStoreConflict("information interaction is not restorable")
    return BoundInformationInteraction(
        store=store,
        interaction_id=interaction_id,
        goal_id=str(interaction["goal_id"]),
        information_need_id=str(interaction["information_need_id"]),
    )
