# JARVIS V1 Current Architecture

## Status

**IMPLEMENTED/HUMAN-ACCEPTED THROUGH PHASE 3B.10A, WITH THE 48-kHz LIVEKIT MEDIADEVICES CONVERSATION-AUDIO REPLACEMENT IMPLEMENTED AFTER REAL-MACHINE ACCEPTANCE. INTEGRATED MEDIADEVICES + RAW GSTREAMER SENSOR COEXISTENCE IS THE NEXT ACCEPTANCE GATE. 3B.11 ACTIVE-SPEAKER CORROBORATION FOLLOWS. ATTENTION REMAINS DEFERRED. T2 REMAINS DISABLED.**

This document records accepted production architecture and the exact replacement boundaries currently being integrated. Detailed benchmark evidence belongs in `docs/research/`; active work order belongs in `docs/CURRENT_PLAN.md`; significant choices are recorded in ADRs.

---

## Accepted platform foundation

JARVIS has accepted foundations for:

- natural realtime conversation with JARVIS-owned conversation state;
- local wake detection and JARVIS-owned voice lifecycle;
- Pocket3 visual capture, person detection, persistent tracking, head evidence, explicit target selection and safe PTZ follow;
- deterministic Step-3 authority, policy, approval, audit, Windows-session and strong-verification boundaries;
- one persistent encrypted OWNER profile;
- pinned/integrity-verified YuNet + SFace face runtime;
- real OWNER multi-prototype SFace enrollment;
- passive MiniFAS temporal RGB liveness plus randomized active challenge fallback;
- runtime OWNER identity + liveness binding on the same Windows session and visual track;
- CAM++ speaker-embedding foundation and passive turn-capture/OWNER-context bridge;
- LiveKit `rtc.MediaDevices` full-duplex conversation audio at 48 kHz using WebRTC AEC/NS/HPF/AGC and the accepted NVIDIA HDMI/TV render path.

T2 `CORROBORATED_OWNER` is still intentionally disabled until the final multimodal predicate is accepted.

---

## Step 3A — Authority foundation — ACCEPTED + MERGED

Identity/context evidence, graduated trust and action authority are separate layers:

```text
IDENTITY / CONTEXT EVIDENCE
        ↓
GRADUATED TRUST
        ↓
ACTION AUTHORITY
```

No layer may be skipped.

Accepted trust vocabulary:

- `T0 UNVERIFIED`
- `T1 PRESENT_CONTEXT`
- `T2 CORROBORATED_OWNER`
- `T3 VERIFIED_OWNER`

There is no ambient T4/admin-superuser state.

### Strong verification

Windows Hello is wrapped behind JARVIS's `StrongVerifier` boundary.

```text
exact ActionProposal
+ exact JARVIS/Windows session
        ↓
Windows Hello / PIN
        ↓
proposal/session-bound strong proof
        ↓
StrongApprovalService
        ↓
one proposal-bound STRONG approval
```

Cancellation/unavailability never falls back to face, voice, wake word, spoken confirmation, Windows-unlocked state or LLM confidence.

### Action authority

Consequential actions use immutable, expiring, session-bound `ActionProposal` objects with canonical material fingerprints.

Accepted protections include:

- deterministic hard risk floors;
- fail-closed OPA policy evaluation;
- proposal-bound approval;
- one-time short-lived execution permits;
- final pre-execution proposal/risk/policy/session revalidation;
- replay/mutation/expiry/TOCTOU rejection;
- privacy-aware authoritative audit.

### Windows session boundary

`WindowsWtsSessionProvider` tracks the active Windows session and lock/unlock state. Session lock/switch invalidates authority and biometric evidence contexts.

Windows unlocked is context only; it does not prove the person on camera or microphone is OWNER.

### Permanent authority invariant

```text
face match       ≠ permission
speaker match    ≠ permission
liveness         ≠ permission
active speaker   ≠ permission
attention        ≠ permission
wake word        ≠ owner
Windows unlocked ≠ owner speaking
LLM confidence   ≠ permission
```

Even T3 is not permission by itself; exact proposal, risk, policy and bound approval remain required.

Decision: `docs/decisions/ADR-006_STEP_3_IDENTITY_TRUST_AUTHORITY_GOVERNANCE.md`.

