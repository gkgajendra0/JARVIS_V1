# JARVIS V1 Current Plan

## Active Step

**Step 3 — Identity, Graduated Trust, Authority, and Observability Foundation**

## Current Stage

**PHASE 3A COMPLETE + MERGED — PHASE 3B ACTIVE — 3B.1 HUMAN-ACCEPTED, 3B.2/3 HUMAN-ACCEPTED AS MODEL-INTEGRITY/RUNTIME BOUNDARY, 3B.4 REAL POCKET-3 LIVE BENCHMARK NEXT**

Step 0, Step 1, Step 2, Step 2.5, and Step 3A are complete. The development-only `jarvis-dev` supervisor and time-aware startup greetings are also implemented, automated-validated, human-accepted, and merged to protected `main`.

Step-3 research, security/privacy threat modeling, technology comparisons, canonical governance contracts, trust/risk vocabulary, degraded behavior, validation gates, and the Apple-inspired attention/intent amendment are complete. The combined architecture package received explicit human approval on 2026-08-30.

Phase 3A is implemented, automated-validated, human-accepted on real Windows hardware, documentation-reconciled, and merged to protected `main` through PR #7 on 2026-08-30. Merge commit: `6651de01d0c4ae81a25480ef26d2399181cee870`.

Accepted Phase-3A evidence includes a real Windows lock transition invalidating authority state, a real Windows Hello/PIN strong-verification success, proposal/session-bound STRONG approval, R4 authority allow, one-time execution-permit consumption, and a canceled Hello verification that produced DENY with no permit and no weak fallback.

Phase 3B is proceeding on draft PR #10 in bounded slices. Accepted/validated progress so far:

- **3B.1 secure single-OWNER profile/storage — HUMAN-ACCEPTED** on the real Windows owner account using synthetic non-biometric bytes only. Windows Hello gated create/delete, user-scoped DPAPI survived reopen, plaintext synthetic template bytes were absent from SQLite/WAL, and no live OWNER remained after delete.
- **3B.2 model manifest/asset boundary — AUTOMATED-VALIDATED and subsequently exercised by the 3B.3 human run.** YuNet/SFace assets are pinned to an immutable OpenCV Zoo revision, exact filenames/sizes/SHA-256 values, external verified cache, and no automatic model drift. SFace training-data provenance remains explicitly unresolved for future commercial distribution review.
- **3B.3 non-enrollment model smoke — HUMAN-ACCEPTED** on the real owner machine. It exercised the 3B.2 manifest/cache boundary end-to-end: exact model integrity verified, OpenCV 5 loaded YuNet/SFace, both executed successfully on synthetic inputs, SFace emitted a `(1, 128)` feature, and no camera/profile/template was used or persisted.
- **3B.4 selected-track live face benchmark — IMPLEMENTED + AUTOMATED-VALIDATED; REAL POCKET-3 RUN NEXT.** The diagnostic reuses the existing Step-2.5 person-track/head-association path, runs YuNet/SFace only on the selected track's associated head crop, uses read-only camera capture with a no-op PTZ boundary, and persists no frame or feature vector.

Accepted ADRs:

- `docs/decisions/ADR-006_STEP_3_IDENTITY_TRUST_AUTHORITY_GOVERNANCE.md`
- `docs/decisions/ADR-007_STEP_3_ATTENTION_INTENT_EVIDENCE.md`

Research artifacts:

- `docs/research/STEP_3_IDENTITY_TRUST_AUTHORITY_RESEARCH.md`
- `docs/research/STEP_3_THREAT_PRIVACY_MODEL.md`
- `docs/research/STEP_3_INDIA_PRIVACY_CONTEXT.md`
- `docs/research/STEP_3_ARCHITECTURE_PROPOSAL.md`
- `docs/research/STEP_3_ATTENTION_INTENT_AMENDMENT.md`
- `docs/research/STEP_3B_FACE_MODEL_MANIFEST_RESEARCH.md`

## Step-3 Objective

Build the smallest trustworthy governance foundation that can answer four separate questions without conflating them:

1. **Who or what is present?** — identity/presence evidence.
2. **How much should JARVIS trust that evidence for this session/action?** — graduated trust.
3. **Is this specific requested action permitted?** — authority, policy, and consent.
4. **What happened and why?** — privacy-aware observability/audit evidence.

Step 3 does **not** yet implement the later generic capability runtime or broad computer/file/browser/email/device actions. It establishes the governance contracts those later steps must reuse.

