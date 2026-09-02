# JARVIS V1 Current Plan

## Active Step

**Step 4 — Live Context and Personal Memory**

## Current Stage

**STEP 3 HUMAN-ACCEPTED AND CLOSING THROUGH PROTECTED-MAIN PR — STEP 4 RESEARCH/PREPARATION IS NEXT**

This file is the operational source of truth for current work. Detailed evidence belongs in `docs/research/`; significant architecture decisions belong in `docs/decisions/`.

---

## Step 3 closure status

Step 3 established the minimum trustworthy identity, graduated-trust, authority, approval, audit, observability, and owner-evidence foundation required before later JARVIS capabilities may read, write, communicate, or control anything.

Accepted Step-3 outcomes:

- deterministic trust vocabulary T0–T3;
- deterministic action-risk floors R0–R5;
- immutable proposal fingerprints and proposal-bound approvals;
- fail-closed policy boundary;
- one-time final execution revalidation;
- privacy-aware audit state;
- Windows-session invalidation;
- Windows Hello strong verification for consequential authority;
- encrypted local OWNER profile;
- Pocket3 OWNER face identity + passive/active liveness evidence;
- one accepted Pocket3 microphone owner through LiveKit MediaDevices/WebRTC AEC+NS+HPF+AGC;
- LR-ASD active-speaker diagnostics on canonical JARVIS audio + Vision timelines;
- encrypted CAM++ OWNER voice enrollment and asynchronous per-turn speaker-shadow scoring;
- audio-only speaker-shadow operation without requiring the camera;
- normal conversation remains non-blocking while CAM++ runs in parallel;
- raw biometric audio/video remains memory-only by default;
- identity/perception evidence never directly grants consequential execution permission.

### 3B.11 accepted diagnostic evidence

| Scenario | Evidence | Final Step-3 disposition |
| --- | --- | --- |
| A OWNER visible + OWNER speaks | zero-offset mean `0.8676`, median `0.9248` | clean positive evidence |
| B OWNER visible + TV/off-camera speech | mean about `0.0014` | strong negative evidence |
| C JARVIS playback only | quality rejected | fail-closed system evidence; not threshold data |
| D replayed OWNER voice from another device | mean about `0.0014` | LR-ASD replay negative |
| E OWNER + another visible; OWNER speaks | not run with a real second person | explicitly waived for Step-3 closure; T2 remains disabled |
| F OWNER + another visible; other speaks | not run with a real second person | explicitly waived for Step-3 closure; T2 remains disabled |
| G OWNER + concurrent other/background speech | mean about `0.8253` | known overlap-semantics limitation; never treated as owner-only authority |
| H temporary OWNER head loss | insufficient | expected fail-close |

Scenario G proves LR-ASD answers “is the visible OWNER speaking?” rather than “is the OWNER the only active speaker in the mixed audio?”. Streaming diarization/overlap detection is therefore a future improvement before audio/AV evidence can be promoted into stronger unattended authority. It does **not** block Step 3 because `active_speaker_confirmed`, voice-based authority, and T2 remain disabled.

### 3B.12 real-machine acceptance

One-time OWNER voice enrollment passed on the real JARVIS machine:

- 12 accepted natural English/Hindi/Hinglish/near/far samples;
- 6 persisted CAM++ prototypes;
- 192-dimensional embeddings;
- enrollment coverage cosine: min `0.7593`, p05 `0.7749`, median `0.8726`;
- existing face template preserved; OWNER profile modalities are `face + voice`;
- raw audio not persisted;
- no speaker threshold selected;
- no speaker authority enabled.

Normal JARVIS conversation then produced quality-qualified OWNER scores:

- `0.7154` at `91.2 ms`;
- `0.6737` at `57.5 ms`;
- `0.7450` at `173.2 ms`;
- `0.7028` at `140.1 ms`.

Observed mean OWNER cosine was about `0.7092`; observed CAM++ median inference latency was about `115.7 ms`. Work ran off the conversation critical path and did not block normal responses. A `0.46 s` turn correctly failed quality as too short. One otherwise understood user turn was missed by local Silero (`max_vad_probability=0.2034`); this is retained as a coverage limitation, not converted into an identity failure and not “fixed” by blindly lowering VAD thresholds.

Decision: `docs/decisions/ADR-014_AUDIO_FIRST_SPEAKER_SHADOW.md`.

