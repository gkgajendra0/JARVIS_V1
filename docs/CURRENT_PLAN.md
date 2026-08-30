# JARVIS V1 Current Plan

## Active Step

**Step 3 — Identity, Graduated Trust, Authority, and Observability Foundation**

## Current Stage

**PHASE 3A AUTHORITY FOUNDATION HUMAN-ACCEPTED — PHASE 3B OWNER IDENTITY + FACE/LIVENESS NEXT**

Step 0, Step 1, Step 2, and Step 2.5 are complete. The development-only `jarvis-dev` supervisor and time-aware startup greetings are implemented, automated-validated, human-accepted, and merged to protected `main`.

Step-3 research, security/privacy threat modeling, technology comparisons, canonical governance contracts, trust/risk vocabulary, degraded behavior, validation gates, and the Apple-inspired attention/intent amendment are complete. The combined architecture package received explicit human approval on 2026-08-30.

Phase 3A is now implemented, automated-validated, and human-accepted on real Windows hardware. The accepted evidence includes a real Windows lock transition invalidating authority state, a real Windows Hello/PIN strong-verification success, proposal/session-bound STRONG approval, R4 authority allow, one-time execution-permit consumption, and a canceled Hello verification that produced DENY with no permit and no weak fallback.

Accepted ADRs:

- `docs/decisions/ADR-006_STEP_3_IDENTITY_TRUST_AUTHORITY_GOVERNANCE.md`
- `docs/decisions/ADR-007_STEP_3_ATTENTION_INTENT_EVIDENCE.md`

Research artifacts:

- `docs/research/STEP_3_IDENTITY_TRUST_AUTHORITY_RESEARCH.md`
- `docs/research/STEP_3_THREAT_PRIVACY_MODEL.md`
- `docs/research/STEP_3_INDIA_PRIVACY_CONTEXT.md`
- `docs/research/STEP_3_ARCHITECTURE_PROPOSAL.md`
- `docs/research/STEP_3_ATTENTION_INTENT_AMENDMENT.md`

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
- Pocket 3 visual capture, RF-DETR person detection, OC-SORT tracking, head evidence, explicit target selection, and safe PTZ follow;
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

## Accepted Step-3 Architecture

The approved architecture includes:

- one persistent `OWNER` identity plus ephemeral `UNKNOWN` subjects for v1;
- typed local identity evidence rather than a universal confidence score;
- OpenCV YuNet + SFace as the initial face deployment candidate, benchmarked against InsightFace `buffalo_l` as an accuracy reference;
- randomized active face liveness through MediaPipe Face Landmarker instead of relying on uncertain passive-PAD weights;
- Apple-inspired attention/intent evidence as a separate short-lived `ATTENTION` modality, using the existing MediaPipe Face Landmarker path first and benchmarking OpenVINO gaze estimation only if needed;
- deterministic `OWNER_ATTENTIVE = T2 + fresh same-track attention + no relevant ambiguity`, used as an interaction predicate rather than a new trust tier;
- private ambient disclosure and R3 spoken consequential approval gated by fresh owner attention where policy requires it;
- explicit ambient biometric-attempt throttling with escalation to Windows Hello rather than weakening requirements after repeated failed explicit elevation attempts;
- sherpa-onnx speaker embedding candidate benchmarked against SpeechBrain ECAPA, with voice remaining corroborating evidence only;
- Windows session/lock state as contextual evidence only;
- Windows Hello `UserConsentVerifier` as the initial strong verifier, with WebAuthn/FIDO2 behind the same future-facing interface;
- four deterministic trust tiers: T0 `UNVERIFIED`, T1 `PRESENT_CONTEXT`, T2 `CORROBORATED_OWNER`, T3 `VERIFIED_OWNER`;
- deterministic risk classes R0 `ROUTINE`, R1 `PRIVATE_READ`, R2 `REVERSIBLE_LOCAL_CHANGE`, R3 `PERSISTENT_OR_EXTERNAL`, R4 `CRITICAL`, R5 `RESTRICTED_DEV_ONLY`;
- Open Policy Agent behind a fail-closed JARVIS `PolicyEngine` adapter;
- immutable exact-action proposals, one-time approval receipts, and final pre-execution revalidation;
- SQLite local state/audit with envelope-encrypted biometric templates and user-scoped DPAPI key sealing;
- privacy-aware structured audit plus optional tamper-evident chaining, with OpenTelemetry restricted to operational telemetry;
- STRIDE + LINDDUN PRO as the security/privacy threat-model baseline, extended by attention-specific spoofing/privacy cases.

## Phase 3A — Authority Foundation — ACCEPTED

Phase 3A is implemented and human-accepted. It establishes the authority boundary before biometric evidence can participate in protected decisions.

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

Automated validation on the accepted PR head covers Ruff, the complete pytest suite, Windows .NET helper compilation, and execution of the helper JSON contract probe.

Real-machine human acceptance on 2026-08-30 established:

