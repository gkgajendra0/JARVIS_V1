# JARVIS V1 Current Plan

## Active Step

**Step 3 — Identity, Graduated Trust, Authority, and Observability Foundation**

## Current Stage

**PHASE 3A COMPLETE + MERGED — PHASE 3B ACTIVE — STARTUP OPERABILITY ACCEPTED — LIVEKIT 48-kHz FULL-DUPLEX AUDIO ACCEPTED — ADR-013 SINGLE-MICROPHONE ACTIVE-SPEAKER BOUNDARY ACCEPTED — 3B.11 LR-ASD CORE EVIDENCE ACCEPTED WITH E/F PENDING + OVERLAP GAP DISCOVERED — 3B.12 AUDIO-FIRST CAM++ SPEAKER SHADOW IMPLEMENTED + REAL-MACHINE OWNER VOICE ENROLLMENT ACCEPTED — NORMAL-CONVERSATION UX/SIMILARITY ACCEPTANCE NEXT**

This file is the operational source of truth for what is done, what is accepted, and what happens next. Detailed evidence belongs in `docs/research/`; significant architecture decisions belong in `docs/decisions/`.

---

## Completed / accepted foundation

| Slice | Status | Current disposition |
|---|---|---|
| Step 0 | Complete | product/repo foundation |
| Step 1 | Complete | realtime natural conversation architecture |
| Step 2 | Complete | local wake + voice lifecycle |
| Step 2.5 | Complete | Pocket3 vision/tracking/PTZ foundation |
| Step 3A | Complete + merged | authority/policy/approval/audit/session boundaries |
| 3B.1 | Accepted | encrypted single OWNER storage |
| 3B.2/3 | Accepted | pinned YuNet + SFace runtime/assets |
| 3B.4 | Accepted | Pocket3 face pipeline |
| 3B.5A | Accepted baseline | positive OWNER face calibration |
| 3B.6 | Accepted | encrypted multi-prototype OWNER enrollment |
| 3B.7A | Accepted | active facial-liveness fallback |
| 3B.7B | Human-accepted | passive MiniFAS temporal RGB liveness |
| 3B.8 | Human-accepted | runtime OWNER identity + liveness binding |
| 3B.9 | Deferred | attention waits for fixed monitor-relative sensor |
| 3B.10 | Accepted shadow provider | CAM++ speaker embedding foundation |
| 3B.10A | Human-accepted | passive canonical user-turn capture + OWNER-context bridge |
| Startup operability | Human-accepted | `jarvis-setup`, machine profile, stable device selectors, consolidated preflight |
| Conversation full duplex | Human-accepted | LiveKit MediaDevices + NVIDIA/TV 48 kHz |
| 3B.11 integration boundary | Human-accepted | single Pocket3 mic owner + canonical PCM + normal timestamped Vision |
| 3B.11 A/B/C/D/G/H evidence | Accepted diagnostic evidence | A positive; B/D strong negatives; C/H fail closed; G exposes overlap semantics gap |
| 3B.12 implementation | Code accepted | encrypted OWNER voice prototypes + asynchronous per-turn CAM++ shadow |
| 3B.12 OWNER voice enrollment | Real-machine accepted | 12 quality-qualified regions → 6 encrypted CAM++ prototypes; face + voice preserved in OWNER profile |

T2 `CORROBORATED_OWNER` remains intentionally disabled.

---

## Accepted normal startup

Normal operation no longer depends on rebuilding environment variables from chat/PowerShell history.

```text
one-time jarvis-setup
        ↓
%LOCALAPPDATA%\JARVIS\machine.json
        +
Windows environment for API keys only
        ↓
jarvis-voice
```

Real-machine setup proved:

- wake model persisted;
- tuned wake threshold `0.82` preserved;
- Pocket3 microphone persisted as stable `name + hostapi` selector;
- NVIDIA `24'TV` persisted as stable 48-kHz output selector;
- Gemini credential detected;
- vision/speaker/active-speaker switches persisted;
- official pinned LR-ASD AVA checkpoint acquired and integrity-verified automatically;
- legacy non-secret `JARVIS_*` Windows User overrides removed;
- stale inherited Tribit environment state no longer overrides the machine profile;
- `jarvis-voice` preflight passes without manually setting runtime variables.

