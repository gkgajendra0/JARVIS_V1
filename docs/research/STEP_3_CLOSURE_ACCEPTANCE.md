# Step 3 — Final Closure Acceptance

Status: **PRODUCT SCOPE ACCEPTED ON FINALIZATION BRANCH — BOUNDED T2 PRODUCTION-ACCEPTED; SPOKEN ACTOR BINDING DEFERRED; PR #18 PENDING PROTECTED-MAIN MERGE**

Final acceptance date: 2026-09-04

## History

Step 3 was initially closed and merged through PR #15 on 2026-09-02 with T2 disabled. It was deliberately reopened on branch `step3-final-identity-completion` / draft PR #18 to complete additional identity/security work before moving on.

This record supersedes the earlier T2-disabled closure disposition. The authority foundation from the earlier closure remains valid; the finalization branch adds production bounded T2 and native overlap evidence while explicitly deferring spoken actor binding.

## Purpose

Step 3 establishes the minimum trustworthy identity, graduated-trust, authority, approval, audit, observability, and OWNER-evidence foundation required before later JARVIS capabilities can safely read, write, communicate, or control anything.

Step 3 does **not** promise perfect biometric perception or proof of the spoken actor for every turn. That remaining problem is intentionally bounded by the authority model and can be resumed later without blocking unrelated roadmap work.

---

## Accepted authority and governance foundation

Accepted:

- T0–T3 trust vocabulary;
- deterministic R0–R5 risk floors;
- immutable exact-action proposals;
- proposal-bound expiring approvals;
- fail-closed OPA policy boundary;
- final one-time execution revalidation;
- one-time execution permits;
- privacy-aware structured audit state;
- Windows-session invalidation on lock/user/session change;
- Windows Hello strong verification for T3;
- no face/voice/liveness/active-speaker/overlap/model output directly authorizes consequential execution.

Current risk boundary:

```text
R0 ROUTINE                  -> T0
R1 PRIVATE_READ             -> T2 + policy/direct-intent rules
R2 REVERSIBLE_LOCAL_CHANGE  -> T2 + policy/direct-intent rules
R3 PERSISTENT_OR_EXTERNAL   -> T2 + approval + actor_unambiguous
R4 CRITICAL                 -> T3 + proposal-bound strong verification
R5 RESTRICTED_DEV_ONLY      -> T3 + strong verification + extra context
```

---

## Accepted OWNER visual identity and liveness

Accepted:

- encrypted single OWNER profile;
- YuNet/SFace multi-prototype OWNER matching;
- temporal OWNER-candidate evidence;
- active liveness fallback;
- passive MiniFAS temporal RGB liveness;
- same-session/same-track OWNER context binding;
- Windows WTS active/unlocked session binding;
- freshness-bounded production T2 context;
- attention/gaze deferred because the movable Pocket3 is not a stable monitor-relative sensor.

### Production T2 composition

T2 `CORROBORATED_OWNER` is emitted only when:

1. temporal enrolled OWNER SFace evidence is `OWNER_CANDIDATE`;
2. passive MiniFAS liveness is `LIVE` for the same visual track;
3. fused evidence is fresh (2-second runtime TTL);
4. evidence session matches the current Windows WTS session; and
5. that Windows session is active and unlocked.

Current T2 deliberately emits:

```text
trust_tier = CORROBORATED_OWNER
actor_unambiguous = false
attention_state = UNAVAILABLE
```

Any stale/ambiguous/unknown/spoof/uncertain/session-mismatch/locked/unavailable state falls back to `UNVERIFIED`.

Decision: `docs/decisions/ADR-015_BOUNDED_T2_OWNER_CONTEXT.md`.

---

## Production T2 smoke — PASSED

Normal `jarvis-dev` was run on the actual target Windows machine with:

- DJI Pocket3 microphone/video;
- real OWNER face template;
- real MiniFAS liveness;
- real Windows WTS session;
- Gemini Live conversation;
- CAM++ shadow;
- LR-ASD shadow;
- native Sortformer overlap shadow on RTX 5060 Ti.

Observed behavior:

- OWNER face+liveness context loaded for bounded T2;
- context became `live_owner_candidate`;
- Vision reported one canonical person track while keeping tracking separate from identity;
- JARVIS first truthfully answered only that one person was visible;
- when asked about identity, JARVIS used the dedicated identity context and confirmed the visible person as OWNER;
- when directly asked identity + trust level, JARVIS reported OWNER and **Tier 2**;
- T3 was not claimed;
- CAM++/LR-ASD/Sortformer stayed diagnostic and non-authoritative.

Final direct response during the accepted smoke:

> You are corroborated as the owner. Your current trust level is Tier 2, which validates presence and liveness within this session.

