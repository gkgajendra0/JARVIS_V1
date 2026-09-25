# EngineeringChange Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** A durable EngineeringChange coordinates multiple canonical WorkItems with exact-revision owner gates and restart-safe provenance.

**Architecture:** Extend the encrypted local WorkStore with additive change tables and append-only decision/event records. A deterministic coordinator uses the existing WorkOrchestrator/DBOS for each stage and reconciles from canonical state after crashes. No separate task queue or execution authority.

**Tech Stack:** Python 3.11+, SQLite WAL, existing DBOS 2.31.1 production Postgres, RFC-8785, pytest, Ruff.

**Spec:** `docs/superpowers/specs/2026-09-25-engineering-change-design.md`

**Implementation status:** Tasks 1–5 are complete on PR #108. Final implementation head `6af843cff7bf4a0b7f6091a85a991f410f8d0ec5` passed Code Quality run #4426 (Ruff, full pytest, Windows Hello helper, Windows DPAPI). Phase 3 was OWNER-MACHINE ACCEPTED 2026-09-25 with persistent Gemini HTTP 429 pressure recorded as an external limitation; see `docs/PHASE3_ENGINEERING_CHANGE_ACCEPTANCE_2026-09-25.md`. The final documentation head must remain CI-green before merge.

## Global Constraints

- Only RESEARCH and DEVELOPMENT actions are currently executable; unsupported stage types fail closed.
- Preserve existing Authority, WorkPayloadCodec, WorkStep interrupted handling, WorkDelivery and isolated development controls.
- No automatic push, protected-main merge, deployment or secret acquisition.
- Any approval is tied to an immutable artifact revision and trusted owner interaction.
- Source turns have a unique `(session, turn, type)` constraint; use deterministic distinct stage turn keys and preserve original owner turn on the change.

## Review Focus

- Repeated same source turn: one change, no duplicate WorkItems (Task 3 test).
- Duplicate decision request with conflicting digest: reject, never replace prior approval (Task 2 test).
- Changed architecture after approval: block old development attempts (Task 4 test).
- Crash after local WorkItem creation but before DBOS submission: one WorkItem, eventual submission (Task 3 test).
- Unknown process schema on restart: block all dependent work (Task 1 and Task 4 tests).

---

### Task 1: Canonical change model and safe store

**Files:** Create `src/jarvis/engineering_change/models.py`, `src/jarvis/engineering_change/store.py`, `src/jarvis/engineering_change/__init__.py`; modify `src/jarvis/work/store.py`; create `tests/test_engineering_change_core.py`.

**Interfaces:** `ChangeState`, `EngineeringChange`, `ChangeArtifact`, `ChangeDecision`, `ChangeStage`, `ChangeStore`; `ChangeStore.create/get/transition/add_artifact/record_decision/link_work/list_active`. Store shares `SQLiteWorkStore` connection/codec and uses foreign keys to work_items. The registry recognizes a versioned initial process and refuses unsupported versions.

- [x] Write tests for create/read, CAS conflict, encrypted sensitive fields, unknown version, immutable revisions, forbidden lifecycle transition, and atomic stage WorkItem link. Run `PYTHONPATH=src python -m pytest tests/test_engineering_change_core.py -q` and see import/behavior failure.
- [x] Add SQLite tables/indexes with positive versions, unique `(source_session_id, source_turn_id, process_key)`, unique stage attempt keys, and append-only decision/event constraints. Add protected payload handling. Implement models and store and rerun tests to green.
- [x] Run targeted existing `test_work_orchestration.py` and `test_work_privacy.py`; commit `feat: add durable EngineeringChange state`.

### Task 2: Typed gate and artifact binding

**Files:** Create `src/jarvis/engineering_change/gates.py`; update models/store; create `tests/test_engineering_change_gates.py`.

