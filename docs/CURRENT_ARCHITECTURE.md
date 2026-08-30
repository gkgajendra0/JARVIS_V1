# JARVIS V1 Current Architecture

## Status

**IMPLEMENTED + HUMAN-ACCEPTED ARCHITECTURE THROUGH PHASE 3B.7B. PHASE 3B.8 RUNTIME OWNER IDENTITY + LIVENESS BINDING IS NEXT AND IS NOT YET PART OF THE ACCEPTED RUNTIME ARCHITECTURE.**

This document records only implemented and human-accepted architecture. Proposed or still-integration-stage behavior belongs in research/plan documents until accepted.

## Accepted platform foundation

JARVIS currently has accepted foundations for:

- natural realtime conversation with JARVIS-owned canonical conversation state;
- local wake detection and JARVIS-owned audio lifecycle;
- Pocket 3 visual capture, person detection, persistent person tracking, head evidence, explicit target selection, and safe PTZ follow;
- development-only supervised update tooling outside model authority;
- deterministic Step-3 authority, policy, approval, audit, Windows-session, and strong-verification boundaries;
- one persistent encrypted OWNER profile;
- pinned and integrity-verified YuNet/SFace face runtime;
- real OWNER multi-prototype SFace enrollment;
- randomized active facial liveness fallback;
- passive RGB presentation-attack detection using MiniFAS + JARVIS-owned temporal fusion for the current Pocket-3 prototype.

## Step 3A — Authority foundation — ACCEPTED + MERGED

Identity/context evidence, graduated trust, and action authority are separate layers:

```text
IDENTITY / CONTEXT EVIDENCE
        ↓
GRADUATED TRUST
        ↓
ACTION AUTHORITY
```

No layer may be skipped.

Accepted trust vocabulary:

- `T0 UNVERIFIED`
- `T1 PRESENT_CONTEXT`
- `T2 CORROBORATED_OWNER`
- `T3 VERIFIED_OWNER`

There is no ambient T4/admin-superuser state.

### Strong verification

Windows Hello is wrapped behind JARVIS's `StrongVerifier` boundary using the desktop .NET helper and Microsoft user-consent verification.

```text
exact ActionProposal
+ exact JARVIS/Windows session
        ↓
Windows Hello / PIN
        ↓
proposal/session-bound strong proof
        ↓
StrongApprovalService
        ↓
one proposal-bound STRONG approval
```

Cancellation/unavailability never falls back to face, voice, wake word, spoken confirmation, Windows-unlocked state, or LLM confidence.

### Action authority

Consequential actions use immutable, expiring, session-bound `ActionProposal` objects with canonical material fingerprints.

Accepted protections include:

- deterministic hard risk floors;
- fail-closed OPA policy evaluation;
- proposal-bound approval;
- one-time short-lived execution permits;
- final pre-execution proposal/risk/policy/session revalidation;
- replay/mutation/expiry/TOCTOU rejection;
- privacy-aware authoritative audit.

### Windows session boundary

`WindowsWtsSessionProvider` tracks the current Windows session and explicit lock/unlock state. Session lock/switch invalidates authority state.

Windows unlocked is context only; it does not prove the person on camera or microphone is OWNER.

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

T3 also is not permission by itself; exact proposal, deterministic risk/policy, and bound approval are still required.

## Step 2.5 visual association reused by identity — ACCEPTED

```text
Pocket 3 capture
        ↓
RF-DETR person detection
        ↓
persistent person track
        ↓
TargetManager explicit selected/locked track
        ↓
MediaPipe BlazeFace head observations
        ↓
HeadFirstFramingPolicy body↔head association
```

The persistent visual track is the stable subject handle. Head/face observations are supporting evidence associated with that track; they are not standalone authority identities.

## Phase 3B.1 — Secure single-OWNER storage — ACCEPTED

Persistent subject model:

```text
OWNER
```

Unknown people remain ephemeral/session-scoped.

OWNER template storage:

```text
biometric template bytes
        ↓
AES-256-GCM
        ↓
random per-profile DEK
        ↓
user-scoped Windows DPAPI KeyProtector
        ↓
SQLite
```

OWNER create/replace/delete is strongly verified. Exact candidate template bytes are SHA-256 committed into the authorization proposal before mutation.

Raw biometric bytes are not exposed to policy/audit.

## Phase 3B.2/3B.3 — Face model integrity/runtime — ACCEPTED

Pinned OpenCV Zoo baseline:

- YuNet `face_detection_yunet_2026may.onnx`;
- SFace `face_recognition_sface_2021dec.onnx`;
- exact byte-count/SHA verification;
- model files stored outside Git;
- temporary download + integrity verification + atomic promotion;
- no silent model drift.

SFace released-weight training-data provenance remains an explicit future commercial-distribution review item.

## Phase 3B.4 — Pocket-3 live face pipeline — ACCEPTED

Accepted real-machine identity sensor path:

```text
Pocket 3
    ↓
RF-DETR + persistent visual track
    ↓
selected/head-confirmed track
    ↓
BlazeFace head association
    ↓
YuNet
    ↓
SFace 128-D embedding
```

The live benchmark demonstrated significant same-owner frame variation, so one-frame identity thresholds are not accepted.

## Phase 3B.5A — OWNER positive baseline — ACCEPTED

Positive-only calibration established genuine OWNER behavior on the Pocket 3 but did not define an absolute OWNER-vs-UNKNOWN threshold.

Subject semantics remain:

- `OWNER` — sufficiently proven enrolled owner;
- `UNKNOWN` — not sufficiently proven;
- `AMBIGUOUS` — evidence is insufficient/conflicting.

No persistent non-owner biometric profiles are created.

## Phase 3B.6 — Real OWNER enrollment — ACCEPTED

OWNER face template format:

```text
sface-prototype-set-v1
```

The enrolled payload contains 8 normalized prototypes selected deterministically using centroid + farthest inliers. The serialized payload is committed before Windows Hello, encrypted at rest through the accepted profile store, and decoded strictly.

Enrollment does not grant T2.

## Phase 3B.7A — Active liveness fallback — ACCEPTED

The active fallback uses MediaPipe Face Landmarker primitives and a JARVIS-owned randomized state machine.

Challenge vocabulary:

- blink;
- open mouth;
- smile.

Each action requires `neutral → action → neutral`, repeated observations, same Windows session, same visual track, bounded expiry, and fail-closed handling.

A passed challenge creates short-lived typed `FACE_LIVENESS` evidence. It does not independently prove OWNER or grant T2.

This mechanism is a fallback rather than the preferred everyday UX.

## Phase 3B.7B — Passive RGB liveness — ACCEPTED FOR CURRENT POCKET-3 PROTOTYPE

### Selected PAD provider

MiniFASNet V1SE + V2 ensemble is the accepted current RGB PAD candidate.

OpenVINO `anti-spoof-mn3` is rejected for this Pocket-3 integration because genuine-live OWNER remained near-zero even after a bounded reference-style contextual crop retest.

### Why temporal fusion is mandatory

A static phone-photo attack produced an isolated single-frame MiniFAS apparent-real score of `0.8838`. Therefore a single PAD frame is never enough to create accepted liveness evidence.

Real-machine 15-frame temporal evidence showed:

- genuine normal-use live minimum: `0.9855`;
- phone-photo attack maximum: `0.2229`;
- prerecorded phone-video attack maximum: `0.0000` at reported precision.

### Accepted temporal liveness contract

`TemporalPassiveLiveness` is JARVIS-owned and bound to exactly one:

- Windows session;
- visual track;
- PAD provider.

Cross-session, cross-track, and cross-provider observations are rejected rather than fused.

A gap greater than `0.50 s` clears the observation window.

Decision rule:

```text
< 15 fresh observations  → INSUFFICIENT
15-frame median >= 0.95  → LIVE
15-frame median <= 0.50  → SPOOF
otherwise                → UNCERTAIN
```

Behavior:

- `LIVE` → typed short-lived `FACE_LIVENESS` `PASSED` evidence;
- `SPOOF` → typed `FAILED` evidence and fail closed;
- `UNCERTAIN` → `INSUFFICIENT` evidence and active challenge may be requested when the trust/risk path requires it;
- `INSUFFICIENT` → no trust upgrade.

Initial passive evidence TTL is `2.0 s`.

### Privacy and authority boundary

- raw frames/crops/PAD tensors/output vectors are not persisted by this evidence path;
- passive PAD alone does not prove OWNER;
- passive PAD alone does not grant T2;
- passive PAD never authorizes actions;
- RGB PAD is not treated as equivalent to depth/IR/ToF liveness.

The accepted decision is recorded in `docs/decisions/ADR-008_STEP_3_PASSIVE_RGB_LIVENESS.md`.

## What is intentionally NOT yet accepted

The following are **not** current accepted runtime architecture yet:

- runtime binding of encrypted OWNER SFace matching and passive liveness on the same subject track;
- automatic T2 derivation from face+liveness;
- attention implementation/acceptance;
- speaker identity/corroboration implementation/acceptance;
- depth/IR/ToF liveness hardware.

These belong to subsequent Phase 3B slices.

## Next architecture slice — 3B.8

3B.8 will integrate OWNER face recognition and passive/active liveness on the same stable visual track while still keeping T2 disabled during acceptance testing.

Target integration:

```text
expected Windows session
        +
stable visual track
        ↓
associated face/head
        ├── SFace → OWNER / UNKNOWN / AMBIGUOUS evidence
        └── MiniFAS temporal liveness → LIVE / UNCERTAIN / SPOOF
                                      └── active challenge fallback if needed
        ↓
fresh typed evidence bound to same session + same visual track
```

Only after that integrated evidence path is real-machine accepted should deterministic T2 corroborated-owner composition be enabled.
