# JARVIS V1 Current Plan

## Active Step

**Step 3 — Identity, Graduated Trust, Authority, and Observability Foundation**

## Current Stage

**RESEARCH COMPLETE — ARCHITECTURE + ATTENTION/INTENT AMENDMENT PROPOSED — AWAITING HUMAN APPROVAL**

Step 0, Step 1, Step 2, and Step 2.5 are complete. The development-only `jarvis-dev` supervisor and time-aware startup greetings are implemented, automated-validated, human-accepted, and merged to protected `main`.

Step-3 implementation has **not** started. Current research, security/privacy threat modeling, technology comparisons, canonical governance contracts, trust/risk vocabulary, degraded behavior, validation gates, and the Apple-inspired attention/intent amendment are recorded on the Step-3 research branch. The complete proposal package must receive explicit human approval before ADRs are accepted or runtime code is written.

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
- deterministic JARVIS-owned scripted speech for startup/system prompts.

## Step-3 Non-Negotiable Invariants

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

## Proposed Step-3 Architecture — Pending Approval

The research proposes:

- one persistent `OWNER` identity plus ephemeral `UNKNOWN` subjects for v1;
- typed local identity evidence rather than a universal confidence score;
- OpenCV YuNet + SFace as the initial face deployment candidate, benchmarked against InsightFace `buffalo_l` as an accuracy reference;
- randomized active face liveness through MediaPipe Face Landmarker instead of relying on uncertain passive-PAD weights;
- Apple-inspired attention/intent evidence as a separate short-lived `ATTENTION` modality, using the existing MediaPipe Face Landmarker path first and benchmarking OpenVINO gaze estimation only if needed;
- deterministic `OWNER_ATTENTIVE = T2 + fresh same-track attention + no relevant ambiguity`, used as an interaction predicate rather than a new trust tier;
- private ambient disclosure and R3 spoken consequential approval gated by fresh owner attention where the amended policy requires it;
- explicit ambient biometric-attempt throttling with escalation to Windows Hello rather than weakening requirements after repeated failures;
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

No item in this section is accepted architecture yet.

## Research Completion Coverage

The research package now covers:

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

## Expected Step-3 Deliverables

Before implementation begins:

- current research record — **DONE on research branch**;
- concrete STRIDE + LINDDUN threat/privacy model — **DONE on research branch**;
- India privacy-context record — **DONE on research branch**;
- trust/risk vocabulary and canonical contracts — **DONE as proposal**;
- Apple-inspired attention/intent security amendment — **DONE as proposed amendment**;
- scope/non-scope and human acceptance scenarios — **DONE as proposal + amendment**;
- measurable security/privacy/latency/false-accept/false-reject/attention validation gates — **DONE as proposal + amendment**;
- explicit human architecture approval — **PENDING**;
- accepted ADRs for the approved major decisions — **PENDING APPROVAL**.

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
-> human approval                           CURRENT GATE
-> accepted ADRs
-> implementation
-> automated validation
-> real human acceptance
-> documentation reconciliation
-> protected-main merge
```

No Step-3 component becomes authoritative merely because a model/provider API works in isolation.

## Immediate Next Actions

1. Review the complete Step-3 research/threat/architecture package plus the attention/intent amendment with the human owner.
2. Resolve any final requested architecture changes.
3. Obtain explicit human approval of the combined proposal package.
4. Only then create accepted ADRs and begin Phase 3A authority-foundation implementation, with attention contracts/policy tests established before model integration.
