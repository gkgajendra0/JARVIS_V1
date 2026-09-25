# Phase 3 EngineeringChange Owner-Machine Acceptance — 2026-09-25

## Final disposition

**ACCEPTED WITH EXTERNAL PROVIDER LIMITATION.**

Owner acceptance was granted on 2026-09-25 for PR #108 after the exact tested Phase-3 implementation head `6af843cff7bf4a0b7f6091a85a991f410f8d0ec5` had passed Code Quality run #4426 (Ruff, full pytest, Windows Hello helper, Windows DPAPI) and the live owner-machine run demonstrated durable EngineeringChange/WorkItem behavior across process restart and a full Windows shutdown/reboot.

The live run was prevented from reaching the architecture, Windows Hello, isolated-development, acceptance and promotion gates by repeated Gemini HTTP 429 provider pressure after research had already executed successfully through Exa. The owner explicitly accepted Phase 3 with that external provider limitation recorded. No Authority, security, sandboxing, verification, credential, protected-main, acceptance or promotion control was weakened or bypassed.

## Tested runtime

- Repository: `gkgajendra0/JARVIS_V1`
- PR: #108 — `feat: introduce governed EngineeringChange lifecycle`
- Tested implementation head: `6af843cff7bf4a0b7f6091a85a991f410f8d0ec5`
- Acceptance source worktree: `C:\Users\gkgaj\Desktop\jarvis_phase3_acceptance`
- Dependency/runtime substrate: protected-main `.venv`, read-only
- Phase-3 source selected through process-local `PYTHONPATH`
- Durable backend: DBOS 2.31.1 over PostgreSQL container `jarvis-work-postgres`
- Search provider: Exa
- Active cloud reasoning provider during acceptance: Gemini

## Canonical acceptance change

- EngineeringChange: `change_7cafb747e8244d44`
- Research WorkItem: `work_effa1415733546e8`
- Research stage attempt: `1`

The same accepted owner request was started twice and returned the same EngineeringChange and the same research WorkItem, proving start idempotency without duplicate submission.

## Owner-input resume

The research WorkItem initially entered `WAITING_FOR_OWNER` because live Exa credentials were absent. After `EXA_API_KEY` was configured in the owner environment, the existing WorkItem was resumed rather than replaced.

Observed canonical transition:

`WAITING_FOR_OWNER -> RUNNING`

The owner-input step was persisted as completed. Multiple subsequent `research_web` steps also completed, proving that the Exa credential and live web-research path were functioning.

A non-blocking UX issue was observed: immediately after owner input was submitted, voice could describe the pre-submit WorkItem snapshot as though it were still current. Canonical storage and DBOS execution subsequently showed the correct resumed state. This is a follow-up truthfulness/UX item, not a durability or governance failure.

## Full Windows cold-boot recovery

The owner shut down the entire Windows machine, restarted it, and inspected durable state before JARVIS startup.

Before the restarted runtime was launched, the same canonical records were present:

- EngineeringChange: `change_7cafb747e8244d44`
- change state: `researching`
- WorkItem: `work_effa1415733546e8`
- WorkItem state: `running`
- WorkItem version: `32`
- research stage attempt: `1`

No replacement change or WorkItem was created.

After runtime startup, DBOS reported recovery of one workflow from application version `0.1.0`. PostgreSQL inspection showed the workflow under the same canonical WorkItem ID:

- workflow UUID: `work_effa1415733546e8`
- workflow name: `durable_workflow`
- status: `PENDING`
- recovery attempts observed: `3`
- queue: `jarvis-work`

DBOS operation history showed recovered `_advance_work`, `DBOS.setEvent` and `DBOS.sleep` operations continuing under that same identity with no operation error.

This is accepted evidence that canonical EngineeringChange/WorkItem identity and DBOS execution survive a real machine shutdown/restart.

## External Gemini provider pressure

After cold-boot recovery, the research workflow encountered repeated Gemini HTTP 429 rate-limit responses during model reasoning.

The canonical WorkItem advanced rather than becoming stale or being duplicated:

- later state: `waiting_resource`
- later version: `41`
- EngineeringChange remained `researching`

Five consecutive `provider_pressure` WorkSteps were persisted as completed. DBOS remained `PENDING` and the operation history showed the designed backoff progression reaching the 60-second ceiling. The DBOS operations themselves had no recorded error.

This behavior is classified as an **external provider limitation**, not a Phase-3 persistence failure. The durable workflow correctly retained state and waited for provider capacity instead of silently failing, fabricating completion or bypassing governance.

Because the external 429 condition persisted, this specific live run did not naturally reach:

- architecture proposal/gate presentation;
- generic-yes rejection plus digest-bound Windows Hello approval;
- architecture revision invalidation;
- isolated development completion;
- owner acceptance gate;
- promotion-intent gate.

Those contracts remain covered by the exact green PR automated suite, including explicit rejection, strong-verification failure-closed behavior, architecture revision invalidation, verified-development evidence requirements, promotion intent without merge/deploy, gate idempotency and restart delivery behavior.

The owner explicitly accepted the Phase-3 implementation under this external limitation rather than switching providers solely to force the live acceptance flow to complete.

## Accepted conclusions

The owner-machine run demonstrated:

- same-turn EngineeringChange start idempotency;
- canonical WorkItem persistence and encrypted WorkStore continuity;
- owner-input resume of the same WorkItem;
- successful Exa-backed research actions;
- restart-safe PostgreSQL DBOS identity;
- full Windows cold-boot survival;
- no duplicate change or WorkItem creation after recovery;
- transient provider-pressure handling through durable `WAITING_RESOURCE` and backoff;
- no automatic push, protected-main merge, deployment or promotion caused by recovery or provider pressure.

## Non-blocking follow-ups

1. After owner-input submission, voice should refresh canonical state before describing the result so it does not speak a stale pre-submit snapshot.
2. Long-lived provider pressure should eventually surface a clear owner-facing notification/escalation rather than remaining silently retryable indefinitely.

These follow-ups do not weaken or invalidate the accepted Phase-3 governance model.

## Promotion decision

Phase 3 EngineeringChange Lifecycle / Mission Orchestration is **DONE / OWNER-MACHINE ACCEPTED 2026-09-25**, with the persistent Gemini 429 condition recorded as an external acceptance limitation.

PR #108 is authorized for merge once its final documentation head is CI-green. After merge, the next active cross-cutting phase is **Phase 4 — Research + Diagnostic Model Router**.
