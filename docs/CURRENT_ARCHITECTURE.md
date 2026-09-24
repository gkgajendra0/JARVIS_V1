# JARVIS V1 Current Architecture

## Status

**STEPS 0–3 COMPLETE. STEPS 4–6 BOUNDED COMPLETE. STEP 7 COMPLETE. POST-STEP-7 HANDS / POCKET 3 / PERFORMANCE / STABILITY / SAFETY WORK IS ACCEPTED IN PRODUCTION. SELF-AWARENESS PR #41 IS OWNER ACCEPTED. PERSISTENT CONCURRENT WORK ORCHESTRATION PR #55 IS OWNER ACCEPTED. THE DETERMINISTIC REPAIR FRAMEWORK AND R2 RUNTIME CRASH/HANG RECOVERY FOUNDATION ARE OWNER ACCEPTED ON 2026-09-23. PHASE 1H FOUNDATION HARDENING IS THE NEXT ACCEPTANCE GATE BEFORE REPAIRKNOWLEDGE; STEP 8 REMAINS THE NEXT NUMBERED PRODUCT SLICE.**

The latest owner-machine accepted Self-Repair runtime baseline is `6a0ba73f46f68d9d0c2e8fa2c20c5fccaed8378a`; later documentation-only reconciliation commits may advance protected `main` without changing that runtime behavior.

This file describes architecture that actually exists on protected `main`. Historical proposals and experiments belong to Git history; active work belongs in `CURRENT_PLAN.md`, and accepted/deferred/superseded status belongs in `PROJECT_STATE.md`.

---

## Top-level production architecture

```text
                         JARVIS V1
                             |
                one active cloud-AI provider
                             |
        +--------------------+--------------------+
        |                    |                    |
      VOICE                VISION              AUTHORITY
        |                    |                    |
LiveKit MediaDevices    Pocket3/OpenCV      ActionProposal
AEC/NS/HPF/AGC          RF-DETR/OC-SORT     risk + OPA
        |                OWNER face/liveness approvals/Hello
        |                    |
        |              DJI native tracking
        |                    |
        +-- CAM++ / LR-ASD shadow evidence -------+
                             |
                    SELF-AWARENESS / OBSERVABILITY
                             |
               Self Model + health + dependencies
               rotating evidence + incident memory
                             |
                    DURABLE WORK ORCHESTRATION
                             |
          WorkItem / WorkStep / WorkDelivery truth
          SQLite protected payloads + DBOS/Postgres
          bounded research + isolated development
                             |
                EXTERNAL SELF-REPAIR SUPERVISION
                             |
          RepairPolicy / RepairAttempt / budgets
          startup readiness + authenticated liveness
          bounded same-version recovery + verification

canonical USER turns
   +-> LiveContext / MemoryService
   +-> CurrentResearchService / Exa
   +-> CapabilityResolver / CapabilityRuntime
   +-> HandsGoalAgentTools
          +-> native Windows semantics
          +-> Playwright
          +-> Microsoft winapp UI Automation
          +-> bounded file/document/device/Git executors
          +-> target-window visual Computer Use fallback
          -> AuthorityService -> one-time permit -> verify -> audit
```

Models may decide what capability is useful, but they do not own canonical truth, identity, memory mutation, risk, permissions, lifecycle state, or execution permits.

---

## Voice and canonical conversation

LiveKit MediaDevices remains the single production Pocket 3 microphone owner at 48 kHz with WebRTC AEC/NS/HPF/AGC. Provider-native realtime turn completion remains authoritative for accepted USER conversation items.

Accepted hardening includes:

- raw VAD / `user_state_changed` activity advances only a user-activity epoch; it does **not** manufacture command identity;
- only accepted final/committed canonical USER turns advance `user_utterance_generation`;
- Hands grounds executable voice goals to those canonical USER generations;
- false/empty speech activity therefore cannot create stale command-generation debt;
- final-empty realtime transcription still retires abandoned pending USER activity where applicable;
- near-silent realtime assistant PCM with valid text can replay through scripted TTS;
- semantic zero-argument `enter_standby` replaces vocabulary-bound exit phrase matching;
- the model may request standby, but `VoiceRuntimeController` remains the lifecycle owner;
- accepted standby isolates realtime input/output, interrupts realtime speech, ends only the cloud conversation, and returns the process to local wake detection while Vision/Pocket remain alive;
- JARVIS standby is explicitly distinct from Windows sleep/restart/shutdown/lock/sign-out;
- low-CPU wake uses an openWakeWord streaming proposal stage followed by the bounded exact verifier.

Fixed lifecycle/system speech now uses cloud scripted TTS as primary with bounded local Windows speech fallback. TTS quota failure remains dependency degradation and must not be interpreted as standby/lifecycle or runtime-liveness failure.