## Frozen Prerequisites

The following are already accepted and must be treated as inputs, not redesigned casually:

- natural realtime conversation and canonical accepted conversation state;
- local wake detection and JARVIS-owned audio lifecycle;
- Pocket 3 visual capture, RF-DETR person detection, tracker-based person tracking, head evidence, explicit target selection, and safe PTZ follow;
- vision/head/person tracking as **evidence only**, never permission;
- wake word as an activation signal only, never authentication;
- `jarvis-dev` as development tooling outside model authority;
- protected `main` requiring PR flow plus `ruff` and `pytest` checks;
- explicit spoken software-update approval parsed deterministically outside the realtime model;
- last-known-good rollback for failed development updates;
- deterministic JARVIS-owned scripted speech for startup/system prompts;
- Phase 3A deterministic authority contracts and Windows strong-verification/session boundaries.

## Accepted Step-3 Non-Negotiable Invariants

- Identity evidence is not execution permission.
- Attention/gaze evidence is intent-to-engage evidence only; it is not identity, authentication, or execution permission.
- Face recognition, voice recognition, attention, presence, Windows/session context, wake word, or model confidence must never directly grant consequential authority.
- The model may recommend or explain; deterministic JARVIS-owned policy decides whether an action may proceed.
- Capabilities cannot self-authorize or broaden their own permission.
- Approval must bind to the materially relevant action, target, and parameters.
- Ambiguous or missing approval must fail safely for consequential actions.
- Trust friction should increase with consequence rather than making ordinary conversation annoying.
- Observability must capture enough evidence to explain decisions without becoming hidden surveillance.
- Raw audio/video, eye crops, gaze vectors, full transcripts, biometric material, secrets, and sensitive payloads are not retained merely because they are available.
- Provider/device/model implementations remain replaceable behind JARVIS-owned contracts.
- Pocket-3 RGB attention/liveness must never be represented as Face-ID-equivalent security or as iris authentication; Windows Hello/FIDO2 remains the strong-verification path.
- A generic approval path may not claim `STRONG_VERIFIER`; a verified strong proof must be bound to the exact proposal/session and consumed only once.
- Face-model reference thresholds, live benchmark cosine values, and diagnostic quality metrics are never authority decisions and are not accepted trust thresholds without explicit calibration/acceptance.

## Phase 3A — Authority Foundation — COMPLETE

Accepted implementation includes:

- canonical Step-3 trust/risk/approval/attention/evidence contracts;
- immutable, expiring, session-bound `ActionProposal` canonicalization and SHA-256 material fingerprinting;
- Unicode-normalized-key collision rejection and fingerprint re-computation at authority boundaries;
- deterministic `RiskClassifier` with hard security floors that policy/model output cannot lower;
- fail-closed `PolicyEngine` boundary and loopback-only OPA adapter with strict response/policy-version validation;
- proposal-bound `ApprovalService` with expiry, cancellation, denial, one-time consumption, session invalidation, and strength ordering;
- proposal/session-bound `StrongVerificationResult` carrying a unique one-time verification ID;
- `StrongApprovalService` as the only path that can convert a verified strong proof into a STRONG approval;
- prohibition on generic approval APIs pretending `STRONG_VERIFIER` happened;
- `AuthorityService` decision, audit-before-protected-execution, short-lived execution permits, and final pre-execution revalidation/consumption;
- structured privacy-aware audit boundary plus SQLite audit store and forbidden sensitive metadata keys;
- Windows WTS session adapter using explicit lock state and authority invalidation on lock/session transition;
- desktop Windows Hello adapter plus .NET 9 interop helper and lowercase JSON wire contract;
- attention-evidence contract established without yet integrating an attention model;
- failure-path tests for unauthorized execution, policy failure, approval/proof replay, proposal mutation, expiry, session invalidation, risk-floor downgrade, audit failure, and TOCTOU revalidation.

Automated validation covers Ruff, the complete pytest suite, Windows .NET helper compilation, and execution of the helper JSON contract probe.

Real-machine human acceptance on 2026-08-30 established:

- current WTS session reports unlocked during normal use;
- `Win+L` produces authority invalidation for the active session;
- Windows Hello/PIN can produce `VERIFIED`;
- verified proof is bound to the exact proposal fingerprint and session;
- the resulting STRONG approval allows an R4 diagnostic proposal;
- the resulting execution permit and approval are consumed exactly once;
- canceling Windows Hello produces a canceled approval, authority `DENY`, and no execution permit.

