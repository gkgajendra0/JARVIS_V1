# JARVIS V1 Current Plan

## Active Step

**Step 3 — Identity, Graduated Trust, Authority, and Observability Foundation**

## Current Stage

**PHASE 3A COMPLETE + MERGED — PHASE 3B ACTIVE — 3B.8 RUNTIME OWNER + LIVENESS BINDING HUMAN-ACCEPTED — 3B.9 ATTENTION DEFERRED UNTIL FIXED WEBCAM — 3B.10 SPEAKER RESEARCH + REAL-MACHINE BAKE-OFF COMPLETE — 3B.10A PASSIVE TURN/OWNER-CONTEXT BRIDGE HUMAN-ACCEPTED — 3B.11 ACTIVE-SPEAKER CORROBORATION NEXT**

Step 0, Step 1, Step 2, Step 2.5, and Step 3A are complete. Phase 3A was real-machine accepted, reconciled, and merged through protected `main`.

Phase 3B continues on draft PR #10 and remains deliberately unmerged until the remaining identity/trust slices are integrated, real-machine accepted, reconciled, and ready for protected-main review.

## Accepted Phase 3B slices

### 3B.1 — Secure OWNER profile/storage — ACCEPTED

- exactly one persistent `OWNER` profile;
- unknown subjects remain ephemeral;
- AES-256-GCM encrypted template envelope;
- random per-profile DEK protected by user-scoped Windows DPAPI;
- SQLite persistence;
- exact candidate template commitment in the immutable authorization proposal;
- Windows Hello-gated create/replace/delete;
- no raw biometric payload in policy/audit.

### 3B.2/3 — Face model asset/runtime boundary — ACCEPTED

- OpenCV 5.0.0 runtime;
- pinned YuNet `face_detection_yunet_2026may.onnx`;
- pinned SFace `face_recognition_sface_2021dec.onnx`;
- exact size/SHA integrity verification;
- external model cache;
- fail closed on asset drift/tampering;
- SFace training-weight provenance remains a future commercial-distribution review item.

### 3B.4 — Pocket-3 live face pipeline — ACCEPTED

Accepted real-machine path:

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

The live benchmark established that identity must use temporal evidence rather than one-frame cosine decisions.

### 3B.5A — OWNER positive calibration — ACCEPTED BASELINE

A positive-only OWNER run established real Pocket-3 same-owner score behavior. It did not define an absolute OWNER-vs-UNKNOWN threshold.

Operational subject semantics remain:

- `OWNER` — sufficiently proven enrolled owner;
- `UNKNOWN` — not sufficiently proven owner;
- `AMBIGUOUS` — current evidence cannot safely decide.

No persistent non-owner biometric profiles are created.

### 3B.6 — Real OWNER enrollment — ACCEPTED

Real OWNER enrollment produced a deterministic encrypted multi-prototype SFace template:

- format `sface-prototype-set-v1`;
- 8 bounded prototypes;
- deterministic centroid + farthest-inlier selection;
- exact payload commitment before Windows Hello;
- encrypted DPAPI/AES-GCM storage;
- no raw frames or aligned faces persisted.

Face enrollment itself does not grant T2.

### 3B.7A — Active liveness fallback — ACCEPTED

MediaPipe Face Landmarker randomized challenge:

- blink;
- smile;
- open mouth;
- randomized order;
- neutral → action → neutral transitions;
- same Windows session + same visual track binding;
- bounded timeout and fail-closed behavior;
- short-lived `FACE_LIVENESS` evidence;
- no frame/landmark/blendshape-vector persistence.

A real Pocket-3 run completed all three actions and passed. This primitive is retained as a fallback, not the normal everyday UX.

### 3B.7B — Passive RGB liveness — HUMAN-ACCEPTED

Research benchmarked two mature PAD candidates on the real Pocket 3:

- OpenVINO `anti-spoof-mn3` — **rejected** for this integration because genuine-live OWNER remained near-zero even after a bounded reference-style crop correction;
- MiniFASNet V1SE + V2 ensemble — **selected** for the current RGB prototype behind JARVIS-owned temporal fusion.

Real MiniFAS evidence included two genuine-live baselines, a static OWNER photo on another phone, a prerecorded moving OWNER video replay, and normal-use genuine-live robustness.

Critical temporal separation:

- normal-use live 15-frame minimum: `0.9855`;
- phone-photo 15-frame maximum: `0.2229`;
- phone-video 15-frame maximum: `0.0000` at reported precision.

