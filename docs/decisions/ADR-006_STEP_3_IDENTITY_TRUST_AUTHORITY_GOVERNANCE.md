# ADR-006 — Step 3 Identity, Trust, Authority, and Observability Governance

**Status:** ACCEPTED  
**Accepted:** 2026-08-30  
**Scope:** Step 3 governance foundation

## Context

JARVIS is moving from conversation and sensing into capabilities that will eventually read private data and perform side effects. Identity evidence, trust, authorization, approval, execution, and audit must therefore be separated before those capabilities exist.

The accepted Step-3 research package is:

- `docs/research/STEP_3_IDENTITY_TRUST_AUTHORITY_RESEARCH.md`
- `docs/research/STEP_3_THREAT_PRIVACY_MODEL.md`
- `docs/research/STEP_3_INDIA_PRIVACY_CONTEXT.md`
- `docs/research/STEP_3_ARCHITECTURE_PROPOSAL.md`
- `docs/research/STEP_3_ATTENTION_INTENT_AMENDMENT.md`

Human approval was given on 2026-08-30 after the attention/intent amendment was added.

## Decision

Adopt the Step-3 governance architecture with these permanent boundaries:

1. **Identity evidence is not authority.** Face, voice, presence, attention, Windows session state, wake word, and model confidence may produce typed evidence only.
2. **Trust is deterministic JARVIS state.** Use T0 `UNVERIFIED`, T1 `PRESENT_CONTEXT`, T2 `CORROBORATED_OWNER`, and T3 `VERIFIED_OWNER`; do not use a universal weighted confidence score.
3. **Authority is exact-action specific.** Every consequential action is represented by an immutable canonical `ActionProposal`; material mutation changes its fingerprint and invalidates prior approval.
4. **Risk is deterministic.** Use R0 `ROUTINE`, R1 `PRIVATE_READ`, R2 `REVERSIBLE_LOCAL_CHANGE`, R3 `PERSISTENT_OR_EXTERNAL`, R4 `CRITICAL`, and R5 `RESTRICTED_DEV_ONLY`. An LLM may not lower risk.
5. **Policy is outside the LLM.** Adopt Open Policy Agent behind a JARVIS-owned fail-closed `PolicyEngine` adapter. Undefined, malformed, timed-out, or unavailable policy evaluation is deny for protected actions.
6. **Approvals are proposal-bound, short-lived, and one-time.** Spoken approval is allowed only where policy permits and actor association is unambiguous. Critical R4 actions require strong platform verification.
7. **Strong verification uses the platform.** Adopt Windows Hello `UserConsentVerifier` first behind a `StrongVerifier` interface; preserve WebAuthn/FIDO2 as a future stronger adapter.
8. **Final authority is revalidated immediately before execution.** Later capability executors must not be able to bypass proposal, policy, trust, approval, session, or expiry checks.
9. **Security/audit state is JARVIS-owned.** Use structured local audit events with redaction and bounded retention. OpenTelemetry, if used, is operational telemetry and never authorization/audit authority.
10. **Biometric state is local and minimized.** Raw identity audio/video is memory-only by default. Persist only explicitly enrolled OWNER templates, encrypted with AES-GCM under a profile DEK sealed with user-scoped Windows DPAPI. Use SQLite for local structured state/audit initially.
11. **Unknown people remain ephemeral.** Step-3 v1 supports one persistent `OWNER`; `UNKNOWN` subjects are session/track scoped and never silently enrolled.
12. **Fail safely.** Sensor, policy, audit, identity, or verifier failures reduce capability rather than relaxing requirements.
13. **Threat baseline is STRIDE + LINDDUN.** The accepted threat/privacy model and its replay, spoof, multi-person, stale-evidence, TOCTOU, policy-tamper, audit, and degraded-mode tests are implementation gates.

### Accepted technology direction