- current WTS session reports unlocked during normal use;
- `Win+L` produces authority invalidation for the active session;
- Windows Hello/PIN can produce `VERIFIED`;
- verified proof is bound to the exact proposal fingerprint and session;
- the resulting STRONG approval allows an R4 diagnostic proposal;
- the resulting execution permit and approval are consumed exactly once;
- canceling Windows Hello produces a canceled approval, authority `DENY`, and no execution permit.

**Phase 3A rule remains permanent:** no face, speaker, liveness, gaze, wake-word, or LLM output may directly authorize an action.

## Phase 3B — Owner Identity + Face/Liveness — NEXT

Phase 3B adds local OWNER enrollment and typed face/liveness evidence behind the already accepted authority contracts. It must not weaken or bypass Phase 3A.

Planned work:

1. implement the single-OWNER profile/enrollment lifecycle with explicit create/replace/delete semantics;
2. implement DPAPI-backed key protection and envelope-encrypted biometric-template storage before persisting any owner biometric material;
3. add model/version/checksum/license manifests for YuNet/SFace and MediaPipe assets;
4. implement `FaceIdentityProvider` using YuNet + SFace on the selected/head crop rather than creating a second full-frame perception pipeline;
5. benchmark/calibrate face matching on the real Pocket 3 across lighting, pose, glasses, distance, and ordinary appearance variation;
6. implement randomized MediaPipe Face Landmarker active-liveness challenges on the same stable OWNER track;
7. emit typed `FACE_MATCH` and `FACE_LIVENESS` evidence with quality, freshness, source/model IDs, verdicts, and reason codes;
8. implement the first deterministic T0/T1/T2 trust derivation from Windows session + stable OWNER track + fresh face + fresh liveness, with no generic weighted confidence sum;
9. test print/photo/phone-screen/video replay and track-association failure cases on the real Pocket 3;
10. keep attention and speaker identity as subsequent evidence-provider slices unless needed to complete the approved T2 acceptance matrix.

Phase 3B is not complete merely because face recognition works. Persistent owner storage, deletion/re-enrollment, spoof testing, freshness/invalidation, and trust derivation must all pass before face evidence can become accepted architecture.

## Research Completion Coverage

The accepted research package covers:

- owner identity/presence evidence for Windows + Pocket 3;
- current face-recognition/embedding candidates, local deployment shape, licensing/provenance, and thresholds;
- face liveness/PAD limitations and randomized active challenge-response;
- Apple Face ID/Optic ID security lessons relevant to JARVIS, including the distinction between face identity, attention/intent, depth/IR anti-spoofing, iris authentication, and platform strong verification;
- local attention/eye-open/look-direction evidence, MediaPipe limitations, OpenVINO fallback, privacy boundaries, and real Pocket-3 acceptance gates;
- speaker-verification candidates plus replay/deepfake limitations;
- multi-person ambiguity, active-speaker options, attention-bound spoken approval, and safe escalation behavior;
- Windows Hello/WebAuthn strong-verification options;
- session continuity and typed evidence fusion;
- graduated-trust semantics and freshness/invalidation;
- action-risk classification and approval/consent state machines;
- exact-action binding, one-time receipts, expiry, mutation invalidation, and TOCTOU revalidation;
- policy-engine comparison (OPA/Cedar/Casbin) and fail-closed behavior;
- enrollment/re-enrollment/deletion and model-version lifecycle;
- encrypted biometric storage, DPAPI/TPM options, audit retention/redaction/integrity;
- STRIDE security threats and LINDDUN privacy threats, including attention/gaze surveillance and spoofing cases;
- degraded behavior for camera/mic/model/policy/Hello/audit failures;
- measurable face/liveness/attention/voice/Hello/policy/audit/resource benchmarks;
- explicit human acceptance scenarios;
- implementation sequencing that builds authority before biometrics or attention can influence it.

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
- Phase 3B owner identity + face/liveness implementation — **NEXT**;
- remaining Step-3 identity/attention/speaker validation — **PENDING**;
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
-> Phase 3A real human acceptance           DONE
-> Phase 3B owner identity + face/liveness  NEXT
-> attention/speaker evidence implementation
-> full Step-3 automated validation
-> full real-human security/privacy acceptance
-> documentation reconciliation
-> protected-main merge(s)
```

No Step-3 component becomes authoritative merely because a model/provider API works in isolation.

## Immediate Next Actions

1. Reconcile Phase 3A accepted implementation into `CURRENT_ARCHITECTURE.md`.
2. Merge PR #7 through protected `main` after the final documentation head passes required checks.
3. Create a dedicated Phase 3B implementation branch from the new `main` baseline.
4. Build OWNER lifecycle + encrypted biometric storage before persisting face templates.
5. Integrate and benchmark YuNet/SFace + randomized MediaPipe liveness on the existing Pocket 3 selected-track crop.
6. Only after real spoof/lighting/pose acceptance, allow typed face/liveness evidence to participate in deterministic T0/T1/T2 trust derivation.