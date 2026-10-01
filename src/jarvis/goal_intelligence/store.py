"""Protected additive persistence for GICC canonical state."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.work.privacy import build_default_work_payload_codec
from jarvis.work.store import SQLiteWorkStore, default_work_store_path

from .models import (
    CapabilityGapState,
    CapabilityGapV1,
    CapabilityRequirementGraphV1,
    GoalContinuationV1,
    GoalState,
    InformationNeedState,
    InformationNeedV1,
    MonitorPredicateV1,
    OwnerGoalV2,
    PlanGraphV1,
    ResourceBindingV1,
    WorldEntityRefV1,
)


class GoalStoreError(RuntimeError):
    pass


class GoalStoreConflict(GoalStoreError):
    pass


class GoalStore:
    """Own GICC tables while reusing the canonical protected WorkStore database."""

    def __init__(self, work_store: SQLiteWorkStore) -> None:
        if not isinstance(work_store, SQLiteWorkStore):
            raise TypeError("work_store must be SQLiteWorkStore")
        self.work = work_store
        self._initialize()

    @property
    def payload_protected(self) -> bool:
        return self.work.payload_protected

    def _initialize(self) -> None:
        with self.work.extension_transaction() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS owner_goals_v2 (
                    goal_id TEXT PRIMARY KEY,
                    goal_revision INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    source_session_id TEXT NOT NULL,
                    source_turn_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    digest TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(source_session_id, source_turn_id)
                );

                CREATE TABLE IF NOT EXISTS world_entities_v1 (
                    entity_id TEXT PRIMARY KEY,
                    entity_type TEXT NOT NULL,
                    lifecycle_state TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    digest TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS resource_bindings_v1 (
                    binding_id TEXT PRIMARY KEY,
                    binding_revision INTEGER NOT NULL,
                    entity_id TEXT NOT NULL,
                    provider_id TEXT NOT NULL,
                    provider_resource_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    binding_digest TEXT NOT NULL,
                    last_verified_at TEXT NOT NULL,
                    FOREIGN KEY(entity_id) REFERENCES world_entities_v1(entity_id),
                    UNIQUE(entity_id, provider_id, provider_resource_id)
                );

                CREATE TABLE IF NOT EXISTS information_needs_v1 (
                    information_need_id TEXT PRIMARY KEY,
                    revision INTEGER NOT NULL,
                    goal_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    category TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    digest TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    resolved_at TEXT,
                    FOREIGN KEY(goal_id) REFERENCES owner_goals_v2(goal_id)
                );

                CREATE INDEX IF NOT EXISTS idx_information_needs_goal_state
                    ON information_needs_v1(goal_id, state);

                CREATE TABLE IF NOT EXISTS capability_requirement_graphs_v1 (
                    graph_id TEXT PRIMARY KEY,
                    goal_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    digest TEXT NOT NULL,
                    FOREIGN KEY(goal_id) REFERENCES owner_goals_v2(goal_id)
                );

                CREATE TABLE IF NOT EXISTS capability_gaps_v1 (
                    gap_id TEXT PRIMARY KEY,
                    revision INTEGER NOT NULL,
                    goal_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    reusable_capability_family TEXT NOT NULL,
                    target_entity_type TEXT NOT NULL,
                    target_entity_id TEXT,
                    minimum_operations_key TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    digest TEXT NOT NULL,
                    FOREIGN KEY(goal_id) REFERENCES owner_goals_v2(goal_id)
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_active_capability_gap
                    ON capability_gaps_v1(
                        goal_id,
                        reusable_capability_family,
                        target_entity_type,
                        IFNULL(target_entity_id, ''),
                        minimum_operations_key
                    )
                    WHERE state = 'open';

                CREATE TABLE IF NOT EXISTS plan_graphs_v1 (
                    plan_id TEXT PRIMARY KEY,
                    goal_id TEXT NOT NULL,
                    goal_revision INTEGER NOT NULL,
                    plan_revision INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    digest TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(goal_id) REFERENCES owner_goals_v2(goal_id),
                    UNIQUE(goal_id, goal_revision, plan_revision)
                );

                CREATE TABLE IF NOT EXISTS goal_continuations_v1 (
                    continuation_id TEXT PRIMARY KEY,
                    revision INTEGER NOT NULL,
                    goal_id TEXT NOT NULL,
                    plan_id TEXT NOT NULL,
                    blocked_by_type TEXT NOT NULL,
                    blocked_by_id TEXT NOT NULL,
                    resume_node_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    digest TEXT NOT NULL,
                    resumed_at TEXT,
                    FOREIGN KEY(goal_id) REFERENCES owner_goals_v2(goal_id),
                    UNIQUE(
                        goal_id,
                        plan_id,
                        blocked_by_type,
                        blocked_by_id,
                        resume_node_id
                    )
                );

                CREATE TABLE IF NOT EXISTS monitor_predicates_v1 (
                    predicate_id TEXT PRIMARY KEY,
                    goal_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    digest TEXT NOT NULL,
                    FOREIGN KEY(goal_id) REFERENCES owner_goals_v2(goal_id)
                );
                """
            )

    def _encode(self, payload: dict[str, object]) -> str:
        return self.work.encode_extension_json(payload)

    def _decode(self, payload: str) -> dict[str, object]:
        decoded = self.work.decode_extension_json(payload)
        if not isinstance(decoded, dict):
            raise GoalStoreError("stored GICC payload must decode to an object")
        return decoded

    def create_goal(self, goal: OwnerGoalV2) -> OwnerGoalV2:
        if not isinstance(goal, OwnerGoalV2):
            raise TypeError("goal must be OwnerGoalV2")
        with self.work.extension_transaction() as db:
            existing = db.execute(
                "SELECT payload, digest FROM owner_goals_v2 WHERE goal_id=?",
                (goal.goal_id,),
            ).fetchone()
            if existing is not None:
                current = OwnerGoalV2.from_payload(
                    self._decode(existing["payload"]), existing["digest"]
                )
                if current.digest != goal.digest:
                    raise GoalStoreConflict("goal_id already exists with different payload")
                return current
            db.execute(
                """
                INSERT INTO owner_goals_v2 (
                    goal_id, goal_revision, state, source_session_id, source_turn_id,
                    payload, digest, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    goal.goal_id,
                    goal.goal_revision,
                    goal.state.value,
                    goal.source_session_id,
                    goal.source_turn_id,
                    self._encode(goal.canonical_payload()),
                    goal.digest,
                    goal.created_at,
                    goal.updated_at,
                ),
            )
        return goal

    def get_goal(self, goal_id: str) -> OwnerGoalV2 | None:
        with self.work.extension_transaction() as db:
            row = db.execute(
                "SELECT payload, digest FROM owner_goals_v2 WHERE goal_id=?",
                (goal_id,),
            ).fetchone()
        if row is None:
            return None
        return OwnerGoalV2.from_payload(self._decode(row["payload"]), row["digest"])

    def update_goal_state(
        self,
        goal_id: str,
        state: GoalState,
        *,
        expected_revision: int,
        updated_at: str | None = None,
    ) -> OwnerGoalV2:
        if not isinstance(state, GoalState):
            raise TypeError("state must be GoalState")
        with self.work.extension_transaction() as db:
            row = db.execute(
                """
                SELECT goal_revision, payload, digest
                FROM owner_goals_v2
                WHERE goal_id=?
                """,
                (goal_id,),
            ).fetchone()
            if row is None:
                raise GoalStoreError(f"unknown goal_id: {goal_id}")
            current = OwnerGoalV2.from_payload(
                self._decode(row["payload"]), row["digest"]
            )
            if current.goal_revision != expected_revision:
                raise GoalStoreConflict(
                    "goal revision changed before compare-and-swap update"
                )
            if current.state is state:
                return current
            updated = current.with_state(state, updated_at=updated_at)
            result = db.execute(
                """
                UPDATE owner_goals_v2
                SET goal_revision=?, state=?, payload=?, digest=?, updated_at=?
                WHERE goal_id=? AND goal_revision=?
                """,
                (
                    updated.goal_revision,
                    updated.state.value,
                    self._encode(updated.canonical_payload()),
                    updated.digest,
                    updated.updated_at,
                    goal_id,
                    expected_revision,
                ),
            )
            if result.rowcount != 1:
                raise GoalStoreConflict("goal compare-and-swap update lost")
        return updated

    def put_entity(self, entity: WorldEntityRefV1) -> WorldEntityRefV1:
        if not isinstance(entity, WorldEntityRefV1):
            raise TypeError("entity must be WorldEntityRefV1")
        with self.work.extension_transaction() as db:
            row = db.execute(
                "SELECT digest, payload FROM world_entities_v1 WHERE entity_id=?",
                (entity.entity_id,),
            ).fetchone()
            if row is not None:
                current = WorldEntityRefV1.from_payload(
                    self._decode(row["payload"]), row["digest"]
                )
                if current.digest != entity.digest:
                    raise GoalStoreConflict(
                        "entity_id already exists with different canonical payload"
                    )
                return current
            db.execute(
                """
                INSERT INTO world_entities_v1 (
                    entity_id, entity_type, lifecycle_state, payload, digest
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    entity.entity_id,
                    entity.entity_type,
                    entity.lifecycle_state.value,
                    self._encode(entity.canonical_payload()),
                    entity.digest,
                ),
            )
        return entity

    def get_entity(self, entity_id: str) -> WorldEntityRefV1 | None:
        with self.work.extension_transaction() as db:
            row = db.execute(
                "SELECT payload, digest FROM world_entities_v1 WHERE entity_id=?",
                (entity_id,),
            ).fetchone()
        if row is None:
            return None
        return WorldEntityRefV1.from_payload(
            self._decode(row["payload"]), row["digest"]
        )

    def put_resource_binding(self, binding: ResourceBindingV1) -> ResourceBindingV1:
        if not isinstance(binding, ResourceBindingV1):
            raise TypeError("binding must be ResourceBindingV1")
        with self.work.extension_transaction() as db:
            row = db.execute(
                """
                SELECT payload, binding_digest
                FROM resource_bindings_v1
                WHERE binding_id=?
                """,
                (binding.binding_id,),
            ).fetchone()
            if row is not None:
                current = ResourceBindingV1.from_payload(
                    self._decode(row["payload"]), row["binding_digest"]
                )
                if current.binding_digest != binding.binding_digest:
                    raise GoalStoreConflict(
                        "binding_id already exists with different canonical payload"
                    )
                return current
            db.execute(
                """
                INSERT INTO resource_bindings_v1 (
                    binding_id, binding_revision, entity_id, provider_id,
                    provider_resource_id, payload, binding_digest, last_verified_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    binding.binding_id,
                    binding.binding_revision,
                    binding.entity_id,
                    binding.provider_id,
                    binding.provider_resource_id,
                    self._encode(binding.canonical_payload()),
                    binding.binding_digest,
                    binding.last_verified_at,
                ),
            )
        return binding

    def get_resource_binding(self, binding_id: str) -> ResourceBindingV1 | None:
        with self.work.extension_transaction() as db:
            row = db.execute(
                """
                SELECT payload, binding_digest
                FROM resource_bindings_v1
                WHERE binding_id=?
                """,
                (binding_id,),
            ).fetchone()
        if row is None:
            return None
        return ResourceBindingV1.from_payload(
            self._decode(row["payload"]), row["binding_digest"]
        )

    def create_information_need(self, need: InformationNeedV1) -> InformationNeedV1:
        if not isinstance(need, InformationNeedV1):
            raise TypeError("need must be InformationNeedV1")
        with self.work.extension_transaction() as db:
            row = db.execute(
                """
                SELECT payload, digest
                FROM information_needs_v1
                WHERE information_need_id=?
                """,
                (need.information_need_id,),
            ).fetchone()
            if row is not None:
                current = InformationNeedV1.from_payload(
                    self._decode(row["payload"]), row["digest"]
                )
                if current.digest != need.digest:
                    raise GoalStoreConflict(
                        "information_need_id already exists with different payload"
                    )
                return current
            db.execute(
                """
                INSERT INTO information_needs_v1 (
                    information_need_id, revision, goal_id, state, category,
                    payload, digest, created_at, resolved_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    need.information_need_id,
                    need.revision,
                    need.goal_id,
                    need.state.value,
                    need.category.value,
                    self._encode(need.canonical_payload()),
                    need.digest,
                    need.created_at,
                    need.resolved_at,
                ),
            )
        return need

    def get_information_need(self, need_id: str) -> InformationNeedV1 | None:
        with self.work.extension_transaction() as db:
            row = db.execute(
                """
                SELECT payload, digest
                FROM information_needs_v1
                WHERE information_need_id=?
                """,
                (need_id,),
            ).fetchone()
        if row is None:
            return None
        return InformationNeedV1.from_payload(
            self._decode(row["payload"]), row["digest"]
        )

    def resolve_information_need(
        self,
        need_id: str,
        *,
        resolution_ref: str,
        evidence_refs: tuple[str, ...] | list[str] = (),
        expected_revision: int | None = None,
        resolved_at: str | None = None,
    ) -> InformationNeedV1:
        with self.work.extension_transaction() as db:
            row = db.execute(
                """
                SELECT revision, payload, digest
                FROM information_needs_v1
                WHERE information_need_id=?
                """,
                (need_id,),
            ).fetchone()
            if row is None:
                raise GoalStoreError(f"unknown information_need_id: {need_id}")
            current = InformationNeedV1.from_payload(
                self._decode(row["payload"]), row["digest"]
            )
            if current.state is InformationNeedState.RESOLVED:
                if current.resolution_ref == resolution_ref:
                    return current
                raise GoalStoreConflict(
                    "information need is already resolved to another reference"
                )
            if expected_revision is not None and current.revision != expected_revision:
                raise GoalStoreConflict(
                    "information need revision changed before resolution"
                )
            updated = current.with_resolution(
                resolution_ref=resolution_ref,
                evidence_refs=evidence_refs,
                resolved_at=resolved_at,
            )
            result = db.execute(
                """
                UPDATE information_needs_v1
                SET revision=?, state=?, payload=?, digest=?, resolved_at=?
                WHERE information_need_id=? AND revision=?
                """,
                (
                    updated.revision,
                    updated.state.value,
                    self._encode(updated.canonical_payload()),
                    updated.digest,
                    updated.resolved_at,
                    need_id,
                    current.revision,
                ),
            )
            if result.rowcount != 1:
                raise GoalStoreConflict(
                    "information need compare-and-swap resolution lost"
                )
        return updated

    def put_requirement_graph(
        self, graph: CapabilityRequirementGraphV1
    ) -> CapabilityRequirementGraphV1:
        return self._put_immutable(
            table="capability_requirement_graphs_v1",
            id_column="graph_id",
            id_value=graph.graph_id,
            goal_id=graph.goal_id,
            payload=graph.canonical_payload(),
            digest=graph.digest,
            loader=CapabilityRequirementGraphV1.from_payload,
        )

    def get_requirement_graph(
        self, graph_id: str
    ) -> CapabilityRequirementGraphV1 | None:
        result = self._get_immutable(
            table="capability_requirement_graphs_v1",
            id_column="graph_id",
            id_value=graph_id,
            loader=CapabilityRequirementGraphV1.from_payload,
        )
        return result if isinstance(result, CapabilityRequirementGraphV1) else None

    def put_gap(self, gap: CapabilityGapV1) -> CapabilityGapV1:
        if not isinstance(gap, CapabilityGapV1):
            raise TypeError("gap must be CapabilityGapV1")
        operations_key = "|".join(gap.minimum_required_operations)
        with self.work.extension_transaction() as db:
            row = db.execute(
                "SELECT payload, digest FROM capability_gaps_v1 WHERE gap_id=?",
                (gap.gap_id,),
            ).fetchone()
            if row is not None:
                current = CapabilityGapV1.from_payload(
                    self._decode(row["payload"]), row["digest"]
                )
                if current.digest != gap.digest:
                    raise GoalStoreConflict(
                        "gap_id already exists with different canonical payload"
                    )
                return current
            db.execute(
                """
                INSERT INTO capability_gaps_v1 (
                    gap_id, revision, goal_id, state, reusable_capability_family,
                    target_entity_type, target_entity_id, minimum_operations_key,
                    payload, digest
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    gap.gap_id,
                    gap.revision,
                    gap.goal_id,
                    gap.state.value,
                    gap.reusable_capability_family,
                    gap.target_entity_type,
                    gap.target_entity_id,
                    operations_key,
                    self._encode(gap.canonical_payload()),
                    gap.digest,
                ),
            )
        return gap

    def get_gap(self, gap_id: str) -> CapabilityGapV1 | None:
        with self.work.extension_transaction() as db:
            row = db.execute(
                "SELECT payload, digest FROM capability_gaps_v1 WHERE gap_id=?",
                (gap_id,),
            ).fetchone()
        if row is None:
            return None
        return CapabilityGapV1.from_payload(
            self._decode(row["payload"]), row["digest"]
        )

    def update_gap_state(
        self,
        gap_id: str,
        state: CapabilityGapState,
        *,
        expected_revision: int,
    ) -> CapabilityGapV1:
        if not isinstance(state, CapabilityGapState):
            raise TypeError("state must be CapabilityGapState")
        with self.work.extension_transaction() as db:
            row = db.execute(
                "SELECT payload, digest FROM capability_gaps_v1 WHERE gap_id=?",
                (gap_id,),
            ).fetchone()
            if row is None:
                raise GoalStoreError(f"unknown gap_id: {gap_id}")
            current = CapabilityGapV1.from_payload(
                self._decode(row["payload"]), row["digest"]
            )
            if current.revision != expected_revision:
                raise GoalStoreConflict("gap revision changed before update")
            if current.state is state:
                return current
            candidate = replace(
                current,
                revision=current.revision + 1,
                state=state,
                digest="pending",
            )
            updated = replace(
                candidate,
                digest=canonical_digest(candidate.canonical_payload()),
            )
            result = db.execute(
                """
                UPDATE capability_gaps_v1
                SET revision=?, state=?, payload=?, digest=?
                WHERE gap_id=? AND revision=?
                """,
                (
                    updated.revision,
                    updated.state.value,
                    self._encode(updated.canonical_payload()),
                    updated.digest,
                    gap_id,
                    current.revision,
                ),
            )
            if result.rowcount != 1:
                raise GoalStoreConflict("gap compare-and-swap update lost")
        return updated

    def put_plan(self, plan: PlanGraphV1) -> PlanGraphV1:
        if not isinstance(plan, PlanGraphV1):
            raise TypeError("plan must be PlanGraphV1")
        with self.work.extension_transaction() as db:
            row = db.execute(
                "SELECT payload, digest FROM plan_graphs_v1 WHERE plan_id=?",
                (plan.plan_id,),
            ).fetchone()
            if row is not None:
                current = PlanGraphV1.from_payload(
                    self._decode(row["payload"]), row["digest"]
                )
                if current.digest != plan.digest:
                    raise GoalStoreConflict(
                        "plan_id already exists with different canonical payload"
                    )
                return current
            db.execute(
                """
                INSERT INTO plan_graphs_v1 (
                    plan_id, goal_id, goal_revision, plan_revision, state,
                    payload, digest, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan.plan_id,
                    plan.goal_id,
                    plan.goal_revision,
                    plan.plan_revision,
                    plan.state.value,
                    self._encode(plan.canonical_payload()),
                    plan.digest,
                    plan.created_at,
                    plan.updated_at,
                ),
            )
        return plan

    def get_plan(self, plan_id: str) -> PlanGraphV1 | None:
        with self.work.extension_transaction() as db:
            row = db.execute(
                "SELECT payload, digest FROM plan_graphs_v1 WHERE plan_id=?",
                (plan_id,),
            ).fetchone()
        if row is None:
            return None
        return PlanGraphV1.from_payload(self._decode(row["payload"]), row["digest"])

    def put_continuation(
        self, continuation: GoalContinuationV1
    ) -> GoalContinuationV1:
        if not isinstance(continuation, GoalContinuationV1):
            raise TypeError("continuation must be GoalContinuationV1")
        with self.work.extension_transaction() as db:
            row = db.execute(
                """
                SELECT payload, digest
                FROM goal_continuations_v1
                WHERE continuation_id=?
                """,
                (continuation.continuation_id,),
            ).fetchone()
            if row is not None:
                current = GoalContinuationV1.from_payload(
                    self._decode(row["payload"]), row["digest"]
                )
                if current.digest != continuation.digest:
                    raise GoalStoreConflict(
                        "continuation_id already exists with different payload"
                    )
                return current
            db.execute(
                """
                INSERT INTO goal_continuations_v1 (
                    continuation_id, revision, goal_id, plan_id, blocked_by_type,
                    blocked_by_id, resume_node_id, state, payload, digest, resumed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    continuation.continuation_id,
                    continuation.revision,
                    continuation.goal_id,
                    continuation.plan_id,
                    continuation.blocked_by_type.value,
                    continuation.blocked_by_id,
                    continuation.resume_node_id,
                    continuation.state.value,
                    self._encode(continuation.canonical_payload()),
                    continuation.digest,
                    continuation.resumed_at,
                ),
            )
        return continuation

    def get_continuation(self, continuation_id: str) -> GoalContinuationV1 | None:
        with self.work.extension_transaction() as db:
            row = db.execute(
                """
                SELECT payload, digest
                FROM goal_continuations_v1
                WHERE continuation_id=?
                """,
                (continuation_id,),
            ).fetchone()
        if row is None:
            return None
        return GoalContinuationV1.from_payload(
            self._decode(row["payload"]), row["digest"]
        )

    def resume_continuation(
        self,
        continuation_id: str,
        *,
        expected_revision: int,
        resumed_at: str | None = None,
    ) -> GoalContinuationV1:
        with self.work.extension_transaction() as db:
            row = db.execute(
                """
                SELECT payload, digest
                FROM goal_continuations_v1
                WHERE continuation_id=?
                """,
                (continuation_id,),
            ).fetchone()
            if row is None:
                raise GoalStoreError(f"unknown continuation_id: {continuation_id}")
            current = GoalContinuationV1.from_payload(
                self._decode(row["payload"]), row["digest"]
            )
            if current.state.value == "resumed":
                return current
            if current.revision != expected_revision:
                raise GoalStoreConflict(
                    "continuation revision changed before resume"
                )
            updated = current.resumed(resumed_at=resumed_at)
            result = db.execute(
                """
                UPDATE goal_continuations_v1
                SET revision=?, state=?, payload=?, digest=?, resumed_at=?
                WHERE continuation_id=? AND revision=?
                """,
                (
                    updated.revision,
                    updated.state.value,
                    self._encode(updated.canonical_payload()),
                    updated.digest,
                    updated.resumed_at,
                    continuation_id,
                    current.revision,
                ),
            )
            if result.rowcount != 1:
                raise GoalStoreConflict("continuation compare-and-swap resume lost")
        return updated

    def put_monitor_predicate(
        self, predicate: MonitorPredicateV1
    ) -> MonitorPredicateV1:
        return self._put_immutable(
            table="monitor_predicates_v1",
            id_column="predicate_id",
            id_value=predicate.predicate_id,
            goal_id=predicate.goal_id,
            payload=predicate.canonical_payload(),
            digest=predicate.digest,
            loader=MonitorPredicateV1.from_payload,
        )

    def get_monitor_predicate(
        self, predicate_id: str
    ) -> MonitorPredicateV1 | None:
        result = self._get_immutable(
            table="monitor_predicates_v1",
            id_column="predicate_id",
            id_value=predicate_id,
            loader=MonitorPredicateV1.from_payload,
        )
        return result if isinstance(result, MonitorPredicateV1) else None

    def _put_immutable(
        self,
        *,
        table: str,
        id_column: str,
        id_value: str,
        goal_id: str,
        payload: dict[str, object],
        digest: str,
        loader,
    ):
        allowed = {
            ("capability_requirement_graphs_v1", "graph_id"),
            ("monitor_predicates_v1", "predicate_id"),
        }
        if (table, id_column) not in allowed:
            raise GoalStoreError("unsupported immutable GICC table")
        with self.work.extension_transaction() as db:
            row = db.execute(
                f"SELECT payload, digest FROM {table} WHERE {id_column}=?",
                (id_value,),
            ).fetchone()
            if row is not None:
                current = loader(self._decode(row["payload"]), row["digest"])
                if current.digest != digest:
                    raise GoalStoreConflict(
                        f"{id_column} already exists with different payload"
                    )
                return current
            db.execute(
                f"""
                INSERT INTO {table} ({id_column}, goal_id, payload, digest)
                VALUES (?, ?, ?, ?)
                """,
                (id_value, goal_id, self._encode(payload), digest),
            )
        return loader(payload, digest)

    def _get_immutable(
        self,
        *,
        table: str,
        id_column: str,
        id_value: str,
        loader,
    ):
        allowed = {
            ("capability_requirement_graphs_v1", "graph_id"),
            ("monitor_predicates_v1", "predicate_id"),
        }
        if (table, id_column) not in allowed:
            raise GoalStoreError("unsupported immutable GICC table")
        with self.work.extension_transaction() as db:
            row = db.execute(
                f"SELECT payload, digest FROM {table} WHERE {id_column}=?",
                (id_value,),
            ).fetchone()
        if row is None:
            return None
        return loader(self._decode(row["payload"]), row["digest"])


def build_default_goal_store(path: str | Path | None = None) -> GoalStore:
    database_path = Path(path or default_work_store_path()).expanduser().resolve()
    codec = build_default_work_payload_codec(database_path)
    return GoalStore(SQLiteWorkStore(database_path, payload_codec=codec))