**Permanent Phase-3A rule:** no face, speaker, liveness, gaze, wake-word, or LLM output may directly authorize an action.

## Phase 3B — Owner Identity + Face/Liveness — ACTIVE

Phase 3B adds local OWNER enrollment and typed face/liveness evidence behind the already accepted authority contracts. It must not weaken or bypass Phase 3A.

### 3B.1 — Secure OWNER profile/storage — HUMAN-ACCEPTED

Implemented/accepted:

1. single persistent OWNER with explicit create/replace/delete semantics;
2. AES-256-GCM envelope-encrypted biometric-template payloads;
3. per-profile DEK sealed with user-scoped Windows DPAPI behind a replaceable `KeyProtector`;
4. SQLite profile/template store with integrity-bound metadata;
5. strong-verifier-gated lifecycle mutations with Windows-session revalidation;
6. exact candidate-template SHA-256 commitment in the authorization proposal;
7. real Windows synthetic-template create/reopen/delete acceptance with plaintext-at-rest checks.

No real owner face was enrolled during 3B.1.

### 3B.2/3 — Model integrity + non-enrollment runtime — HUMAN-ACCEPTED BOUNDARY

The 3B.2 manifest/cache layer was automated-validated first and then exercised on the real owner machine by 3B.3. The accepted boundary includes only model identity/integrity/cache behavior and synthetic-input runtime viability.

Implemented/accepted:

1. OpenCV Zoo revision and exact model assets pinned;
2. YuNet 2026 dynamic-input asset selected for OpenCV 5;
3. SFace model pinned with explicit unresolved training-data-provenance caveat;
4. external cache with exact size/SHA-256 verification and atomic download promotion;
5. no model binaries committed to Git;
6. no silent provider/model version drift;
7. upstream SFace thresholds retained as benchmark references only;
8. real-machine exact-hash fetch/verification and OpenCV-5 model construction;
9. synthetic YuNet/SFace inference and finite `(1, 128)` SFace feature.

Real owner-machine evidence on 2026-08-30:

- OpenCV `5.0.0`;
- YuNet exact checksum verified;
- SFace exact checksum verified;
- YuNet load `47.8 ms`;
- YuNet synthetic inference median `3.49 ms`, p95 `3.79 ms`;
- SFace load `92.9 ms`;
- SFace synthetic feature median `6.92 ms`, p95 `7.56 ms`;
- SFace feature shape `(1, 128)`;
- no camera opened;
- no OWNER profile created;
- no biometric template persisted;
- `STEP_3B3_MODEL_SMOKE = PASS`.

OpenCV-5 graph-engine warnings caused by explicitly requesting `DNN_TARGET_CPU` were non-blocking; the diagnostic has since been corrected to use the default OpenCV-5 backend/target path.

This boundary does **not** accept face-match accuracy or any production match threshold.

### 3B.4 — Selected-track live face benchmark — REAL MACHINE NEXT

Implemented/automated-validated diagnostic:

- command: `jarvis-face-live-benchmark`;
- opens the Pocket 3 read-only through the existing camera boundary;
- reuses RF-DETR person detection, existing tracker, `TargetManager`, BlazeFace head detection, and `HeadFirstFramingPolicy`;
- requires the user to click a head-confirmed person track before identity diagnostics begin;
- exposes the exact same associated head selected by the existing framing policy;
- runs YuNet only within that selected track's associated head crop;
- aligns/crops with SFace and computes a volatile feature in memory;
- uses one same-session anchor feature only for diagnostic cosine stability;
- records only transient scalar metrics such as latency/confidence/brightness/sharpness/head size;
- uses a no-op PTZ boundary and never arms/moves the camera;
- writes no frame, face crop, feature vector, OWNER profile, or biometric template.

The live benchmark is **not** owner recognition and its anchor cosine is **not** a match threshold. It exists only to measure live capture quality, association, latency, and within-session embedding stability before any real enrollment.

### Remaining Phase 3B work

After 3B.4 real acceptance:

1. define and run structured positive/negative face calibration across lighting, pose, distance, glasses, ordinary appearance variation, and at least one non-owner;
2. implement/gate real OWNER enrollment only after the calibration data shows the provider is viable;
3. implement randomized MediaPipe Face Landmarker active-liveness challenges on the same stable OWNER track;
4. emit typed `FACE_MATCH` and `FACE_LIVENESS` evidence with quality, freshness, source/model IDs, verdicts, and reason codes;
5. implement deterministic T0/T1/T2 trust derivation from Windows session + stable OWNER track + fresh face + fresh liveness, with no generic weighted confidence sum;
6. test print/photo/phone-screen/video replay and track-association failure cases on the real Pocket 3;
7. keep attention and speaker identity as subsequent evidence-provider slices unless needed to complete the approved T2 acceptance matrix.

