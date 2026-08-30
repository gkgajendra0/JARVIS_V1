# JARVIS V1 Current Architecture

## Status

**IMPLEMENTED + HUMAN-ACCEPTED ARCHITECTURE THROUGH PHASE 3B.3; PHASE 3B.4 LIVE BENCHMARK IMPLEMENTED/AUTOMATED-VALIDATED BUT NOT YET HUMAN-ACCEPTED**

This document records only architecture that has been implemented and accepted through the project's required validation lifecycle. Proposed or not-yet-human-accepted components remain in research/plan documents and must not be represented here as authoritative runtime behavior.

## Accepted platform foundation

JARVIS currently has accepted foundations for:

- natural realtime conversation with JARVIS-owned canonical conversation state;
- local wake detection and JARVIS-owned audio lifecycle;
- Pocket 3 visual capture, person detection, persistent person tracking, head evidence, explicit target selection, and safe PTZ follow;
- development-only supervised update tooling outside model authority;
- deterministic Step-3 authority, policy, approval, audit, Windows-session, and strong-verification boundaries;
- secure single-OWNER profile/template storage foundation;
- pinned/verified local YuNet/SFace model asset boundary, exercised by the accepted real-machine 3B.3 smoke;
- real-machine non-enrollment OpenCV-5 YuNet/SFace runtime viability.

## Step 3A — Identity/Trust/Authority foundation — ACCEPTED

### Identity evidence, trust, and authority are separate

```text
IDENTITY / CONTEXT EVIDENCE
"Who or what might be present?"
        ↓
GRADUATED TRUST
"How strongly do fresh facts support owner authority?"
        ↓
ACTION AUTHORITY
"May this exact action execute now?"
```

No layer may be skipped.

### Accepted trust vocabulary

- `T0 UNVERIFIED`
- `T1 PRESENT_CONTEXT`
- `T2 CORROBORATED_OWNER`
- `T3 VERIFIED_OWNER`

There is no ambient T4/admin-superuser trust state.

### Strong verification

Windows Hello is wrapped behind JARVIS's `StrongVerifier` boundary using a desktop .NET 9 helper and Microsoft `UserConsentVerifier` desktop-window interop.

The runtime behavior accepted on real Windows hardware is:

```text
exact ActionProposal
+ exact JARVIS/Windows session
        ↓
Windows Hello / PIN
        ↓
proposal/session-bound StrongVerificationResult
+ unique one-time verification_id
        ↓
StrongApprovalService
        ↓
one proposal-bound STRONG approval
```

A generic approval API cannot claim `STRONG_VERIFIER`. Strong proof/approval replay is rejected.

Cancellation/unavailability never falls back to face, voice, spoken yes, wake word, Windows unlocked state, or LLM confidence.

### Action proposal and authority

Consequential actions use immutable, expiring, session-bound `ActionProposal` objects with canonical JSON and SHA-256 material fingerprints.

Accepted protections include:

- Unicode NFC canonicalization and normalized-key collision rejection;
- deterministic hard risk floors;
- fail-closed policy evaluation;
- proposal-bound approval;
- short-lived execution permits;
- final pre-execution proposal/risk/policy/session revalidation;
- one-time approval/permit consumption;
- failure on proposal mutation, replay, expiry, policy changes, session changes, audit failure, and TOCTOU conditions.

### Windows session boundary

`WindowsWtsSessionProvider` reads the current WTS session and explicit lock/unlock state. A transition away from the active unlocked session invalidates authority state. This was accepted with a real `Win+L` transition.

Windows unlocked is context only; it does not prove that the person on camera/microphone is OWNER.

### Policy and audit

- OPA is wrapped behind JARVIS's `PolicyEngine` boundary.
- OPA communication is loopback-only with strict response/version validation and fail-closed behavior.
- JARVIS owns action schemas, risk floors, trust evaluation, approval state, and final enforcement.
- `AuditEventStore` is the authoritative security audit boundary.
- audit metadata rejects secret/biometric/raw-media fields.
- raw A/V, embeddings, credentials, or sensitive action payloads are not retained simply because they are available.

### Permanent authority invariant

```text
face match       ≠ permission
speaker match    ≠ permission
liveness         ≠ permission
attention        ≠ permission
wake word        ≠ owner
Windows unlocked ≠ owner speaking
LLM confidence   ≠ permission
```

T3 also is not permission by itself:

```text
T3 VERIFIED_OWNER
+ exact ActionProposal
+ deterministic risk/policy
+ proposal-bound approval
= possible authority
```

## Step 2.5 — Accepted visual association boundary reused by identity

The accepted visual pipeline remains provider-neutral at its boundaries:

```text
Pocket 3 capture
        ↓
RF-DETR person detection
        ↓
tracker-based persistent person tracks
        ↓
TargetManager explicit selected/locked track
        ↓
MediaPipe BlazeFace head observations
        ↓
HeadFirstFramingPolicy body↔head association
        ↓
head-first framing / safe follow
```

The person track is the stable visual subject handle. Head/face observations are supporting evidence associated to that track; they are not standalone authority identities.

`HeadFirstFramingPolicy` is the canonical body↔head association policy. Phase 3B identity diagnostics reuse this association rather than creating a parallel full-frame identity scanner.

## Phase 3B.1 — Secure single-OWNER profile/storage — ACCEPTED

### Subject model

The persistent v1 subject model contains exactly one durable identity:

```text
OWNER
```

Unknown people remain ephemeral/session-scoped and are not persisted as biometric profiles.

### OWNER lifecycle

JARVIS implements explicit OWNER create, replace/re-enroll, and delete semantics through `OwnerProfileLifecycleService`.