3B.12 changes the dependency semantics:

- passive CAM++ speaker shadow is audio-only and does **not** require Vision;
- LR-ASD active-speaker shadow still requires both speaker shadow and Vision.

Decision: `docs/decisions/ADR-012_MACHINE_CONFIGURATION_AND_STARTUP_PREFLIGHT.md`.

---

## Accepted conversation audio

```text
Pocket3 microphone @ 48 kHz
        ↓
LiveKit rtc.MediaDevices
WebRTC AEC + NS + HPF + AGC
        ↓
Gemini Live / AgentSession
        ↓
LiveKit MediaDevices output @ 48 kHz
        ↓
NVIDIA HDMI → 24'TV
```

Real acceptance proved:

- JARVIS can complete speech without triggering on its own TV output;
- deliberate human barge-in still interrupts correctly;
- Bluetooth/Tribit is not the accepted production render path.

Decision: `docs/decisions/ADR-011_LIVEKIT_MEDIADEVICES_48K_FULL_DUPLEX.md`.

---

## 3B.11 integration correction — dual Pocket3 audio ownership REJECTED

Real-machine testing rejected two simultaneous independent consumers of the Pocket3 microphone.

```text
GStreamer first  → LiveKit/PortAudio microphone open fails
PortAudio first  → GStreamer paired AV fails to reach PLAYING
```

Therefore a production architecture with separate LiveKit and GStreamer microphone ownership is forbidden on this machine.

Evidence: `docs/research/STEP_3B11_DUAL_AUDIO_OWNERSHIP_ACCEPTANCE_RESULTS.md`.

---

## ADR-013 replacement — REAL-MACHINE ACCEPTED

Production Step-3 active-speaker diagnostics use one microphone owner and the existing canonical JARVIS timelines:

```text
                            POCKET3
                               │
                ┌──────────────┴──────────────┐
                │                             │
             AUDIO                           VIDEO
                │                             │
     LiveKit MediaDevices only        normal OpenCV Vision
     AEC + NS + HPF + AGC                    │
                │                     timestamped frame
canonical timestamped user PCM               │
                │                     exact track/head sequence
                └──────────────┬──────────────┘
                               │
                       monotonic alignment
                               │
                            LR-ASD
```

Accepted real-machine run proved all of the following can operate together:

- startup preflight;
- Pocket3 LiveKit microphone capture;
- NVIDIA/TV 48-kHz output;
- WebRTC AEC/NS/HPF/AGC;
- integrated Vision;
- RF-DETR person detection;
- persistent person tracking;
- head detection;
- wake detection;
- Gemini realtime conversation;
- speaker-shadow canonical turn capture;
- LR-ASD CUDA inference;
- target lock;
- PTZ follow.

LR-ASD produced real `SCORED` observations. This accepts the integration boundary, not an active-speaker authority threshold.

Evidence: `docs/research/STEP_3B11_SINGLE_OWNER_ACTIVE_SPEAKER_ACCEPTANCE_RESULTS.md`.

Decision: `docs/decisions/ADR-013_SINGLE_OWNER_POCKET3_AUDIO_FOR_ACTIVE_SPEAKER.md`.

---

## 3B.11 score-distribution status

The corrected real-machine A-H harness has produced enough evidence to stop broad scripted testing while the remaining architecture is developed.

| Scenario | Current evidence | Disposition |
|---|---|---|
| A. OWNER visible + OWNER speaking | focused zero-offset mean `0.8676`, median `0.9248` | KEEP — clean positive |
| B. OWNER visible + TV/off-camera speech | zero-offset mean about `0.0014` | KEEP — strong negative |
| C. OWNER visible + JARVIS playback only | `quality_rejected` | KEEP — system-level fail-closed evidence, not LR-ASD threshold sample |
| D. OWNER visible + OWNER replay from phone | zero-offset mean about `0.0014` | KEEP — replay negative for LR-ASD |
| E. OWNER + another visible; OWNER speaks | pending real second person | PARK |
| F. OWNER + another visible; other speaks | pending real second person | PARK |
| G. overlapping OWNER + other/background speech | zero-offset mean about `0.8253` | KEEP — real architecture gap, never binary threshold training |
| H. temporary OWNER head/face loss | `insufficient` | KEEP — expected visual fail-close |

