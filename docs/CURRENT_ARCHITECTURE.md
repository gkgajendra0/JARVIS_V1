# JARVIS V1 Current Architecture

## Status

**STEPS 0–3 COMPLETE. STEPS 4–6 BOUNDED COMPLETE. STEP 7 COMPLETE. POST-STEP-7 HANDS / POCKET 3 / PERFORMANCE / STABILITY WORK IS ACCEPTED IN PRODUCTION. STEP 8 IS REQUIREMENTS / RESEARCH.**

This file describes architecture that actually exists. Historical proposals and experiments belong in `docs/research/`; active work belongs in `CURRENT_PLAN.md`.

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

Models may decide what capability is useful, but they do not own canonical truth, identity, memory mutation, risk, permissions, or execution permits.

---

## Voice and canonical conversation

LiveKit MediaDevices remains the single production Pocket 3 microphone owner at 48 kHz with WebRTC AEC/NS/HPF/AGC. Provider-native realtime turn completion remains authoritative while local speech activity protects the outer lifecycle from expiring during active speech.

Accepted hardening now includes:

- FIFO canonical USER generations for genuine delayed transcripts;
- final-empty realtime transcription retires one abandoned pending USER generation;
- near-silent realtime assistant PCM with valid text can replay through scripted TTS;
- `go back to sleep` performs an immediate audible standby transition and returns to local wake detection;
- low-CPU wake uses an openWakeWord streaming proposal stage followed by the original bounded exact verifier.

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
- one synchronous BLE provisioning batch is bounded to two attempts, while later reconnects remain available through the observer lifecycle;
- reconnect cooldown starts when a failed attempt actually finishes rather than from a stale pre-attempt frame timestamp;
- after a slow successful transport connection, the old pre-connection frame is discarded and OWNER targeting resumes on a fresh vision frame.

---

## Speaker evidence and trust

CAM++ and LR-ASD remain shadow/diagnostic evidence. They do not independently authorize actions, and turn-specific spoken actor binding remains deferred.

Trust vocabulary remains T0 `UNVERIFIED`, T1 `PRESENT_CONTEXT`, T2 `CORROBORATED_OWNER`, T3 `VERIFIED_OWNER`.

General biometric/voice-derived T2 promotion remains deferred. Hands may establish a bounded same-session T2 convenience window **only after successful direct-user Windows Hello/T3 verification**. That window is absolute 30 minutes, non-sliding, session-local, unavailable to proactive/model-suggested work, and never substitutes for T3 when policy requires T3.

---

## Authority

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

---

## Memory, resilience and current research

Step 4 keeps separate owners for canonical conversation, live context and durable memory. SQLCipher/SQLite is canonical storage; FTS5 and Qwen-derived retrieval are rebuildable indexes over eligible records. Provider-assisted `recall_memory` is explicit and fail-closed. The strict independent 4.5D verifier and automatic 4.5E memory injection remain deferred.

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

Hands additionally provides canonical USER-generation claiming, duplicate suppression, stale-goal supersession, bounded multilingual grounding, safe fast-path execution for eligible simple operations, postcondition verification, and structured-UI stagnation escalation to the already-governed visual fallback.

Visual Computer Use is explicit opt-in, target-window scoped, rejects stale/out-of-window/global-switch actions, and has a deterministic CRITICAL authority floor.

Higher-risk operations that are outside the accepted bounded contracts remain unavailable.

Hands pulls forward bounded foundations for future Steps 9, 10 and 12 but does not mark those product slices complete.

---

## Performance and diagnostics

Accepted performance architecture includes bounded MiniFAS ONNX threading, low-CPU streaming wake proposal + exact verifier, opt-in production vision preview, and `jarvis-runtime-profile` for CPU/RAM/thread/GPU measurement.

Old PRs #31/#32 are historical performance experiments; accepted pieces were selectively recovered through PR #36 and later Pocket/stability work. Automatic Windows workstation locking from OWNER absence is not production architecture.

---

## Known residuals / deliberate deferrals

Not currently claimed as solved:

- turn-specific spoken actor binding and general biometric T2 promotion;
- CAM++/LR-ASD authority thresholds and complete ambient false-turn elimination;
- strict independent semantic-memory release and automatic memory injection;
- full offline conversation or automatic provider failover;
- full future Steps 9, 10 and 12 beyond accepted Hands foundations;
- calendar/email communication, proactive/background automation, plugin lifecycle, world-awareness/HUD end state, or autonomous self-repair/self-improvement.

Detailed accepted/deferred/superseded/rejected history: `docs/research/POST_STEP_7_INTEGRATION_ACCEPTANCE.md`.

---

## Active architecture work

Step 8 — Notes, Tasks, Reminders, and Scheduling — is research only. No Step-8 implementation architecture is accepted yet. It must reuse canonical conversation, memory, capability, authority, audit and lifecycle boundaries rather than creating parallel task/reminder truth or permissions.
