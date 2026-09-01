# JARVIS V1 Current Architecture

## Status

**IMPLEMENTED/HUMAN-ACCEPTED THROUGH PHASE 3B.10A. STARTUP MACHINE CONFIGURATION + PREFLIGHT ARE ACCEPTED FOR NORMAL OPERATION. LIVEKIT MEDIADEVICES + NVIDIA/TV 48-kHz CONVERSATION AUDIO IS THE ACCEPTED FULL-DUPLEX PATH. DUAL LIVEKIT + GSTREAMER POCKET3 MICROPHONE OWNERSHIP HAS BEEN REJECTED BY REAL-MACHINE EVIDENCE. ADR-013 SINGLE-MICROPHONE ACTIVE-SPEAKER REPLACEMENT IS IMPLEMENTED AND AWAITS REAL-MACHINE ACCEPTANCE. ATTENTION REMAINS DEFERRED. T2 REMAINS DISABLED.**

This file describes current production boundaries. Detailed evidence belongs in `docs/research/`; active work order belongs in `docs/CURRENT_PLAN.md`; significant choices belong in ADRs.

---

## Top-level production architecture

```text
                           JARVIS V1
                               │
        ┌──────────────────────┼──────────────────────┐
        │                      │                      │
      VOICE                  VISION                AUTHORITY
        │                      │                      │
Pocket3 microphone      Pocket3 video          typed evidence
        │                      │                      │
LiveKit MediaDevices     OpenCV capture       deterministic trust
AEC/NS/HPF/AGC                 │                      │
        │                 RF-DETR + OC-SORT      proposal/risk/policy
Gemini/OpenAI                  │                      │
        │                 head/face/liveness    Windows Hello/FIDO2
NVIDIA 48k → TV                │                      │
        │                 OWNER context              │
        └──────────────┬───────┘                      │
                       │                              │
            speaker / active-speaker                 │
                 diagnostics                          │
                       │                              │
                 no direct authority ────────────────┘
```

Identity/perception evidence never directly becomes execution permission.

---

## Persistent machine configuration — accepted

Normal startup is machine-profile driven:

```text
%LOCALAPPDATA%\JARVIS\machine.json
        +
Windows environment for provider secrets
        ↓
startup preflight
        ↓
jarvis-voice
```

Current accepted machine roles:

- Pocket3 microphone: stable Windows WASAPI `name + hostapi` selector;
- conversation output: NVIDIA `24'TV`, Windows WASAPI, 48 kHz;
- wake model: persisted local path;
- provider: Gemini on the current machine;
- LR-ASD AVA checkpoint: automatically managed/integrity-verified local asset;
- vision/speaker/active-speaker feature state: persisted.

Machine profile values win over stale ambient non-secret `JARVIS_*` variables. Explicit diagnostic runtime overrides require `JARVIS_RUNTIME_ENV_OVERRIDES=true`. API keys remain environment-only.

Decision: `docs/decisions/ADR-012_MACHINE_CONFIGURATION_AND_STARTUP_PREFLIGHT.md`.

---

## Production conversation audio — accepted

```text
Pocket3 microphone @ 48 kHz mono
        ↓
LiveKit rtc.MediaDevices.open_input()
WebRTC AEC + NS + HPF + AGC
        ↓
JARVIS wake / AgentSession / realtime provider
        ↓
LiveKit MediaDevices OutputPlayer
same APM reverse-render reference
        ↓
NVIDIA HDMI @ 48 kHz
        ↓
24'TV speakers
```

Requirements:

- capture and render share one LiveKit `MediaDevices`/APM loop;
- physical render must accept 48 kHz;
- Bluetooth/Tribit 44.1-kHz A2DP is not the accepted production output;
- JARVIS's own speech must not create false user turns;
- real human barge-in remains supported by the realtime conversation stack rather than a custom local gate.

Decision: `docs/decisions/ADR-011_LIVEKIT_MEDIADEVICES_48K_FULL_DUPLEX.md`.

---

## Vision / OWNER evidence — accepted foundation

Normal Vision uses video-only OpenCV capture:

```text
Pocket3 video
        ↓
OpenCVCameraSource
CapturedFrame(frame_id, captured_at=time.monotonic())
        ↓
RF-DETR person detection
        ↓
OC-SORT persistent visual track
        ↓
BlazeFace head association
        ↓
YuNet + SFace OWNER identity
        +
MiniFAS temporal passive liveness
        ↓
same Windows session + same visual track
        ↓
LIVE_OWNER_CANDIDATE / UNKNOWN / AMBIGUOUS / INSUFFICIENT
```

`LIVE_OWNER_CANDIDATE` remains evidence-only and does not create T2.

---

## Speaker identity — accepted shadow foundation

Canonical user speech is captured in memory from the actual conversation input:

```text
LiveKit processed user PCM
        ↓
ObservedSessionAudioInput
        ↓
InMemorySpeakerTurnCapture
        ↓
speech-region + quality gate
        ↓
CAM++ shadow diagnostics
```

Current disposition:

- CAM++ = provisional speaker-embedding provider;
- ERes2NetV2 = fallback challenger;
- no persistent voice template yet;
- no accepted speaker threshold yet;
- no prototype admission from mere visible OWNER context.

