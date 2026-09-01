# JARVIS V1 Current Plan

## Active Step

**Step 3 — Identity, Graduated Trust, Authority, and Observability Foundation**

## Current Stage

**PHASE 3A COMPLETE + MERGED — PHASE 3B ACTIVE — 3B.8 OWNER + LIVENESS HUMAN-ACCEPTED — 3B.9 ATTENTION DEFERRED — 3B.10/3B.10A SPEAKER FOUNDATION HUMAN-ACCEPTED — FULL-DUPLEX CONVERSATION AUDIO SOLUTION PROVEN + IMPLEMENTED — INTEGRATED AUDIO/SENSOR COEXISTENCE ACCEPTANCE NEXT — THEN 3B.11 ACTIVE-SPEAKER ACCEPTANCE**

Step 0, Step 1, Step 2, Step 2.5, and Step 3A are complete. Phase 3A was real-machine accepted, reconciled, and merged through protected `main`.

Phase 3B continues on `feature/step-3b11-sensor-av-foundation` / draft PR #10 and remains deliberately unmerged until the remaining identity/trust slices are integrated, real-machine accepted, reconciled, and ready for protected-main review.

This file is the operational source of truth for **what is done, what is accepted, and what happens next**. Significant architecture decisions must also have an ADR; detailed benchmark evidence belongs in `docs/research/`.

---

## Accepted Phase 3B foundation

### 3B.1 — Secure OWNER profile/storage — ACCEPTED

- exactly one persistent `OWNER` profile;
- unknown subjects remain ephemeral;
- AES-256-GCM encrypted template envelope;
- random per-profile DEK protected by user-scoped Windows DPAPI;
- SQLite persistence;
- exact candidate template commitment in immutable authorization proposals;
- Windows Hello-gated create/replace/delete;
- no raw biometric payload in policy/audit.

### 3B.2/3 — Face model asset/runtime boundary — ACCEPTED

- OpenCV 5.0.0 runtime;
- pinned YuNet `face_detection_yunet_2026may.onnx`;
- pinned SFace `face_recognition_sface_2021dec.onnx`;
- exact size/SHA integrity verification;
- external model cache;
- fail closed on asset drift/tampering;
- SFace released-weight provenance remains a future commercial-distribution review item.

### 3B.4 — Pocket-3 live face pipeline — ACCEPTED

```text
Pocket 3
    ↓
RF-DETR person detection
    ↓
persistent visual track
    ↓
selected track
    ↓
BlazeFace head association
    ↓
head crop
    ↓
YuNet → SFace
```

Identity decisions use temporal evidence; one-frame cosine decisions are not accepted.

### 3B.5A — OWNER positive calibration — ACCEPTED BASELINE

Positive-only OWNER calibration established real Pocket-3 same-owner behavior but did **not** establish an authoritative OWNER-vs-UNKNOWN threshold.

Operational subject semantics:

- `OWNER` — sufficiently proven enrolled owner;
- `UNKNOWN` — not sufficiently proven owner;
- `AMBIGUOUS` — evidence cannot safely decide.

No persistent non-owner biometric profile is created.

### 3B.6 — Real OWNER enrollment — ACCEPTED

- format `sface-prototype-set-v1`;
- 8 bounded normalized prototypes;
- deterministic centroid + farthest-inlier selection;
- exact payload commitment before Windows Hello;
- encrypted DPAPI/AES-GCM storage;
- no raw frames or aligned faces persisted.

Face enrollment itself does not grant T2.

### 3B.7A — Active facial liveness fallback — ACCEPTED

MediaPipe Face Landmarker randomized challenge:

- blink;
- smile;
- open mouth;
- randomized order;
- neutral → action → neutral transitions;
- same Windows session + same visual track;
- bounded timeout/fail-closed behavior;
- short-lived `FACE_LIVENESS` evidence;
- no frame/landmark/blendshape persistence.

Retained as fallback rather than normal everyday UX.

### 3B.7B — Passive RGB liveness — HUMAN-ACCEPTED

Selected provider: **MiniFASNet V1SE + V2 ensemble** behind JARVIS-owned temporal fusion.