Closure record: `docs/research/STEP_3_CLOSURE_ACCEPTANCE.md`.

---

## Step-3 authority freeze

The accepted Step-3 release intentionally stops before speculative biometric authority promotion.

```text
face identity            = accepted evidence
face liveness            = accepted evidence
CAM++ speaker similarity = shadow evidence only
LR-ASD active speaker    = shadow evidence only
T2 CORROBORATED_OWNER    = disabled
Windows Hello            = strong verification path
```

Non-negotiable rules carried into every later step:

- identity evidence is not execution permission;
- model/provider/UI output cannot bypass JARVIS authority;
- stale/cross-session/cross-track evidence may not silently elevate trust;
- spoof/uncertain/insufficient evidence fails closed for stronger trust;
- ordinary conversation remains frictionless;
- consequential actions use proportional approval/verification;
- raw biometric media is not durably retained by default;
- normal conversation never auto-adapts the OWNER voice template from similarity alone.

Known future identity improvements are deliberately deferred until a later capability actually requires them:

- streaming overlap / speaker-change detection (Sortformer or current best equivalent);
- replay/synthetic-voice countermeasures;
- real second-person E/F calibration;
- direct non-owner CAM++ score distributions;
- short-turn same-speaker continuity;
- attention/gaze when fixed monitor-relative hardware exists;
- any eventual T2 predicate or audio-based authority promotion.

These are backlog items, not Step-3 blockers.

---

## Step 4 goal

Step 4 builds **one JARVIS-owned personal-context and memory system** that makes the assistant genuinely continuous across conversations without turning every sentence into permanent memory.

Capabilities in scope:

- CAP-008 Live Session Context;
- CAP-009 Long-Term Personal Memory;
- CAP-010 Episodic Memory;
- CAP-011 Semantic Memory;
- CAP-012 Reflection and Session Learning;
- CAP-013 Emotional Interaction Context.

Step 4 must preserve the Step-3 privacy and authority foundation. Models may propose memory candidates but may not directly mutate durable memory.

---

## Immediate Step-4 work order

Do **not** implement a memory database/provider yet.

1. Recover the exact Step-4 product requirements from `PRODUCT.md`, `LEGACY_REQUIREMENTS_MAP.md`, and relevant old-JARVIS lessons.
2. Research the best current 2026 memory/context technology and patterns instead of rebuilding mature infrastructure.
3. Separate responsibilities before technology selection:
   - live/session working context;
   - durable semantic facts/preferences/rules;
   - episodic events/milestones;
   - memory candidate extraction/reflection;
   - provenance/confidence/supersession;
   - correction/forgetting;
   - retrieval/ranking;
   - transient emotional interaction state.
4. Define one authoritative memory owner and provider boundaries.
5. Decide what is local vs cloud and what data is allowed to leave the machine.
6. Define durable schema/lifecycle only after research.
7. Obtain human architecture approval before implementation.

---

## Step-4 hard requirements already inherited from PRODUCT.md

- not every sentence becomes durable memory;
- explicit user correction outranks inference/history;
- durable memory keeps provenance and enough timing/confidence to support correction and supersession;
- correction and forgetting are first-class;
- session context is distinct from durable memory;
- provider history/caches are not automatically canonical JARVIS memory;
- transient emotional interpretations stay transient by default;
- secrets are not normal model context;
- models do not write directly to persistent memory;
- there must be one authoritative owner for conversation/context/memory state;
- future providers remain replaceable.

---

## Git / integration state

Step-3 closure branch:

```text
step3b12-speaker-shadow-runtime
```

The final closure PR should target protected `main` and supersede PR #13 because this branch contains the full 3B.11 history plus 3B.12 and the Step-3 reconciliation.

Required before merge:

- exact final head passes Ruff formatting/lint;
- full pytest suite passes;
- Windows DPAPI smoke passes;
- Windows Hello helper build/contract passes;
- review final diff against `main`;
- protected-main merge succeeds.

After merge, Step 3 is `DONE` and Step 4 is the only active product slice.

## Immediate Next Action

**Finish the Step-3 closure PR/CI/merge. Then begin Step-4 requirements + current-technology research from protected `main`; do not start another Step-3 identity feature unless a later step exposes a concrete blocking requirement.**