---

## Vision and Pocket 3 native OWNER tracking

Base vision remains OpenCV capture -> RF-DETR person detection -> OC-SORT tracking -> head/face association -> OWNER identity/liveness.

Native tracking adds BLE/Wi-Fi/DUML transport, A6 OWNER target selection and A5/0x89 native tracking evidence. JARVIS marks native `LOCKED` only from fresh trusted OWNER evidence plus observed native tracking evidence; physical camera motion alone is insufficient.

Accepted behavior:

- 10 FPS while searching/reacquiring, 1 FPS while healthy native OWNER lock is maintained;
- confirmed OWNER loss clears target then recenters;
- returning OWNER is freshly detected and reacquired;
- stale native evidence is invalidated on transport close;
- bounded repeated reacquisition failure rebuilds the native session with cooldown;
- A6 waiter registration precedes fast ACK arrival;
- hardware-proven Wi-Fi AP settle occurs before Windows association;
- startup greeting waits for trusted native lock when configured, with bounded silent fallback to wake-idle;
- BLE startup subscribes to FFF4 and requires a valid inbound DUML frame before entering pairing;
- after protocol readiness, the accepted sequence is session wake -> 0.4 s settle -> pair arm -> 0.2 s settle -> JARVIS authentication;
- BLE readiness, pairing, SSID and password waits are shutdown-aware;
- bounded in-session pairing retransmission/service-settle pacing handles already-paired confirmation reliably;
- one synchronous BLE provisioning batch is bounded to two attempts, while later reconnects remain available through the observer lifecycle;
- reconnect cooldown starts when a failed attempt actually finishes rather than from a stale pre-attempt frame timestamp;
- after a slow successful transport connection, the old pre-connection frame is discarded and OWNER targeting resumes on a fresh frame;
- native transport last-RX freshness is tracked independently from cached camera `active` state;
- stale transport/native state cannot indefinitely reset the recovery-attempt counter;
- a stale transport watchdog reuses the existing bounded native-session rebuild path;
- only fresh subject/native evidence resets recovery progress after reconnection.

Owner-machine acceptance proved stale transport recovery back to native OWNER `LOCKED` and normal leave-room -> recenter -> return -> reacquisition.

---

## Speaker evidence and trust

CAM++ and LR-ASD remain shadow/diagnostic evidence. They do not independently authorize actions, and turn-specific spoken actor binding remains deferred.

Trust vocabulary remains T0 `UNVERIFIED`, T1 `PRESENT_CONTEXT`, T2 `CORROBORATED_OWNER`, T3 `VERIFIED_OWNER`.

General biometric/voice-derived T2 promotion remains deferred. Hands may establish a bounded same-session T2 convenience window **only after successful direct-user Windows Hello/T3 verification**. That window is absolute 30 minutes, non-sliding, session-local, unavailable to proactive/model-suggested work, and never substitutes for T3 when policy requires T3.

---

## Authority and power/session safety

General authority remains:

```text
grounded request
 -> immutable ActionProposal
 -> deterministic R0-R5 risk floor
 -> fail-closed OPA policy
 -> approval / Windows Hello as required
 -> final revalidation
 -> one-time permit
 -> bounded executor
 -> postcondition/result verification
 -> privacy-aware audit
```

Provider/model/UI output cannot self-authorize or lower deterministic risk.

Power/session actions have an additional fail-closed semantic boundary:

- exact evidence must come from the latest accepted canonical USER turn;
- that exact evidence must explicitly name both the proposed operation and the local computer/Windows target;
- JARVIS standby/sleep language is not Windows power evidence;
- `intent_operation` and bounded `intent_evidence` are carried into the immutable proposal fingerprint and Windows Hello material summary;
- the native power/session executor rejects unbound calls and operation substitution even if a caller bypasses Hands;
- Authority audit records bounded operation-specific intent evidence for incident reconstruction.

Owner-machine acceptance proved that an explicit `Restart my computer` request reached `restart_workstation`, Windows Hello was shown, owner cancellation returned `user_canceled`, and no restart occurred.

---

## Memory, resilience and current research

Step 4 keeps separate owners for canonical conversation, live context and durable memory. SQLCipher/SQLite is canonical storage; FTS5 and Qwen-derived retrieval are rebuildable indexes over eligible records. Provider-assisted `recall_memory` is explicit and fail-closed.

The strict independent 4.5D verifier remains deferred. Phase 4.5E.1 shadow context retrieval had a functional owner-machine pass but was **not** fully production-accepted because its resource-profile gate was deferred. Phase 4.5E.2 rejected the Qwen utility/steering influence gate. Automatic 4.5E provider-context memory injection remains disabled.