OpenVINO `anti-spoof-mn3` was rejected for the current Pocket-3 integration.

Accepted prototype rule:

```text
15 fresh observations
same Windows session
same visual track
same MiniFAS provider
        ↓
median >= 0.95  → LIVE
median <= 0.50  → SPOOF
otherwise       → UNCERTAIN
<15 samples     → INSUFFICIENT
```

Gap > `0.50 s` resets the window. Passive evidence TTL starts at `2.0 s`. `SPOOF` fails closed. `UNCERTAIN` may invoke the accepted active challenge.

Decision: `docs/decisions/ADR-008_STEP_3_PASSIVE_RGB_LIVENESS.md`  
Evidence: detailed 3B.7B research/acceptance records under `docs/research/`.

### 3B.8 — Runtime OWNER identity + liveness binding — HUMAN-ACCEPTED

```text
active/unlocked Windows session
        +
selected stable visual track
        ↓
associated head/face
        ├── YuNet + SFace
        │       ↓
        │ encrypted OWNER prototype set
        │       ↓
        │ temporal OWNER identity
        │
        └── MiniFAS V1SE + V2
                ↓
           temporal liveness
                ↓
        same session + same track
                ↓
LIVE_OWNER_CANDIDATE / ACTIVE_CHALLENGE_ELIGIBLE /
SPOOFED_OWNER_PRESENTATION / UNKNOWN / AMBIGUOUS / INSUFFICIENT
```

Current provisional identity band remains evidence-only:

```text
>= 0.65 → OWNER_CANDIDATE
<= 0.35 → UNKNOWN
middle  → AMBIGUOUS
```

Fifteen fresh observations are required. This band is **not authoritative** because a consenting live non-owner calibration set is still unavailable.

Important invariants:

- OWNER identity and liveness combine only on the same Windows session + same visual track;
- target loss/session change invalidates the evidence;
- `OWNER_CANDIDATE + LIVE` creates `LIVE_OWNER_CANDIDATE` only;
- face/liveness evidence does not grant T2;
- raw frames, aligned faces, embeddings, PAD tensors and PAD outputs are not persisted.

Evidence: `docs/research/STEP_3B8_OWNER_LIVENESS_ACCEPTANCE_RESULTS.md`.

---

## Deferred 3B.9 — Attention / intent-to-engage

Implementation remains deferred until a fixed monitor-mounted webcam or stronger accepted attention/eye sensor is available.

The movable DJI Pocket 3 is not a stable monitor-relative gaze sensor. JARVIS therefore must not invent `OWNER_ATTENTIVE` from visibility, face match, liveness, wake word or conversation state.

```text
T2 CORROBORATED_OWNER
= corroborated OWNER identity/presence context

OWNER_ATTENTIVE
= separate interaction predicate layered on T2 when an accepted attention provider exists
```

Attention does **not** block completion of the rest of Step 3.

Decision: `docs/decisions/ADR-007_STEP_3_ATTENTION_INTENT_EVIDENCE.md`.

---

## 3B.10 — Speaker identity model selection — RESEARCH + BAKE-OFF COMPLETE

Mature speaker technology was benchmarked instead of rebuilding a speaker frontend.

Current disposition:

- **CAM++ — provisional shadow speaker-embedding provider**;
- **ERes2NetV2 — retained fallback challenger**;
- TitaNet-Large removed from the first deployment path.

Current speaker-model boundary includes:

- exact CAM++ model size/SHA verification;
- sherpa-onnx frontend rather than hand-written MFCC/fbank;
- duration/RMS/clipping quality gate;
- bounded multi-prototype matching;
- memory-only shadow prototype storage;
- no deployment threshold while calibration is incomplete;
- no T2/T3/action-authority effect.

Evidence: `docs/research/STEP_3B10_SPEAKER_BAKEOFF_RESULTS.md`.

## 3B.10A — Passive normal-turn + OWNER-context bridge — HUMAN-ACCEPTED

Accepted safe plumbing:

```text
Pocket-3 frame + exact VisionSnapshot
        ↓
3B.8 OWNER + liveness temporal logic
        ↓
short-lived OWNER context

canonical LiveKit user PCM
        +
user speaking/listening lifecycle
        ↓
bounded memory-only turn capture
        ↓
speaker quality gate
        ↓
shadow diagnostics
```

A live OWNER face being visible is **necessary but not sufficient** to attribute microphone speech to that OWNER. TV audio, phone playback, another person, overlap or off-camera speech must not poison the OWNER voice bank.

Therefore passive voice prototype admission remains disabled until active-speaker actor corroboration is accepted.

---

## Conversation audio correction — PROVEN + IMPLEMENTED, FINAL INTEGRATION GATE PENDING

### Problem discovered

The earlier paired GStreamer + Tribit Bluetooth conversation path passed isolated DSP measurements but failed real Gemini Live acceptance. JARVIS repeatedly heard fragments of its own speech as new user turns. A custom local Silero barge-in gate also falsely admitted residual assistant speech.

Those approaches are not production conversation architecture.

### Accepted solution

Use the current LiveKit `rtc.MediaDevices` full-duplex helper end to end:

```text
Pocket 3 microphone @ 48 kHz
        ↓
LiveKit MediaDevices
WebRTC AEC + NS + HPF + AGC
        ↓
Gemini Live / AgentSession
        ↓
LiveKit MediaDevices OutputPlayer @ 48 kHz
        ↓
NVIDIA HDMI
        ↓
24'TV speakers
```

The exact Pocket3 + NVIDIA/TV 48-kHz path passed real human acceptance:

- JARVIS completed a long answer while the user stayed silent without self-interruption;
- deliberate real human barge-in correctly interrupted JARVIS;
- the Bluetooth control run produced fake user transcripts from JARVIS speech while the TV/48-kHz path did not.

Production implementation now exists in:

- `src/jarvis/voice/media_devices_audio.py`;
- `src/jarvis/voice/production_runtime.py`;
- `jarvis-voice = jarvis.voice.production_runtime:main`;
- `tests/test_media_devices_audio.py`.

`JARVIS_AUDIO_OUTPUT_DEVICE` is the conversation render selector. The production path fails closed if the selected render endpoint cannot accept 48 kHz.

Decision: `docs/decisions/ADR-011_LIVEKIT_MEDIADEVICES_48K_FULL_DUPLEX.md`.

ADR-011 supersedes ADR-010 **for conversation audio**.

### Independent Step-3 raw sensor path

GStreamer remains useful, but only for synchronized raw perception evidence:

```text
Pocket 3 paired raw A/V
        ↓
GStreamer synchronized sensor capture
        ├── video → Vision / exact visual track sequence
        └── raw audio → LR-ASD active-speaker diagnostics
```

It no longer owns production conversation playback/AEC.

### Immediate integration gate — NEXT

Before deleting the historical paired-conversation/custom-barge-in code, run the real production `jarvis-voice` path with Step-3 active-speaker sensing enabled and prove that Windows permits these two consumers to coexist:

```text
Pocket 3 microphone
   ├── LiveKit MediaDevices → conversation AEC/input
   └── GStreamer raw paired A/V → synchronized identity evidence
```

Acceptance requires:

1. `jarvis-voice` starts successfully with integrated vision/active-speaker shadow enabled;
2. Pocket3 conversation mic remains healthy;
3. TV/NVIDIA 48-kHz playback remains healthy;
4. no self-echo while JARVIS speaks;
5. real barge-in still works;
6. raw paired GStreamer audio/video remains available for LR-ASD;
7. no competing-device failure or timing regression.

If this passes, delete the obsolete paired GStreamer conversation AEC and custom Silero barge-in modules/tests rather than maintaining two conversation architectures.

---

## 3B.11 — Active-speaker / actor corroboration — NEXT MAJOR SLICE

Research is already complete enough to proceed. Primary first benchmark: **LR-ASD (IJCV 2025)**. First robustness challenger: **C3ASD (ECCV 2026)**. LASER/TalkNet remain second-wave references.