---

## Rejected architecture — dual Pocket3 microphone ownership

The following architecture is **not production**:

```text
Pocket3 microphone
   ├── LiveKit/PortAudio
   └── GStreamer wasapi2src
```

Real-machine evidence rejected both acquisition orders:

- GStreamer first → LiveKit microphone open fails (`PaErrorCode -9996`);
- PortAudio first → GStreamer paired AV pipeline fails to reach PLAYING.

This establishes a hard current-machine design rule:

> **One Pocket3 microphone owner.**

Evidence: `docs/research/STEP_3B11_DUAL_AUDIO_OWNERSHIP_ACCEPTANCE_RESULTS.md`.

---

## ADR-013 active-speaker architecture — implemented replacement

LR-ASD now reuses existing JARVIS timelines rather than opening another microphone:

```text
                            POCKET3
                               │
                ┌──────────────┴──────────────┐
                │                             │
             AUDIO                           VIDEO
                │                             │
     LiveKit MediaDevices only         OpenCV Vision source
     WebRTC AEC/NS/HPF/AGC                    │
                │                     CapturedFrame.captured_at
canonical accepted user PCM                   │
                │                     exact track/head sequence
ObservedSessionAudioInput                      │
                │                             │
InMemorySpeakerTurnCapture                     │
                └──────────────┬──────────────┘
                               │
                    monotonic-time overlap
                               │
                            LR-ASD
                               │
                    diagnostic score only
```

Production implementation:

- `src/jarvis/voice/media_devices_audio.py` — accepted full-duplex conversation path;
- `src/jarvis/voice/canonical_active_speaker_runtime.py` — canonical-turn speaker/LR-ASD diagnostics;
- `src/jarvis/voice/production_runtime.py` — single-microphone production assembly;
- `src/jarvis/identity/active_speaker.py` — LR-ASD provider + visual temporal buffer.

The production builder no longer instantiates `GStreamerPairedAVSource` for active-speaker sensing.

### Timing boundary

Both canonical audio observations and normal Vision frames use JARVIS monotonic timestamps.

LR-ASD is allowed to score only when:

- there is a fresh same-track OWNER context;
- the bounded canonical speech turn has timestamps;
- the visual buffer contains sufficient same-track coverage over the speech interval;
- temporal gaps remain within the provider boundary;
- speaker quality is accepted.

Insufficient timing/visual/speech evidence fails closed.

### Important uncertainty retained

The canonical audio is WebRTC AEC/NS/HPF/AGC processed rather than a second raw microphone stream. We do **not** assume this has zero impact on LR-ASD. That impact is measured during the real 3B.11 score-distribution bake-off before any active-speaker threshold is accepted.

Decision: `docs/decisions/ADR-013_SINGLE_OWNER_POCKET3_AUDIO_FOR_ACTIVE_SPEAKER.md`.

---

## Authority architecture — accepted and unchanged

```text
identity/context evidence
        ↓
graduated trust
        ↓
immutable ActionProposal
        ↓
deterministic risk floor
        ↓
OPA policy
        ↓
proposal-bound approval / strong verification
        ↓
final revalidation
        ↓
one-time permit
        ↓
execution + redacted audit
```

Accepted trust vocabulary:

- T0 `UNVERIFIED`
- T1 `PRESENT_CONTEXT`
- T2 `CORROBORATED_OWNER`
- T3 `VERIFIED_OWNER`

T2 is currently disabled until final multimodal corroboration is accepted.

Permanent invariant:

```text
face match       ≠ permission
speaker match    ≠ permission
liveness         ≠ permission
active speaker   ≠ permission
attention        ≠ permission
wake word        ≠ owner
Windows unlocked ≠ owner speaking
LLM confidence   ≠ permission
```

Decision: `docs/decisions/ADR-006_STEP_3_IDENTITY_TRUST_AUTHORITY_GOVERNANCE.md`.

---

## Deferred attention boundary

Attention/intent-to-engage remains deferred until a fixed monitor-mounted camera or stronger accepted eye/attention sensor exists. The movable Pocket3 is not treated as a stable monitor-relative gaze sensor.

Decision: `docs/decisions/ADR-007_STEP_3_ATTENTION_INTENT_EVIDENCE.md`.

---

## Current acceptance boundary

The ADR-013 replacement is implemented but not yet human-accepted.

Next real-machine proof must establish simultaneously:

```text
LiveKit Pocket3 microphone healthy
+ TV 48-kHz render healthy
+ normal Vision healthy
+ wake/conversation healthy
+ canonical user-turn timestamps healthy
+ overlapping same-track visual frames healthy
+ LR-ASD diagnostic scoring reachable
```

No active-speaker threshold, persistent voice-template admission, or T2 promotion is enabled by this implementation.

---

## Documentation control

When a production boundary changes:

1. update `CURRENT_ARCHITECTURE.md`;
2. update `CURRENT_PLAN.md`;
3. create/update an ADR for significant choices;
4. record real-machine evidence under `docs/research/`;
5. mark superseded experiments clearly;
6. delete dead production plumbing after replacement acceptance.
