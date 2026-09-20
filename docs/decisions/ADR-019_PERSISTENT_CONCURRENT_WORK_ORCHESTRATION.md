# ADR-019 — Persistent Concurrent Work Orchestration Foundation

## Status

**OWNER ACCEPTED — PRODUCTION FOUNDATION APPROVED FOR PROTECTED-MAIN MERGE IN PR #55 (2026-09-20).**

This ADR records the accepted production boundary for issue #53. It does not mark Step 8, Step 15, autonomous repair, protected-main mutation by background workers, or later proactive/event-driven automation complete.

## Context

Self-Awareness acceptance exposed a structural limitation: a realtime tool turn could remain occupied for minutes even when the underlying JARVIS evidence read itself completed in milliseconds. The required product behavior is broader than one timeout fix: the owner must be able to ask JARVIS to keep working on independent development/research, continue normal conversation and immediate Hands actions, inspect/cancel/reprioritize work, and receive a result later.

The orchestration substrate must survive process restart without allowing a provider/model, queue engine, or background worker to become canonical truth or gain new Authority.

## Decision

### 1. JARVIS owns canonical WorkItem truth

JARVIS defines provider-neutral `WorkItem`, `WorkStep` and `WorkDelivery` records. Canonical state is persisted in a local SQLite/WAL store owned by JARVIS. Provider conversation history and DBOS workflow metadata are not semantic truth.

Current lifecycle states include `QUEUED`, `RUNNING`, `WAITING_RESOURCE`, `WAITING_DEPENDENCY`, `WAITING_UNTIL`, `WAITING_FOR_OWNER`, `PAUSED`, `RETRYING`, `COMPLETED`, `FAILED` and `CANCELLED`.

### 2. DBOS is the durable execution substrate, not the brain

DBOS is adopted for workflow persistence/recovery, durable sleep, queueing, events and workflow messaging. The JARVIS `work_id` is also the DBOS workflow identity so durable execution cannot silently create a second task identity.

DBOS steps call back onto the canonical JARVIS event loop for semantic work advancement. DBOS does not choose goals, permissions, actions, success criteria, or user-visible truth.

Production orchestration requires an explicit Postgres DBOS system database. SQLite remains acceptable for direct tests/local development, but it is not the production DBOS default for this feature.

### 3. One interactive brain has absolute priority

The live owner conversation has absolute priority over background model reasoning.

When the user is speaking or the live agent is thinking/speaking, the interactive brain gate is active. An in-flight background model reasoning call is cancelled/preempted and the WorkItem waits without consuming failure budget. Once voice is idle/listening, background reasoning may continue.

Already-started deterministic bounded executor work may continue while conversation uses the brain. Reasoning is serialized by priority; safe mechanical work may continue independently.

### 4. Waiting time is not failure

The durable workflow has a bounded semantic reasoning-cycle limit, but waiting/paused states do not consume that budget. A task may wait for the owner or a dependency for an arbitrarily long real-world interval without being failed merely because time passed.

Crash recovery is deliberately split by evidence quality. Canonical active WorkItems are re-submitted using the same DBOS workflow ID so a process death after SQLite state creation but before durable enqueue cannot orphan work or create a duplicate execution. However, if process death leaves a persisted WorkStep in RUNNING state, JARVIS treats that executor outcome as unknown: the step is marked `INTERRUPTED` rather than ordinary `FAILED`, and the WorkItem moves to `WAITING_FOR_OWNER` rather than automatically replaying a potentially side-effecting action. Saved COMPLETED / FAILED / WAITING_FOR_OWNER states also reconstruct any missing durable delivery record after restart.

Dependency relationships are validated before persistence. A new WorkItem is rejected if its dependency chain would reach the new WorkItem and create a cycle/deadlock.

### 5. Workers are bounded typed executors

The orchestrator is not a monolithic worker. A registry exposes only actions explicitly supported for a WorkType. The initial production candidate deliberately supports source-aware background research and isolated JARVIS repository development.

Resource leases bound shared work/CPU/Git/network surfaces and reserve named GPU/browser/desktop/provider-API classes for workers that need exclusive or bounded access. The runtime also applies a conservative available-RAM admission floor before CPU/GPU/global work starts. Resource pressure produces `WAITING_RESOURCE`; it is not treated as task failure.

Background semantic reasoning has a bounded per-WorkItem cycle budget. Waiting/paused states do not consume it. The current production-candidate default is 64 reasoning cycles; exhausting it fails the task truthfully instead of allowing an unbounded sequence of model calls. This is a runaway-call guard, not precise monetary accounting; exact provider-cost accounting remains unavailable until the provider adapter exposes reliable per-call usage/cost data.

Priorities affect future brain/resource opportunities but never Authority.

### 6. Owner control is canonical and race-safe

Pause, resume, cancel and reprioritize update canonical JARVIS state. Optimistic versions reject stale writes. After model reasoning returns, the engine re-reads canonical state before starting an action, so an owner pause/cancel that occurred during reasoning stops execution cleanly. Cancellation is requested from the durable backend before canonical state claims `CANCELLED`; if that request fails, JARVIS leaves canonical work active rather than falsely reporting terminal cancellation. If cancellation happens while an already-started atomic executor is running, the executor may finish, but its later bookkeeping cannot resurrect the cancelled WorkItem or announce success.

