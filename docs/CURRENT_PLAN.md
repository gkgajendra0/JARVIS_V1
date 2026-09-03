# JARVIS V1 Current Plan

## Active Step

**Step 3 — Identity, Graduated Trust, Authority, and Observability Foundation**

## Current Stage

**FINALIZATION — BOUNDED T2 ACTIVATED; STEP 4 STILL PAUSED UNTIL ONE PRODUCTION SMOKE**

This file is the operational source of truth for current work. Detailed evidence belongs
in `docs/research/`; significant architecture decisions belong in `docs/decisions/`.

---

## Owner decision on 2026-09-03

Step 3 will not remain blocked waiting for every biometric/voice diagnostic to become
perfect. The accepted OWNER face+liveness path is now allowed to provide useful,
short-lived **T2 `CORROBORATED_OWNER`** context in the normal production JARVIS runtime.

This is a bounded trust decision, not a claim that biometrics are strong authentication.
T3 remains proposal-bound strong verification through Windows Hello/FIDO2-class intent
for critical actions.

ADR: `docs/decisions/ADR-015_BOUNDED_T2_OWNER_CONTEXT.md`.

---

## Accepted foundation — KEEP

Do not redesign these unless new evidence exposes a material problem:

- T0–T3 trust vocabulary and deterministic R0–R5 risk floors;
- immutable proposal fingerprints and proposal-bound approval records;
- OPA fail-closed policy boundary;
- final pre-execution revalidation and one-time permits;
- privacy-aware local audit;
- Windows-session invalidation;
- Windows Hello strong verification for T3;
- encrypted local OWNER profile with FACE + VOICE modalities;
- YuNet/SFace OWNER identity and accepted active/passive liveness;
- Pocket3 person/head/track Vision pipeline;
- one production Pocket3 microphone owner through LiveKit MediaDevices/WebRTC AEC + NS + HPF + AGC;
- canonical timestamped user PCM reused by conversation and diagnostics;
- CAM++ audio-first OWNER speaker shadow;
- LR-ASD visible-OWNER active-speaker diagnostics;
- no raw biometric media persistence by default;
- model/sensor evidence never grants an execution permit directly.

---

## Bounded T2 — IMPLEMENTED

The production trust bridge may emit T2 only when all are true:

1. temporal enrolled OWNER SFace evidence is `OWNER_CANDIDATE`;
2. passive MiniFAS liveness is `LIVE` for the same visual track;
3. fused OWNER evidence is fresh (2-second TTL);
4. evidence is bound to the current Windows WTS session; and
5. the Windows session is active and unlocked.

Any stale evidence, ambiguity, unknown subject, spoof/uncertain liveness, WTS mismatch,
Windows lock, or WTS failure drops the context to T0/UNVERIFIED.

The bridge deliberately emits:

```text
trust_tier = T2 / CORROBORATED_OWNER
actor_unambiguous = false
attention = unavailable
```

Seeing a live enrolled OWNER is useful presence/identity context, but it does not prove
that the OWNER spoke a specific command. Spoken actor binding remains separate.

### Current authority floors

```text
R0 routine                  -> T0
R1 private read             -> T2 + policy/direct-intent rules
R2 reversible local change  -> T2 + policy/direct-intent rules
R3 persistent/external      -> T2 + approval + actor_unambiguous
R4 critical                 -> T3 + proposal-bound strong verification
R5 restricted/dev-only      -> T3 + strong verification + extra context
```

Because current T2 intentionally has `actor_unambiguous=false`, persistent/external
spoken actions continue to fail closed until actor binding is accepted. Critical actions
remain T3 regardless.

---

## LR-ASD disposition — STOP BASIC CALIBRATION

Real-machine Pocket3 testing established enough for the current architectural decision:

- replay/phone speech while visible OWNER is silent repeatedly scores strongly negative;
- this includes playback of the OWNER's own recorded voice;
- canonical 0 ms A/V alignment is adequate; no fixed offset is promoted;
- full-phase genuine OWNER speech can score strongly positive;
- short 1-second and 2-second genuine-OWNER recall varies across runs;
- therefore no LR-ASD deployment threshold/window is promoted to authority.

LR-ASD remains useful **corroborative/negative evidence**, not the sole T2 gate. Do not
run more basic phone-replay/alignment experiments unless a concrete production failure
or model/runtime change creates a new question.

CAM++ and Sortformer likewise remain supporting evidence until their own thresholds and
actor-binding semantics are accepted. Voice alone cannot create T2.

---

## Production voice behavior

Normal `jarvis-dev` now receives a dedicated `inspect_identity_context` tool when Vision
OWNER context is configured. It exposes only derived trust information:

- current trust tier;
- T2 active/inactive;
- Windows-session validity;
- bound visual track id;
- actor-binding status; and
- non-sensitive reason codes.

It never exposes raw images, face templates, SFace similarity values, liveness scores,
or other biometric material.

Tracker IDs alone remain non-identity evidence. JARVIS may call a person GK/the OWNER
only when the dedicated identity context currently reports T2.

---

## Remaining Step-3 hardening

These are important, but they no longer block the existence of bounded T2:

### Spoken actor binding

Derive `actor_unambiguous=true` only from accepted fresh turn-specific evidence. Any
speaker conflict, overlap, spoof concern, stale binding, lost track, or insufficient
evidence must fail closed or step up to Windows Hello according to risk.

### Speaker calibration

Collect real non-OWNER CAM++ data before selecting an OWNER-speaker threshold. Never use
vendor defaults or OWNER-only data as a production threshold.

### Voice anti-spoof

Keep speaker identity and spoof probability as separate evidence. Benchmark an
ASVspoof/SASV-class candidate only if it materially improves the spoken actor-binding
problem on the JARVIS microphone route.

### Overlap / speaker-change evidence

Sortformer-class overlap evidence remains useful for Scenario G and actor ambiguity.
It must stay on canonical PCM and must not become a second microphone owner.

### Short-turn continuity

If later implemented, short turns may inherit recent accepted speaker state only within
the same session/conversation and only when no overlap/change/spoof/device discontinuity
exists. Inherited voice state can never be the sole basis for stronger authority.

---

## Implementation / validation order from here

1. Run CI for the bounded T2 implementation.
2. Run **one** normal production smoke: `jarvis-dev`, establish live OWNER context, ask
   JARVIS who it currently identifies/trusts and what trust level it sees.
3. If that smoke passes, record bounded T2 as accepted production behavior.
4. Continue spoken actor-binding/overlap/anti-spoof hardening as separate bounded work;
   do not reopen basic LR-ASD replay/alignment calibration without a new failure.
5. Complete automated threat/degraded-mode checks around T2/T3 policy boundaries.
6. Reconcile final Step-3 docs and human review.
7. Merge only after the Step-3 draft PR is intentionally approved, then resume Step 4.

---

## Hard boundaries

- T2 never implies T3.
- Critical actions remain T3 + strong verification.
- Current face+liveness T2 never sets `actor_unambiguous=true`.
- Persistent/external actions require accepted actor binding in addition to T2.
- CAM++/LR-ASD/Sortformer thresholds are not silently promoted.
- No second microphone owner.
- No hidden cloud biometric processing.
- No raw biometric media persistence without explicit approved need.
- No model/provider output bypasses JARVIS policy/authority.
- Any missing/stale/conflicting identity evidence fails closed.

## Immediate Next Action

**Finish CI on bounded T2, then perform one normal `jarvis-dev` identity/trust smoke. No
more LR-ASD replay/alignment experiments are required for this decision.**