Single-frame decisions are explicitly rejected because a phone-photo frame reached `0.8838` apparent-real probability.

Accepted current prototype rule:

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

A gap > `0.50 s` resets the window. Passive evidence TTL is initially `2.0 s`. `UNCERTAIN` may invoke the accepted active challenge. `SPOOF` fails closed.

This selection is recorded in `docs/decisions/ADR-008_STEP_3_PASSIVE_RGB_LIVENESS.md`.

### 3B.8 — Runtime OWNER identity + liveness binding — HUMAN-ACCEPTED

Accepted integrated evidence path:

```text
active/unlocked Windows session
        +
selected stable person track
        ↓
associated head/face
        ├── YuNet + SFace
        │       ↓
        │ encrypted OWNER 8-prototype set
        │       ↓
        │ 15-frame temporal OWNER identity
        │
        └── MiniFAS V1SE + V2
                ↓
           15-frame passive liveness
                ↓
        same session + same track
                ↓
LIVE_OWNER_CANDIDATE / ACTIVE_CHALLENGE_ELIGIBLE /
SPOOFED_OWNER_PRESENTATION / UNKNOWN / AMBIGUOUS / INSUFFICIENT
```

Accepted 3B.8 properties:

- encrypted OWNER template is loaded through the accepted DPAPI/AES-GCM identity-store boundary;
- exact template/model compatibility is required and mismatches fail closed;
- SFace identity and MiniFAS liveness are fused only when bound to the same Windows session and visual track;
- temporal identity uses a provisional evidence-only band: `>=0.65 OWNER_CANDIDATE`, `<=0.35 UNKNOWN`, middle `AMBIGUOUS`, with 15 fresh samples required;
- the identity threshold is explicitly **not authoritative** because a consenting live non-owner calibration set is still unavailable;
- identity/liveness observation gaps > `0.50 s` reset temporal state;
- selected-target loss immediately discards both identity and liveness windows and stops evidence collection;
- Windows lock/session transition invalidates the evidence session and fails closed;
- `OWNER_CANDIDATE + LIVE` produces only `LIVE_OWNER_CANDIDATE` evidence;
- `OWNER_CANDIDATE + UNCERTAIN` is challenge-eligible rather than silently upgraded;
- `OWNER_CANDIDATE + SPOOF` fails closed as `SPOOFED_OWNER_PRESENTATION`;
- no raw frames, aligned faces, embeddings, PAD tensors, or PAD outputs are persisted;
- `face_evidence_grants_T2 = False` remains enforced.

Real Pocket-3 evidence:

- 300 integrated live OWNER observations;
- temporal OWNER similarity median `0.7982`;
- MiniFAS live median `0.9998`;
- `272` observations reached `LIVE_OWNER_CANDIDATE` after temporal warm-up/reset periods;
- real WTS Windows-lock test produced `SESSION_INVALIDATED_FAIL_CLOSED`.

Acceptance evidence: `docs/research/STEP_3B8_OWNER_LIVENESS_ACCEPTANCE_RESULTS.md`.

## Deferred Phase 3B.9 — Attention / intent-to-engage evidence

Attention implementation is deliberately deferred until JARVIS has a fixed monitor-mounted webcam or stronger accepted attention/eye sensor.

Reason:

- DJI Pocket 3 is a movable gimbal camera;
- camera-relative eye/head geometry changes whenever its placement or gimbal orientation changes;
- repeated camera-to-screen calibration would create unacceptable everyday friction;
- looking at a monitor is not itself proof that the OWNER is engaging with JARVIS.

ADR-007 remains the architectural boundary, but its implementation is hardware-dependent and non-blocking for unrelated Step-3 work.

Architecture correction:

```text
T2 CORROBORATED_OWNER
= corroborated OWNER identity/presence context

OWNER_ATTENTIVE
= separate interaction predicate layered on T2 when an accepted attention provider exists
```

Until attention is implemented, JARVIS must not invent `OWNER_ATTENTIVE`. A policy that genuinely requires it must fail closed or escalate to stronger explicit verification.

## 3B.10 — Speaker identity model selection — RESEARCH + BAKE-OFF COMPLETE

Mature speaker technology was evaluated rather than rebuilding a speaker frontend from scratch. The current deployment runtime is `sherpa-onnx==1.13.6`.

Real JARVIS bake-off candidates:

- 3D-Speaker CAM++ zh/en advanced;
- 3D-Speaker ERes2NetV2;
- NVIDIA TitaNet-Large.