- Windows session context: WTS/session notifications, context only.
- Strong verifier: Windows Hello `UserConsentVerifier`; future WebAuthn/FIDO2 adapter.
- Face deployment candidate: OpenCV YuNet + SFace, subject to real Pocket-3 benchmark and recorded model provenance.
- Face accuracy reference only: InsightFace `buffalo_l`; public pretrained weights are not the default production dependency.
- Liveness: MediaPipe Face Landmarker randomized active challenge-response; RGB liveness remains supporting evidence.
- Speaker deployment candidate: sherpa-onnx + appropriately licensed WeSpeaker model, benchmarked against SpeechBrain ECAPA; voice never becomes strong authentication.
- Active-speaker/diarization: deferred behind interfaces unless real multi-person use demonstrates the need.
- Policy: OPA initially; Cedar remains a replaceable alternative.
- State/audit: SQLite.
- Sensitive-field protection: AES-GCM + user-scoped DPAPI key sealing; TPM/CNG remains future hardening.

## Alternatives considered

- Face recognition directly authorizing actions — rejected.
- Voice recognition as authentication — rejected.
- Wake word or unlocked Windows session as owner proof — rejected.
- Weighted multimodal confidence where weak signals add into strong authority — rejected.
- LLM-owned approval or risk classification — rejected.
- DeepFace as the production authority abstraction — rejected; provider/model/license boundaries remain explicit.
- InsightFace public pretrained weights as the default production face model — rejected because of pretrained-model licensing constraints.
- Passive RGB PAD as the sole liveness/security mechanism — rejected.
- Cedar or Casbin as the initial policy engine — retained as alternatives, but OPA best matches structured decision/obligation needs now.
- A generic executor in Step 3 — rejected; governance is built before Step-7 capability execution.

## Why this choice

The architecture preserves a natural user experience for ordinary conversation while preventing convenient biometric signals from becoming security theater. Mature commodity components are adopted where appropriate, while JARVIS retains the authority-critical contracts: evidence schemas, trust derivation, risk floors, proposal fingerprints, approvals, final enforcement, retention, and audit semantics.

Building the authority skeleton before biometric integration also guarantees that a face or speaker model can never accidentally become the execution gate simply because it was implemented first.

## Consequences and tradeoffs

- Protected actions may fail closed when OPA, audit storage, identity evidence, or Windows Hello is unavailable.
- R4 actions deliberately have more friction than ordinary interaction.
- Face/speaker thresholds are not accepted from vendor defaults; they require real-device calibration and human acceptance.
- OPA introduces a local process/lifecycle dependency, bounded behind a replaceable adapter.
- SQLite/DPAPI are Windows-first choices for the current single-PC deployment and will need reconsideration for cross-device or multi-user deployments.
- Step 3 does not itself provide broad file/browser/email/device execution.

## Replacement boundary

Provider implementations are replaceable behind JARVIS-owned interfaces including:

- `FaceIdentityProvider`
- `FaceLivenessProvider`
- `AttentionEvidenceProvider`
- `SpeakerIdentityProvider`
- `ActiveSpeakerProvider`
- `WindowsSessionProvider`
- `StrongVerifier`
- `PolicyEngine`
- `KeyProtector`
- `AuditEventStore`

Replacing a provider must not change trust semantics, risk floors, proposal binding, approval rules, or final authority enforcement without a new architecture decision.

## Conditions that should trigger reconsideration

Revisit this ADR if any of the following occurs:

- JARVIS becomes multi-user, distributed, commercial, remote, or cross-device;
- a trusted depth/IR biometric sensor replaces the Pocket 3 RGB-only identity path;
- Windows Hello/UserConsentVerifier cannot reliably satisfy the required local strong-verification UX;
- OPA operational cost materially harms the local runtime and another engine can preserve the same fail-closed structured policy contract;
- face/speaker benchmark gates cannot be met on the accepted hardware;
- later capabilities expose a missing authority primitive that cannot be represented safely by the accepted proposal/risk/approval model;
- the threat model gains a stronger endpoint-compromise assumption than the current trusted-Windows/JARVIS boundary.
