# Pocket 3 OWNER Continuity Acceptance — 2026-09-20

**Status: OWNER-MACHINE ACCEPTED for issue #56 / PR #61**

## Scope

Validate that a Pocket 3 OWNER lock, once established from fresh face + liveness evidence, survives temporary biometric/head-evidence gaps while the exact already-authorized visual tracker identity remains continuous. Native DJI tracking must never become identity evidence and a genuinely lost OWNER must still require fresh verification on return.

## Owner-machine evidence

The accepted run used PR #61 with the continuity implementation at core revision `c46eb6236d3c6cb544d02198db7e05dc0fd2b156`; temporary acquisition diagnostics were present only to expose the evidence pipeline and were removed after validation.

Observed sequence:

1. Vision produced one person track and one head.
2. The 15-sample identity/liveness windows initially remained insufficient/ambiguous.
3. Identity crossed the OWNER candidate threshold and passive liveness eventually became LIVE.
4. JARVIS sent the initial A6 OWNER target.
5. Native DJI tracking confirmed the lock.
6. JARVIS persisted the exact authorized visual tracker ID:
   - `Pocket 3 OWNER track continuity authorized: track_id=0`
7. Immediately after lock, fused face/liveness evidence fell back to uncertain/ambiguous states and later repeatedly lost usable face/head evidence.
8. JARVIS explicitly preserved the already-authorized track:
   - `Pocket 3 preserving authorized OWNER continuity through biometric/head evidence gap: track_id=0`
9. For the remainder of the captured run, the Pocket state stayed `locked` while:
   - identity repeatedly moved between OWNER-candidate, ambiguous and insufficient windows;
   - passive liveness repeatedly became uncertain;
   - the face detector repeatedly reported no face in the head crop;
   - head association temporarily disappeared while the bound visual track remained alive.
10. No false `confirmed_owner_absence`, A6 clear-target, or confirmed-owner-loss recenter occurred after the lock.

## Security semantics preserved

- Fresh face + liveness evidence is still required for initial acquisition and reacquisition.
- DJI native tracking is not treated as identity evidence.
- Continuity applies only to the exact visual tracker ID that was fresh-OWNER-authorized and then confirmed by native lock.
- A different visual track cannot inherit the authorization.
- The continuity binding is released on confirmed OWNER absence or tracking-session reset.
- No authority, Windows-lock, or protected-main behavior changed.

## CI

The core continuity implementation had already passed the complete code-quality workflow at `c46eb6236d3c6cb544d02198db7e05dc0fd2b156`. A later temporary diagnostics-only revision reproduced the accepted owner-machine behavior; those diagnostics were then removed before merge.

## Result

Issue #56 is accepted as fixed. The reliability cleanup sequence advances to issue #57: durable WorkDelivery TTS retry/backoff.