If exactly one task is `WAITING_FOR_OWNER`, a natural reply may continue it without requiring an internal WorkItem ID. Multiple waiting tasks require disambiguation. Owner-input and durable control messages use idempotency keys, and replay of an already-applied identical owner response is treated idempotently instead of creating duplicate owner-input steps.

### 7. Result delivery is durable and truthful

`WorkDelivery` supports `SILENT`, `WHEN_IDLE` and `INTERRUPT`. Delivery is persisted separately from WorkItem completion and marked delivered only after speech succeeds. Wake-idle/standby does not cause unexpected speech; pending delivery survives for the next eligible active session.

### 8. Persistent work payloads are protected at rest

Work identity/state/dependency metadata remains queryable by the orchestrator, but potentially private payload fields are protected separately: request text, result/status text, WorkStep summary/input/observation/error, and delivery messages.

On the Windows production path, JARVIS uses a separate random 256-bit AES-GCM work-payload key sealed to the current Windows user with the existing DPAPI `KeyProtector` boundary. The work key is independent of canonical Memory's SQLCipher key. Existing plaintext WorkStore payloads are migrated on startup, followed by WAL checkpoint/VACUUM cleanup. Corrupt protected payloads fail closed.

Direct non-Windows test/development use currently retains the explicit plaintext codec; this ADR does not claim cross-platform at-rest protection.

### 9. Development work is isolated and proof-gated

Each development WorkItem receives its own Git worktree/branch. The worker cannot push, merge, deploy or mutate protected main.

Model-edited code executes only through the approved locked-down Docker pytest runner. Host Git commands disable repository hooks; Git textconv/external diff execution is disabled; Git-control files, credential-like paths/content and symlink escapes are blocked.

Development completion requires ordered evidence:

`latest edit -> passing sandboxed tests -> final diff inspection -> clean isolated commit -> completion`.

### 10. Background work does not expand Authority

This foundation does not grant unrestricted shell, credential access, protected-main merge, deployment, autonomous self-repair or privileged background Hands execution. Future background workers must reuse existing Capability/Authority boundaries.

### 11. Production and console launch paths remain distinct

Persistent orchestration is assembled by the `jarvis-voice` production runtime. WorkRuntime lifetime spans the production controller's wake-idle/active-session loop, so entering conversational standby closes the cloud voice session without stopping eligible background work. The historical `src/jarvis/voice/entrypoint.py` LiveKit console entrypoint remains a Step-1 development path and is not an acceptance path for this foundation.

## Technology disposition

- JARVIS WorkItem/step/delivery/state machine: **KEEP JARVIS-OWNED**.
- DBOS workflows/queues/messages/events/recovery: **ADOPT** as durable execution mechanics.
- PostgreSQL: **ADOPT FOR PRODUCTION DBOS SYSTEM STATE**.
- SQLite/WAL: **KEEP** for JARVIS canonical local WorkItem domain truth, with protected sensitive payload fields on Windows production.
- Git worktrees: **ADOPT** for per-development-job isolation.
- Locked-down Docker pytest image: **ADOPT** as the current model-edited code-execution boundary.
- Provider-native asynchronous tool semantics: **REJECT AS CANONICAL ARCHITECTURE**.
- Unrestricted shell / automatic push / merge / deployment: **REJECT**.

## Acceptance result

Owner-machine acceptance completed on 2026-09-20. The runtime candidate `b2ba211becdef1b123852a44e7d0c39ffe36cf58` proved independent durable research/development WorkItems, normal conversation while work remained active, standby continuation, truthful canonical status/progress, restart recovery, cancellation, and an immediate verified Hands `Open Calculator` action while background work remained active.

The exact runtime head passed Code Quality run #3929 (pytest, Ruff, Windows DPAPI, Windows Hello helper). The automated suite additionally covers pause/resume/cancel isolation, resource/dependency limits, bounded reasoning budget, unknown mid-executor recovery to `INTERRUPTED` + `WAITING_FOR_OWNER`, backend-cancellation truthfulness, protected WorkStore round-trip/migration, and isolated development proof gates.

The owner explicitly approved PR #55 for merge on 2026-09-20. Detailed acceptance and residual disposition are recorded in `docs/research/PERSISTENT_WORK_ACCEPTANCE_2026-09-20.md`.

Two observed issues are deliberately separate follow-ups rather than blockers for this foundation:
- #56 — Pocket 3 OWNER continuity can falsely declare absence during transient biometric/head evidence gaps;
- #57 — scripted TTS 429 delivery retries should respect provider backoff.

Detailed procedure: `docs/research/PERSISTENT_WORK_ACCEPTANCE_PLAN_2026-09-18.md`.

## Research references

- DBOS durable workflows: https://docs.dbos.dev/python/tutorials/workflow-tutorial
- DBOS queues/concurrency: https://docs.dbos.dev/python/reference/queues
- DBOS workflow messaging/events: https://docs.dbos.dev/python/tutorials/workflow-communication
- DBOS workflow recovery: https://docs.dbos.dev/production/workflow-recovery
- DBOS database connections: https://docs.dbos.dev/python/tutorials/database-connection
