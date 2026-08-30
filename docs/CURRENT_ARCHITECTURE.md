# JARVIS V1 Current Architecture

## Status

**IMPLEMENTED + HUMAN-ACCEPTED ARCHITECTURE THROUGH PHASE 3B.8. PHASE 3B.9 ATTENTION / INTENT-TO-ENGAGE EVIDENCE IS NEXT. T2 REMAINS DISABLED.**

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
- passive RGB presentation-attack detection using MiniFAS + JARVIS-owned temporal fusion for the current Pocket-3 prototype;
- runtime temporal OWNER identity + liveness binding on the same Windows session and visual track, with T2 explicitly disabled.

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

## Phase 3B.8 — Runtime OWNER identity + liveness binding — ACCEPTED

### Runtime identity contract

The accepted 3B.8 path decrypts the enrolled OWNER face template through the accepted profile-store boundary and requires exact compatibility with the pinned SFace runtime before comparing embeddings.

Compatibility includes:

- face modality;
- `sface-prototype-set-v1` template format;
- JARVIS SFace provider id;
- current model id/revision/SHA-256;
- embedding dimension;
- enrollment compatibility version.

Mismatch fails closed.

Temporal identity is bound to exactly one Windows session, visual track, and face provider. A 15-observation median uses the current provisional evidence-only band:

```text
<15 fresh observations        → INSUFFICIENT
median max-prototype >= 0.65 → OWNER_CANDIDATE
median max-prototype <= 0.35 → UNKNOWN
otherwise                    → AMBIGUOUS
```

This threshold is **not authoritative OWNER-vs-UNKNOWN authentication** because a consenting live non-owner calibration dataset is still unavailable.

### Same-track OWNER + liveness binding

```text
active/unlocked Windows session
        +
selected stable visual track
        ↓
associated head/face
        ├── YuNet/SFace → temporal OWNER identity
        └── MiniFAS → temporal passive liveness
        ↓
same session + same track + co-fresh observations
        ↓
combined evidence state
```

Accepted combined states:

```text
OWNER_CANDIDATE + LIVE      → LIVE_OWNER_CANDIDATE
OWNER_CANDIDATE + UNCERTAIN → ACTIVE_CHALLENGE_ELIGIBLE
OWNER_CANDIDATE + SPOOF     → SPOOFED_OWNER_PRESENTATION
UNKNOWN + any liveness      → UNKNOWN_SUBJECT
AMBIGUOUS + any liveness    → AMBIGUOUS_SUBJECT
anything insufficient       → INSUFFICIENT
```

`LIVE_OWNER_CANDIDATE` is deliberately **not** T2.

### Invalidation behavior

- identity/liveness gaps > `0.50 s` clear their temporal windows;
- cross-session, cross-track, and cross-provider observations are rejected;
- selected-target loss immediately discards both temporal windows, clears the combined result, stops collection, and requires fresh selection/evidence;
- target-id change resets both windows;
- Windows lock/session transition clears evidence and terminates the evidence context fail-closed;
- stale identity/liveness observations cannot be combined beyond the co-freshness bound.

### Real-machine acceptance

Real Pocket-3 live OWNER integration:

- 300 valid integrated observations;
- OWNER max-prototype cosine median `0.7982`;
- MiniFAS real probability median `0.9998`;
- 272 post-warm-up/reset observations reached `LIVE_OWNER_CANDIDATE`;
- no raw biometric persistence;
- T2 remained disabled.

Real Windows WTS lock acceptance produced:

```text
session_invalidated = True
STEP_3B8_OWNER_LIVENESS_EVIDENCE = SESSION_INVALIDATED_FAIL_CLOSED
```

The already accepted real Pocket-3 3B.7B phone-photo/video attack evidence is reused rather than redundantly recollected. Automated 3B.8 tests verify deterministic spoof binding and cross-track/co-freshness behavior.

### Authority boundary

- `FACE_MATCH` evidence is typed but provisional;
- liveness does not repair ambiguous identity;
- attention is not inferred from face visibility;
- `face_evidence_grants_T2 = False` remains invariant;
- no 3B.8 result directly authorizes any action.

Acceptance evidence is recorded in `docs/research/STEP_3B8_OWNER_LIVENESS_ACCEPTANCE_RESULTS.md`.

## What is intentionally NOT yet accepted

The following are **not** current accepted runtime architecture yet:

- automatic T2 derivation from face+liveness;
- attention/intent-to-engage implementation/acceptance;
- speaker identity/corroboration implementation/acceptance;
- depth/IR/ToF liveness hardware.

These belong to subsequent Phase 3B slices.

## Next architecture slice — 3B.9 Attention / intent-to-engage

ADR-007 is already accepted. 3B.9 will implement attention evidence on the same selected/head-associated OWNER track rather than treating visibility as intent.

Target integration:

```text
same selected OWNER/head track
        ↓
MediaPipe Face Landmarker
        ├── eye-open state
        ├── look blendshapes
        ├── head pose / facial transform
        ├── iris/eye geometry
        └── temporal stability
        ↓
ATTENTIVE / NOT_ATTENTIVE / AMBIGUOUS
        ↓
short-lived typed ATTENTION evidence
```

Looking away removes fresh intent evidence but does not revoke OWNER identity. Attention itself is not permission and does not create a new trust tier.

Only after attention/intent evidence is implemented and real-machine accepted should deterministic T2 `CORROBORATED_OWNER` composition be implemented against the full accepted evidence predicate.