Step 5 classifies terminal provider failures in deterministic JARVIS code and can speak a local truthful status before closing the failed session. Full local/offline conversation and automatic provider failover are not claimed.

Step 6 uses `CurrentResearchService` with Exa as the first replaceable retrieval adapter. JARVIS owns provenance, source sufficiency and truthful failure behavior.

---

## Self-Awareness and operational evidence

PR #41 adds the owner-accepted bounded read-only Self-Awareness foundation.

Canonical architecture includes:

- a version-controlled hierarchical whole-JARVIS Self Model with stable component IDs, parent/child relationships, source/test/config/resource/probe metadata and dependency edges;
- deterministic component health with HEALTHY / DEGRADED / FAILED / UNKNOWN states, freshness/TTL handling and top-level bounded system health;
- dependency criticality and blast-radius queries;
- privacy-aware structured operational events with correlation context;
- deny-by-default redaction at write time plus re-redaction when evidence is read;
- human-readable console logging plus bounded rotating local JSONL evidence;
- OpenTelemetry trace/metric adapter with external OTLP export disabled by default;
- separate local SQLite engineering incident memory;
- typed governed Self-Awareness reads for component discovery, health, details, operational evidence, incident history and similar resolved incidents.

Self-Awareness is evidence/truth infrastructure, not execution authority. Incident history is historical evidence rather than repair instruction, UNKNOWN remains truthful missing/stale evidence, and no Self-Awareness read can grant autonomous code mutation, deployment, merge or Authority expansion.

Owner-machine acceptance proved natural architecture/component questions, provider/blast-radius inspection, operational Pocket evidence reads and normal live Pocket recovery. The evidence query itself completed in ~47 ms.

A long synchronous Gemini Live multi-tool interaction originally exposed the need for durable concurrent work/result delivery. That limitation was resolved structurally by the later owner-accepted Persistent Concurrent Work Orchestration foundation rather than hidden inside Self-Awareness with special-case vocabulary or timeout behavior.

Acceptance/status history is summarized in `PROJECT_STATE.md`.

---

## Capability runtime and JARVIS Hands

Step 7 established the provider-neutral capability/runtime boundary, approved-root reads, isolated MarkItDown document conversion, `inspect_local`, and canonical authority integration.

Production Hands reuses that boundary. Executor preference is:

1. native/semantic OS or app operation;
2. dedicated bounded integration;
3. Playwright for browser work;
4. Microsoft `winapp` UI Automation for desktop work;
5. target-window visual Computer Use when structured evidence is insufficient;
6. truthful failure/clarification.

Hands provides canonical USER-generation claiming, duplicate suppression, stale-goal supersession, bounded multilingual grounding, safe fast-path execution for eligible simple operations, postcondition verification, and structured-UI stagnation escalation to the already-governed visual fallback.

Visual Computer Use is explicit opt-in, target-window scoped, rejects stale/out-of-window/global-switch actions, and has a deterministic CRITICAL authority floor.

Higher-risk operations outside accepted bounded contracts remain unavailable. Hands pulls forward bounded foundations for future Steps 9, 10 and 12 but does not mark those product slices complete.

---

## Performance and diagnostics

Accepted performance architecture includes bounded MiniFAS ONNX threading, low-CPU streaming wake proposal + exact verifier, opt-in production vision preview, and `jarvis-runtime-profile` for CPU/RAM/thread/GPU measurement.

Old PRs #31/#32 are historical performance experiments; accepted pieces were selectively recovered through PR #36 and later Pocket/stability work. Automatic Windows workstation locking from OWNER absence is not production architecture.

---

## Persistent concurrent work orchestration

PR #55 adds the owner-accepted durable work foundation and was merged to protected `main` at `3980b212d657106abd45bfae119d2207551c409f` on 2026-09-20.

Canonical JARVIS architecture now includes:

- provider-neutral `WorkItem`, `WorkStep` and `WorkDelivery` truth persisted independently of any voice/model session;
- DBOS as durable workflow/recovery/messaging mechanics while JARVIS remains semantic owner;
- explicit Postgres system state for production DBOS plus local SQLite/WAL canonical work truth;
- protected sensitive WorkStore payloads on the Windows production path using a separate AES-GCM key sealed through the existing DPAPI boundary;
- live owner conversation as absolute priority for shared model reasoning, with background reasoning preempted/yielded and already-started deterministic bounded executor work allowed to continue;
- bounded concurrency/resource admission, dependencies, priorities, pause/resume/cancel/reprioritize, owner-input waits and bounded reasoning cycles;
- restart-safe reconciliation: a RUNNING executor step with unknown crash outcome becomes `INTERRUPTED` and the WorkItem moves to `WAITING_FOR_OWNER` instead of silently replaying a possibly side-effecting action;
- structured JARVIS-owned progress/ETA facts exposed to the voice brain, which speaks naturally without hardcoded status sentences or model-invented progress;
- durable `SILENT` / `WHEN_IDLE` / `INTERRUPT` delivery records that are marked delivered only after speech succeeds;
- bounded background research and isolated repository-development workers;
- per-development-WorkItem Git worktrees plus locked-down Docker pytest, disabled hooks/textconv/external diff, final diff inspection and clean isolated commit proof;
- no background-worker permission to push, merge, deploy, mutate protected main, or bypass canonical Authority.

