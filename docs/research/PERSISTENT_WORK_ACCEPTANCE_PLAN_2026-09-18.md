# Persistent Concurrent Work Orchestration — Owner-Machine Acceptance Plan

Date: 2026-09-18
Scope: draft PR #55 / issue #53
Status: **NOT YET OWNER-ACCEPTED**

## Purpose

Prove that JARVIS can keep independent work moving, remain immediately conversational, perform normal immediate Hands actions, survive restart, ask for input without losing the task, and report results later without pretending success.

Acceptance must use the production `jarvis-voice` path, not the historical Step-1 `lk agent console src/jarvis/voice/entrypoint.py` path.

## Prerequisites

- Docker Desktop is running.
- `feat/persistent-work-orchestration` is checked out and installed in the active JARVIS environment.
- Existing voice/Pocket/Hands configuration remains unchanged.
- Protected `main` is not modified or merged during this procedure.

## 1. Build the approved development test sandbox

```powershell
docker build -f tools/development-sandbox/Dockerfile -t jarvis-dev-tests:local .
docker image inspect jarvis-dev-tests:local
```

No background development test may fall back to host execution.

## 2. Start a local Postgres DBOS system database

```powershell
$alphabet = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789".ToCharArray()
$pgPassword = -join (1..32 | ForEach-Object { Get-Random -InputObject $alphabet })
docker volume create jarvis-work-postgres-data
docker run -d --name jarvis-work-postgres --restart unless-stopped -p 127.0.0.1:54329:5432 -e POSTGRES_USER=jarvis -e "POSTGRES_PASSWORD=$pgPassword" -e POSTGRES_DB=jarvis_work -v jarvis-work-postgres-data:/var/lib/postgresql/data postgres:17-alpine
docker exec jarvis-work-postgres pg_isready -U jarvis -d jarvis_work
$env:JARVIS_WORK_DBOS_DATABASE_URL = "postgresql://jarvis:$pgPassword@127.0.0.1:54329/jarvis_work"
```

The DB URL is intentionally not persistable in `machine.json`. If the named container/volume already exists, do not delete it automatically; deliberately reuse its accepted credentials or inspect it first.

## 3. Enable the bounded candidate

```powershell
$env:JARVIS_WORK_ORCHESTRATION_ENABLED = "true"
$env:JARVIS_WORK_GLOBAL_CONCURRENCY = "4"
$env:JARVIS_DEV_TEST_DOCKER_IMAGE = "jarvis-dev-tests:local"
```

These non-secret settings are machine-profile-persistable after acceptance; keep them session-scoped until then.

## 4. Start production JARVIS

```powershell
jarvis-voice
```

Expected startup evidence: orchestration enabled, supported work types shown, DBOS durable backend active, and no regression in voice/Pocket/Hands startup.

## 5. Acceptance matrix

### A. Background research

Say: “Research the current DBOS workflow recovery behavior and let me know when the summary is ready. Keep working while we continue.”

Expected: brief durable-acceptance acknowledgement; voice turn becomes available immediately; canonical WorkItem type is `research`.

### B. Independent development before A finishes

Say: “In the JARVIS repo, make a small safe documentation improvement on an isolated branch, run the required tests, and let me know when it is ready for review. Keep doing it in the background.”

Expected: second independent `development` WorkItem; A remains active; isolated `jarvis/work/<id>` branch/worktree; protected main unchanged.

### C. Immediate voice and Hands

Ask a normal question, then: “Open Calculator.”

Expected: normal conversational response and immediate Hands execution while background work remains durable. Background model reasoning yields to active conversation; already-running deterministic work may continue.

### D. Canonical status

Ask: “What are you working on right now?”

Expected: truthful canonical WorkItem states; no progress inferred from provider conversation history.

### E. Pause/resume/cancel isolation

Pause one task, verify the other remains active, resume it, then cancel one task.

Expected: pause/cancel during in-flight reasoning prevents the next action from starting; cancelling one WorkItem does not affect another.

### F. WAITING_FOR_OWNER

Use a genuinely ambiguous background request that explicitly requires JARVIS to ask before choosing a material option.

Expected when reached: `WAITING_FOR_OWNER`, one durable owner-input delivery, natural reply routes automatically if exactly one task is waiting, multiple waiting tasks require disambiguation, and waiting several minutes does not consume/fail semantic-work budget.

Do not manufacture a pass if the real task never requires clarification; record the gate as not exercised and try another naturally ambiguous task.

### G. Restart recovery

Start a non-terminal task, note its WorkItem ID/state, stop `jarvis-voice`, then restart with the same Postgres URL and local work state.

Expected: same WorkItem identity; eligible DBOS workflow recovers; no duplicate task; waiting wall-clock time does not cause false failure.

### H. Completion delivery

Allow work to complete while an active session is listening.

Expected: `WHEN_IDLE` waits for listening/user-silent state, announces once, marks delivered only after speech succeeds, and remains pending during wake-idle/standby until the next eligible active session.

### I. Development proof/isolation

Verify latest edit -> passing Docker tests -> final diff -> clean isolated commit; no worker hook/textconv execution; no secret-like model-visible content; no push/merge/deployment; protected-main checkout remains clean.

## Blockers

Any serial voice blocking, brain competition with active conversation, duplicate/lost work after restart, waiting-time false failure, cross-task cancellation, premature success delivery, host execution of model-edited code, protected-main mutation, secret exposure, or production orchestration without explicit Postgres fails acceptance.

## Acceptance record

Record exact PR head SHA, Postgres/Docker versions, A-I pass/fail, corrections, representative non-secret WorkItem IDs/states, proof main stayed clean, and the owner’s explicit acceptance statement.

Only then reconcile `CURRENT_ARCHITECTURE.md` and product capability status and make PR #55 merge-ready.
