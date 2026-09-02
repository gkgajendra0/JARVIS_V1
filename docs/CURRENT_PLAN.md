# JARVIS V1 Current Plan

## Active Step

**Step 3 — Identity, Graduated Trust, Authority, and Observability Foundation**

## Current Stage

**REOPENED FOR FINAL IDENTITY/VOICE SECURITY COMPLETION — STEP 4 PAUSED**

This file is the operational source of truth for current work. Detailed evidence belongs in `docs/research/`; significant architecture decisions belong in `docs/decisions/`.

---

## Why Step 3 is reopened

The previously merged Step-3 checkpoint correctly established the authority skeleton, OWNER face/liveness, encrypted face+voice profile, Windows Hello, CAM++ speaker shadow, LR-ASD diagnostics, and the single-owner LiveKit audio architecture. However, human review identified that the intended graduated-trust system was closed before the remaining evidence-composition and spoken-actor security work was finished.

The original accepted architecture intended a usable T2 `CORROBORATED_OWNER` path for bounded R1/R2/R3 authority while keeping voice alone non-authoritative and reserving Windows Hello/T3 for critical R4 operations.

Therefore Step 4 is paused. We will finish the already-discovered Step-3 work rather than silently deferring it.

Active tracking issue: GitHub Issue #14 — `Step 3 final identity/security completion`.

Branch:

```text
step3-final-identity-completion
```

---

## Accepted foundation — KEEP

Do not redesign these unless new evidence exposes a material problem:

- T0–T3 trust vocabulary and deterministic R0–R5 risk floors;
- immutable proposal fingerprints and proposal-bound approval records;
- OPA fail-closed policy boundary;
- final pre-execution revalidation and one-time permits;
- privacy-aware local audit;
- Windows-session invalidation;
- Windows Hello strong verification;
- encrypted local OWNER profile with FACE + VOICE modalities;
- YuNet/SFace OWNER identity and accepted active/passive liveness;
- Pocket3 person/head/track Vision pipeline;
- one production Pocket3 microphone owner through LiveKit MediaDevices/WebRTC AEC + NS + HPF + AGC;
- canonical timestamped user PCM reused by conversation and diagnostics;
- CAM++ audio-first OWNER speaker shadow;
- LR-ASD visible-OWNER active-speaker diagnostics;
- no raw biometric media persistence by default;
- no sensor/model directly grants execution permission.

---

## Known evidence already accepted

### CAM++

- one-time real-machine OWNER enrollment passed;
- 12 accepted natural samples -> 6 persisted 192-d prototypes;
- enrollment coverage cosine min `0.7593`, p05 `0.7749`, median `0.8726`;
- first ordinary-conversation OWNER observations: `0.6737–0.7450`;
- observed CAM++ inference: `57.5–173.2 ms`, asynchronous/non-blocking;
- short/poor/missed speech becomes `INSUFFICIENT`, not non-OWNER;
- no production speaker threshold selected yet.

### LR-ASD

- A OWNER visible + OWNER speaks: strong positive, mean about `0.8676`;
- B TV/off-camera speech: strong negative, about `0.0014`;
- C JARVIS playback: quality-rejected/fail-closed diagnostic;
- D replayed OWNER voice while OWNER visually silent: about `0.0014`;
- G OWNER + concurrent other/background speech: high, about `0.8253`, proving LR-ASD means “visible OWNER is speaking” rather than “OWNER is the only speaker”;
- H temporary OWNER head loss: `INSUFFICIENT`;
- E/F remain pending a real second visible person.

---

## Final Step-3 completion scope

### 3B.13 — streaming overlap / speaker-change evidence

Goal: close Scenario G without creating another microphone owner or blocking the realtime conversation path.

Research candidates:

- NVIDIA Streaming Sortformer v2.1 — leading candidate;
- pyannote Community-1 — strong offline/self-hosted reference, but no native streaming path out of the box;
- diart/pyannote streaming — reference alternative requiring older/extra streaming infrastructure.

Required output vocabulary is JARVIS-owned and non-authoritative by itself:

```text
SINGLE_SPEAKER
OVERLAP_DETECTED
SPEAKER_CHANGE
AMBIGUOUS
INSUFFICIENT
```

No production integration until the candidate passes a real RTX 5060 Ti latency/VRAM/contention benchmark.

### Speaker calibration

Collect direct live non-OWNER CAM++ distributions and sufficient OWNER variation before freezing any `OWNER_SPEAKER_CANDIDATE` threshold. Vendor/default thresholds remain forbidden.

### Anti-spoof / replay / cloned voice

Research and benchmark a separate spoof countermeasure. Current reference family is ASVspoof5 (AASIST / RawNet2 / SASV). Speaker similarity and spoof probability stay separate evidence types.

No anti-spoof model is accepted until it demonstrates useful behavior on the JARVIS microphone path and does not harm realtime UX.

