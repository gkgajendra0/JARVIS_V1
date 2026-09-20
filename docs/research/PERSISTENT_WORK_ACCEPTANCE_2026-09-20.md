# Persistent Concurrent Work Orchestration — Final Acceptance

Date: 2026-09-20  
Scope: issue #53 / PR #55  
Decision: **OWNER ACCEPTED — APPROVED FOR PROTECTED-MAIN MERGE**

## What was accepted

JARVIS now owns provider-neutral durable `WorkItem`, `WorkStep` and `WorkDelivery` truth independently of voice/model sessions. DBOS provides durable workflow mechanics and Postgres-backed recovery, while local SQLite/WAL retains canonical JARVIS work state. Live conversation has absolute priority over background model reasoning; already-started bounded deterministic work may continue.

The accepted worker boundary includes background current research, isolated JARVIS repository development, dependencies/priorities/resource leases, pause/resume/cancel/reprioritize and owner-input waits, structured progress/ETA facts, durable result delivery, restart-safe reconciliation, and per-WorkItem worktree/Docker proof gates. Workers gain no push/merge/deploy/protected-main authority.

## Owner-machine evidence

Acceptance on the real Windows owner machine demonstrated:

1. independent research and development WorkItems with separate canonical state;
2. responsive realtime conversation while durable work existed;
3. standby survival and development progress after the cloud voice session ended;
4. verified `Open Calculator` foreground Hands execution while background work remained active;
5. structured canonical status/progress rather than provider-history guesses or hardcoded status sentences;
6. clean durable restart recovery without duplicate identity;
7. bounded DBOS shutdown without the earlier teardown/retry failure chain;
8. durable cancellation followed by no task resurrection;
9. resilient `jarvis-dev` spoken update approval after transient control-channel timeouts.

## Automated hardening accepted with the owner-machine run

The exact-head suite covers pause/resume/cancel isolation, WAITING_FOR_OWNER behavior, dependency-cycle rejection, resource/RAM admission, bounded reasoning cycles, unknown RUNNING step -> `INTERRUPTED` -> `WAITING_FOR_OWNER`, no silent replay of unknown side effects, cancellation-backend failure truthfulness, idempotent owner/control messages, durable-delivery reconstruction, protected payload round-trip/migration, and isolated development worktree/Docker/diff/clean-commit proof gates.

## Exact runtime candidate

Runtime acceptance head: `b2ba211becdef1b123852a44e7d0c39ffe36cf58`

Code Quality run #3929:
- pytest — PASS
- Ruff — PASS
- Windows DPAPI — PASS
- Windows Hello helper — PASS

The final documentation-only descendant must also pass exact-head CI before merge.

## Corrections made during acceptance

Acceptance directly caused corrections for truthful durable cancellation ordering/races, provider-pressure handling, approximate canonical progress/ETA, removal of hardcoded owner-status dialogue, bounded DBOS shutdown drain, update-approval retry semantics, and bounded startup greeting behavior.

## Residuals / follow-up issues

- **#56 Pocket 3 OWNER continuity:** separate vision continuity/state-semantics defect; do not weaken identity authorization.
- **#57 durable delivery TTS retry backoff:** TTS 429 failures correctly leave delivery pending, but retry scheduling should respect provider delay/backoff.
- **Research-provider credentials:** an Exa credential blocker was reported truthfully and is environment/provider configuration, not orchestration correctness.

## Owner decision

The owner explicitly approved merging PR #55 on 2026-09-20 after the central Iron-Man-style scenario was proven: independent background work remained alive while JARVIS continued conversation and executed an unrelated immediate foreground action.

Issue #53 may close with PR #55. Step 8 can now build notes/tasks/reminders/scheduling on this accepted durable work foundation.
