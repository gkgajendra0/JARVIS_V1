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

                CREATE TABLE IF NOT EXISTS goal_interpretation_shadow_evidence_v1 (
                    evidence_id TEXT PRIMARY KEY,
                    source_session_id TEXT NOT NULL,
                    source_turn_id TEXT NOT NULL,
                    provider_name TEXT NOT NULL,
                    model_name TEXT NOT NULL,
                    actionable INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    digest TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(source_session_id, source_turn_id)
                );

                CREATE TABLE IF NOT EXISTS information_need_interactions_v1 (
                    interaction_id TEXT PRIMARY KEY,
                    goal_id TEXT NOT NULL,
                    information_need_id TEXT NOT NULL UNIQUE,
                    state TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    digest TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    resolved_at TEXT,
                    FOREIGN KEY(goal_id) REFERENCES owner_goals_v2(goal_id),
                    FOREIGN KEY(information_need_id)
                        REFERENCES information_needs_v1(information_need_id)
                );

                CREATE TABLE IF NOT EXISTS plan_node_results_v1 (
                    result_id TEXT PRIMARY KEY,
                    plan_id TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    attempt INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    digest TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(plan_id, node_id, attempt),
                    FOREIGN KEY(plan_id) REFERENCES plan_graphs_v1(plan_id)
                );

                CREATE TABLE IF NOT EXISTS plan_no_progress_v1 (
                    fingerprint_id TEXT PRIMARY KEY,
                    goal_id TEXT NOT NULL,
                    plan_id TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    action_fingerprint TEXT NOT NULL,
                    state_fingerprint TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    digest TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(goal_id, action_fingerprint, state_fingerprint),
                    FOREIGN KEY(goal_id) REFERENCES owner_goals_v2(goal_id),
                    FOREIGN KEY(plan_id) REFERENCES plan_graphs_v1(plan_id)
                );

                CREATE TABLE IF NOT EXISTS goal_replan_budget_v1 (
                    goal_id TEXT PRIMARY KEY,
                    attempt_count INTEGER NOT NULL,
                    max_attempts INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(goal_id) REFERENCES owner_goals_v2(goal_id)
                );

                CREATE TABLE IF NOT EXISTS monitor_runtime_state_v1 (
                    predicate_id TEXT PRIMARY KEY,
                    revision INTEGER NOT NULL,
                    goal_id TEXT NOT NULL,
                    work_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    digest TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(goal_id) REFERENCES owner_goals_v2(goal_id),
                    FOREIGN KEY(predicate_id)
                        REFERENCES monitor_predicates_v1(predicate_id)
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
                    raise GoalStoreConflict(
                        "goal_id already exists with different payload"
                    )
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

    def list_active_goals(self, *, limit: int = 20) -> tuple[OwnerGoalV2, ...]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("limit must be a positive integer")
        terminal = (
            GoalState.COMPLETED.value,
            GoalState.FAILED.value,
            GoalState.CANCELLED.value,
        )
        with self.work.extension_transaction() as db:
            rows = db.execute(
                """
                SELECT payload, digest
                FROM owner_goals_v2
                WHERE state NOT IN (?, ?, ?)
                ORDER BY updated_at DESC, goal_id ASC
                LIMIT ?
                """,
                (*terminal, limit),
            ).fetchall()
        return tuple(
            OwnerGoalV2.from_payload(self._decode(row["payload"]), row["digest"])
            for row in rows
        )

    def list_entities(self, *, limit: int = 50) -> tuple[WorldEntityRefV1, ...]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("limit must be a positive integer")
        with self.work.extension_transaction() as db:
            rows = db.execute(
                """
                SELECT payload, digest
                FROM world_entities_v1
                ORDER BY lifecycle_state ASC, entity_type ASC, entity_id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return tuple(
            WorldEntityRefV1.from_payload(self._decode(row["payload"]), row["digest"])
            for row in rows
        )

    def put_shadow_interpretation(
        self,
        *,
        source_session_id: str,
        source_turn_id: str,
        provider_name: str,
        model_name: str,
        actionable: bool,
        payload: dict[str, object],
        created_at: str,
    ) -> dict[str, object]:
        if not isinstance(actionable, bool):
            raise TypeError("actionable must be a bool")
        session_id = str(source_session_id).strip()
        turn_id = str(source_turn_id).strip()
        provider = str(provider_name).strip().casefold()
        model = str(model_name).strip()
        timestamp = str(created_at).strip()
        if not session_id or not turn_id or not provider or not model or not timestamp:
            raise ValueError("shadow interpretation metadata must not be empty")
        if not isinstance(payload, dict):
            raise TypeError("payload must be a dict")
        canonical = {
            "source_session_id": session_id,
            "source_turn_id": turn_id,
            "provider_name": provider,
            "model_name": model,
            "actionable": actionable,
            "payload": payload,
            "created_at": timestamp,
        }
        digest = canonical_digest(canonical)
        evidence_id = f"gicc_shadow_{canonical_digest({'session': session_id, 'turn': turn_id})[:20]}"
        with self.work.extension_transaction() as db:
            row = db.execute(
                """
                SELECT payload, digest
                FROM goal_interpretation_shadow_evidence_v1
                WHERE evidence_id=?
                """,
                (evidence_id,),
            ).fetchone()
            if row is not None:
                existing_payload = self._decode(row["payload"])
                if row["digest"] != digest or existing_payload != canonical:
                    raise GoalStoreConflict(
                        "shadow interpretation already exists with different evidence"
                    )
                return canonical | {"evidence_id": evidence_id, "digest": digest}
            db.execute(
                """
                INSERT INTO goal_interpretation_shadow_evidence_v1 (
                    evidence_id, source_session_id, source_turn_id,
                    provider_name, model_name, actionable, payload, digest, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence_id,
                    session_id,
                    turn_id,
                    provider,
                    model,
                    1 if actionable else 0,
                    self._encode(canonical),
                    digest,
                    timestamp,
                ),
            )
        return canonical | {"evidence_id": evidence_id, "digest": digest}

    def get_shadow_interpretation(
        self,
        *,
        source_session_id: str,
        source_turn_id: str,
    ) -> dict[str, object] | None:
        with self.work.extension_transaction() as db:
            row = db.execute(
                """
                SELECT evidence_id, payload, digest
                FROM goal_interpretation_shadow_evidence_v1
                WHERE source_session_id=? AND source_turn_id=?
                """,
                (source_session_id, source_turn_id),
            ).fetchone()
        if row is None:
            return None
        payload = self._decode(row["payload"])
        if canonical_digest(payload) != row["digest"]:
            raise GoalStoreError("shadow interpretation digest mismatch")
        return payload | {"evidence_id": row["evidence_id"], "digest": row["digest"]}

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

    def list_resource_bindings(
        self,
        *,
        entity_id: str | None = None,
        limit: int = 100,
    ) -> tuple[ResourceBindingV1, ...]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("limit must be a positive integer")
        with self.work.extension_transaction() as db:
            if entity_id is None:
                rows = db.execute(
                    """
                    SELECT payload, binding_digest
                    FROM resource_bindings_v1
                    ORDER BY last_verified_at DESC, binding_id ASC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            else:
                rows = db.execute(
                    """
                    SELECT payload, binding_digest
                    FROM resource_bindings_v1
                    WHERE entity_id=?
                    ORDER BY last_verified_at DESC, binding_id ASC
                    LIMIT ?
                    """,
                    (str(entity_id).strip(), limit),
                ).fetchall()
        return tuple(
            ResourceBindingV1.from_payload(
                self._decode(row["payload"]),
                row["binding_digest"],
            )
            for row in rows
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

    def update_information_need_state(
        self,
        need_id: str,
        state: InformationNeedState,
        *,
        expected_revision: int,
        self_resolution_attempts: tuple[str, ...] | list[str] | None = None,
        owner_question: str | None = None,
    ) -> InformationNeedV1:
        if not isinstance(state, InformationNeedState):
            raise TypeError("state must be InformationNeedState")
        if state is InformationNeedState.RESOLVED:
            raise ValueError("use resolve_information_need for RESOLVED state")
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
                raise GoalStoreError(f"unknown information_need_id: {need_id}")
            current = InformationNeedV1.from_payload(
                self._decode(row["payload"]),
                row["digest"],
            )
            if current.revision != expected_revision:
                raise GoalStoreConflict(
                    "information need revision changed before state update"
                )
            attempts = (
                current.self_resolution_attempts
                if self_resolution_attempts is None
                else tuple(
                    sorted(
                        {
                            *current.self_resolution_attempts,
                            *(
                                str(item).strip()
                                for item in self_resolution_attempts
                                if str(item).strip()
                            ),
                        }
                    )
                )
            )
            question = (
                current.owner_question
                if owner_question is None
                else str(owner_question).strip() or None
            )
            if (
                current.state is state
                and attempts == current.self_resolution_attempts
                and question == current.owner_question
            ):
                return current
            candidate = replace(
                current,
                revision=current.revision + 1,
                state=state,
                self_resolution_attempts=attempts,
                owner_question=question,
                digest="pending",
            )
            updated = replace(
                candidate,
                digest=canonical_digest(candidate.canonical_payload()),
            )
            result = db.execute(
                """
                UPDATE information_needs_v1
                SET revision=?, state=?, payload=?, digest=?
                WHERE information_need_id=? AND revision=?
                """,
                (
                    updated.revision,
                    updated.state.value,
                    self._encode(updated.canonical_payload()),
                    updated.digest,
                    need_id,
                    current.revision,
                ),
            )
            if result.rowcount != 1:
                raise GoalStoreConflict(
                    "information need compare-and-swap state update lost"
                )
        return updated

    def begin_information_interaction(
        self,
        *,
        need_id: str,
        created_at: str,
    ) -> dict[str, object]:
        timestamp = str(created_at).strip()
        if not timestamp:
            raise ValueError("created_at must not be empty")
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
                raise GoalStoreError(f"unknown information_need_id: {need_id}")
            need = InformationNeedV1.from_payload(
                self._decode(row["payload"]),
                row["digest"],
            )
            if need.state is not InformationNeedState.WAITING_FOR_OWNER:
                raise GoalStoreConflict(
                    "information need must be WAITING_FOR_OWNER before interaction"
                )
            interaction_id = (
                "gicc_interaction_"
                + canonical_digest(
                    {
                        "goal_id": need.goal_id,
                        "information_need_id": need.information_need_id,
                    }
                )[:20]
            )
            existing = db.execute(
                """
                SELECT payload, digest
                FROM information_need_interactions_v1
                WHERE interaction_id=?
                """,
                (interaction_id,),
            ).fetchone()
            if existing is not None:
                payload = self._decode(existing["payload"])
                if canonical_digest(payload) != existing["digest"]:
                    raise GoalStoreError("information interaction digest mismatch")
                return payload | {
                    "interaction_id": interaction_id,
                    "digest": existing["digest"],
                }
            payload = {
                "goal_id": need.goal_id,
                "information_need_id": need.information_need_id,
                "expected_answer_schema": need.answer_schema,
                "allowed_candidate_values": list(need.candidate_values),
                "state": "active",
                "created_at": timestamp,
                "resolved_at": None,
                "resolved_turn_id": None,
                "resolution_ref": None,
            }
            digest = canonical_digest(payload)
            db.execute(
                """
                INSERT INTO information_need_interactions_v1 (
                    interaction_id, goal_id, information_need_id, state,
                    payload, digest, created_at, resolved_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    interaction_id,
                    need.goal_id,
                    need.information_need_id,
                    "active",
                    self._encode(payload),
                    digest,
                    timestamp,
                    None,
                ),
            )
        return payload | {"interaction_id": interaction_id, "digest": digest}

    def get_information_interaction(
        self,
        interaction_id: str,
    ) -> dict[str, object] | None:
        with self.work.extension_transaction() as db:
            row = db.execute(
                """
                SELECT payload, digest
                FROM information_need_interactions_v1
                WHERE interaction_id=?
                """,
                (str(interaction_id).strip(),),
            ).fetchone()
        if row is None:
            return None
        payload = self._decode(row["payload"])
        if canonical_digest(payload) != row["digest"]:
            raise GoalStoreError("information interaction digest mismatch")
        return payload | {
            "interaction_id": str(interaction_id).strip(),
            "digest": row["digest"],
        }

    def submit_information_interaction_reply(
        self,
        *,
        interaction_id: str,
        goal_id: str,
        need_id: str,
        source_turn_id: str,
        resolution_ref: str,
        resolved_at: str,
    ) -> InformationNeedV1:
        interaction_key = str(interaction_id).strip()
        goal_key = str(goal_id).strip()
        need_key = str(need_id).strip()
        turn_key = str(source_turn_id).strip()
        resolution = str(resolution_ref).strip()
        timestamp = str(resolved_at).strip()
        if not all(
            (interaction_key, goal_key, need_key, turn_key, resolution, timestamp)
        ):
            raise ValueError("bound information reply metadata must not be empty")
        with self.work.extension_transaction() as db:
            interaction_row = db.execute(
                """
                SELECT payload, digest
                FROM information_need_interactions_v1
                WHERE interaction_id=?
                """,
                (interaction_key,),
            ).fetchone()
            if interaction_row is None:
                raise GoalStoreError(
                    f"unknown information interaction: {interaction_key}"
                )
            interaction = self._decode(interaction_row["payload"])
            if canonical_digest(interaction) != interaction_row["digest"]:
                raise GoalStoreError("information interaction digest mismatch")
            if (
                interaction["goal_id"] != goal_key
                or interaction["information_need_id"] != need_key
            ):
                raise GoalStoreConflict(
                    "owner reply does not match the bound InformationNeed interaction"
                )
            if interaction["state"] == "resolved":
                if interaction["resolution_ref"] == resolution:
                    need_row = db.execute(
                        """
                        SELECT payload, digest
                        FROM information_needs_v1
                        WHERE information_need_id=?
                        """,
                        (need_key,),
                    ).fetchone()
                    if need_row is None:
                        raise GoalStoreError(f"unknown information_need_id: {need_key}")
                    return InformationNeedV1.from_payload(
                        self._decode(need_row["payload"]),
                        need_row["digest"],
                    )
                raise GoalStoreConflict(
                    "information interaction already resolved differently"
                )

            need_row = db.execute(
                """
                SELECT payload, digest
                FROM information_needs_v1
                WHERE information_need_id=?
                """,
                (need_key,),
            ).fetchone()
            if need_row is None:
                raise GoalStoreError(f"unknown information_need_id: {need_key}")
            current = InformationNeedV1.from_payload(
                self._decode(need_row["payload"]),
                need_row["digest"],
            )
            if current.goal_id != goal_key:
                raise GoalStoreConflict(
                    "InformationNeed does not belong to the bound goal"
                )
            if current.state is not InformationNeedState.WAITING_FOR_OWNER:
                raise GoalStoreConflict(
                    "InformationNeed is not waiting for owner input"
                )
            updated = current.with_resolution(
                resolution_ref=resolution,
                evidence_refs=(f"owner_turn:{turn_key}",),
                resolved_at=timestamp,
            )
            need_update = db.execute(
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
                    need_key,
                    current.revision,
                ),
            )
            if need_update.rowcount != 1:
                raise GoalStoreConflict(
                    "information need compare-and-swap owner resolution lost"
                )

            resolved_interaction = {
                **interaction,
                "state": "resolved",
                "resolved_at": timestamp,
                "resolved_turn_id": turn_key,
                "resolution_ref": resolution,
            }
            interaction_digest = canonical_digest(resolved_interaction)
            interaction_update = db.execute(
                """
                UPDATE information_need_interactions_v1
                SET state='resolved', payload=?, digest=?, resolved_at=?
                WHERE interaction_id=? AND state='active'
                """,
                (
                    self._encode(resolved_interaction),
                    interaction_digest,
                    timestamp,
                    interaction_key,
                ),
            )
            if interaction_update.rowcount != 1:
                raise GoalStoreConflict(
                    "information interaction compare-and-swap resolution lost"
                )
        return updated

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
        return CapabilityGapV1.from_payload(self._decode(row["payload"]), row["digest"])

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

    def update_plan_execution(
        self,
        plan: PlanGraphV1,
        *,
        expected_digest: str,
    ) -> PlanGraphV1:
        if not isinstance(plan, PlanGraphV1):
            raise TypeError("plan must be PlanGraphV1")
        expected = str(expected_digest).strip().casefold()
        if not expected:
            raise ValueError("expected_digest must not be empty")
        with self.work.extension_transaction() as db:
            row = db.execute(
                "SELECT payload, digest FROM plan_graphs_v1 WHERE plan_id=?",
                (plan.plan_id,),
            ).fetchone()
            if row is None:
                raise GoalStoreError(f"unknown plan_id: {plan.plan_id}")
            current = PlanGraphV1.from_payload(
                self._decode(row["payload"]),
                row["digest"],
            )
            if current.digest != expected:
                raise GoalStoreConflict("plan execution digest changed before update")
            if (
                current.goal_id != plan.goal_id
                or current.goal_revision != plan.goal_revision
                or current.plan_revision != plan.plan_revision
            ):
                raise GoalStoreConflict(
                    "plan execution update cannot change plan identity/revision"
                )
            result = db.execute(
                """
                UPDATE plan_graphs_v1
                SET state=?, payload=?, digest=?, updated_at=?
                WHERE plan_id=? AND digest=?
                """,
                (
                    plan.state.value,
                    self._encode(plan.canonical_payload()),
                    plan.digest,
                    plan.updated_at,
                    plan.plan_id,
                    expected,
                ),
            )
            if result.rowcount != 1:
                raise GoalStoreConflict("plan execution compare-and-swap update lost")
        return plan

    def put_plan_node_result(
        self,
        *,
        plan_id: str,
        node_id: str,
        attempt: int,
        status: str,
        payload: dict[str, object],
        created_at: str,
    ) -> dict[str, object]:
        if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
            raise ValueError("attempt must be a positive integer")
        plan_key = str(plan_id).strip()
        node_key = str(node_id).strip()
        status_value = str(status).strip().casefold()
        timestamp = str(created_at).strip()
        if not all((plan_key, node_key, status_value, timestamp)):
            raise ValueError("plan result metadata must not be empty")
        if not isinstance(payload, dict):
            raise TypeError("payload must be a dict")
        canonical = {
            "plan_id": plan_key,
            "node_id": node_key,
            "attempt": attempt,
            "status": status_value,
            "payload": payload,
            "created_at": timestamp,
        }
        digest = canonical_digest(canonical)
        result_id = f"plan_result_{canonical_digest({'plan': plan_key, 'node': node_key, 'attempt': attempt})[:20]}"
        with self.work.extension_transaction() as db:
            row = db.execute(
                """
                SELECT payload, digest
                FROM plan_node_results_v1
                WHERE result_id=?
                """,
                (result_id,),
            ).fetchone()
            if row is not None:
                existing = self._decode(row["payload"])
                if existing != canonical or row["digest"] != digest:
                    raise GoalStoreConflict(
                        "plan node attempt already has different result evidence"
                    )
                return canonical | {"result_id": result_id, "digest": digest}
            db.execute(
                """
                INSERT INTO plan_node_results_v1 (
                    result_id, plan_id, node_id, attempt, status,
                    payload, digest, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result_id,
                    plan_key,
                    node_key,
                    attempt,
                    status_value,
                    self._encode(canonical),
                    digest,
                    timestamp,
                ),
            )
        return canonical | {"result_id": result_id, "digest": digest}

    def list_plan_node_results(
        self,
        *,
        plan_id: str,
        node_id: str | None = None,
        limit: int = 100,
    ) -> tuple[dict[str, object], ...]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("limit must be a positive integer")
        with self.work.extension_transaction() as db:
            if node_id is None:
                rows = db.execute(
                    """
                    SELECT result_id, payload, digest
                    FROM plan_node_results_v1
                    WHERE plan_id=?
                    ORDER BY attempt ASC, result_id ASC
                    LIMIT ?
                    """,
                    (plan_id, limit),
                ).fetchall()
            else:
                rows = db.execute(
                    """
                    SELECT result_id, payload, digest
                    FROM plan_node_results_v1
                    WHERE plan_id=? AND node_id=?
                    ORDER BY attempt ASC, result_id ASC
                    LIMIT ?
                    """,
                    (plan_id, node_id, limit),
                ).fetchall()
        results: list[dict[str, object]] = []
        for row in rows:
            payload = self._decode(row["payload"])
            if canonical_digest(payload) != row["digest"]:
                raise GoalStoreError("plan node result digest mismatch")
            results.append(
                payload | {"result_id": row["result_id"], "digest": row["digest"]}
            )
        return tuple(results)

    def record_no_progress(
        self,
        *,
        goal_id: str,
        plan_id: str,
        node_id: str,
        action_fingerprint: str,
        state_fingerprint: str,
        reason: str,
        created_at: str,
    ) -> dict[str, object]:
        canonical = {
            "goal_id": str(goal_id).strip(),
            "plan_id": str(plan_id).strip(),
            "node_id": str(node_id).strip(),
            "action_fingerprint": str(action_fingerprint).strip().casefold(),
            "state_fingerprint": str(state_fingerprint).strip().casefold(),
            "reason": str(reason).strip(),
            "created_at": str(created_at).strip(),
        }
        if any(not value for value in canonical.values()):
            raise ValueError("no-progress evidence fields must not be empty")
        fingerprint_id = (
            "no_progress_"
            + canonical_digest(
                {
                    "goal_id": canonical["goal_id"],
                    "action_fingerprint": canonical["action_fingerprint"],
                    "state_fingerprint": canonical["state_fingerprint"],
                }
            )[:20]
        )
        digest = canonical_digest(canonical)
        with self.work.extension_transaction() as db:
            row = db.execute(
                """
                SELECT payload, digest
                FROM plan_no_progress_v1
                WHERE fingerprint_id=?
                """,
                (fingerprint_id,),
            ).fetchone()
            if row is not None:
                existing = self._decode(row["payload"])
                if existing != canonical or row["digest"] != digest:
                    raise GoalStoreConflict(
                        "no-progress fingerprint already has different evidence"
                    )
                return canonical | {
                    "fingerprint_id": fingerprint_id,
                    "digest": digest,
                }
            db.execute(
                """
                INSERT INTO plan_no_progress_v1 (
                    fingerprint_id, goal_id, plan_id, node_id, action_fingerprint,
                    state_fingerprint, payload, digest, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fingerprint_id,
                    canonical["goal_id"],
                    canonical["plan_id"],
                    canonical["node_id"],
                    canonical["action_fingerprint"],
                    canonical["state_fingerprint"],
                    self._encode(canonical),
                    digest,
                    canonical["created_at"],
                ),
            )
        return canonical | {"fingerprint_id": fingerprint_id, "digest": digest}

    def has_no_progress(
        self,
        *,
        goal_id: str,
        action_fingerprint: str,
        state_fingerprint: str,
    ) -> bool:
        with self.work.extension_transaction() as db:
            row = db.execute(
                """
                SELECT 1
                FROM plan_no_progress_v1
                WHERE goal_id=?
                  AND action_fingerprint=? AND state_fingerprint=?
                """,
                (
                    str(goal_id).strip(),
                    str(action_fingerprint).strip().casefold(),
                    str(state_fingerprint).strip().casefold(),
                ),
            ).fetchone()
        return row is not None

    def consume_replan_budget(
        self,
        *,
        goal_id: str,
        max_attempts: int,
        updated_at: str,
    ) -> int:
        if (
            isinstance(max_attempts, bool)
            or not isinstance(max_attempts, int)
            or max_attempts < 1
        ):
            raise ValueError("max_attempts must be a positive integer")
        goal_key = str(goal_id).strip()
        timestamp = str(updated_at).strip()
        if not goal_key or not timestamp:
            raise ValueError("replan budget metadata must not be empty")
        with self.work.extension_transaction() as db:
            row = db.execute(
                """
                SELECT attempt_count, max_attempts
                FROM goal_replan_budget_v1
                WHERE goal_id=?
                """,
                (goal_key,),
            ).fetchone()
            if row is None:
                count = 1
                db.execute(
                    """
                    INSERT INTO goal_replan_budget_v1 (
                        goal_id, attempt_count, max_attempts, updated_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (goal_key, count, max_attempts, timestamp),
                )
                return count
            configured_max = int(row["max_attempts"])
            if configured_max != max_attempts:
                raise GoalStoreConflict(
                    "replan budget maximum changed for active goal"
                )
            count = int(row["attempt_count"])
            if count >= max_attempts:
                raise GoalStoreConflict("replan budget exhausted")
            count += 1
            db.execute(
                """
                UPDATE goal_replan_budget_v1
                SET attempt_count=?, updated_at=?
                WHERE goal_id=?
                """,
                (count, timestamp, goal_key),
            )
        return count

    def create_monitor_runtime_state(
        self,
        *,
        predicate_id: str,
        goal_id: str,
        work_id: str,
        payload: dict[str, object],
        updated_at: str,
    ) -> dict[str, object]:
        predicate_key = str(predicate_id).strip()
        goal_key = str(goal_id).strip()
        work_key = str(work_id).strip()
        timestamp = str(updated_at).strip()
        if not all((predicate_key, goal_key, work_key, timestamp)):
            raise ValueError("monitor runtime identifiers must not be empty")
        if not isinstance(payload, dict):
            raise TypeError("payload must be a dict")
        canonical = {
            "predicate_id": predicate_key,
            "revision": 1,
            "goal_id": goal_key,
            "work_id": work_key,
            "payload": payload,
            "updated_at": timestamp,
        }
        digest = canonical_digest(canonical)
        with self.work.extension_transaction() as db:
            row = db.execute(
                """
                SELECT payload, digest
                FROM monitor_runtime_state_v1
                WHERE predicate_id=?
                """,
                (predicate_key,),
            ).fetchone()
            if row is not None:
                existing = self._decode(row["payload"])
                if canonical_digest(existing) != row["digest"]:
                    raise GoalStoreError("monitor runtime state digest mismatch")
                return existing | {"digest": row["digest"]}
            db.execute(
                """
                INSERT INTO monitor_runtime_state_v1 (
                    predicate_id, revision, goal_id, work_id,
                    payload, digest, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    predicate_key,
                    1,
                    goal_key,
                    work_key,
                    self._encode(canonical),
                    digest,
                    timestamp,
                ),
            )
        return canonical | {"digest": digest}

    def get_monitor_runtime_state(
        self,
        predicate_id: str,
    ) -> dict[str, object] | None:
        with self.work.extension_transaction() as db:
            row = db.execute(
                """
                SELECT payload, digest
                FROM monitor_runtime_state_v1
                WHERE predicate_id=?
                """,
                (str(predicate_id).strip(),),
            ).fetchone()
        if row is None:
            return None
        payload = self._decode(row["payload"])
        if canonical_digest(payload) != row["digest"]:
            raise GoalStoreError("monitor runtime state digest mismatch")
        return payload | {"digest": row["digest"]}

    def update_monitor_runtime_state(
        self,
        *,
        predicate_id: str,
        expected_revision: int,
        runtime_payload: dict[str, object],
        updated_at: str,
    ) -> dict[str, object]:
        if (
            isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
            or expected_revision < 1
        ):
            raise ValueError("expected_revision must be positive")
        predicate_key = str(predicate_id).strip()
        timestamp = str(updated_at).strip()
        if not isinstance(runtime_payload, dict):
            raise TypeError("runtime_payload must be a dict")
        with self.work.extension_transaction() as db:
            row = db.execute(
                """
                SELECT payload, digest
                FROM monitor_runtime_state_v1
                WHERE predicate_id=?
                """,
                (predicate_key,),
            ).fetchone()
            if row is None:
                raise GoalStoreError(
                    f"unknown monitor runtime predicate: {predicate_key}"
                )
            current = self._decode(row["payload"])
            if int(current["revision"]) != expected_revision:
                raise GoalStoreConflict("monitor runtime revision changed")
            canonical = {
                "predicate_id": current["predicate_id"],
                "revision": expected_revision + 1,
                "goal_id": current["goal_id"],
                "work_id": current["work_id"],
                "payload": dict(runtime_payload),
                "updated_at": timestamp,
            }
            digest = canonical_digest(canonical)
            result = db.execute(
                """
                UPDATE monitor_runtime_state_v1
                SET revision=?, payload=?, digest=?, updated_at=?
                WHERE predicate_id=? AND revision=?
                """,
                (
                    canonical["revision"],
                    self._encode(canonical),
                    digest,
                    timestamp,
                    predicate_key,
                    expected_revision,
                ),
            )
            if result.rowcount != 1:
                raise GoalStoreConflict("monitor runtime compare-and-swap lost")
        return canonical | {"digest": digest}

    def put_continuation(self, continuation: GoalContinuationV1) -> GoalContinuationV1:
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
                raise GoalStoreConflict("continuation revision changed before resume")
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

    def get_monitor_predicate(self, predicate_id: str) -> MonitorPredicateV1 | None:
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
