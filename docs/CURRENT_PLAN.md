# JARVIS V1 Current Plan

## Active Work

**PR #41 — Self-Awareness Foundation owner-machine acceptance resumes from the fully reconciled production baseline.**

The accepted production baseline is protected `main` at `e2ff21e78480a09eb243cdd2c121b39e47620d0f` after owner-accepted PRs #43, #49 and #48 were consolidated on 2026-09-18.

PR #41 remains draft/unmerged. Its implementation is complete; the next work is real owner-machine privacy/resource/incident/non-regression acceptance, documentation reconciliation, then explicit protected-main merge approval.

**Step 8 — Notes, Tasks, Reminders, and Scheduling (CAP-027, CAP-028) remains the next formal roadmap slice after the Self-Awareness interlude and remains REQUIREMENTS / RESEARCH.**

## Current Stage

**STEPS 0–3 DONE — STEP 4 BOUNDED COMPLETE — STEP 5 BOUNDED COMPLETE — STEP 6 BOUNDED COMPLETE — STEP 7 DONE — POST-STEP-7 HANDS / POCKET / PERFORMANCE / STABILITY / SAFETY INTERLUDE ACCEPTED — SELF-AWARENESS FOUNDATION ACCEPTANCE NEXT — STEP 8 REQUIREMENTS / RESEARCH QUEUED.**

`PRODUCT.md` owns permanent product intent/status, `ROADMAP.md` owns sequence, `CURRENT_ARCHITECTURE.md` owns accepted running architecture, and `docs/research/` owns detailed evidence.

---

## Accepted state carried forward

- **Step 3:** canonical authority, risk, approval, audit, Windows-session invalidation and Windows Hello/T3 remain authoritative. CAM++ and LR-ASD remain shadow evidence. General biometric/voice-derived T2 is still deferred. Hands may reuse a bounded same-session T2 only after successful direct-user T3 verification; it never comes from face/voice evidence alone and never replaces a required T3 challenge.
- **Step 4:** encrypted canonical memory, explicit lifecycle, FTS5/Qwen retrieval and bounded provider-assisted `recall_memory` are accepted. The strict independent 4.5D verifier and Phase-4.5E automatic semantic-memory injection remain deferred/disabled.
- **Step 5:** deterministic provider-failure diagnosis, local truthful status speech and safe failed-session closure are accepted. Full local/offline conversation and automatic provider failover remain deferred.
- **Step 6:** provider-neutral source-aware current research with Exa, provenance and fail-closed source sufficiency is accepted. Long-running/background research remains later work.
- **Step 7:** governed capability discovery/runtime, approved-root local reads, isolated MarkItDown document conversion, canonical authority binding and production `inspect_local` are accepted.

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
| Issue #50 fixed lifecycle/system speech | **DEFERRED RELIABILITY** | Startup/standby scripted phrases can still depend on cloud TTS quota; lifecycle transitions must remain independent of TTS success. |
| Issue #44 relative/provider volume fast-path semantics | **DEFERRED BUG** | Absolute provider aliasing and relative volume deltas need bounded normalization/current-volume resolution. |
| Issue #45 false-interruption resume | **DEFERRED BUG** | Production audio output cannot pause, so configured resume behavior is unavailable. |
| Issue #46 intermittent LiveKit AudioMixer timeout | **DEFERRED INVESTIGATION** | Warning has not yet been proven to cause a user-visible audio failure. |
| Issue #19 production voice isolation / turn ownership | **DEFERRED RESEARCH** | Accepted security evidence remains shadow-only; rejected isolation/target-speaker candidates are not production control. |
| Background Deep Research/proactive monitoring | **DEFERRED** | Belongs to later background/proactivity governance. |
| PR #27 | **SUPERSEDED** | Replaced by accepted Step-7 PR #28. |
| PR #31 | **SUPERSEDED** | Profiler work recovered cleanly in PR #36. |
| PR #32 | **SUPERSEDED / PARTIALLY RECOVERED** | Proven performance pieces were recovered; stale Pocket/runtime drift and rejected experiments were excluded. |
| Workstation auto-lock experiment | **REJECTED / NOT PRODUCTION** | Explicitly excluded from accepted Pocket/performance recovery; OWNER absence affects tracking/recenter, not Windows locking. |
| PR #37 | **SUPERSEDED AS STANDALONE** | Its canonical generation fix is retained in PR #38. |
| Steps 9/10/12 | **PLANNED WITH PARTIAL FOUNDATIONS** | Hands pulled forward bounded foundations, not the complete future product slices. |
| Steps 13–20 | **PLANNED** | Awareness, proactivity, extensibility, self-repair and self-improvement remain future governed work. |

---

## Step 8 — queued formal requirements / research

Step 8 must start research-first from the reconciled production baseline:

1. recover CAP-027/CAP-028 requirements and privacy/authority constraints;
2. inspect conversation, memory, authority, capability-runtime, Hands and lifecycle boundaries;
3. research mature notes/tasks/reminders/scheduling and platform notification/scheduling technology;
4. define canonical JARVIS task/reminder truth separately from provider reasoning and platform delivery state;
5. define timezone, recurrence, edit/cancel, acknowledgement, missed-run, restart/recovery and audit semantics;
6. reuse canonical capability/authority boundaries;
7. propose the smallest provider-neutral architecture;
8. obtain owner architecture approval before implementation.

## Immediate Next Action

**REBASE / RECONCILE PR #41 ON THIS PRODUCTION BASELINE -> OWNER-MACHINE SELF-AWARENESS PRIVACY / RESOURCE / INCIDENT / NON-REGRESSION ACCEPTANCE -> FINAL DOCS -> EXPLICIT PROTECTED-MAIN MERGE APPROVAL.**

After that interlude, resume **STEP 8 REQUIREMENTS RECOVERY -> FRESH RESEARCH -> TECHNOLOGY DECISION -> ARCHITECTURE PROPOSAL -> OWNER APPROVAL BEFORE IMPLEMENTATION.**
