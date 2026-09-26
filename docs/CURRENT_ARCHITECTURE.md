# JARVIS V1 Current Architecture

## Status

**STEPS 0–3 COMPLETE. STEPS 4–6 BOUNDED COMPLETE. STEP 7 COMPLETE. POST-STEP-7 HANDS / POCKET 3 / PERFORMANCE / STABILITY / SAFETY WORK IS ACCEPTED IN PRODUCTION. SELF-AWARENESS PR #41 IS OWNER ACCEPTED. PERSISTENT CONCURRENT WORK ORCHESTRATION PR #55 IS OWNER ACCEPTED. THE DETERMINISTIC REPAIR FRAMEWORK AND R2 RUNTIME CRASH/HANG RECOVERY FOUNDATION ARE OWNER ACCEPTED ON 2026-09-23. PHASE 1H FOUNDATION HARDENING IS OWNER-MACHINE ACCEPTED ON 2026-09-24. PHASE 2 ENGINEERINGKNOWLEDGE AND PHASE 3 ENGINEERINGCHANGE ARE OWNER-MACHINE ACCEPTED ON 2026-09-25. PHASE 4 RESEARCH + DIAGNOSTIC MODEL ROUTER IS OWNER-MACHINE ACCEPTED ON 2026-09-26. PHASE 5 SECURE AUTONOMOUS ENGINEERING SUBSTRATE IS THE NEXT CROSS-CUTTING SLICE; STEP 8 REMAINS THE NEXT NUMBERED PRODUCT SLICE.**

The latest owner-machine accepted Self-Repair runtime baseline includes Phase 1H foundation hardening promoted through PR #90 on 2026-09-24; later documentation-only reconciliation commits may advance protected `main` without changing that runtime behavior.

This file describes architecture that actually exists on protected `main`. Historical proposals and experiments belong to Git history; active work belongs in `CURRENT_PLAN.md`, and accepted/deferred/superseded status belongs in `PROJECT_STATE.md`.

---

## Top-level production architecture