Research: `docs/research/STEP_3B11_ACTIVE_SPEAKER_CORROBORATION_RESEARCH.md`.

Target boundary:

```text
fresh LIVE_OWNER_CANDIDATE
        +
exact visual track/head sequence
        +
canonical user-turn PCM / synchronized raw evidence
        ↓
active-speaker provider
        ↓
ACTIVE_OWNER_SPEAKER / OTHER_OR_OFFCAMERA /
AMBIGUOUS / INSUFFICIENT
```

Only accepted `ACTIVE_OWNER_SPEAKER` evidence may permit **session-only** CAM++ prototype admission.

No threshold is accepted from leaderboard/default values. LR-ASD must first pass real Pocket3 conditions including:

- OWNER speaking on-camera;
- OWNER visible but silent while TV/other audio is present;
- off-camera speaker;
- playback/replay;
- multiple visible people when available;
- overlapping speech;
- temporary head/face loss;
- insufficient/short/poor-quality windows.

Active-speaker evidence remains diagnostic and non-authoritative until human acceptance.

---

## Work after 3B.11 acceptance

1. Permit **session-only** CAM++ prototype admission only when fresh OWNER+liveness and active-speaker evidence agree on the same actor/turn.
2. Collect speaker similarity distributions passively during ordinary use.
3. Decide whether CAM++ separation is sufficient or ERes2NetV2 materially improves real ambiguity.
4. Perform minimum targeted direct-non-owner / OWNER-replay / overlap acceptance before speaker-threshold promotion.
5. Define persistent encrypted voice-template format only behind strongly verified OWNER enrollment/update semantics.
6. Resolve the authoritative OWNER-vs-UNKNOWN face threshold when consenting live non-owner calibration becomes available, or redesign T2 so provisional face evidence can never be mistaken for authoritative identity.
7. Implement deterministic T2 `CORROBORATED_OWNER` composition from the final accepted evidence predicate.
8. Run broader negative/attack coverage: replay, stale evidence, expiry, cross-session, cross-track, cross-actor, overlap, policy failure and degraded-mode behavior.
9. Remove superseded experimental/dead audio code once replacement acceptance is complete.
10. Reconcile `CURRENT_PLAN.md`, `CURRENT_ARCHITECTURE.md`, ADRs, research results, quality gates and roadmap.
11. Protected-main review and merge of Phase 3B.
12. Revisit attention later when fixed monitor-mounted hardware exists.

---

## Non-negotiable Step-3 invariants

- Identity evidence is not execution permission.
- Face recognition, speaker recognition, liveness, active-speaker detection, attention, presence, Windows session state, wake word or model confidence never directly authorizes a consequential action.
- Weak signals do not become strong trust by adding generic confidence scores.
- Windows Hello/FIDO2 remains the strong-verification path for consequential authority.
- Raw audio/video, face crops, embeddings, secrets or sensitive payloads are not retained merely because they are available.
- Provider/device/model implementations remain replaceable behind JARVIS-owned contracts.
- Passive RGB liveness is not equivalent to depth/IR liveness.
- `SPOOF` fails closed.
- `UNCERTAIN` may request stronger evidence but may not silently upgrade trust.
- T2 remains disabled until its final evidence predicate is accepted.

---

## Documentation discipline

For Step 3 and later:

- `CURRENT_PLAN.md` must be updated whenever the active slice, acceptance state or immediate next action changes;
- `CURRENT_ARCHITECTURE.md` must be updated whenever production architecture is accepted or superseded;
- significant technology/architecture choices require an ADR in `docs/decisions/`;
- real-machine benchmark/acceptance evidence belongs in `docs/research/`;
- superseded experiments must be marked clearly and eventually removed from production code;
- documentation reconciliation is part of acceptance, not an optional cleanup task.

## Immediate Next Action

**Run the integrated production audio/sensor coexistence acceptance on the real PC.**

If that passes:

1. record the acceptance result;
2. remove obsolete paired-conversation/custom-Silero code;
3. update this plan/architecture again;
4. proceed directly to **3B.11 LR-ASD real-machine active-speaker acceptance**.