Each persistent identity mutation is strongly verified using the accepted Step-3A Windows Hello flow and the Windows session is checked both before strong verification and immediately before storage mutation.

The candidate biometric template bytes themselves are SHA-256 committed into the exact authorization proposal. A different template cannot be substituted after Hello while retaining the same metadata/proposal.

### Biometric template encryption

Persistent template payloads use envelope encryption:

```text
biometric template bytes
        ↓
AES-256-GCM
        ↓
random per-profile DEK
        ↓
user-scoped Windows DPAPI KeyProtector
        ↓
SQLite profile/template store
```

Accepted properties:

- `cryptography` supplies AES-GCM; JARVIS does not implement custom cryptographic primitives;
- the per-profile DEK is sealed behind a replaceable `KeyProtector` contract;
- Windows implementation uses user-scoped DPAPI with purpose-bound entropy;
- AEAD additional authenticated data binds profile/template/model metadata to ciphertext;
- create/re-enroll rotates the profile DEK and replaces old active templates;
- delete removes the live sealed DEK and encrypted template rows;
- deletion is described as application/logical crypto-erasure only and does not claim guaranteed physical SSD erasure.

Real Windows acceptance using synthetic non-biometric bytes proved:

- Hello-gated create/delete;
- encrypted template round-trip;
- same-user DPAPI reopen/decrypt;
- plaintext synthetic template absent from SQLite database and WAL;
- no live OWNER after deletion.

No real owner face was enrolled during this acceptance.

## Phase 3B.2/3B.3 — Face asset boundary + non-enrollment runtime — ACCEPTED

The model manifest/cache boundary was first automated-validated in 3B.2 and then exercised end-to-end by the human-accepted 3B.3 real-machine smoke. The combined accepted boundary is therefore limited to model integrity, local cache behavior, model construction, and synthetic-input runtime viability.

### Frozen model baseline

OpenCV Zoo source revision:

`47534e27c9851bb1128ccc0102f1145e27f23f98`

YuNet detector:

- `face_detection_yunet_2026may.onnx`
- exact SHA-256 `ebafce4e3c118d6554634be5c27ab333b4c047a9a8c3faf1d7cf93101c22f0f0`
- exact size `229738` bytes
- MIT directory/model license declaration
- selected because this dynamic-input re-export is the OpenCV-5-compatible default.

SFace recognizer:

- `face_recognition_sface_2021dec.onnx`
- exact SHA-256 `0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79`
- exact size `38696353` bytes
- OpenCV Zoo directory declaration Apache-2.0
- exact weight training-dataset provenance remains unresolved for future commercial-distribution review.

The model binary files are not stored in Git.

### Model cache

`ModelAssetCache` stores models outside the repository (`%LOCALAPPDATA%/JARVIS/models` on Windows by default) and requires:

- exact filename/source revision;
- exact byte count;
- exact SHA-256;
- temporary download;
- integrity verification before atomic promotion;
- no silent auto-upgrade/model drift;
- fail closed if the asset is missing or tampered.

Upstream model-match thresholds are reference values only and are not JARVIS trust/authority thresholds.

### Real-machine non-enrollment evidence

Real-machine result on OpenCV `5.0.0`:

- pinned YuNet and SFace checksums verified;
- YuNet load `47.8 ms`;
- YuNet synthetic inference median `3.49 ms`, p95 `3.79 ms`;
- SFace load `92.9 ms`;
- SFace synthetic feature median `6.92 ms`, p95 `7.56 ms`;
- SFace feature shape `(1, 128)`;
- no camera opened;
- no OWNER profile created;
- no biometric template persisted;
- `STEP_3B3_MODEL_SMOKE = PASS`.

OpenCV-5 graph-engine warnings caused by explicit target selection were non-blocking; the accepted diagnostic implementation now uses the default OpenCV-5 backend/target path.

This acceptance proves model integrity/load/runtime viability only. It does **not** accept face recognition accuracy, any match threshold, liveness, OWNER enrollment, T2 trust, or authority use.

## Phase 3B.4 — Selected-track live benchmark — NOT YET HUMAN-ACCEPTED

A read-only diagnostic is implemented and automated-validated but does not become accepted architecture until the real Pocket-3 run passes.

Its intended boundary is:

```text
existing selected person track
        ↓
existing HeadFirstFramingPolicy associated head
        ↓
volatile head crop
        ↓
YuNet within that crop
        ↓
SFace alignment + volatile feature
        ↓
transient diagnostic scalar metrics only
```

The diagnostic uses a no-op PTZ boundary and never arms/moves the camera. It writes no frame, face crop, feature vector, OWNER profile, or biometric template.

Its same-session anchor-cosine value is a diagnostic stability measurement only. It is not a face-match threshold and cannot contribute to trust/authority until later calibration and acceptance.

## Not yet accepted / implemented as authoritative identity

The following remain outside accepted runtime architecture:

- real persistent OWNER face enrollment;
- promoted `FaceIdentityProvider` face-match evidence;
- production face-match threshold/calibration;
- randomized active-liveness runtime;
- face/liveness participation in T2;
- attention/gaze provider implementation;
- speaker identity provider implementation;
- multi-person active-speaker disambiguation;
- generic capability/tool execution beyond the Step-3 authority foundation.

The future intended T2 structure remains a proposal from the accepted Step-3 architecture until its evidence providers are implemented and human-accepted:

```text
active/unlocked expected Windows session
+ same stable OWNER track
+ fresh OWNER face match
+ fresh randomized liveness
+ fresh attention/intent evidence
+ no unresolved association ambiguity
= T2 CORROBORATED_OWNER
```

No weak signal combination may be promoted into stronger trust merely by adding confidence scores.