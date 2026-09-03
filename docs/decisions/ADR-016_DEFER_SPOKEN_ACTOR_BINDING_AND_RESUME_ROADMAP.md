# ADR-016 — Defer Spoken Actor Binding and Resume the Roadmap

- **Status:** Accepted
- **Date:** 2026-09-04
- **Scope:** Step 3 closure and future authority hardening

## Context

Step 3 now has a production-accepted bounded T2 `CORROBORATED_OWNER` state based on fresh enrolled OWNER face evidence, passive liveness, matching active/unlocked Windows WTS session, and short evidence freshness.

The remaining unresolved identity problem is **turn-specific spoken actor binding**: proving that a particular spoken command was actually issued by the OWNER rather than merely occurring while the OWNER is present.

The repository already contains mature supporting components for future actor binding:

- CAM++ enrolled-speaker similarity;
- LR-ASD visible active-speaker evidence;
- native Sortformer overlap/speaker-change evidence;
- fresh T2 OWNER presence and Windows-session binding.

However, promoting those signals into `actor_unambiguous=true` would require additional calibration and attack/degraded validation. Continuing that work now would block unrelated JARVIS capabilities even though the current authority model can safely fail closed without it.

## Decision

Step 3 is closed for the current product scope with **spoken actor binding explicitly deferred**.

The accepted production authority boundary is:

```text
R0 ROUTINE                  -> T0
R1 PRIVATE_READ             -> T2 + policy/direct-intent rules
R2 REVERSIBLE_LOCAL_CHANGE  -> T2 + policy/direct-intent rules
R3 PERSISTENT_OR_EXTERNAL   -> T2 + approval + actor_unambiguous
R4 CRITICAL                 -> T3 + proposal-bound strong verification
R5 RESTRICTED_DEV_ONLY      -> T3 + strong verification + extra context
```

Current bounded T2 deliberately emits:

```text
trust_tier = CORROBORATED_OWNER
actor_unambiguous = false
```

Therefore spoken R3 persistent/external actions remain unavailable/fail-closed until actor binding is intentionally resumed and accepted. Critical R4 actions remain T3/Windows-Hello strong-verification work regardless.

Actor binding is **not a blocker for Step 4 or other unrelated roadmap research/implementation**.

## Why this choice

This preserves both progress and safety:

- JARVIS can use accepted T2 OWNER context for bounded low/medium-risk behavior now;
- unfinished probabilistic voice/AV evidence does not receive authority merely to finish a milestone;
- later memory/context and other capabilities can progress;
- the missing R3 spoken-actor capability remains explicit rather than silently assumed;
- existing CAM++/LR-ASD/Sortformer work is retained as reusable evidence rather than discarded.

## Deferred hardening package

When actor binding is resumed, treat the following as one bounded package rather than separate mandatory projects:

1. define a turn-specific multi-signal actor-binding rule;
2. calibrate CAM++ with real non-OWNER data only as necessary;
3. use LR-ASD as corroborative/negative AV evidence, not sole authority;
4. use Sortformer overlap/speaker-change evidence to detect ambiguity;
5. evaluate voice anti-spoof only if research shows it materially improves the real threat;
6. add short-turn continuity only if needed for natural use;
7. validate OWNER, non-OWNER, overlap, replay/off-camera, lost visual binding, and stale-evidence scenarios;
8. only then allow the TrustEvaluator to derive `actor_unambiguous=true`.

## Consequences and tradeoffs

Positive:

- Step 3 no longer blocks the wider JARVIS roadmap.
- T2 remains useful and production-accepted.
- R3 stays safe by default.
- No additional biometric threshold is promoted without evidence.

Tradeoff:

- JARVIS cannot yet safely authorize spoken persistent/external actions solely from a normal voice turn while relying on T2.
- Such actions must remain unavailable, use a future accepted actor-binding path, or step up to a stronger explicit verification path when designed.

## Replacement boundary

The deferred actor-binding implementation must plug into the existing authority `InteractionContext.actor_unambiguous` field and must not create a parallel authorization system.

No biometric/model output may directly mint execution permission. The normal path remains:

```text
identity/context evidence
-> trust/context derivation
-> ActionProposal
-> deterministic risk floor
-> OPA policy
-> approval/strong verification as required
-> final revalidation
-> one-time execution permit
```

## Reconsideration triggers

Resume actor-binding hardening when any of these becomes true:

- a roadmap capability requires spoken R3 persistent/external authority;
- real usage shows T2-only local behavior is insufficient;
- a materially better mature speaker/ASD/anti-spoof technology changes the cost/benefit;
- a production failure exposes a gap that cannot be handled by current fail-closed policy.

Until then, do not reopen basic LR-ASD replay/alignment calibration or promote CAM++/Sortformer thresholds merely to complete a checklist.