**Disposition: bounded T2 production behavior is accepted.**

---

## Accepted audio ownership and conversation path

```text
Pocket3 microphone @ 48 kHz
        ↓
LiveKit MediaDevices only
WebRTC AEC + NS + HPF + AGC
        ↓
canonical timestamped user PCM
        ├── realtime conversation
        ├── CAM++ speaker shadow
        ├── LR-ASD active-speaker shadow
        └── native Sortformer overlap shadow
```

Dual independent Pocket3 microphone ownership is forbidden in production.

---

## CAM++ disposition

Accepted:

- explicit OWNER voice enrollment;
- encrypted persisted voice prototypes;
- raw enrollment audio discarded;
- asynchronous per-turn embedding/scoring;
- poor/short/missed speech returns `INSUFFICIENT`;
- no conversation self-enrollment/adaptation.

Observed real OWNER conversation similarities remain useful engineering evidence, but **no production OWNER-speaker threshold is promoted**.

CAM++ remains reusable evidence for future spoken actor binding.

---

## LR-ASD disposition

Real-machine testing established:

- OWNER visible + OWNER speech can score strongly positive;
- TV/off-camera speech can score strongly negative;
- replayed OWNER voice while OWNER is visually silent can score strongly negative;
- temporary head/visual loss correctly becomes insufficient;
- canonical 0 ms AV alignment is adequate;
- short-window genuine-OWNER recall varies across runs;
- OWNER + concurrent other/background speech can remain strongly positive because OWNER really is also speaking.

Therefore:

- no fixed AV offset correction is promoted;
- no LR-ASD authority threshold/window is promoted;
- LR-ASD remains corroborative/negative evidence;
- basic replay/alignment calibration is closed unless a new production failure/model change creates a new question.

---

## Native Sortformer overlap disposition

Native NeMo-Speech Sortformer is integrated on canonical PCM and runs on the RTX 5060 Ti without becoming a second microphone owner.

During the accepted production smoke it loaded successfully and returned `single_speaker` evidence on normal OWNER turns.

Current role:

- overlap/speaker-change diagnostic evidence;
- future input to spoken actor ambiguity;
- no direct authority effect.

---

## Explicitly deferred spoken actor binding

The remaining unresolved Step-3 hardening question is:

> Did this exact spoken command come from the OWNER?

This is deliberately deferred rather than blocking the roadmap.

Until resumed and accepted:

- normal T2 keeps `actor_unambiguous=false`;
- spoken R3 persistent/external actions remain fail-closed;
- CAM++/LR-ASD/Sortformer thresholds are not silently promoted;
- critical R4 actions remain T3/Windows Hello.

When resumed, actor binding must reuse the existing authority `InteractionContext.actor_unambiguous` field and combine multiple fresh signals rather than making any one model authoritative.

Decision: `docs/decisions/ADR-016_DEFER_SPOKEN_ACTOR_BINDING_AND_RESUME_ROADMAP.md`.

---

## Other deferred identity improvements

Backlog rather than Step-4 blockers:

1. non-OWNER speaker calibration as needed for actor binding;
2. voice replay/synthetic/cloned-voice defense if current research proves it materially useful;
3. short-turn speaker/actor continuity if natural use requires it;
4. stronger overlap/diarization semantics beyond current Sortformer evidence;
5. fixed monitor-relative attention/gaze;
6. lip reading / AV target-speaker extraction.

These are not reasons to reopen Step 3 by default.

---

## Final quality-gate state

- Scope: PASS for the amended Step-3 product boundary.
- Architecture ownership: PASS — one Pocket3 mic owner, one Vision path, one authority path.
- Automated validation: PASS for bounded-T2 checkpoint `e8a9073`; Code Quality run #1244 completed successfully.
- Human production validation: PASS — normal `jarvis-dev` T2 smoke accepted on 2026-09-04.
- Truthfulness: PASS — tracking and identity remained separate; T2 was reported only from the identity layer; T3 was not falsely claimed.
- Authority/risk: PASS — R3 remains fail-closed without actor binding; R4 remains T3/strong-verifier.
- Privacy: PASS — raw biometric media memory-only by default; explicit encrypted enrollment only.
- Resilience: PASS — diagnostic model evidence remains non-authoritative and missing/insufficient states fail closed.
- Documentation: being reconciled on PR #18 finalization branch.
- Git: protected-main merge of PR #18 remains pending explicit human approval.

## Completion disposition

**Step 3 product scope is accepted with spoken actor binding explicitly deferred.**

After documentation reconciliation and protected-main merge of PR #18, the roadmap may proceed to Step 4 without waiting for actor binding. Any future capability that needs spoken R3 persistent/external authority must either resume the actor-binding hardening package or use a separately accepted stronger verification path.