---

## Step 2.5 visual association reused by identity — ACCEPTED

```text
Pocket3 capture
        ↓
RF-DETR person detection
        ↓
persistent person track
        ↓
TargetManager selected/locked track
        ↓
MediaPipe BlazeFace head observations
        ↓
body↔head association
```

The persistent visual track is the stable subject handle. Head/face observations support that track; they are not standalone authority identities.

---

## Phase 3B.1 — Secure single-OWNER storage — ACCEPTED

Persistent subject model:

```text
OWNER
```

Unknown people remain ephemeral/session-scoped.

OWNER storage:

```text
biometric template bytes
        ↓
AES-256-GCM
        ↓
random per-profile DEK
        ↓
user-scoped Windows DPAPI KeyProtector
        ↓
SQLite
```

OWNER create/replace/delete is strongly verified. Candidate template bytes are committed before mutation. Raw biometric payloads are not exposed to policy/audit.

---

## Phase 3B.2/3 — Face model integrity/runtime — ACCEPTED

Pinned OpenCV Zoo baseline:

- YuNet `face_detection_yunet_2026may.onnx`;
- SFace `face_recognition_sface_2021dec.onnx`;
- exact byte-count/SHA verification;
- model files outside Git;
- integrity-verified atomic promotion;
- no silent model drift.

---

## Phase 3B.4 — Pocket3 live face pipeline — ACCEPTED

```text
Pocket3
    ↓
RF-DETR + persistent visual track
    ↓
selected/head-confirmed track
    ↓
BlazeFace head association
    ↓
YuNet
    ↓
SFace 128-D embedding
```

Real-machine evidence showed meaningful same-owner frame variation; one-frame identity thresholds are not accepted.

---

## Phase 3B.5A / 3B.6 — OWNER calibration + enrollment — ACCEPTED BASELINE

Positive OWNER calibration established real-device same-owner behavior but not an authoritative OWNER-vs-UNKNOWN threshold.

OWNER template format:

```text
sface-prototype-set-v1
```

The encrypted enrolled payload contains 8 normalized prototypes selected deterministically using centroid + farthest inliers.

Enrollment does not grant T2.

---

## Phase 3B.7A — Active liveness fallback — ACCEPTED

MediaPipe Face Landmarker drives a JARVIS-owned randomized challenge state machine:

- blink;
- open mouth;
- smile;
- neutral → action → neutral;
- same Windows session;
- same visual track;
- bounded expiry/fail-closed behavior.

A passed challenge creates short-lived typed `FACE_LIVENESS` evidence. It does not independently prove OWNER or grant T2.

---

## Phase 3B.7B — Passive RGB liveness — ACCEPTED FOR CURRENT POCKET3 PROTOTYPE

Selected provider: **MiniFASNet V1SE + V2 ensemble**.

`TemporalPassiveLiveness` is JARVIS-owned and bound to one Windows session, visual track and PAD provider.

Decision rule:

```text
<15 fresh observations       → INSUFFICIENT
15-frame median >= 0.95      → LIVE
15-frame median <= 0.50      → SPOOF
otherwise                    → UNCERTAIN
```

Gap > `0.50 s` resets the window. Initial evidence TTL: `2.0 s`.

- `LIVE` creates short-lived passed liveness evidence;
- `SPOOF` fails closed;
- `UNCERTAIN` may request active challenge;
- liveness alone never proves OWNER or grants authority;
- RGB PAD is not treated as equivalent to depth/IR/ToF liveness.

Decision: `docs/decisions/ADR-008_STEP_3_PASSIVE_RGB_LIVENESS.md`.

---

## Phase 3B.8 — Runtime OWNER identity + liveness binding — ACCEPTED

Temporal OWNER identity is bound to exactly one Windows session, visual track and face provider.

Current provisional evidence-only band:

```text
<15 fresh observations        → INSUFFICIENT
median max-prototype >= 0.65  → OWNER_CANDIDATE
median max-prototype <= 0.35  → UNKNOWN
otherwise                     → AMBIGUOUS
```

This is **not authoritative OWNER-vs-UNKNOWN authentication** because a consenting live non-owner calibration set is not yet available.

Same-track fusion:

```text
active/unlocked Windows session
        +
selected stable visual track
        ↓
associated head/face
        ├── YuNet/SFace → temporal OWNER identity
        └── MiniFAS → temporal passive liveness
        ↓
same session + same track + co-fresh observations
        ↓
combined evidence state
```

Combined states:

```text
OWNER_CANDIDATE + LIVE       → LIVE_OWNER_CANDIDATE
OWNER_CANDIDATE + UNCERTAIN  → ACTIVE_CHALLENGE_ELIGIBLE
OWNER_CANDIDATE + SPOOF      → SPOOFED_OWNER_PRESENTATION
UNKNOWN + any liveness       → UNKNOWN_SUBJECT
AMBIGUOUS + any liveness     → AMBIGUOUS_SUBJECT
anything insufficient        → INSUFFICIENT
```

`LIVE_OWNER_CANDIDATE` is deliberately **not T2**.

Target loss, track change, stale gaps or Windows session transitions invalidate the evidence fail-closed.

Evidence: `docs/research/STEP_3B8_OWNER_LIVENESS_ACCEPTANCE_RESULTS.md`.

---

## Deferred 3B.9 — Attention / intent-to-engage

Attention implementation is deferred until fixed monitor-mounted camera hardware or a stronger accepted attention/eye sensor is available.

The movable Pocket3 must not be used to infer stable monitor-relative gaze through repeated calibration.

```text
T2 CORROBORATED_OWNER
        +
accepted fresh attention evidence (when available/required)
        ↓
OWNER_ATTENTIVE interaction predicate
```

Attention is not a trust tier and does not block completion of the rest of Step 3.

Decision: `docs/decisions/ADR-007_STEP_3_ATTENTION_INTENT_EVIDENCE.md`.

---

## Phase 3B.10 — Speaker identity foundation — ACCEPTED SHADOW PROVIDER

Current disposition:

- CAM++ = provisional shadow speaker-embedding provider;
- ERes2NetV2 = retained challenger;
- TitaNet-Large = removed from first deployment path.

Speaker evidence is protected by:

- exact model integrity checks;
- sherpa-onnx frontend;
- duration/RMS/clipping quality gate;
- bounded multi-prototype matching;
- memory-only shadow prototype state during calibration;
- no deployment threshold while calibration remains incomplete.

Bad/insufficient audio becomes `INSUFFICIENT`, not `UNKNOWN_SPEAKER`.

Speaker identity does not independently create T2/T3 or authorize actions.

Evidence: `docs/research/STEP_3B10_SPEAKER_BAKEOFF_RESULTS.md`.

---

## Phase 3B.10A — Passive normal-turn + OWNER-context bridge — ACCEPTED

```text
exact Pocket3 frame + VisionSnapshot
        ↓
3B.8 SFace + MiniFAS temporal logic
        ↓
thread-safe short-lived OWNER context

canonical accepted user PCM
        +
LiveKit user lifecycle
        ↓
bounded memory-only turn capture
        ↓
speaker quality gate
        ↓
shadow diagnostics
```

A visible live OWNER does **not** prove that current room speech came from that person.

Unsafe prototype-learning rule rejected:

```text
LIVE_OWNER_CANDIDATE visible
        +
any microphone speech
        ↓
OWNER voice prototype   ← forbidden
```

This prevents TV, phone playback, off-camera people and overlapping speech from poisoning the OWNER voice bank.

Prototype admission remains disabled until 3B.11 active-speaker actor corroboration is accepted.

---

## Production conversation audio — ACCEPTED REPLACEMENT ARCHITECTURE

### Superseded path

ADR-010's GStreamer full-duplex conversation path with Tribit Bluetooth is **superseded for conversation audio**.

Although isolated WebRTC DSP tests showed strong suppression, real Gemini Live conversation still generated false user turns containing JARVIS's own spoken fragments. A custom Silero barge-in gate also falsely admitted residual assistant speech.

Those layers are not part of the production conversation architecture.

### Accepted LiveKit MediaDevices path

```text
Pocket3 microphone @ 48 kHz mono
        ↓
rtc.MediaDevices.open_input()
WebRTC AEC + NS + HPF + AGC
        ↓
JARVIS wake / AgentSession / Gemini Live
        ↓
rtc.MediaDevices.open_output()
(shared MediaDevices/APM reverse render reference)
        ↓
48 kHz physical output
        ↓
NVIDIA HDMI → 24'TV speakers
```