Owner-machine acceptance on 2026-09-20 proved independent research/development WorkItems, standby continuation, truthful status/progress, clean restart recovery, cancellation, and verified `Open Calculator` foreground Hands execution while durable background work remained active.

WorkDelivery speech now persists provider-directed retry/backoff while preserving pending delivery truth, and Pocket 3 OWNER continuity has separate accepted handling for transient biometric/head evidence gaps. Neither condition is part of orchestration truth or runtime-liveness authorization.

Acceptance/status history is summarized in `PROJECT_STATE.md`.

---

## Deterministic Self-Repair production foundation

Issue #65 and PRs #73–#86 establish the owner-accepted deterministic repair
framework and R2 runtime crash/hang Self-Repair foundation. R1 exists in the typed
risk/action vocabulary but no automatic production R1 policy has yet been
owner-accepted.

Current production architecture includes:

- typed `RepairTrigger`, `RepairPolicy`, `RepairAction`, `RepairAttempt` and
  `RepairVerdict` contracts;
- a version-controlled fail-closed repair registry;
- durable RepairAttempt persistence linked to engineering incidents;
- one process-external runtime-restart owner in `jarvis-dev`;
- independent crash and alive-but-unresponsive policies;
- durable attempt budgets/cooldowns and crash-loop exhaustion;
- explicit startup readiness separate from control-channel connection;
- authenticated liveness probes and stabilization before `RECOVERED`;
- same-version runtime restart;
- provider/search/TTS degradation excluded from runtime-liveness truth;
- background Git update polling isolated from the liveness watchdog;
- Windows virtual-environment runtime-tree fault injection and child-first force cleanup.

The final owner-machine hang acceptance suspended both Windows runtime-tree
processes, observed three failed liveness probes plus confirmation, force-cleaned
the frozen tree, started a same-revision replacement, completed startup readiness
and six authenticated stabilization probes, and persisted the RepairAttempt as
`recovered`.

This architecture is deliberately bounded. RepairKnowledge, DiagnosticModelRouter,
AI-assisted diagnosis, source repair and self-evolution are not current production
execution surfaces.

The complete forward program is defined in
`docs/SELF_REPAIR_AND_EVOLUTION_MASTER_PLAN.md`.

Final acceptance/status history is summarized in `PROJECT_STATE.md`.

## Known residuals / deliberate deferrals

Not currently claimed as solved:

- issue #19: production-grade conversation voice isolation / turn ownership;
- turn-specific spoken actor binding and general biometric T2 promotion;
- CAM++/LR-ASD authority thresholds and complete ambient false-turn elimination;
- strict independent semantic-memory release and automatic memory injection;
- issue #44: provider alias / relative volume fast-path semantics;
- issue #45: false-interruption resume is configured although production audio cannot pause;
- issue #46: intermittent LiveKit AudioMixer timeout investigation;
- full offline conversation or automatic provider failover;
- full future Steps 9, 10 and 12 beyond accepted Hands foundations;
- calendar/email communication, proactive/event-driven automation, plugin lifecycle and world-awareness/HUD end state;
- AI-assisted diagnostics, RepairKnowledge execution promotion, sandboxed source repair, Repair Curriculum and governed self-improvement beyond the accepted deterministic Self-Repair foundation.

Repository-wide accepted/deferred/superseded/rejected truth is centralized in `PROJECT_STATE.md`.

---

## Next architecture acceptance

The next active cross-cutting acceptance slice is **Phase 1H — Self-Repair
Foundation Hardening** from `docs/SELF_REPAIR_PHASE1H_HARDENING.md`.

RepairKnowledge research is preserved separately, but implementation remains blocked
until the repair foundation has hardened restart budgets, verification/provenance,
engineering-DB migrations, Windows process ownership and supervisor survivability.

**Step 8 — Notes, Tasks, Reminders, and Scheduling (CAP-027/CAP-028)** remains
the next numbered product slice and must still reuse the accepted durable
WorkItem/WorkDelivery foundation when numbered roadmap work resumes.
