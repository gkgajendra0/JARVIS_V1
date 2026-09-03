# JARVIS V1 Current Plan

## Active state

**STEP 3 PRODUCT SCOPE ACCEPTED — DOCUMENTATION / PROTECTED-MAIN MERGE REMAIN. SPOKEN ACTOR BINDING IS EXPLICITLY DEFERRED.**

After the Step-3 branch is reviewed and merged, the next active product slice is **Step 4 — Live Context and Personal Memory**.

This file is the operational source of truth for current work. Detailed evidence belongs in `docs/research/`; durable architecture decisions belong in `docs/decisions/`.

---

## Step 3 accepted outcome

The following are accepted production foundations:

- T0–T3 trust vocabulary and deterministic R0–R5 risk floors;
- immutable ActionProposal fingerprints and proposal-bound approvals;
- fail-closed OPA policy boundary;
- final pre-execution revalidation and one-time execution permits;
- privacy-aware local audit;
- Windows-session invalidation;
- Windows Hello strong verification for T3;
- encrypted local OWNER profile with FACE + VOICE modalities;
- YuNet/SFace temporal OWNER identity;
- MiniFAS passive liveness plus active-liveness fallback;
- Pocket3 person/head/track Vision pipeline;
- one production Pocket3 microphone owner through LiveKit MediaDevices/WebRTC AEC + NS + HPF + AGC;
- canonical timestamped user PCM shared by conversation and diagnostics;
- CAM++ enrolled-speaker shadow;
- LR-ASD visible active-speaker shadow;
- native Sortformer overlap/speaker-change shadow on RTX 5060 Ti;
- production bounded T2 `CORROBORATED_OWNER` bridge;
- no raw biometric media persistence by default;
- no model/sensor output directly grants execution permission.

### Bounded T2 production acceptance

Normal `jarvis-dev` on the real target machine passed the production smoke on 2026-09-04:

- OWNER face+liveness context loaded successfully;
- OWNER context became `live_owner_candidate`;
- Vision kept tracking count separate from identity;
- JARVIS used the dedicated identity context and identified the visible user as OWNER;
- JARVIS reported **Tier 2** when directly asked for current trust;
- T3 was not falsely claimed;
- CAM++, LR-ASD, and Sortformer remained non-authoritative diagnostics;
- Code Quality CI run #1244 passed on checkpoint `e8a9073`.

**Bounded T2 is accepted. Basic T2 and LR-ASD replay/alignment calibration are closed unless a new production failure appears.**

---

## Accepted authority boundary

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
trust_tier = T2 / CORROBORATED_OWNER
actor_unambiguous = false
attention = unavailable
```

This means JARVIS can know **GK/the OWNER is currently present and live** without pretending that every spoken command has been proven to come from GK.

---

## Explicitly deferred Step-3 hardening

### Spoken actor binding

Turn-specific spoken actor binding is **deferred**, not lost and not silently treated as complete.

The unresolved question is:

> Did this exact spoken command come from the OWNER?

Existing reusable evidence for future work:

- CAM++ enrolled-speaker similarity;
- LR-ASD visible-speaker corroboration/negative evidence;
- native Sortformer overlap/speaker-change evidence;
- fresh T2 OWNER presence;
- Windows-session binding.

Until actor binding is intentionally resumed and accepted:

- `actor_unambiguous` remains false for normal bounded T2;
- spoken R3 persistent/external actions remain fail-closed;
- no CAM++/LR-ASD/Sortformer threshold is promoted merely to complete Step 3;
- critical R4 actions remain T3/Windows Hello regardless.

Decision: `docs/decisions/ADR-016_DEFER_SPOKEN_ACTOR_BINDING_AND_RESUME_ROADMAP.md`.

Actor binding is **not a blocker for Step 4 or unrelated roadmap work**.

---

## Other deferred identity improvements

These are backlog items, not current Step-4 prerequisites:

- real non-OWNER speaker calibration unless needed by future actor binding;
- voice replay/synthetic/cloned-voice countermeasures unless research shows they materially improve a real authority threat;
- short-turn speaker continuity unless needed for practical actor binding;
- stronger overlap/diarization semantics beyond the current native Sortformer evidence;
- fixed monitor-relative attention/gaze sensing;
- lip reading / target-speaker extraction.

Do not reopen them simply because they exist in old research notes.

---

## Hard boundaries that future steps inherit

- T2 never implies T3.
- Critical actions remain T3 + strong verification.
- Current face+liveness T2 never sets `actor_unambiguous=true` by itself.
- Spoken R3 persistent/external actions remain unavailable until actor binding is accepted.
- No second production Pocket3 microphone owner.
- No hidden cloud biometric processing.
- No raw biometric media persistence without an explicit approved need.
- No model/provider output bypasses JARVIS policy/authority.
- Missing, stale, ambiguous, or conflicting identity evidence fails closed.
- Future capabilities must reuse the existing authority path rather than invent parallel permission systems.

---

## Closure actions before Step 4 branch work

1. Reconcile Step-3 source-of-truth documentation to bounded T2 + deferred actor binding.
2. Ensure final Step-3 branch CI is green.
3. Review PR #18 as the coherent Step-3 final checkpoint.
4. Merge through protected `main` only after explicit human approval.
5. Restore any intentionally stashed local-only helper files after branch transition if still needed.
6. Begin Step 4 with requirements recovery and current-technology research; do not carry speculative old memory architecture forward automatically.

## Immediate next action

**Finish Step-3 documentation/Git closure, then begin Step 4 research. Spoken actor binding remains a documented future hardening package rather than a current blocker.**