**Interfaces:** `GateService.present(change_id, gate_kind, artifact_id)`, `GateService.decide(change_id, gate_id, decision, actor_id, source_session_id, source_turn_id, request_key)`; decisions verify current artifact digest and are stored once. Canonical SHA-256 uses existing RFC-8785 helper. Decision has no Authority permit semantics.

- [x] Write RED tests for exact artifact binding, trusted-source requirement, duplicate idempotency, conflicting duplicate, rejection, changed revision invalidation and unrelated Authority invariants.
- [x] Implement immutable gate challenges/decisions and admission predicates; use existing WorkDelivery for prompts, keyed by `(change, gate, revision)`, and keep any secret value out of evidence. Run targeted tests GREEN.
- [x] Commit `feat: bind EngineeringChange gates to reviewed artifacts`.

### Task 3: Reuse canonical WorkItems and DBOS submission

**Files:** Create `src/jarvis/engineering_change/coordinator.py`; update `src/jarvis/work/orchestrator.py` and `src/jarvis/work/dbos_backend.py`; create `tests/test_engineering_change_coordinator.py`.

**Interfaces:** `ChangeCoordinator.reconcile(change_id)` and `reconcile_for_work(work_id)`; stage creation atomically persists WorkItem and link, submission invokes existing backend with the same work ID, startup reconciles missing submission. Child WorkItem source turns are deterministic `(change_id, stage_key, attempt)`.

- [x] Write RED tests for one owner goal with multiple dependent WorkItems, parallel ready research items, stage gating, idempotent duplicate submission, local commit/submission crash, and terminal WorkItem recovery.
- [x] Implement coordinator and narrow existing orchestrator adapter, leaving direct WorkItem behavior intact. Call reconciliation at completion and startup. Run new and existing DBOS/work tests GREEN.
- [x] Commit `feat: coordinate governed changes through WorkItems`.

### Task 4: Fail-closed lifecycle and owner-facing flow

**Files:** Create `src/jarvis/engineering_change/service.py`; update `src/jarvis/work/runtime.py` and `src/jarvis/voice/work_tools.py` as required; create `tests/test_engineering_change_lifecycle.py`.

**Interfaces:** Trusted application-facing start/list/status/review/decide operations preserve canonical user turn and disambiguate concurrent gates. Work owner-input remains separate from change approval. Typed process contracts enforce mandatory architecture, verification, acceptance and promotion prerequisites.

- [x] Write RED tests for rejection, retry as fresh attempt, stale approval, unknown process, racing approval/revision updates, owner intent provenance, two simultaneous gates, and no automatic promotion.
- [x] Implement minimal process registry, lifecycle transitions, trusted owner bridge and canonical status. Preserve approximate progress and unknown ETA semantics. Run targeted tests GREEN.
- [x] Commit `feat: expose governed EngineeringChange lifecycle`.

### Task 5: Verification, owner-machine harness, and documentation

**Files:** Create `tests/test_engineering_change_recovery.py`, `src/jarvis/engineering_change/acceptance.py`, `docs/PHASE3_ENGINEERING_CHANGE_OWNER_ACCEPTANCE.md`; update `docs/CURRENT_ARCHITECTURE.md`, `docs/CURRENT_PLAN.md`, `docs/PROJECT_STATE.md` as evidence allows.

**Interfaces:** The harness emits bounded, sanitized JSON evidence for owner-machine Postgres/restart/approval tests. It does not claim acceptance before an actual run on the owner's machine.

- [x] Write RED fault-injection tests for each transaction/submission/decision/reconcile boundary and a negative test proving no automatic merge/deployment.
- [x] Implement the runner and documentation, run targeted tests GREEN; run `ruff format --check .`, `ruff check .`, and `pytest -q` with the CI dependency set. Review the diff for protected surfaces and secrets.
- [x] Commit `test: verify Phase 3 recovery and document owner acceptance` and open a PR. Merge green implementation only under standing authorization and accepted gates; stop if owner-machine input is required.
