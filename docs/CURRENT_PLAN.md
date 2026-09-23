# JARVIS V1 Current Plan

## Active Work

**PR #41 — Self-Awareness Foundation is OWNER ACCEPTED and merged to protected `main` (2026-09-18) at `e5484cb9d599783e7f715bc6fb435af459dc49a0`.**

The accepted runtime-code baseline produced by owner-accepted PRs #43, #49 and #48 is `e2ff21e78480a09eb243cdd2c121b39e47620d0f`; later documentation-only reconciliation commits may advance protected `main` without changing that earlier runtime state.

PR #41 now adds the bounded read-only hierarchical whole-JARVIS Self Model, deterministic health/dependency/blast-radius reasoning, structured operational-evidence queries, typed Self-Awareness reads and resolved-incident/fix retrieval. Autonomous diagnosis/repair remains explicitly out of scope. Final acceptance evidence is recorded in `docs/research/SELF_AWARENESS_ACCEPTANCE_2026-09-18.md`.

**Persistent Concurrent Work Orchestration (issue #53 / PR #55) is OWNER ACCEPTED and merged to protected `main` on 2026-09-20 at `3980b212d657106abd45bfae119d2207551c409f`. Issue #53 is closed.** Independent durable research/development work, standby continuation, restart recovery, canonical progress/status, cancellation, and immediate foreground Hands while background work remains active were proven on the owner machine. Exact runtime-head CI passed, final reconciliation CI passed, and the production merge result is recorded below.

**Owner-approved sequence change (2026-09-20): reliability cleanup issues #56 -> #57 -> #50 are complete; the bounded Self-Repair Foundation interlude is now active before formal Step 8 implementation.** This does not renumber the roadmap or mark Step 19 complete. Step 8 remains the next numbered product slice after the interlude. Detailed rationale and scope: `docs/research/SELF_REPAIR_SEQUENCE_DECISION_2026-09-20.md`.

## Current Stage

**STEPS 0–3 DONE — STEP 4 BOUNDED COMPLETE — STEP 5 BOUNDED COMPLETE — STEP 6 BOUNDED COMPLETE — STEP 7 DONE — POST-STEP-7 HANDS / POCKET / PERFORMANCE / STABILITY / SAFETY INTERLUDE ACCEPTED — SELF-AWARENESS FOUNDATION OWNER ACCEPTED — PERSISTENT CONCURRENT WORK ORCHESTRATION OWNER ACCEPTED AND MERGED — RELIABILITY CLEANUP COMPLETE — SELF-REPAIR FOUNDATION INTERLUDE ACTIVE — STEP 8 REMAINS THE NEXT NUMBERED SLICE.**

`PRODUCT.md` owns permanent product intent/status, `ROADMAP.md` owns sequence, `CURRENT_ARCHITECTURE.md` owns accepted running architecture, and `docs/research/` owns detailed evidence.

---

## Accepted state carried forward

- **Step 3:** canonical authority, risk, approval, audit, Windows-session invalidation and Windows Hello/T3 remain authoritative. CAM++ and LR-ASD remain shadow evidence. General biometric/voice-derived T2 is still deferred. Hands may reuse a bounded same-session T2 only after successful direct-user T3 verification; it never comes from face/voice evidence alone and never replaces a required T3 challenge.
- **Step 4:** encrypted canonical memory, explicit lifecycle, FTS5/Qwen retrieval and bounded provider-assisted `recall_memory` are accepted. The strict independent 4.5D verifier and Phase-4.5E automatic semantic-memory injection remain deferred/disabled.
- **Step 5:** deterministic provider-failure diagnosis, local truthful status speech and safe failed-session closure are accepted. Full local/offline conversation and automatic provider failover remain deferred.
- **Step 6:** provider-neutral source-aware current research with Exa, provenance and fail-closed source sufficiency is accepted. PR #55 now supplies the durable background execution foundation; proactive/event-driven research remains later Step-15 work.
- **Step 7:** governed capability discovery/runtime, approved-root local reads, isolated MarkItDown document conversion, canonical authority binding and production `inspect_local` are accepted.
- **Self-Awareness Foundation (PR #41):** owner-accepted bounded whole-JARVIS Self Model, deterministic health/dependency/blast-radius reasoning, redacted rotating operational evidence, local incident engineering memory and typed governed read-only Self-Awareness tools. A long synchronous realtime multi-tool delay discovered during acceptance was resolved structurally by the later concurrent-work foundation; the measured Self-Awareness evidence read itself completed in ~47 ms.
- **Persistent Concurrent Work Orchestration (PR #55):** owner-accepted durable WorkItems/steps/deliveries, DBOS recovery, single-brain interactive priority, bounded resources, natural structured progress/ETA, restart-safe control, deferred result delivery, background research, and isolated repository development. Owner-machine acceptance proved parallel research/development state, standby continuation, restart recovery, cancellation, and verified Calculator Hands execution while background work remained active.

Detailed acceptance: `docs/research/SELF_AWARENESS_ACCEPTANCE_2026-09-18.md` and `docs/research/PERSISTENT_WORK_ACCEPTANCE_2026-09-20.md`.

---

## Accepted post-Step-7 integration interlude

These capabilities are production-accepted foundations but do **not** mean Steps 9, 10 or 12 are fully complete.

### JARVIS Hands — PR #30

Accepted governed computer-operation foundation:

- one voice-facing `use_computer` handoff;
- canonical USER-generation binding, duplicate suppression, per-turn leases and stale-goal supersession;
- native Windows audio/media/clipboard/window/app operations;
- Microsoft `winapp` UI Automation for generic structured desktop work;
- Playwright browser execution;
- bounded file/document creation and editing;
- display/Bluetooth/software surfaces within their implemented contracts;
- bounded Git/development operations instead of arbitrary shell;
- window-scoped visual Computer Use as last resort, with a deterministic CRITICAL authority floor;
- generic multilingual grounding;
- safe fast path for eligible simple reads/reversible actions;
- postcondition verification and truthful failure/unverified states.

Unrestricted shell/PowerShell, destructive/security/credential authority and self-modification remain blocked.

### Pocket 3 native OWNER tracking — PRs #33–#35, #38, #40, #42 and #48

Accepted native DJI path includes BLE/Wi-Fi/DUML transport, A6 OWNER targeting, A5/0x89 native tracking evidence, leave/re-enter reacquisition, confirmed-loss clear/recenter, 10 FPS search/reacquisition -> 1 FPS healthy native lock, resilient session rebuild, stale-state invalidation, Wi-Fi AP settle handling, and startup greeting gated on trusted native lock when configured.

PR #40 additionally hardened cold/restart startup: FFF4 notification subscription must produce valid inbound DUML protocol evidence before pairing begins; the accepted pairing sequence then preserves session wake -> 0.4 s settle -> pair arm -> 0.2 s settle -> JARVIS authentication. BLE readiness/pairing/credential waits are shutdown-aware, one synchronous provisioning batch is bounded to two attempts, reconnect cooldown starts when a failed attempt actually finishes, and a slow successful connection discards the old pre-connection frame before OWNER targeting resumes on a fresh frame.

PR #42 made BLE pairing confirmation reliable with bounded in-session authentication retransmission and service-settle pacing.

PR #48 added transport-liveness evidence and recovery for the live failure where cached native `active=True` could remain stale. Fresh transport RX and fresh native subject evidence now govern recovery progress; stale transport triggers the existing bounded native-session rebuild path. Owner-machine tests proved recovery back to native OWNER lock after transport/Wi-Fi disruption.

### Runtime performance — PR #36

Accepted selective OPT-1 work includes bounded MiniFAS ONNX threading, low-CPU streaming wake proposal + exact verifier, opt-in vision preview, and `jarvis-runtime-profile`.

### Runtime stability — PRs #38 and #43

PR #38 accepted final-empty USER-generation cleanup, near-silent assistant-audio replay, immediate standby, Hands app-field normalization, structured-UI stagnation escalation to governed visual fallback, Pocket A6 ACK race removal, bounded native-session recovery, reliable clear/recenter sequencing and startup lock gating.

PR #43 completed the canonical USER-grounding correction: raw VAD activity advances activity only, while only accepted canonical USER turns advance command identity/generation. It also replaced hardcoded standby phrase matching with provider-neutral semantic `enter_standby`; JARVIS remains the deterministic lifecycle owner, isolates realtime I/O before the local acknowledgement path, closes only the cloud conversation, and returns to local wake detection.

### Power/session semantic safety — PR #49

Power/session operations now fail closed unless the exact latest canonical USER evidence explicitly names both the proposed operation and the local computer/Windows target. The bound operation/evidence are part of the immutable Authority proposal and Windows Hello material, the native power executor rejects unbound/substituted calls, and bounded intent evidence is retained in Authority audit for incident reconstruction. Owner-machine acceptance proved canceling Windows Hello yields `user_canceled` and no restart.

Full consolidated evidence and disposition history: `docs/research/POST_STEP_7_INTEGRATION_ACCEPTANCE.md`.

---

## Deferred / unfinished / superseded / rejected ledger

| Item | Disposition | Reason |
| --- | --- | --- |
| Turn-specific spoken actor binding | **DEFERRED** | OWNER presence does not prove who spoke a specific turn; speaker/ASD signals need separate calibration and acceptance before gaining authority. |
| PR #18 Step-3 branch | **UNMERGED HISTORICAL** | Main has moved beyond it; useful actor-binding reasoning remains evidence, but the branch is not current architecture. |
| Strict independent 4.5D verifier | **DEFERRED / UNRESOLVED** | Required independent release quality was not proven strongly enough. |
| Phase 4.5E automatic memory influence | **DEFERRED / DISABLED** | Automatic injection would influence ordinary conversation before the release boundary is strong enough. |
| Phase 4.5E.1 shadow context branch | **FUNCTIONAL PASS / NOT PRODUCTION-ACCEPTED** | Owner-machine functional shadow behavior passed, but the resource-profile gate was explicitly deferred; do not merge the branch as accepted production. |
| Phase 4.5E.2 Qwen utility gate | **REJECTED** | Multilingual holdout produced unsafe false influence and zero ESSENTIAL recall; no provider-context injection was authorized. |
| Full local/offline conversation | **DEFERRED** | Minimal truthful provider-failure survival solved the immediate need without a second unvalidated conversation stack. |
| Issue #50 fixed lifecycle/system speech | **OWNER ACCEPTED / PR #64 MERGED** | Gemini/cloud lifecycle speech remains primary with provider retries disabled; local Windows speech is the bounded fallback. PR #64 merged to protected `main` at `b44376f6f4a8d94967c8740a34f1208d1fcdb1af`. |
| Issue #44 relative/provider volume fast-path semantics | **DEFERRED BUG** | Absolute provider aliasing and relative volume deltas need bounded normalization/current-volume resolution. |
| Issue #45 false-interruption resume | **DEFERRED BUG** | Production audio output cannot pause, so configured resume behavior is unavailable. |
| Issue #46 intermittent LiveKit AudioMixer timeout | **DEFERRED INVESTIGATION** | Warning has not yet been proven to cause a user-visible audio failure. |
| Issue #56 Pocket OWNER continuity | **OWNER ACCEPTED / PR #61 MERGED** | Exact authorized visual-track continuity bridges temporary biometric/head gaps without converting DJI tracking into identity evidence. PR #61 merged to protected `main` at `a4668ea2708d58b703296f522887d1d6f5ffd085`; owner-machine acceptance is recorded in `docs/research/POCKET3_OWNER_CONTINUITY_ACCEPTANCE_2026-09-20.md`. |
| Issue #57 durable work TTS retry backoff | **OWNER ACCEPTED / PR #62 MERGED** | WorkDelivery now persists retry metadata, respects provider RetryInfo, uses bounded fallback backoff, suppresses premature retries and disables nested LiveKit retries only for WorkDelivery speech. Owner-machine acceptance proved 24.8s then 59.2s provider-directed cooldowns with no 2-second retry hammering. PR #62 merged to protected `main` at `9a3cd00ac24d57b8692b771cccae93f8621e4d5d`. |
| Issue #63 blocked background-work status truth | **DEFERRED FOLLOW-UP** | Owner-machine testing exposed stale 15% progress/ETA language while research was blocked by missing Exa credentials and Gemini provider pressure. Status responses must surface canonical blockers and avoid normal ETA claims when recovery time is unknown. |
| Issue #19 production voice isolation / turn ownership | **DEFERRED RESEARCH** | Accepted security evidence remains shadow-only; rejected isolation/target-speaker candidates are not production control. |
| Persistent concurrent work orchestration | **OWNER ACCEPTED / PR #55 MERGED** | Durable WorkItems, DBOS recovery, single-brain voice priority, bounded resources, structured progress/status, deferred delivery and isolated development execution passed owner-machine acceptance on 2026-09-20. |
| Proactive monitoring / event-driven background work | **PLANNED** | Step 15 remains the later product slice for proactive/event-driven behavior; it will reuse the orchestration foundation rather than invent a second background-work system. |
| PR #27 | **SUPERSEDED** | Replaced by accepted Step-7 PR #28. |
| PR #31 | **SUPERSEDED** | Profiler work recovered cleanly in PR #36. |
| PR #32 | **SUPERSEDED / PARTIALLY RECOVERED** | Proven performance pieces were recovered; stale Pocket/runtime drift and rejected experiments were excluded. |
| Workstation auto-lock experiment | **REJECTED / NOT PRODUCTION** | Explicitly excluded from accepted Pocket/performance recovery; OWNER absence affects tracking/recenter, not Windows locking. |
| PR #37 | **SUPERSEDED AS STANDALONE** | Its canonical generation fix is retained in PR #38. |
| Steps 9/10/12 | **PLANNED WITH PARTIAL FOUNDATIONS** | Hands pulled forward bounded foundations, not the complete future product slices. |
| Steps 13–20 | **PLANNED** | Awareness, proactivity, extensibility, self-repair and self-improvement remain future governed work. |

---

## Persistent Concurrent Work Orchestration — accepted foundation

PR #55 implements the owner-accepted foundation from issue #53:

1. JARVIS-owned provider-neutral WorkItems/steps/deliveries persist independently of voice/model sessions;
2. DBOS supplies durable workflow recovery and messaging while JARVIS retains canonical semantic state;
3. live owner conversation has absolute priority over background model reasoning; already-running deterministic work may continue;
4. dependencies, priorities, resource leases, pause/resume/cancel/retry and WAITING_FOR_OWNER are explicit canonical states;
5. SILENT / WHEN_IDLE / INTERRUPT delivery is persisted and only marked delivered after speech succeeds;
6. current worker support is deliberately bounded to research and isolated development rather than pretending all future WorkTypes exist;
7. development work uses per-WorkItem Git worktrees, locked-down Docker pytest, disabled Git hooks/textconv, secret-content filtering, and ordered proof of latest edit -> passing sandbox tests -> final diff -> clean isolated commit;
8. production DBOS execution requires explicit Postgres; the canonical local JARVIS work store remains SQLite/WAL;
9. no protected-main push/merge/deployment or Authority expansion is granted by this foundation.

Owner-machine acceptance passed on 2026-09-20. Runtime head `b2ba211becdef1b123852a44e7d0c39ffe36cf58` passed Code Quality run #3929, final PR head `a38b2e5dd3f1e4c31f08bd7efbcd0457617eee91` passed Code Quality run #3951, and PR #55 merged to protected `main` as `3980b212d657106abd45bfae119d2207551c409f`. Acceptance detail is in `docs/research/PERSISTENT_WORK_ACCEPTANCE_2026-09-20.md`.

## Reliability cleanup + Self-Repair Foundation — queued before Step 8

Owner-approved sequence:

1. **#56 Pocket OWNER continuity — OWNER ACCEPTED / PR #61 MERGED** — exact already-authorized visual-track continuity now survives transient biometric/head gaps without weakening fresh verification for acquisition/reacquisition;
2. **#57 durable WorkDelivery TTS backoff — OWNER ACCEPTED / PR #62 MERGED** — provider RetryInfo and durable bounded backoff now govern failed WorkDelivery speech without altering canonical completion truth;
3. **#50 lifecycle/system speech resilience — OWNER ACCEPTED / PR #64 MERGED** — Gemini/JARVIS lifecycle speech remains primary while local deterministic speech is the bounded fallback;
4. **Self-Repair Foundation interlude — ACTIVE / issue #65** — ADR-019 is owner-approved and refined with Hermes-style staged repair knowledge, Ornith-style repair curriculum, and Nemotron/NeMo-style model routing + verifiable training patterns while deterministic repair authority remains JARVIS-owned;
5. only after the bounded Self-Repair Foundation is accepted, begin formal Step 8 requirements/research.

The Self-Repair interlude must reuse Self-Awareness, incidents, WorkItems/DBOS, isolated development worktrees, Docker pytest and repository governance. It must begin with deterministic repair contracts and an outer supervision boundary. AI-assisted diagnosis and sandboxed source repair come later; autonomous protected-main merge/deployment and self-evolution remain out of scope.

## Step 8 — next numbered product slice after the interlude

Step 8 must reuse the durable WorkItem foundation while remaining research-first from the reconciled production baseline:

1. recover CAP-027/CAP-028 requirements and privacy/authority constraints;
2. inspect conversation, memory, authority, capability-runtime, Hands and lifecycle boundaries;
3. research mature notes/tasks/reminders/scheduling and platform notification/scheduling technology;
4. define canonical JARVIS task/reminder truth separately from provider reasoning and platform delivery state;
5. define timezone, recurrence, edit/cancel, acknowledgement, missed-run, restart/recovery and audit semantics;
6. reuse canonical capability/authority boundaries;
7. propose the smallest provider-neutral architecture;
8. obtain owner architecture approval before implementation.

## Immediate Next Action

**BEGIN ISSUE #65 IMPLEMENTATION FROM OWNER-APPROVED ADR-019: DETERMINISTIC REPAIR MODELS/REGISTRY -> REPAIRATTEMPT PERSISTENCE -> EXTERNAL SUPERVISOR CRASH BUDGET/RESTART -> LIVENESS VERIFICATION.**

Then add staged RepairKnowledge and the provider-neutral DiagnosticModelRouter. AI diagnostics, synthetic Repair Curriculum and source repair remain later gated phases. Keep issue #63 separate: blocked-work status truth is not itself a Self-Repair restart trigger.
