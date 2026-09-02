# Step 3 — Closure Acceptance

Status: **DONE — HUMAN-ACCEPTED + CI-PASSED + MERGED TO PROTECTED `main`**

Date: 2026-09-02

Integration: PR #15, merge commit `360a72c58402fbe357fa409437a4ce181921d837`.

## Purpose

This record closes Step 3 at the product boundary defined by `ROADMAP.md`: the minimum trustworthy identity, graduated-trust, authority, approval, audit, observability, and OWNER-evidence foundation required before later JARVIS capabilities can safely read, write, communicate, or control anything.

Step 3 is not a promise to perfect biometric perception. Advanced overlap separation, anti-deepfake voice security, lip reading, target-speaker extraction, and attention sensing are deliberately deferred unless a later product capability makes them necessary.

## Human-accepted foundation

### Authority and governance

Accepted:

- T0–T3 trust vocabulary;
- deterministic R0–R5 risk floors;
- immutable exact-action proposals;
- proposal-bound expiring approvals;
- fail-closed OPA policy boundary;
- final one-time execution revalidation;
- privacy-aware structured audit state;
- Windows-session invalidation on lock/user/session change;
- Windows Hello strong verification;
- no face/voice/liveness/active-speaker/model output directly authorizes consequential actions.

### OWNER visual evidence

Accepted:

- encrypted single OWNER profile;
- YuNet/SFace OWNER matching;
- multi-prototype OWNER enrollment;
- active liveness fallback;
- passive MiniFAS temporal RGB liveness;
- same-session/same-track OWNER context binding;
- attention/gaze deferred because the movable Pocket3 is not a stable monitor-relative sensor.

### Audio ownership and conversation

Accepted production path:

```text
Pocket3 microphone @ 48 kHz
        ↓
LiveKit MediaDevices only
WebRTC AEC + NS + HPF + AGC
        ↓
canonical timestamped user PCM
        ├── realtime conversation
        ├── CAM++ speaker shadow
        └── LR-ASD active-speaker shadow
```

Dual independent Pocket3 microphone ownership by LiveKit + GStreamer was rejected on real hardware and is forbidden in production.

## LR-ASD diagnostic evidence

| Scenario | Result | Closure interpretation |
| --- | --- | --- |
| A OWNER visible + OWNER speech | mean `0.8676`, median `0.9248` at 0 ms | clean positive |
| B TV/off-camera speech | mean about `0.0014` | strong negative |
| C JARVIS playback | quality rejected | fail-closed; not threshold data |
| D OWNER replay from phone | mean about `0.0014` | replay negative for LR-ASD |
| E OWNER + second visible person, OWNER speaks | not collected | waived while T2/active-speaker authority remain disabled |
| F OWNER + second visible person, other speaks | not collected | waived while T2/active-speaker authority remain disabled |
| G OWNER + concurrent other/background speech | mean about `0.8253` | semantic overlap gap; never owner-only authority |
| H temporary OWNER head loss | insufficient | expected fail-close |

Scenario G is not an LR-ASD model error: OWNER really is speaking. The missing information is whether another speaker is also active. Streaming diarization/overlap detection is therefore a future prerequisite before stronger audio/AV authority promotion, but is not required while all such authority remains disabled.

No LR-ASD deployment threshold is selected.

## Audio-first CAM++ acceptance

### Enrollment

Real-machine OWNER enrollment passed:

- 12 accepted natural speech samples;
- 6 persisted prototypes;
- embedding dimension `192`;
- coverage cosine min `0.7593`, p05 `0.7749`, median `0.8726`;
- existing face profile preserved and VOICE added;
- raw audio discarded;
- Windows Hello approved exact encrypted profile replacement;
- no threshold or authority promoted.

### Normal conversation

Ordinary JARVIS use produced:

| Cosine | Embedding latency |
| ---: | ---: |
| `0.7154` | `91.2 ms` |
| `0.6737` | `57.5 ms` |
| `0.7450` | `173.2 ms` |
| `0.7028` | `140.1 ms` |

Observed mean cosine: about `0.7092`.
Observed median embedding latency: about `115.7 ms`.

CAM++ ran asynchronously off the conversation critical path and did not block responses. A `0.46 s` turn correctly failed quality as too short. One otherwise understood user turn was missed by local Silero with maximum probability `0.2034`; the observer returned insufficient rather than inventing an identity decision.

This accepts the non-blocking UX architecture, not an OWNER threshold.

## Final Step-3 trust disposition

```text
Face identity            = accepted evidence
Face liveness            = accepted evidence
CAM++ speaker similarity = shadow evidence only
LR-ASD active speaker    = shadow evidence only
T2 CORROBORATED_OWNER    = disabled
Windows Hello            = strong verification path
```

No normal-conversation self-enrollment/adaptation is allowed. No speaker similarity, LR-ASD score, face match, liveness result, wake word, Windows-unlocked state, or model confidence directly grants consequential execution permission.

## Explicit residual risks / deferred work

Tracked in Issue #14:

1. Concurrent-speaker/overlap detection for Scenario G.
2. Replay/synthetic/cloned-voice countermeasures before audio-only evidence can support sensitive authority.
3. Direct non-owner CAM++ distributions before threshold promotion.
4. E/F real-second-person calibration when naturally available.
5. Short-turn same-speaker continuity after speaker-change/overlap semantics are accepted.
6. Attention/gaze only with suitable fixed monitor-relative sensing.
7. Any eventual T2 composition requires a new explicit architecture/acceptance decision.
8. Local Silero may occasionally miss a provider-understood user turn; failure remains `INSUFFICIENT`.

None can currently elevate authority because the relevant trust promotions remain disabled.

## Final quality-gate result

- Scope: PASS.
- Architecture ownership: PASS.
- Automated validation: PASS — final PR head passed Ruff, full pytest, Windows DPAPI, and Windows Hello helper checks.
- Truthfulness: PASS — unknown/insufficient/ambiguous states remain explicit; no biometric authority falsely claimed.
- Authority/risk: PASS — consequential strong verification remains Windows Hello; T2 stays disabled.
- Privacy: PASS — raw biometric media is memory-only by default; encrypted bounded templates only where explicitly enrolled.
- Resilience: PASS — missing speaker model/enrollment disables diagnostics rather than normal conversation.
- Performance/human acceptance: PASS — normal conversation remained usable with asynchronous CAM++ enabled.
- Cleanup/documentation/Git: PASS — PR #13 was closed as superseded, PR #15 merged the coherent Step-3 checkpoint, and Step 4 is active.

## Completion

**Step 3 is DONE.**

Future identity hardening is backlog work, not an implicit continuation of Step 3. The active product slice is now Step 4 — Live Context and Personal Memory.
