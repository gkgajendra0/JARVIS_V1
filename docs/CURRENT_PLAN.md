# JARVIS V1 Current Plan

## Active Step

**Step 3 — Identity, Graduated Trust, Authority, and Observability Foundation**

## Current Stage

**PHASE 3A COMPLETE + MERGED — PHASE 3B ACTIVE — 3B.1 HUMAN-ACCEPTED, 3B.2/3 MODEL-INTEGRITY/RUNTIME BOUNDARY HUMAN-ACCEPTED, 3B.4 REAL POCKET-3 LIVE BENCHMARK NEXT**

Step 0, Step 1, Step 2, Step 2.5, and Step 3A are complete. Step-3 research, threat/privacy modeling, architecture, governance contracts, and attention/intent amendment are approved. Phase 3A was automated-validated, accepted on real Windows hardware, reconciled, and merged through PR #7 on 2026-08-30.

Phase 3B is proceeding on draft PR #10 in bounded slices:

- **3B.1 secure OWNER profile/storage — HUMAN-ACCEPTED.** Single persistent OWNER, AES-256-GCM envelope encryption, random per-profile DEK, user-scoped Windows DPAPI, SQLite storage, exact template commitment, and Hello-gated create/replace/delete. Real synthetic-template acceptance proved DPAPI reopen, no plaintext in DB/WAL, and clean deletion.
- **3B.2/3 model integrity + non-enrollment runtime — HUMAN-ACCEPTED BOUNDARY.** YuNet/SFace are pinned to immutable OpenCV Zoo assets with exact checksums and an external verified cache. The 3B.3 real-machine run exercised that boundary end-to-end on OpenCV 5 and passed without camera access or biometric persistence. This accepts model integrity/load/runtime viability only, not face-match accuracy or thresholds.
- **3B.4 selected-track live face benchmark — IMPLEMENTED + AUTOMATED-VALIDATED; REAL POCKET-3 RUN NEXT.** The diagnostic reuses the existing Step-2.5 selected person track and `HeadFirstFramingPolicy`, runs YuNet/SFace only on the associated head crop, uses read-only camera capture with a no-op PTZ boundary, and saves no frame, face crop, feature vector, OWNER profile, or biometric template.

Accepted ADRs:

- `docs/decisions/ADR-006_STEP_3_IDENTITY_TRUST_AUTHORITY_GOVERNANCE.md`
- `docs/decisions/ADR-007_STEP_3_ATTENTION_INTENT_EVIDENCE.md`

Relevant research:

- `docs/research/STEP_3_IDENTITY_TRUST_AUTHORITY_RESEARCH.md`
- `docs/research/STEP_3_THREAT_PRIVACY_MODEL.md`
- `docs/research/STEP_3_INDIA_PRIVACY_CONTEXT.md`
- `docs/research/STEP_3_ARCHITECTURE_PROPOSAL.md`
- `docs/research/STEP_3_ATTENTION_INTENT_AMENDMENT.md`
- `docs/research/STEP_3B_FACE_MODEL_MANIFEST_RESEARCH.md`

## Non-negotiable Step-3 invariants

- Identity evidence is not execution permission.
- Face recognition, speaker recognition, liveness, attention, presence, Windows session state, wake word, or model confidence never directly grant consequential authority.
- Face-model reference thresholds and live benchmark cosine values are diagnostics until explicitly calibrated and accepted.
- Weak signals never combine into stronger trust through a generic confidence sum.
- Windows Hello/FIDO2 remains the strong-verification path for consequential authority.
- Raw audio/video, face crops, embeddings, secrets, or sensitive payloads are not retained merely because they are available.
- Provider/device/model implementations remain replaceable behind JARVIS-owned contracts.

## Phase 3A — COMPLETE

Accepted implementation includes immutable/session-bound `ActionProposal`, deterministic risk floors, fail-closed policy, proposal-bound one-time approvals, proposal/session-bound strong proof, `StrongApprovalService`, one-time execution permits with final revalidation, privacy-aware audit, Windows WTS session invalidation, and desktop Windows Hello verification.