Current disposition:

- **CAM++ — provisional shadow speaker-embedding provider**;
- **ERes2NetV2 — retained fallback challenger**;
- **TitaNet-Large — removed from the first deployment path**.

Real ~3-second embedding latency on the canonical JARVIS PCM route:

- CAM++: ~`54 ms` median;
- ERes2NetV2: ~`319 ms` median;
- TitaNet-Large: ~`143 ms` median.

Observed CAM++ healthy OWNER behavior:

- Hinglish 3 s: `0.7354–0.7579`;
- far-field 3 s: `0.6287–0.6435`;
- 2 s speech: `0.7087–0.7611`;
- TV speech 3 s: `0.1847–0.3943`.

The bake-off also proved that near-silent/too-short audio can still produce embeddings. Therefore bad quality must become `INSUFFICIENT`, never `UNKNOWN_SPEAKER`.

Speaker-model core now exists behind a JARVIS-owned boundary with:

- exact CAM++ model size/SHA verification;
- exact sherpa frontend instead of hand-written MFCC/fbank code;
- conservative duration/RMS/clipping quality gate;
- bounded multi-prototype matching rather than one averaged centroid;
- memory-only shadow prototype storage;
- all speaker evidence forced to `INSUFFICIENT` while calibration is incomplete;
- no deployment similarity threshold;
- no T2/T3 or action authority effect.

Acceptance evidence and model decision:
`docs/research/STEP_3B10_SPEAKER_BAKEOFF_RESULTS.md`.

## 3B.10A — Passive normal-turn + OWNER-context bridge — HUMAN-ACCEPTED

The normal voice runtime contains the accepted safe plumbing needed for passive speaker work without a second microphone or camera.

Implemented boundary:

```text
Pocket-3 canonical frame + VisionSnapshot pair
        ↓
accepted Step-3B.8 SFace + MiniFAS temporal logic
        ↓
thread-safe short-lived OWNER context

canonical LiveKit session PCM
        +
LiveKit user speaking/listening lifecycle
        ↓
bounded memory-only user-turn capture
        ↓
speaker quality gate
        ↓
shadow diagnostic log
```

3B.10A properties:

- vision identity evaluates an exact camera frame paired with the exact `VisionSnapshot`; stale snapshot/frame coordinate mixing is not allowed;
- the existing VisionService owns the camera and publishes exact-frame pairs to a bounded evidence worker; no second camera is opened;
- the existing `LocalAudioRuntime` remains the only physical microphone owner;
- only audio frames successfully accepted by the LiveKit session queue are observed by shadow capture;
- a bounded `0.20 s` rolling pre-roll protects the beginning of a user turn;
- turn audio remains memory-only and is cleared after inspection/session end;
- embedding work is not performed in the realtime audio callback;
- the feature is opt-in through `JARVIS_SPEAKER_SHADOW_ENABLED` and requires integrated vision;
- update-approval Yes/No sessions are intentionally excluded from passive voice learning;
- normal-turn diagnostics report quality and whether a fresh `LIVE_OWNER_CANDIDATE` context existed;
- `active_speaker_confirmed=False` and `prototype_admission=False` are deliberately enforced in this slice;
- no new speaker profile, voiceprint, threshold, or authority evidence is promoted by 3B.10A.

Real-machine acceptance evidence on the integrated Pocket-3 + canonical voice runtime:

- integrated vision started and maintained a live person/head track during normal realtime conversation;
- stable audio selectors resolved the current Windows WASAPI endpoints dynamically (`Voicemeeter Out B1` input and `Tribit XSound Plus 2` output) without relying on stored numeric indices;
- physical output opened successfully and startup greeting/conversation playback completed;
- normal realtime conversation ran with the speaker-shadow bridge active;
- healthy turns were accepted at `14.29 s / -36.5 dBFS` and `12.18 s / -30.8 dBFS` with `live_owner_context=True`;
- another healthy `9.42 s / -42.7 dBFS` turn remained quality-accepted while `live_owner_context=False`, demonstrating that temporary OWNER-context loss does not fabricate corroboration;
- a `0.20 s` fragment was correctly rejected as `speaker_segment_too_short`;
- a `15.00 s / -48.1 dBFS` segment was correctly rejected as `speaker_segment_below_rms_floor`;
- every observed turn remained `active_speaker_confirmed=False` and `prototype_admission=False`, as required before 3B.11;
- no speaker threshold, persistent voiceprint, T2 upgrade, or action authority was introduced by the acceptance run.

