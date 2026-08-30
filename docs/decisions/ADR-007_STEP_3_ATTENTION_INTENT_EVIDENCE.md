# ADR-007 — Step 3 Attention and Intent-to-Engage Evidence

**Status:** ACCEPTED — IMPLEMENTATION DEFERRED PENDING FIXED MONITOR-MOUNTED CAMERA  
**Accepted:** 2026-08-30  
**Deferred:** 2026-08-30  
**Scope:** Attention/intent evidence for protected interaction

## Context

The Step-3 architecture separates identity evidence, trust, and authority, and also distinguishes between the OWNER merely being visible and the OWNER deliberately engaging with JARVIS now.

That distinction matters for privacy and accidental authorization. A recognized owner may be looking elsewhere, asleep, distracted, or speaking to another person. JARVIS should retain presence/identity continuity without treating visibility as interaction intent.

Apple Face ID provides a useful design principle: recognition can require eyes-open/attention-to-device evidence, while its actual strong security also relies on dedicated TrueDepth IR/depth hardware and secure platform processing. JARVIS adopts the interaction principle without claiming Face-ID-equivalent security.

## Decision

1. `ATTENTION` remains a first-class typed `IdentityEvidence` modality.
2. A future JARVIS-owned `AttentionEvidenceProvider` must operate only on the already selected/eligible head track; it must not create a second full-frame surveillance pipeline.
3. `OWNER_ATTENTIVE` is an interaction predicate, **not a trust tier**. It is layered on top of an already corroborated OWNER context; it is not a prerequisite for defining T2 itself.
4. Looking away does not revoke OWNER identity by itself; it only removes or prevents fresh intent-to-engage evidence.
5. Policy may require `OWNER_ATTENTIVE` before private ambient disclosure or R3 spoken consequential approval.
6. R3 spoken approval additionally requires an exact pending proposal, deterministic approval parsing, unambiguous speaking-actor association, freshness, and one-time receipt semantics. If the actor cannot be bound safely, escalate to `StrongVerifier` or deny.
7. R4 critical actions remain Windows Hello/FIDO2 gated regardless of attention state.
8. Attention evidence is short-lived and memory-only by default. Do not persist eye crops, gaze vectors, iris coordinates, behavioral gaze histories, or inferred emotion/fatigue/interest.
9. Repeated **explicit biometric elevation attempts** that fail required checks may be throttled. Passive look-away, ordinary absence, or another person passing through the frame is not a failed authentication attempt.
10. Until an accepted attention provider exists, JARVIS must not synthesize `OWNER_ATTENTIVE` from generic camera visibility, face match, liveness, wake word, or conversation state. A policy that genuinely requires attention must fail closed or escalate to stronger explicit verification.

## Implementation deferral — DJI Pocket 3 geometry

The initial implementation proposal used MediaPipe Face Landmarker signals such as eye-open state, look blendshapes, head pose, iris/eye geometry, and temporal stability on the Pocket 3.

That implementation is deliberately deferred because the Pocket 3 is a movable gimbal camera rather than a fixed monitor-mounted webcam. Camera-relative gaze/head angles therefore change whenever the camera position or gimbal orientation changes. Requiring repeated camera-to-screen calibration would create poor everyday UX and would still risk confusing "looking at the monitor" with "engaging with JARVIS".

JARVIS will revisit this slice when a fixed monitor-mounted webcam or a stronger accepted eye/attention sensor is available. At that point the provider should be researched again using the then-current hardware and technology rather than blindly implementing the old Pocket-3 proposal.

## Architectural correction

Attention is **not** part of the base definition of T2 `CORROBORATED_OWNER`.

The intended layering is:

```text
corroborated OWNER evidence
        ↓
T2 CORROBORATED_OWNER
        +
fresh same-owner attention/intent evidence (when available/required)
        ↓
OWNER_ATTENTIVE interaction predicate
```

This avoids a circular dependency and keeps identity/trust separate from interaction intent.

Voice-originated protected interactions may separately require active-speaker association and/or explicit strong verification even when T2 is present.

## Future provider direction

When suitable fixed hardware is available, research should compare current options rather than assuming the original implementation:

- MediaPipe Face Landmarker / equivalent head-eye geometry;
- fixed monitor-relative gaze calibration only if calibration can be stable and low-friction;
- hardware eye tracking if available;
- depth/IR attention signals if future hardware provides them;
- interaction-context signals only as supporting evidence, never as a substitute for visual/actor binding when policy requires attention.

## Alternatives considered

- Treat face visibility as interaction intent — rejected.
- Require eye contact with the movable Pocket 3 — rejected.
- Recalibrate every time the Pocket 3 moves — rejected as unacceptable UX.
- Add attention as T4 or direct authorization — rejected.
- Use iris-center geometry alone as gaze truth — rejected.
- Store continuous gaze history — rejected as unnecessary surveillance.
- Claim iris scanning or Face-ID-equivalent authentication from RGB hardware — rejected.

## Consequences and tradeoffs

- Step 3 can continue without pretending the current movable camera provides reliable attention evidence.
- T2 may be implemented independently as corroborated OWNER identity/presence once its own evidence requirements are met.
- Protected interactions that truly require attention must escalate/deny until an accepted attention provider exists.
- Attention remains a deferred hardware-dependent enhancement and does not block unrelated identity, speaker, policy, audit, or authority work.

## Replacement boundary

`AttentionEvidenceProvider` remains replaceable. Any future replacement must emit the same JARVIS-owned typed evidence and may not directly change trust or action-authority state.

## Conditions that should trigger implementation/reconsideration

Revisit this ADR when:

- a fixed monitor-mounted webcam becomes part of the accepted hardware;
- a depth/IR/eye-tracking sensor becomes available;
- multi-person active-speaker association creates a concrete need for visual engagement evidence;
- accessibility needs require alternative intent signals;
- future remote/mobile clients need a different attention model.
