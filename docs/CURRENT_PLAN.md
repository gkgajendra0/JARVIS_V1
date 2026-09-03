# JARVIS V1 Current Plan

## Active Step

**Step 3 — Identity, Graduated Trust, Authority, and Observability Foundation**

## Current Stage

**FINALIZATION — BOUNDED T2 ACCEPTED IN PRODUCTION; SPOKEN ACTOR BINDING IS THE PRIMARY REMAINING WORK**

This file is the operational source of truth for current work. Detailed evidence belongs
in `docs/research/`; significant architecture decisions belong in `docs/decisions/`.

---

## Owner decision on 2026-09-03

Step 3 will not remain blocked waiting for every biometric/voice diagnostic to become
perfect. The accepted OWNER face+liveness path is allowed to provide useful,
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
- native Sortformer overlap shadow on the RTX 5060 Ti;
- bounded T2 production trust bridge;
- no raw biometric media persistence by default;
- model/sensor evidence never grants an execution permit directly.

---

## Bounded T2 — ACCEPTED IN PRODUCTION

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

### Production smoke acceptance — 2026-09-04

Normal `jarvis-dev` on `step3-final-identity-completion` was run with the real Pocket3,
real Windows session, real OWNER template/liveness stack, Gemini Live voice runtime, and
all current Step-3 shadows enabled.

Observed production behavior:

- OWNER face+liveness context loaded successfully for bounded T2;
- current OWNER context became `live_owner_candidate`;
- Vision reported one canonical tracked person while keeping tracking separate from identity;
- JARVIS used the dedicated identity context and stated that the visible person was corroborated as OWNER;
- on the direct trust question, JARVIS reported `Tier 2` and described it as current-session presence/liveness trust;
- T3 was not claimed;
- CAM++, LR-ASD, and Sortformer remained diagnostic/non-authoritative;
- Sortformer reported single-speaker evidence during the smoke;
- the final bounded-T2 checkpoint (`e8a9073`) passed Code Quality CI run #1244.

**Disposition: bounded T2 production acceptance is complete. Do not reopen basic T2 or LR-ASD replay/alignment calibration without a new production failure.**

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

Normal `jarvis-dev` receives a dedicated `inspect_identity_context` tool when Vision
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

### 1. Spoken actor binding — PRIMARY REMAINING WORK

Derive `actor_unambiguous=true` only from accepted fresh turn-specific evidence. Any
speaker conflict, overlap, spoof concern, stale binding, lost track, or insufficient
evidence must fail closed or step up to Windows Hello according to risk.

Use the mature components already integrated where they help:

- CAM++ for enrolled-speaker similarity;
- LR-ASD for visible-speaker corroboration/negative evidence;
- native Sortformer for overlap/speaker-change ambiguity;
- Windows-session and fresh T2 context as the local identity/session anchor.

Do not make any one model the sole actor-binding authority.

### 2. Speaker calibration

Collect real non-OWNER CAM++ data only if required to choose a practical actor-binding
speaker band. Never use vendor defaults or OWNER-only data as a production threshold.
Keep this bounded: gather only the evidence needed for the actor-binding decision.

### 3. Voice anti-spoof

Keep speaker identity and spoof probability as separate evidence. Benchmark an
ASVspoof/SASV-class candidate only if research shows it materially improves the actual
spoken actor-binding threat on the JARVIS microphone route. Do not add anti-spoof tech
merely to complete a checklist.

### 4. Overlap / speaker-change evidence

The native Sortformer integration is operational and produced single-speaker evidence in
the production T2 smoke. Its remaining purpose in Step 3 is to support actor ambiguity,
especially simultaneous OWNER + other/background speech. It must stay on canonical PCM
and must not become a second microphone owner.

### 5. Short-turn continuity

Implement only if needed for practical actor binding. Very short turns may inherit a
recent accepted actor state only within the same session/conversation and only when no
overlap/change/spoof/device discontinuity exists. Inherited state can never be the sole
basis for stronger authority.

---

## Implementation / validation order from here

1. Research and finalize the minimum safe spoken actor-binding rule using the components already integrated; prefer mature existing techniques over new custom models.
2. Implement `actor_unambiguous=true` as fresh, turn-specific derived evidence with fail-closed conflict handling.
3. Validate bounded attack/degraded scenarios needed for that rule: OWNER turn, other-speaker turn, overlap, replay/off-camera speech, lost visual binding, and stale evidence.
4. Complete automated T2/T3 authority threat/degraded-mode checks.
5. Reconcile final Step-3 docs and human review.
6. Approve and merge draft PR #18 only when those Step-3 closure gates pass.
7. Resume Step 4.

---

## Hard boundaries

- T2 never implies T3.
- Critical actions remain T3 + strong verification.
- Current face+liveness T2 never sets `actor_unambiguous=true` by itself.
- Persistent/external actions require accepted actor binding in addition to T2.
- CAM++/LR-ASD/Sortformer thresholds are not silently promoted.
- No second microphone owner.
- No hidden cloud biometric processing.
- No raw biometric media persistence without explicit approved need.
- No model/provider output bypasses JARVIS policy/authority.
- Any missing/stale/conflicting identity evidence fails closed.

## Immediate Next Action

**Begin research-first spoken actor-binding finalization. Bounded T2 and basic LR-ASD replay/alignment validation are closed.**
