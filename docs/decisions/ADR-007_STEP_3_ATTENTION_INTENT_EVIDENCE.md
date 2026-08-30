# ADR-007 — Step 3 Attention and Intent-to-Engage Evidence

**Status:** ACCEPTED  
**Accepted:** 2026-08-30  
**Scope:** Apple-inspired attention/intent evidence for protected interaction

## Context

The original Step-3 proposal correctly separated identity evidence, trust, and authority, but did not explicitly distinguish between the OWNER merely being visible and the OWNER deliberately attending to JARVIS now.

That distinction matters for privacy and accidental authorization. A recognized owner may be looking elsewhere, asleep, distracted, or speaking to another person. JARVIS should retain presence/identity continuity without treating visibility as interaction intent.

Apple Face ID provides a useful design principle: recognition can require eyes-open/attention-to-device evidence, while its actual strong security also relies on dedicated TrueDepth IR/depth hardware and secure platform processing. The DJI Pocket 3 is RGB-only, so JARVIS adopts the interaction principle without claiming Face-ID-equivalent security.

## Decision

1. Add `ATTENTION` as a first-class typed `IdentityEvidence` modality.
2. Add a JARVIS-owned `AttentionEvidenceProvider` operating only on the already selected/eligible head track; it must not create a second full-frame surveillance pipeline.
3. Use MediaPipe Face Landmarker as the preferred initial provider because it is already selected for active liveness and exposes eye/open-look blendshapes, face landmarks, iris/eye geometry, and facial transformation data.
4. The attention classifier combines multiple signals rather than treating iris-center position alone as gaze truth:
   - eye-open state;
   - left/right look blendshapes;
   - head pose/facial transform;
   - eye/iris landmark geometry;
   - same-track continuity;
   - temporal stability across several frames.
5. Define `OWNER_ATTENTIVE` as an interaction predicate, **not a new trust tier**. Conceptually it requires T2 `CORROBORATED_OWNER`, fresh attention on the same owner track, and no relevant actor ambiguity.
6. Looking away does not revoke OWNER identity by itself; it removes fresh intent-to-engage evidence.
7. Policy may require `OWNER_ATTENTIVE` before private ambient disclosure or R3 spoken consequential approval.
8. R3 spoken approval additionally requires an exact pending proposal, deterministic approval parsing, unambiguous speaking-actor association, freshness, and one-time receipt semantics. If the actor cannot be bound safely, escalate to `StrongVerifier` or deny.
9. R4 critical actions remain Windows Hello/FIDO2 gated regardless of attention state.
10. Attention evidence is short-lived and memory-only by default. Do not persist eye crops, gaze vectors, iris coordinates, behavioral gaze histories, or inferred emotion/fatigue/interest.
11. Repeated **explicit biometric elevation attempts** that fail face/liveness/attention checks are throttled. After five consecutive failed explicit attempts in the initial policy, ambient elevation enters cooldown/escalation and the protected interaction must use Windows Hello rather than weakening thresholds.
12. Passive look-away, ordinary absence, or another person passing through the frame does not count as a failed authentication attempt.
13. OpenVINO `gaze-estimation-adas-0002` is a benchmark fallback only if the MediaPipe-based classifier cannot meet real Pocket-3 reliability/latency gates.

## Alternatives considered

- Treat face visibility as interaction intent — rejected.
- Add attention as T4 or as direct authorization — rejected.
- Use iris-center geometry alone as gaze detection — rejected.
- Store continuous gaze history for convenience — rejected as unnecessary surveillance.
- Claim iris scanning or Face-ID-equivalent authentication from the Pocket 3 — rejected.
- Add a second heavy gaze framework immediately — rejected; benchmark only if the existing MediaPipe path is insufficient.

## Why this choice

The decision improves both security and user experience without weakening the authority model. JARVIS can naturally know that the owner is present while requiring a fresh sign of engagement before private or consequential spoken interaction. Reusing the existing MediaPipe path minimizes dependency and compute cost.

## Consequences and tradeoffs

- Sunglasses, unusual lighting, camera angle, or partial occlusion may make attention evidence unavailable or ambiguous.
- Attention thresholds require calibration on the real Pocket 3 setup and must tolerate natural head/eye movement without encouraging users to stare unnaturally.
- False negatives must degrade to stronger verification, not silently lower the threshold.
- RGB attention/liveness remains spoofable supporting evidence and cannot replace Windows Hello/FIDO2 for critical authority.

## Replacement boundary

`AttentionEvidenceProvider` is replaceable. Any replacement must emit the same JARVIS-owned typed evidence and may not directly change trust or authority state.

## Conditions that should trigger reconsideration

Revisit this ADR if:

- MediaPipe cannot meet real-world attention reliability/latency targets;
- a depth/IR/eye-tracking sensor becomes part of the accepted hardware;
- multi-person active-speaker association becomes necessary for normal use;
- accessibility needs require alternative intent signals;
- future remote/mobile clients need a different attention model;
- user testing shows the attention gate creates excessive friction or fails to prevent accidental private/spoken interactions.