### Short-turn continuity

Only after overlap/speaker-change semantics are accepted, permit very short utterances to inherit a recent high-quality OWNER speaker state when:

- same authority/Windows session;
- same active conversation;
- recent fresh speaker evidence;
- no speaker change;
- no overlap/ambiguity/playback concern;
- no device discontinuity;
- the short turn is not the sole basis for stronger authority.

### Missing TrustEvaluator / IdentitySession composition

Implement one JARVIS-owned deterministic evidence resolver that owns freshness/continuity/subject binding and derives T0/T1/T2/T3.

No weighted multimodal confidence score.

Initial T2 composition must require at minimum:

- expected active/unlocked Windows session;
- fresh accepted OWNER face evidence;
- fresh accepted liveness bound to the same visual track/session;
- no identity/track/session ambiguity relevant to the action.

Speaker and active-speaker/overlap evidence may strengthen spoken actor association but voice alone cannot create T2.

T3 remains fresh proposal-bound strong verification through Windows Hello.

### Spoken actor binding

For spoken approvals or voice-originated consequential intent, derive `actor_unambiguous` only from accepted fresh evidence. Any overlap, spoof concern, stale binding, conflicting speaker, lost track, or insufficient evidence must fail closed or step up to Windows Hello according to policy.

### Authority integration

Restore the intended graduated-trust UX:

```text
R0 routine                  -> T0
R1 private read             -> T2
R2 reversible local change  -> T2
R3 persistent/external      -> T2 + exact approval / policy
R4 critical                 -> T3 + proposal-bound Windows Hello
R5 restricted/dev-only      -> deny normal runtime
```

This does not make voice a password. It makes multimodal evidence useful through deterministic JARVIS trust.

---

## Research findings already established for 3B.13

- NVIDIA currently ships `nvidia/diar_streaming_sortformer_4spk-v2.1`, a true streaming four-speaker model with overlap-aware diarization and published low-latency configurations including about 1.04 s.
- The v2.1 checkpoint is roughly 471 MB and uses the NVIDIA Open Model License; NeMo source code is Apache-2.0 but model terms must be tracked separately.
- NeMo Labs Voice Agent uses v2.1 by default, but its high-level wrapper currently collapses to one speaker label per turn. JARVIS must consume underlying frame-level speaker activity/probabilities for Scenario G rather than copy that wrapper semantics.
- pyannote Community-1 is a strong open-source diarization reference with overlap detection, but pyannote explicitly states streaming diarization is not available out of the box; `diart` is its nearest streaming route.
- ASVspoof5 officially provides AASIST and RawNet2 countermeasure baselines plus spoof-aware speaker-verification/SASV references. AASIST code is MIT-licensed. These are benchmark references, not automatic production choices.

Detailed evidence belongs in `docs/research/STEP_3_FINAL_IDENTITY_SECURITY_RESEARCH.md`.

---

## Implementation / validation order

1. Finish current-2026 research and pin exact candidate/model/runtime/license boundaries.
2. Build **benchmark-only** overlap/diarization adapter + telemetry harness; do not wire authority yet.
3. Real-machine RTX 5060 Ti benchmark of Sortformer-class candidate: latency, RTF, VRAM, CPU/RAM, contention with RF-DETR/LR-ASD/CAM++/conversation.
4. If accepted, integrate overlap/speaker-change evidence in shadow mode on canonical PCM.
5. Rerun Scenario G and verify ambiguity is explicit.
6. Build non-OWNER CAM++ calibration harness/collection and freeze threshold only from real distributions.
7. Build anti-spoof benchmark adapter/harness; real replay + synthetic/re-encoded samples; reject weak candidates.
8. Integrate accepted spoof evidence in shadow/fail-closed form.
9. Implement short-turn continuity.
10. Implement IdentitySession / TrustEvaluator and spoken actor binding.
11. Integrate T2/T3 contexts with AuthorityService.
12. Run automated threat/degraded-mode tests.
13. Run focused real-machine acceptance, including E/F when a real second person is available.
14. Reconcile docs, CI, protected-main merge.
15. Only then resume Step 4.

---

## Hard stop conditions

Reject or reconfigure a candidate if any of these occur:

- noticeable realtime conversation slowdown;
- unstable Windows deployment;
- unacceptable GPU/VRAM contention on RTX 5060 Ti;
- second/duplicate microphone ownership;
- hidden cloud biometric processing;
- false certainty instead of `AMBIGUOUS`/`INSUFFICIENT`;
- provider/model license incompatible with JARVIS use;
- raw biometric media persistence without explicit approved need;
- model/provider output bypassing JARVIS trust/policy;
- threshold chosen from vendor defaults or OWNER-only data.

## Immediate Next Action

**Complete the research document and build the benchmark-only Streaming Sortformer v2.1 path. Do not promote any new authority until real-machine overlap/performance evidence exists.**
