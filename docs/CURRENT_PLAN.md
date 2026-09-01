# JARVIS V1 Current Plan

## Active Step

**Step 3 — Identity, Graduated Trust, Authority, and Observability Foundation**

## Current Stage

**PHASE 3A COMPLETE + MERGED — PHASE 3B ACTIVE — STARTUP OPERABILITY ACCEPTED — LIVEKIT 48-kHz FULL-DUPLEX AUDIO ACCEPTED — DUAL POCKET3 AUDIO OWNERSHIP REJECTED — ADR-013 SINGLE-MICROPHONE ACTIVE-SPEAKER INTEGRATION REAL-MACHINE ACCEPTED — LIVE VISION PREVIEW DEFAULT-ON — 3B.11 SCORE-DISTRIBUTION / NEGATIVE-SCENARIO BAKE-OFF NEXT**

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

Production Step-3 active-speaker diagnostics now use one microphone owner and the existing canonical JARVIS timelines:

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

LR-ASD produced multiple real `SCORED` observations. This accepts the **integration boundary**, not an active-speaker threshold.

Evidence: `docs/research/STEP_3B11_SINGLE_OWNER_ACTIVE_SPEAKER_ACCEPTANCE_RESULTS.md`.

Decision: `docs/decisions/ADR-013_SINGLE_OWNER_POCKET3_AUDIO_FOR_ACTIVE_SPEAKER.md`.

---

## Vision observability — default-on

When integrated Vision is enabled, normal production startup now opens the existing `OpenCVVisionObserver` window by default.

The window renders the same canonical interpretation JARVIS uses:

- live Pocket3 frame;
- person track boxes / IDs / confidence;
- head boxes;
- selected/locked target;
- follow SAFE/ARMED state;
- framing anchor;
- pan/tilt/zoom command values;
- analysis age.

An explicit `JARVIS_VISION_PREVIEW=false` may suppress the window for headless/quiet diagnostic runs.

---

## Immediate next work — 3B.11 score-distribution bake-off

The LR-ASD model is integrated and scoring, but no threshold is accepted yet.

Required real-machine scenarios:

```text
A. OWNER visible + OWNER speaking
B. OWNER visible + TV/phone/off-camera other speech
C. OWNER visible + JARVIS playback only
D. OWNER visible + OWNER replay from phone
E. OWNER + another visible person; OWNER speaks
F. OWNER + another visible person; other person speaks
G. overlapping OWNER + other/background speech
H. temporary OWNER head/face loss
```

Measure:

- LR-ASD raw score distributions;
- temporal stability;
- false active assignment to a silent OWNER face;
- off-camera speech behavior;
- replay/playback behavior;
- overlap behavior;
- timing/alignment sensitivity;
- inference latency / GPU / CPU footprint;
- insufficient/ambiguous rate.

No leaderboard/default threshold is accepted directly.

Only after a safe temporal rule is human-accepted may `ACTIVE_OWNER_SPEAKER` permit **session-only** CAM++ prototype admission for the same actor/turn.

---

## Work after 3B.11 acceptance

1. Permit session-only CAM++ prototype admission only when fresh OWNER+liveness and active-speaker evidence agree on the same actor/turn.
2. Collect real speaker similarity distributions passively.
3. Decide whether CAM++ separation is sufficient or ERes2NetV2 materially improves ambiguity.
4. Run targeted non-owner / OWNER-replay / overlap acceptance before any speaker threshold promotion.
5. Define persistent encrypted voice-template format only behind strongly verified OWNER enrollment/update semantics.
6. Resolve authoritative OWNER-vs-UNKNOWN face separation when consenting live non-owner calibration becomes available, or keep T2 designed so provisional face evidence cannot be mistaken for authoritative identity.
7. Define deterministic T2 `CORROBORATED_OWNER` composition from final accepted evidence.
8. Run broader replay/stale/expiry/cross-session/cross-track/cross-actor/policy/degraded-mode tests.
9. Remove obsolete GStreamer paired-conversation and custom barge-in production plumbing after replacement cleanup is safe.
10. Final docs/quality-gate/roadmap reconciliation.
11. Protected-main review and merge of Phase 3B through draft PR #11.
12. Revisit attention when fixed monitor-mounted hardware exists.

---

## Non-negotiable Step-3 invariants

- Identity evidence is not execution permission.
- Face, voice, liveness, active-speaker, attention, wake word, Windows-unlocked state, or model confidence never directly authorize consequential actions.
- Windows Hello/FIDO2 remains the strong-verification path for consequential authority.
- `SPOOF` fails closed.
- `UNCERTAIN` may request stronger evidence but may not silently upgrade trust.
- Raw biometric audio/video is memory-only by default.
- Provider/device/model boundaries remain replaceable.
- T2 stays disabled until its final multimodal predicate is accepted.

---

## Branch / merge state

Current active integration branch:

```text
feature/step-3b11-sensor-av-foundation
```

Current protected integration PR:

```text
PR #11 → main (DRAFT)
```

`main` does **not** yet contain this Phase-3B integration. The branch and PR must remain until the remaining 3B.11 acceptance and final reconciliation are complete. Do not delete the branch before protected-main merge.

The older PR #10 is historical/superseded and is not the current integration path.

## Immediate Next Action

**Pull the latest feature branch, run `jarvis-voice`, confirm the live JARVIS Vision interpretation window appears, then begin the bounded 3B.11 score-distribution scenarios.**