Scenario G is not an LR-ASD error. OWNER really is speaking, so LR-ASD correctly reports visible OWNER speech. The missing question is whether OWNER is the **only** active speaker responsible for the mixed turn. That requires a separate overlap / concurrent-speaker detector.

Therefore:

- do not rerun B/C/D/G/H randomly;
- A is now clean and frozen;
- E/F wait for a real second visible person;
- G remains `AMBIGUOUS` / fail-closed at authority level;
- no LR-ASD deployment threshold is promoted yet;
- `ACTIVE_OWNER_SPEAKER` remains disabled.

---

## 3B.12 — audio-first parallel OWNER speaker shadow

Normal conversation should not require OWNER to face the camera and should not wait for a biometric gate.

Accepted implementation direction:

```text
                         canonical user PCM
                                │
             ┌──────────────────┼──────────────────┐
             │                  │                  │
      realtime conversation   speech-region      later overlap /
             path              + quality          speaker-change
             │                  │                  observer
             │                  ↓
             │             CAM++ embedding
             │                  │
             │          encrypted OWNER
             │          prototype comparison
             │                  │
             └──────────────────┼──────────────────┘
                                ↓
                       rolling evidence state
```

Current 3B.12 implementation provides:

1. one-time explicit OWNER voice enrollment;
2. capture through the accepted LiveKit MediaDevices/WebRTC microphone path;
3. multiple natural English/Hindi/Hinglish/near/far speech regions;
4. existing quality gate before enrollment/scoring;
5. bounded deterministic CAM++ OWNER prototype set;
6. encrypted storage inside the existing OWNER profile boundary;
7. Windows-Hello/OPA/audit-gated exact profile replacement;
8. raw enrollment audio memory-only and discarded;
9. read-only runtime comparison — no normal-conversation self-enrollment;
10. per-turn CAM++ work off the conversation critical path using background tasks / `asyncio.to_thread`;
11. CAM++ and LR-ASD diagnostics may run in parallel when both are enabled;
12. short/poor regions stay `INSUFFICIENT`, never `UNKNOWN_SPEAKER` merely due bad evidence;
13. missing speaker enrollment/model/dependency disables the diagnostic observer rather than making normal JARVIS unavailable;
14. no speaker threshold, OWNER classification, prototype auto-admission, or authority effect yet.

The exact CAM++ model remains the real-machine Step 3B.10 winner. Previous deployment-PC measurements were roughly:

- CAM++ ~54 ms median for a ~3 s region;
- TitaNet-Large ~143 ms;
- ERes2NetV2 ~319 ms.

Decision: `docs/decisions/ADR-014_AUDIO_FIRST_SPEAKER_SHADOW.md`.

---

## 3B.12 OWNER voice enrollment — REAL-MACHINE ACCEPTED

Real-machine enrollment completed successfully through `jarvis-speaker-enroll` using the accepted Pocket3 → LiveKit MediaDevices/WebRTC microphone path.

Observed acceptance evidence:

- 12/12 final enrollment regions accepted;
- two low-energy attempts were correctly rejected at `-53.1 dBFS` and `-71.1 dBFS` and were not enrolled;
- accepted regions covered natural English, Hindi, Hinglish, normal desk distance, slightly quieter speech, and a slightly farther microphone position;
- `prototype_count = 6`;
- `embedding_dimension = 192`;
- prototype coverage cosine: minimum `0.7593`, p05 `0.7749`, median `0.8726`;
- Windows Hello authorized the exact persistent profile update;
- OWNER `profile_version = 2`;
- preserved modalities are `['face', 'voice']`;
- raw audio was not persisted;
- no speaker threshold was selected;
- speaker identity grants no authority;
- terminal result: `STEP_3B12_SPEAKER_ENROLLMENT = PASS`.

This accepts the persistent OWNER voice-template lifecycle and real-machine enrollment UX. It does **not** accept a speaker decision threshold or any trust/authority upgrade.