Phase 3B is not complete merely because face recognition works. Persistent owner storage, deletion/re-enrollment, spoof testing, freshness/invalidation, and trust derivation must all pass before face evidence becomes accepted architecture.

## Step-3 Deliverable Status

- current research record — **DONE**;
- concrete STRIDE + LINDDUN threat/privacy model — **DONE**;
- India privacy-context record — **DONE**;
- trust/risk vocabulary and canonical contracts — **APPROVED + IMPLEMENTED IN 3A**;
- Apple-inspired attention/intent security amendment — **APPROVED; PROVIDER IMPLEMENTATION PENDING**;
- scope/non-scope and human acceptance scenarios — **APPROVED**;
- measurable security/privacy/latency/false-accept/false-reject/attention validation gates — **APPROVED**;
- explicit human architecture approval — **DONE 2026-08-30**;
- accepted ADRs for major decisions — **DONE**;
- Phase 3A implementation — **DONE**;
- Phase 3A automated validation — **DONE**;
- Phase 3A real human acceptance — **DONE 2026-08-30**;
- Phase 3A documentation reconciliation — **DONE**;
- Phase 3A protected-main merge — **DONE 2026-08-30 (PR #7)**;
- Phase 3B.1 OWNER storage lifecycle — **HUMAN-ACCEPTED**;
- Phase 3B.2/3 model integrity + non-enrollment runtime — **HUMAN-ACCEPTED BOUNDARY**;
- Phase 3B.4 selected-track Pocket-3 live face benchmark — **IMPLEMENTED + AUTOMATED-VALIDATED; REAL MACHINE NEXT**;
- remaining Phase 3B owner identity + face/liveness implementation — **PENDING**;
- remaining Step-3 attention/speaker validation — **PENDING**;
- complete Step-3 human acceptance — **PENDING**.

## Explicitly Out of Scope for Step 3

- broad file/system/browser/device/email/calendar execution;
- the Step-7 generic capability runtime;
- long-term personal memory;
- general scene understanding / VLM reasoning;
- OCR, gestures, or visual memory;
- proactive surveillance or continuous recording;
- persistent gaze history, emotion/fatigue/interest inference, or behavioral eye tracking;
- smart-glasses/HUD work;
- unrestricted shell authority;
- autonomous self-modification;
- persistent guest/family identity roles;
- cloud biometric recognition;
- claims of Face-ID-equivalent or iris-authentication security from the Pocket 3 RGB camera.

## Completion Gate

Step 3 is complete only after:

```text
requirements
-> current research                         DONE
-> threat/privacy model                     DONE
-> technology/architecture proposal         DONE
-> attention/intent amendment               DONE
-> human architecture approval              DONE
-> accepted ADRs                            DONE
-> Phase 3A authority implementation        DONE
-> Phase 3A automated validation            DONE
-> Phase 3A real human acceptance            DONE
-> Phase 3A documentation reconciliation   DONE
-> Phase 3A protected-main merge            DONE
-> Phase 3B.1 secure OWNER profile          DONE / HUMAN ACCEPTED
-> Phase 3B.2/3 model integrity/runtime     DONE / HUMAN ACCEPTED BOUNDARY
-> Phase 3B.4 live selected-track benchmark NEXT REAL-MACHINE GATE
-> owner face calibration/enrollment
-> active liveness
-> T0/T1/T2 derivation + spoof testing
-> attention/speaker evidence implementation
-> full Step-3 automated validation
-> full real-human security/privacy acceptance
-> documentation reconciliation
-> protected-main merge(s)
```

No Step-3 component becomes authoritative merely because a model/provider API works in isolation.

## Immediate Next Actions

1. Run `jarvis-face-live-benchmark` on the real Pocket 3 after pulling the exact automated-validated Phase-3B branch head.
2. Select only a head-confirmed body track and collect 30–60 seconds of non-persistent live metrics while moving naturally through frontal, left/right, near/far, and ordinary room lighting.
3. Review association success, embedding success rate, latency, head-size range, brightness/sharpness, and same-session cosine stability.
4. Do **not** create a real OWNER face template from this benchmark.
5. Use the results to design the structured positive/negative calibration gate before enrollment.