```text
                         JARVIS V1
                             |
      one active realtime cloud provider + routed background reasoning pool
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
                             |
                    ENGINEERING KNOWLEDGE
                             |
          immutable revisions + provenance/applicability
          deterministic REPAIR projection + lifecycle
          exact/FTS5/Qwen grounded advisory retrieval
                             |
                    ENGINEERING CHANGE
                             |
          durable mission lifecycle + immutable gates
          architecture/build/acceptance/promotion truth
                             |
                     MODEL ROUTING
                             |
          deterministic eligibility + engineering_stage.v1
          target health/cooldown + bounded fallback
          durable decisions/attempts/outcomes/status

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
- one process-external runtime-restart owner shared by development supervision and the local-only production runtime supervisor;
- independent crash and alive-but-unresponsive policies feeding one shared target/action restart circuit breaker;
- durable rolling attempt budgets/cooldowns whose history is not forgiven by short successful stabilization;
- explicit startup readiness separate from control-channel connection;
- authenticated liveness probes and stabilization before `RECOVERED`;
- same-version runtime restart;
- typed execution-precondition evaluation plus immutable trigger/policy snapshots and policy digests;
- typed verification bound to the registered verification contract before RECOVERED;
- versioned/checksummed engineering-incident database migrations;
- Windows Job Object runtime ownership with kill-on-close semantics and psutil fallback;
- launcher/interpreter cleanup before replacement runtime creation;
- bounded current-user Windows outer guardian for production-supervisor failures;
- production fail-closed escalation that stops the outer guardian instead of bypassing the inner restart budget;
- provider/search/TTS degradation excluded from runtime-liveness truth;
- background Git update polling isolated from the liveness watchdog;
- Windows virtual-environment runtime-tree fault injection and child-first force cleanup.

Owner-machine acceptance covers crash/hang recovery, launcher-only death, interpreter-only death, supervisor death + bounded outer-guardian recovery and absence of an accepted duplicate/orphan runtime. The final shared circuit-breaker proof established three verified recent repairs and then injected a fourth crash; the fourth produced zero new RepairAttempts and left zero guardian/supervisor/runtime processes.

Automatic Windows logon startup was observed. When Windows had not yet enumerated the configured Pocket 3 microphone, preflight failed closed rather than selecting another input. Once the configured device was available, the same production path passed preflight, initialized audio/vision and reached native owner-tracking lock.

This architecture is deliberately bounded. EngineeringKnowledge and the Phase-4
Research + Diagnostic Model Router are accepted production foundations, but
AI-assisted unknown-incident source repair, autonomous dependency/secret acquisition,
governed promotion, capability acquisition and self-evolution are later phases.

The complete forward program is defined in
`docs/SELF_REPAIR_AND_EVOLUTION_MASTER_PLAN.md`.

Final acceptance/status history is summarized in `PROJECT_STATE.md`.

---

## EngineeringKnowledge production foundation

Phase 2 EngineeringKnowledge is owner-machine accepted on 2026-09-25.

Current architecture includes:

- canonical EngineeringKnowledge persistence inside the versioned/checksummed engineering SQLite boundary;
- stable knowledge identity plus immutable revisions;
- registered versioned facets with exact schema identity and fail-closed unknown semantics;
- RFC-8785 canonical JSON + SHA-256 integrity contracts;
- provenance/evidence links and typed verification attestations;
- deterministic REPAIR projection from completed verifier-backed `RECOVERED` RepairAttempts;
- lifecycle state and deterministic promotion from CANDIDATE through accepted terminal handling;
- registered applicability matchers evaluated before relevance;
- accepted/current/applicable filtering before retrieval ranking;
- exact lookup and SQLite FTS5/BM25;
- pinned local Qwen3 embedding support with rebuildable derived indexes;
- RRF fusion where dense ranking may rerank only exact/lexically grounded candidates;
- lexical/exact fallback when the embedding path is unavailable;
- poisoning/instruction and secret-like admission gates;
- sensitivity filtering and integrity checks before advisory use;
- JARVIS-specific qrel/evaluation infrastructure;
- open-ended registered future facets/process semantics without a parallel knowledge database.

EngineeringKnowledge is advisory. It cannot create RepairPolicy, lower deterministic
risk, grant execution permission, authorize credentials, merge protected main or
deploy a source change.

Owner-machine acceptance proved a real production crash was recovered by bounded R2
before any EngineeringKnowledge revision existed for that repair. The recovered
RepairAttempt was then projected, promoted, provenance-checked and retrieved through
exact, lexical and Qwen-256 paraphrase paths. Poisoning/secret gates, future-facet
extensibility and lexical/hybrid qrel safety all passed.

Canonical final record:
`docs/PHASE2_ENGINEERING_KNOWLEDGE_ACCEPTANCE_2026-09-25.md`.


## EngineeringChange production foundation

Phase 3 EngineeringChange Lifecycle / Mission Orchestration is owner-machine accepted on 2026-09-25.

Current architecture includes one durable program-level `EngineeringChange` aggregate above WorkItems, immutable artifact-bound owner gates, architecture revision invalidation, owner-input waits, verified development evidence, acceptance and promotion-intent boundaries, and restart-safe PostgreSQL DBOS mission recovery. WorkItems remain the execution unit; EngineeringChange owns the multi-stage governed lifecycle.

Canonical final record:
`docs/PHASE3_ENGINEERING_CHANGE_ACCEPTANCE_2026-09-25.md`.

## Research + Diagnostic Model Router production foundation

Phase 4 is owner-machine accepted on 2026-09-26.

Current architecture now includes:

- provider/model-neutral routing targets, adapters and strategies;
- deterministic hard eligibility for capability, structured output, context, locality/privacy, credentials, target health and route role;
- `engineering_stage.v1` deterministic WorkStep-aware routing;
- durable route decisions before invocation plus append-only attempts/outcomes and strategy/registry/policy digests;
- target-local health, cooldown and provider-failure classification;
- JARVIS-owned bounded same-target retry/fallback rather than hidden provider-SDK retry ownership for routed background reasoning;
- approved Gemini and OpenAI structured-output targets for durable WorkReasoner use;
- truthful `WAITING_RESOURCE` behavior when approved targets are exhausted;
- bounded owner-visible routing status and offline replay/evaluation;
- restart-safe canonical WorkItem and routing-request lineage;
- coalesced repeated owner-facing routing-blocker speech without discarding engineering evidence.

Owner-machine acceptance naturally proved `Gemini -> rate_limited -> OpenAI fallback -> quota_exhausted` under the same canonical WorkItem, then proved the accepted fallback lineage survived runtime restart with zero duplicate routing-request IDs. Authority/security regressions remained green.

Realtime voice routing is not part of this foundation. Interactive voice/Hands retain their existing provider behavior and priority. Local-model targets, learned routing, Jev and autonomous routing-policy mutation remain deferred.

Canonical final record:
`docs/PHASE4_MODEL_ROUTER_ACCEPTANCE_2026-09-26.md`.

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
- AI-assisted diagnostics, automatic promotion from EngineeringKnowledge into executable RepairPolicy, sandboxed source repair, Engineering Curriculum and governed self-improvement beyond the accepted deterministic Self-Repair + EngineeringKnowledge foundations.

Repository-wide accepted/deferred/superseded/rejected truth is centralized in `PROJECT_STATE.md`.

---

## Next architecture acceptance

Phase 4 Research + Diagnostic Model Router is **DONE / OWNER-MACHINE ACCEPTED 2026-09-26**. Its final evidence is recorded in `docs/PHASE4_MODEL_ROUTER_ACCEPTANCE_2026-09-26.md`.

The next active cross-cutting slice is **Phase 5 — Secure Autonomous Engineering Substrate**. Its research and architecture must define governed dependency acquisition, opaque secret handling, capability manifests, bounded device/service discovery, least-privilege sandbox profiles, provenance and hardware-in-the-loop acceptance without broadening model authority.

**Step 8 — Notes, Tasks, Reminders, and Scheduling (CAP-027/CAP-028)** remains
the next numbered product slice and must still reuse the accepted durable
WorkItem/WorkDelivery foundation when numbered roadmap work resumes.