Real-machine acceptance proved:

- unlocked WTS state;
- `Win+L` authority invalidation;
- Hello/PIN `VERIFIED`;
- proposal/session-bound STRONG approval;
- R4 allow only after required strong verification;
- one-time permit/approval consumption;
- canceled Hello -> DENY -> no permit -> no weak fallback.

**Permanent rule:** face, speaker, liveness, attention, wake word, and LLM output may provide evidence but never directly authorize an action.

## Phase 3B — ACTIVE

### 3B.1 — Secure OWNER profile/storage — ACCEPTED

Persistent identity is one `OWNER`. Unknown people remain ephemeral. Persistent template payloads use AES-256-GCM with a random per-profile DEK protected by user-scoped Windows DPAPI. OWNER create/replace/delete are strongly verified and session-revalidated. The exact candidate template bytes are SHA-256 committed into the authorization proposal.

### 3B.2/3 — Model integrity + synthetic runtime — ACCEPTED BOUNDARY

Frozen OpenCV Zoo revision:

`47534e27c9851bb1128ccc0102f1145e27f23f98`

- YuNet `face_detection_yunet_2026may.onnx`, SHA-256 `ebafce4e3c118d6554634be5c27ab333b4c047a9a8c3faf1d7cf93101c22f0f0`.
- SFace `face_recognition_sface_2021dec.onnx`, SHA-256 `0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79`.
- SFace weight training-data provenance remains unresolved for future commercial-distribution review.
- Model binaries stay outside Git and are verified by exact size/SHA-256 before use.

Real-machine 3B.3 evidence:

- OpenCV `5.0.0`;
- exact YuNet/SFace hashes verified;
- YuNet load `47.8 ms`, synthetic median `3.49 ms`, p95 `3.79 ms`;
- SFace load `92.9 ms`, synthetic feature median `6.92 ms`, p95 `7.56 ms`;
- SFace feature shape `(1, 128)`;
- no camera/profile/template used or persisted;
- `STEP_3B3_MODEL_SMOKE = PASS`.

### 3B.4 — Selected-track live benchmark — REAL MACHINE NEXT

Command: `jarvis-face-live-benchmark`.

The diagnostic uses:

```text
Pocket 3 read-only capture
    ↓
existing RF-DETR person detection + tracker
    ↓
explicit selected TargetManager track
    ↓
existing BlazeFace + HeadFirstFramingPolicy association
    ↓
associated head crop only
    ↓
YuNet → SFace
    ↓
transient scalar diagnostic metrics
```

It never arms PTZ and persists nothing biometric. Its same-session anchor cosine is diagnostic only and is not a face-match/trust threshold.

## Remaining Phase 3B work after 3B.4

1. structured positive/negative calibration across lighting, pose, distance, glasses/appearance variation, and at least one non-owner;
2. real OWNER enrollment only if calibration supports the provider;
3. randomized MediaPipe Face Landmarker active-liveness on the same stable OWNER track;
4. typed `FACE_MATCH` and `FACE_LIVENESS` evidence with quality/freshness/model/source metadata;
5. deterministic T0/T1/T2 derivation from expected Windows session + stable OWNER track + fresh face + fresh liveness, without weighted confidence sums;
6. print/photo/phone/video replay and track-association failure tests;
7. attention and speaker evidence implementation/acceptance as subsequent slices.

Phase 3B is not complete merely because face recognition works.

## Immediate Next Actions

1. Pull the latest Phase-3B branch and reinstall `.[vision,dev]`.
2. Run `jarvis-face-live-benchmark` with the Pocket 3.
3. Click only a green/head-confirmed person track.
4. Collect 30–60 seconds while moving frontal, left/right, near/far, and under ordinary room lighting.
5. Review the printed live benchmark summary.
6. Do **not** enroll a real OWNER face yet; use this run to design the positive/negative calibration gate.