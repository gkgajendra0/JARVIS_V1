# JARVIS V1 Current Architecture

## Status

**STEPS 0–3 COMPLETE. STEPS 4–6 BOUNDED COMPLETE. STEP 7 COMPLETE. POST-STEP-7 HANDS / POCKET 3 / PERFORMANCE / STABILITY / SAFETY WORK IS ACCEPTED IN PRODUCTION. SELF-AWARENESS FOUNDATION PR #41 IS IMPLEMENTED BUT NOT YET PRODUCTION-ACCEPTED. STEP 8 REMAINS QUEUED REQUIREMENTS / RESEARCH.**

Accepted runtime-code baseline after the 2026-09-18 consolidation: `e2ff21e78480a09eb243cdd2c121b39e47620d0f`. Documentation-only reconciliation commits may advance protected `main` without changing that runtime state.

This file describes architecture that actually exists on protected `main`. Historical proposals and experiments belong in `docs/research/`; active acceptance work belongs in `CURRENT_PLAN.md`.

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

Fixed lifecycle/system speech still has a deferred reliability dependency on cloud scripted TTS quota. That is tracked in issue #50. TTS failure must not be interpreted as standby/lifecycle failure.

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

## Known residuals / deliberate deferrals

Not currently claimed as solved:

- issue #19: production-grade conversation voice isolation / turn ownership;
- turn-specific spoken actor binding and general biometric T2 promotion;
- CAM++/LR-ASD authority thresholds and complete ambient false-turn elimination;
- strict independent semantic-memory release and automatic memory injection;
- issue #50: fixed startup/standby lifecycle speech can still depend on cloud TTS quota;
- issue #44: provider alias / relative volume fast-path semantics;
- issue #45: false-interruption resume is configured although production audio cannot pause;
- issue #46: intermittent LiveKit AudioMixer timeout investigation;
- full offline conversation or automatic provider failover;
- full future Steps 9, 10 and 12 beyond accepted Hands foundations;
- calendar/email communication, proactive/background automation, plugin lifecycle, world-awareness/HUD end state, or autonomous self-repair/self-improvement.

Detailed accepted/deferred/superseded/rejected history: `docs/research/POST_STEP_7_INTEGRATION_ACCEPTANCE.md`.
Repository-wide reconciliation evidence: `docs/research/PRODUCTION_RECONCILIATION_2026-09-18.md`.

---

## Next architecture acceptance

PR #41 Self-Awareness Foundation is implemented on its feature branch but is **not part of this production architecture yet**. It must first be reconciled onto this accepted baseline and pass owner-machine privacy, resource, incident, health/blast-radius, console/logging and Voice/Hands/Pocket non-regression acceptance.

After that interlude is explicitly accepted and merged, Step 8 — Notes, Tasks, Reminders, and Scheduling — remains the next formal roadmap slice.
