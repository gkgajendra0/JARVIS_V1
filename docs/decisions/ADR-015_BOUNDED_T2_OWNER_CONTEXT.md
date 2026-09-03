# ADR-015 — Bounded T2 OWNER Context

- **Status:** Accepted for production runtime on the Step-3 branch
- **Date:** 2026-09-03
- **Scope:** Step 3 identity/trust/authority

## Decision

JARVIS now allows the already-accepted local OWNER face+liveness path to grant the
short-lived trust tier **T2 — CORROBORATED_OWNER** when all of the following are true:

1. the enrolled OWNER temporal SFace evidence is in the OWNER-candidate band;
2. passive MiniFAS liveness is LIVE for the same visual track;
3. the fused evidence is fresh (2-second runtime TTL);
4. the evidence is bound to the current Windows WTS session; and
5. the Windows session is active and unlocked.

This T2 bridge is active in the normal production voice runtime. It is independent of
CAM++ speaker-threshold selection, LR-ASD threshold selection, and Sortformer overlap
thresholds.

## Why

Step 3 had reached diminishing returns by keeping all identity evidence shadow-only.
Real-machine testing established that the local OWNER face+liveness route is useful and
that replayed OWNER speech can be strongly rejected by LR-ASD, but short-window
active-speaker recall is not yet stable enough to make LR-ASD a mandatory authority
gate. Blocking all T2 until every voice/overlap component was perfect would prevent the
accepted visual identity stack from providing useful bounded trust.

The chosen architecture therefore separates **contextual trust** from **strong
authentication**:

- T2 is a short-lived, risk-bounded local confidence state.
- T3 remains explicit strong verification, currently Windows Hello/FIDO2-class intent.
- Biometrics and behavioral/risk signals do not replace stronger authentication for
  critical operations.

This is consistent with the risk-based separation in NIST SP 800-63B-4 (July 2025):
biometric/risk signals can be useful controls, while higher-assurance authentication
continues to require stronger authenticator properties.

References:

- https://csrc.nist.gov/pubs/sp/800/63/b/4/final
- https://pages.nist.gov/800-63-FAQ/

## Authority boundaries

The existing authority risk floors remain intentionally conservative:

| Risk class | Minimum trust | Additional boundary |
| --- | --- | --- |
| ROUTINE | T0 | none |
| PRIVATE_READ | T2 | policy/direct-intent rules still apply |
| REVERSIBLE_LOCAL_CHANGE | T2 | policy/direct-intent rules still apply |
| PERSISTENT_OR_EXTERNAL | T2 | **actor binding must be unambiguous** |
| CRITICAL | T3 | **strong verification required** |
| RESTRICTED_DEV_ONLY | T3 | strong verification + attention + actor binding |

The new T2 provider deliberately sets `actor_unambiguous=False`. Seeing a live enrolled
OWNER proves useful local presence context, but it does **not** prove that the OWNER
spoke a specific command. Until spoken actor binding is separately accepted,
persistent/external actions therefore fail closed even when T2 is active.

## Voice-runtime behavior

The production voice tool surface now exposes a dedicated derived
`inspect_identity_context` tool. It reports only:

- current trust tier;
- whether T2 is active;
- whether the Windows session is valid;
- the bound visual track id;
- actor-binding status; and
- non-sensitive reason codes.

It never exposes raw images, face templates, liveness scores, SFace similarities, or
other biometric material. Tracker IDs by themselves remain non-identity evidence.

## What remains shadow-only

The following continue to have **no direct authority effect**:

- CAM++ enrolled-speaker scoring;
- LR-ASD active-speaker scores/thresholds;
- Sortformer overlap scores/thresholds;
- prototype admission from spoken turns.

These signals may later strengthen, veto, or bind T2/T3 decisions after their own
acceptance work, but T2 activation does not wait for them.

## Failure behavior

T2 drops immediately to UNVERIFIED when any required condition is absent, including:

- stale or insufficient OWNER evidence;
- Windows lock;
- WTS unavailability;
- WTS/OWNER session mismatch;
- identity ambiguity or unknown subject;
- passive liveness uncertainty/spoof result.

No T3 state can be produced by this bridge.

## Acceptance

Automated tests must cover at least:

- fresh live OWNER + matching unlocked WTS => T2;
- stale evidence => T0;
- WTS mismatch => T0;
- Windows locked/unavailable => T0;
- non-live binding => no T2;
- actor binding remains false;
- PERSISTENT_OR_EXTERNAL requires actor binding; and
- CRITICAL remains T3 + strong verification.

A single real-machine production smoke test is sufficient after CI: start normal
`jarvis-dev`, stand in front of Pocket3 until OWNER context becomes live, then ask
JARVIS what identity/trust level it currently sees. No further LR-ASD calibration is
required for this decision.