Key requirements:

- capture and render use the **same** `rtc.MediaDevices` instance;
- conversation input is 48 kHz mono;
- physical conversation output must accept 48 kHz;
- the current accepted render endpoint is NVIDIA HDMI `24'TV`;
- a 44.1-kHz-only Bluetooth A2DP endpoint fails closed;
- `JARVIS_AUDIO_OUTPUT_DEVICE` selects the canonical conversation render endpoint;
- `JARVIS_AUDIO_OUTPUT_WASAPI_DEVICE` is not used for production conversation playback.

Real acceptance proved both required behaviors:

```text
JARVIS speaking + user silent
→ JARVIS completes without self-trigger

JARVIS speaking + real user interruption
→ real barge-in interrupts correctly
```

Implementation boundary:

- `src/jarvis/voice/media_devices_audio.py`
- `src/jarvis/voice/production_runtime.py`
- `jarvis-voice = jarvis.voice.production_runtime:main`
- `tests/test_media_devices_audio.py`

Decision: `docs/decisions/ADR-011_LIVEKIT_MEDIADEVICES_48K_FULL_DUPLEX.md`.

---

## Independent synchronized sensor evidence path — CURRENT REPLACEMENT BOUNDARY

Conversation audio and Step-3 synchronized sensor evidence are now separate responsibilities:

```text
                         POCKET3
                            │
             ┌──────────────┴──────────────┐
             │                             │
      Conversation path              Evidence path
             │                             │
 LiveKit MediaDevices              GStreamer paired raw A/V
 AEC + NS + HPF + AGC             synchronized sensor capture
             │                             │
 Gemini Live / wake                  ├── video → Vision
             │                        └── raw audio → LR-ASD
 NVIDIA 48 kHz → TV
```

The GStreamer graph no longer owns production conversation playback or conversation AEC in the production builder.

### Integration gate still pending

Before deleting historical paired-conversation code, the real machine must prove that LiveKit MediaDevices and GStreamer raw sensor capture can coexist on the Pocket3 endpoint without device contention or timing regression.

Until that acceptance passes, this separation is the **implemented replacement boundary with one remaining integration gate**.

---

## Next major architecture slice — 3B.11 active-speaker / actor corroboration

Primary benchmark provider: **LR-ASD**. First robustness challenger: **C3ASD**.

Target:

```text
fresh LIVE_OWNER_CANDIDATE
        +
exact visual track/head sequence
        +
synchronized current speech evidence
        ↓
ActiveSpeakerProvider
        ↓
ACTIVE_OWNER_SPEAKER
OTHER_OR_OFFCAMERA
AMBIGUOUS
INSUFFICIENT
```

`ACTIVE_OWNER_SPEAKER` is actor-corroboration evidence, not execution authority.

Only after real-machine acceptance may it unlock **session-only CAM++ prototype admission** for the same actor/turn.

Required acceptance conditions include owner speech, owner-visible-but-silent with TV/other speech, off-camera speech, replay/playback, overlap, temporary visual loss and insufficient windows.

Research: `docs/research/STEP_3B11_ACTIVE_SPEAKER_CORROBORATION_RESEARCH.md`.

---

## What is intentionally NOT yet accepted

The following are not accepted production trust semantics yet:

- automatic T2 derivation from current face/liveness evidence;
- authoritative OWNER-vs-UNKNOWN face threshold based on live non-owner separation;
- speaker threshold promotion;
- persistent OWNER voice template;
- active-speaker evidence as authoritative until 3B.11 real-machine acceptance;
- attention/intent-to-engage implementation;
- depth/IR/ToF liveness hardware.

---

## Documentation as architecture control

Whenever an accepted runtime boundary changes:

1. `CURRENT_ARCHITECTURE.md` is updated in the same development slice;
2. `CURRENT_PLAN.md` is updated with the resulting state and next action;
3. significant choices are captured in an ADR;
4. real-machine evidence is recorded under `docs/research/`;
5. superseded production paths are marked explicitly and removed after replacement acceptance.

Documentation is part of the acceptance gate, not a later cleanup activity.
