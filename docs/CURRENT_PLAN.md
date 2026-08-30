# JARVIS V1 Current Plan

## Active Step

**Step 3 — Identity, Graduated Trust, Authority, and Observability Foundation**

## Current Stage

**PHASE 3A COMPLETE + MERGED — PHASE 3B ACTIVE — 3B.7B PASSIVE RGB LIVENESS HUMAN-ACCEPTED — 3B.8 RUNTIME OWNER FACE + LIVENESS BINDING NEXT**

Step 0, Step 1, Step 2, Step 2.5, and Step 3A are complete. Phase 3A was real-machine accepted, reconciled, and merged through protected `main`.

Phase 3B continues on draft PR #10 and remains deliberately unmerged until the identity/liveness slices are integrated, real-machine accepted, reconciled, and ready for protected-main review.

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

Real MiniFAS evidence included:

- two genuine-live OWNER baselines;
- static OWNER photo on another phone;
- prerecorded moving OWNER video replay on another phone;
- normal-use genuine-live robustness with moderate head turns, near/far movement, blinking, eye movement, and mouth/body movement.

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

## Phase 3B.8 — NEXT: Runtime OWNER identity + liveness binding

The next bounded slice is to produce runtime identity/liveness evidence for the **same stable subject** rather than leaving face recognition and liveness as separate diagnostics.

Target architecture:

```text
expected active Windows session
        +
stable selected/eligible visual track
        ↓
associated head/face
        ├── SFace → encrypted OWNER prototype match
        └── MiniFAS → 15-frame passive liveness
                         ↓
                  LIVE / UNCERTAIN / SPOOF
                         │
             UNCERTAIN ─┴─→ active challenge when required
        ↓
typed fresh evidence bound to same session + same track
```

3B.8 must initially remain **evidence-only**. It must not automatically grant T2 while the integrated identity/liveness behavior is still being validated.

Required 3B.8 acceptance work:

1. load/decrypt the enrolled OWNER face prototype set through the accepted identity store boundary;
2. run SFace on the associated face/head of one stable visual track;
3. aggregate OWNER match evidence temporally rather than trusting one frame;
4. run MiniFAS passive liveness on that same track;
5. preserve explicit `OWNER / UNKNOWN / AMBIGUOUS` semantics;
6. bind all evidence to the exact active Windows session and visual track;
7. invalidate evidence on track loss, session change/lock, expiry, provider/model mismatch, or material observation gaps;
8. invoke active liveness only for `UNCERTAIN` when the trust/risk path actually requires liveness;
9. keep `face_evidence_grants_T2 = False` during integration testing;
10. perform real OWNER, phone-photo, phone-video, track-loss, and session-lock acceptance tests on the integrated path.

## Work after 3B.8

After integrated runtime OWNER+liveness evidence is accepted:

- deterministic T2 corroborated-owner composition;
- attention/intent evidence implementation and acceptance;
- speaker identity/corroboration implementation and acceptance;
- broader negative/attack coverage;
- future depth/IR provider research and hardware integration without changing the authority contract.

## Accepted ADRs relevant to Step 3

- `docs/decisions/ADR-006_STEP_3_IDENTITY_TRUST_AUTHORITY_GOVERNANCE.md`
- `docs/decisions/ADR-007_STEP_3_ATTENTION_INTENT_EVIDENCE.md`
- `docs/decisions/ADR-008_STEP_3_PASSIVE_RGB_LIVENESS.md`

## Immediate Next Action

Implement **3B.8 runtime OWNER face + passive/active liveness binding** on the same stable visual track, keep T2 disabled, then run automated validation followed by real Pocket-3 human acceptance before any trust-composition change.