---

## Immediate next work — 3B.12 normal-conversation UX + passive similarity acceptance

No more enrollment or full A-H ceremony is required now.

1. Start normal `jarvis-voice` operation with the accepted machine configuration.
2. Talk to JARVIS naturally; do not use a scripted benchmark yet.
3. Confirm ordinary response/barge-in UX feels unchanged while CAM++ runs in the background.
4. Observe per-turn `max_owner_cosine`, `embedding_ms`, quality/insufficient outcomes, and any observer exceptions.
5. Confirm poor/very-short turns fail closed as `INSUFFICIENT` rather than becoming false non-owner decisions.
6. Collect a small ordinary OWNER-only similarity sample across English/Hindi/Hinglish and normal conversational variation.
7. Do not select a production speaker threshold from enrollment or OWNER-only data.
8. If normal conversation becomes slower or unstable, reject/disable the shadow implementation rather than compromising the realtime path.

---

## Work after 3B.12 UX acceptance

1. Research and benchmark mature streaming overlap / speaker-change technology for Scenario G, with NVIDIA Streaming Sortformer as a primary candidate rather than inventing a custom detector.
2. Keep overlap detection parallel to conversation and measure real RTX 5060 Ti latency/GPU impact before leaving it enabled permanently.
3. Add fresh same-speaker continuity for very short follow-ups only after speaker-change/overlap semantics are accepted.
4. Research mature replay/synthetic-voice countermeasures before audio-only speaker evidence can influence consequential authority.
5. Run E/F with a real second visible person when naturally available; do not substitute a photo/video.
6. Collect direct non-owner human speaker distributions before any CAM++ threshold promotion.
7. Decide whether CAM++ remains sufficient or a slower challenger materially improves difficult cases.
8. Resolve authoritative OWNER-vs-UNKNOWN face separation when consenting live non-owner calibration becomes available, or keep T2 designed so provisional face evidence cannot be mistaken for authoritative identity.
9. Define deterministic T2 `CORROBORATED_OWNER` composition only from final accepted evidence.
10. Run broader replay/stale/expiry/cross-session/cross-track/cross-actor/policy/degraded-mode tests.
11. Remove obsolete GStreamer paired-conversation and custom barge-in production plumbing only after replacement cleanup is safe.
12. Final docs/quality-gate/roadmap reconciliation.
13. Revisit attention when fixed monitor-mounted hardware exists.

---

## Non-negotiable Step-3 invariants

- Identity evidence is not execution permission.
- Face, voice, liveness, active-speaker, attention, wake word, Windows-unlocked state, or model confidence never directly authorize consequential actions.
- Windows Hello/FIDO2 remains the strong-verification path for consequential authority.
- `SPOOF` fails closed.
- `UNCERTAIN` may request stronger evidence but may not silently upgrade trust.
- Raw biometric audio/video is memory-only by default.
- Provider/device/model boundaries remain replaceable.
- Normal conversation must not be blocked by speaker-shadow diagnostics.
- Normal conversation must never auto-enroll/adapt the OWNER voice template from its own similarity score.
- T2 stays disabled until its final multimodal predicate is accepted.

---

## Branch / merge state

Current implementation branch:

```text
step3b12-speaker-shadow-runtime
```

It is stacked directly on:

```text
step3b11-lr-asd-bakeoff
```

Step 3B.11 PR state:

```text
PR #13 → open; do not merge yet
```

E/F remain pending and Scenario G still needs an overlap/concurrent-speaker layer, so Step 3B.11 authority acceptance is not complete.

`step3b12-speaker-shadow-runtime` should remain separate until ordinary-conversation CAM++ UX/similarity acceptance is complete on the real JARVIS machine. Do not merge it directly to protected main ahead of its Step 3B.11 base.

## Immediate Next Action

**Run normal `jarvis-voice` conversation on the real JARVIS machine, confirm CAM++ remains invisible to realtime UX, and capture the resulting enrolled-speaker shadow logs (`max_owner_cosine`, `embedding_ms`, and `INSUFFICIENT` outcomes) for passive OWNER-only evaluation.**
