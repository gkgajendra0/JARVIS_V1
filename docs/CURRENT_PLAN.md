# JARVIS V1 Current Plan

## Active Step

**Step 3 — Identity, Graduated Trust, Authority, and Observability Foundation**

## Current Stage

**PHASE 3A COMPLETE + MERGED — PHASE 3B ACTIVE — 3B.8 RUNTIME OWNER + LIVENESS BINDING HUMAN-ACCEPTED — 3B.9 ATTENTION DEFERRED UNTIL FIXED WEBCAM — SPEAKER IDENTITY / ACTIVE-SPEAKER CORROBORATION NEXT**

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

## Non-negotiable Step-3 invariants

- Identity evidence is not execution permission.
- Face recognition, speaker recognition, liveness, attention, presence, Windows session state, wake word, or model confidence never directly authorize a consequential action.
- Weak signals never become strong trust by adding generic confidence scores.
- Windows Hello/FIDO2 remains the strong-verification path for consequential authority.
- Raw audio/video, face crops, embeddings, secrets, or sensitive payloads are not retained merely because they are available.
- Provider/device/model implementations remain replaceable behind JARVIS-owned contracts.
- Passive RGB liveness is not equivalent to depth/IR liveness.
- `SPOOF` fails closed.
- `UNCERTAIN` may request stronger evidence but may not silently upgrade trust.

## Next bounded slice — Speaker identity / active-speaker corroboration

The next independent Step-3 slice is speaker identity and active-speaker ambiguity handling for voice-originated protected interaction.

Research must be refreshed before implementation and should evaluate current mature local speaker-verification/diarization technology rather than rebuilding embeddings/classifiers from scratch.

Target boundary:

```text
JARVIS microphone audio
        ↓
voice activity / speech segment
        ↓
replaceable speaker-evidence provider
        ↓
OWNER_SPEAKER_CANDIDATE / UNKNOWN / AMBIGUOUS
        +
active-speaker / actor ambiguity checks
        ↓
typed short-lived speaker evidence
```

Requirements:

1. speaker evidence never creates T2/T3 or action permission by itself;
2. do not treat wake-word detection as speaker identity;
3. do not treat transcription/LLM confidence as speaker identity;
4. TV/speaker playback and JARVIS's own output must not silently become OWNER evidence;
5. multi-person/ambiguous speech must fail closed for protected voice-originated interaction;
6. provider/model boundaries must remain replaceable;
7. raw audio retention is off by default; store only strongly justified encrypted enrollment material/derived templates;
8. benchmark on the real Windows audio route before promoting any threshold;
9. keep T2 disabled during research, implementation, and acceptance.

## Work after speaker identity

After speaker identity/corroboration is researched, implemented, and accepted:

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

Refresh **speaker identity / active-speaker corroboration research**, select the best mature current technology, define the bounded architecture, obtain human approval, then implement and real-machine validate it. Attention remains deferred until suitable fixed camera hardware exists.