### Safety correction discovered during integration

A live OWNER face being present does **not** prove that the current room speech came from that face.

Unsafe rule rejected:

```text
LIVE_OWNER_CANDIDATE visible
        +
any microphone speech
        ↓
OWNER voice prototype
```

That rule could poison the OWNER voice bank with TV, phone playback, a nearby/off-camera person, or overlapping speech while the OWNER is visible.

Therefore fresh face+liveness context is **necessary but not sufficient** for passive speaker prototype admission.

## 3B.11 — Active-speaker / actor corroboration — NEXT

Research has been refreshed before implementation. The current primary first benchmark candidate is **LR-ASD (IJCV 2025)** because it provides a lightweight audio-visual active-speaker model suitable for continuous local use. **C3ASD (ECCV 2026)** is the first robustness challenger. LASER and TalkNet remain second-wave/reference options.

Research record:
`docs/research/STEP_3B11_ACTIVE_SPEAKER_CORROBORATION_RESEARCH.md`.

Required target boundary:

```text
fresh LIVE_OWNER_CANDIDATE
        +
exact visual track/head sequence
        +
canonical user-turn PCM
        ↓
active-speaker provider
        ↓
ACTIVE_OWNER_SPEAKER / OTHER_OR_OFFCAMERA /
AMBIGUOUS / INSUFFICIENT
        ↓
ACTIVE_OWNER_SPEAKER only
        ↓
CAM++ session-shadow prototype admission
```

No upstream active-speaker threshold is accepted from leaderboard results. The provider must first pass the real Pocket-3 + canonical JARVIS audio route with owner speech, off-camera/TV speech, playback, multiple visible people, overlap, and temporary head/face loss.

## Non-negotiable Step-3 invariants

- Identity evidence is not execution permission.
- Face recognition, speaker recognition, liveness, active-speaker detection, attention, presence, Windows session state, wake word, or model confidence never directly authorize a consequential action.
- Weak signals never become strong trust by adding generic confidence scores.
- Windows Hello/FIDO2 remains the strong-verification path for consequential authority.
- Raw audio/video, face crops, embeddings, secrets, or sensitive payloads are not retained merely because they are available.
- Provider/device/model implementations remain replaceable behind JARVIS-owned contracts.
- Passive RGB liveness is not equivalent to depth/IR liveness.
- `SPOOF` fails closed.
- `UNCERTAIN` may request stronger evidence but may not silently upgrade trust.

## Work after active-speaker acceptance

After active-speaker corroboration is real-machine accepted:

- permit **session-only** CAM++ prototype admission only when fresh OWNER+liveness and active-speaker evidence agree on the same actor/turn;
- collect speaker similarity distributions passively during ordinary use instead of repeated scripted recording ceremonies;
- decide whether CAM++ separation is sufficient or ERes2NetV2 materially resolves remaining real ambiguity;
- perform only the minimum targeted direct-non-owner / OWNER-replay / overlap acceptance checks still required before threshold promotion;
- define a persistent encrypted voice-template format only behind strongly verified OWNER enrollment/update semantics;
- resolve the authoritative OWNER-vs-UNKNOWN face threshold when a consenting live non-owner calibration subject is available, or explicitly redesign the T2 predicate so provisional face evidence cannot be mistaken for authoritative identity;
- implement deterministic T2 `CORROBORATED_OWNER` composition from the final accepted evidence predicate;
- broader negative/attack coverage and expiry/cross-session/cross-actor testing;
- final Phase-3 documentation reconciliation and protected-main review/merge;
- revisit deferred attention later when fixed monitor-mounted hardware is available.

## Accepted ADRs relevant to Step 3

- `docs/decisions/ADR-006_STEP_3_IDENTITY_TRUST_AUTHORITY_GOVERNANCE.md`
- `docs/decisions/ADR-007_STEP_3_ATTENTION_INTENT_EVIDENCE.md` — architecture accepted, implementation deferred;
- `docs/decisions/ADR-008_STEP_3_PASSIVE_RGB_LIVENESS.md`

## Immediate Next Action

Implement and benchmark **3B.11 active-speaker corroboration**, starting with **LR-ASD** on the exact Pocket-3 + canonical JARVIS audio path and retaining **C3ASD** as the first robustness challenger. Do not enable speaker prototype admission until active-speaker attribution is accepted. Attention remains deferred until suitable fixed camera hardware exists.
