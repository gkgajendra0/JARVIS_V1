# ADR-013 — Single-Owner Pocket3 Audio for Active-Speaker Corroboration

**Status:** Accepted for implementation — real-machine replacement acceptance pending  
**Date:** 2026-09-02

## Context

JARVIS already has a real-machine accepted full-duplex conversation path:

```text
Pocket3 microphone @ 48 kHz
        ↓
LiveKit rtc.MediaDevices
WebRTC AEC + NS + HPF + AGC
        ↓
Gemini Live
        ↓
LiveKit MediaDevices output
        ↓
NVIDIA HDMI / 24'TV @ 48 kHz
```

Step 3B.11 initially attempted to preserve a second raw Pocket3 audio stream by opening the same microphone endpoint through GStreamer `wasapi2src` while LiveKit/PortAudio simultaneously owned the conversation microphone.

Real-machine acceptance disproved that boundary in both acquisition orders:

- GStreamer first → LiveKit `sounddevice.InputStream` fails with `PaErrorCode -9996: Invalid device`;
- PortAudio first → GStreamer paired AV pipeline does not reach PLAYING.

Detailed evidence: `docs/research/STEP_3B11_DUAL_AUDIO_OWNERSHIP_ACCEPTANCE_RESULTS.md`.

## Decision

Adopt **one microphone owner** for the current Pocket3/Windows system.

LiveKit MediaDevices remains the only Pocket3 microphone owner because it is the only path that has passed real full-duplex conversation acceptance with correct self-echo suppression and real barge-in on the accepted 48-kHz TV output.

Active-speaker corroboration reuses the existing canonical timestamped user-turn PCM instead of reopening the microphone.

The visual side reuses the accepted OpenCV Vision camera source and the existing exact frame/snapshot tap.

Target architecture:

```text
                            POCKET3
                               │
                ┌──────────────┴──────────────┐
                │                             │
             AUDIO                           VIDEO
                │                             │
     LiveKit MediaDevices only         OpenCV Vision source
     AEC + NS + HPF + AGC                    │
                │                     CapturedFrame.captured_at
     canonical 48-kHz PCM                    │
                │                     exact track/head sequence
ObservedSessionAudioInput                     │
                │                             │
InMemorySpeakerTurnCapture                    │
                └──────────────┬──────────────┘
                               │
                    monotonic-time alignment
                               │
                            LR-ASD
```

## Why canonical processed PCM is acceptable for the next benchmark

LR-ASD requires aligned speech audio and visual face sequences; it does not require a second physical microphone capture. JARVIS already records bounded canonical user-turn PCM and monotonic observation timestamps for speaker-shadow diagnostics.

Using the same canonical PCM for LR-ASD has additional safety/operability advantages:

- one physical microphone owner;
- one conversation/speaker audio timeline;
- no duplicate device contention;
- no second AEC implementation;
- no temporary media files;
- active-speaker scoring is bound to the same speech JARVIS actually accepted as the user turn.

This does **not** mean that AEC/NS/AGC effects on LR-ASD are assumed harmless. Their effect is part of the real-machine score-distribution benchmark. No active-speaker threshold is promoted until measured.

## Timing rule

Audio and video evidence must remain in JARVIS monotonic time.

- canonical audio frames are timestamped when routed into the JARVIS conversation path;
- normal Vision `CapturedFrame` objects are timestamped with `time.monotonic()` at capture publication;
- LR-ASD windows are constructed only when the same visual track has sufficient temporal overlap with the bounded canonical speech turn;
- gaps, stale evidence, track changes, or insufficient overlap fail closed as `INSUFFICIENT` / `AMBIGUOUS`.

## Rejected alternatives

### Retry dual audio ownership with different start order

Rejected by direct real-machine evidence in both orders.

### Restore GStreamer as the canonical conversation audio owner

Rejected. The prior GStreamer conversation path failed real Gemini self-echo acceptance, while the current LiveKit MediaDevices + TV path passed.

### Build another custom echo canceller

Rejected. LiveKit already exposes the mature WebRTC AudioProcessingModule and the current MediaDevices path is accepted. The problem is device ownership, not lack of DSP technology.

### Persist raw AV to files and run LR-ASD offline

Rejected for privacy, latency, and architecture reasons. Step 3 requires bounded memory-only evidence and realtime actor corroboration.

## Consequences

- GStreamer paired audio is removed from the production active-speaker path.
- The historical GStreamer sensor code may remain temporarily for diagnostics/legacy tests until replacement acceptance is complete, then dead production plumbing is removed.
- Active-speaker scoring uses canonical processed user PCM plus the exact Vision frame/track sequence.
- Any AEC/NS/AGC impact on LR-ASD must be measured during 3B.11 acceptance rather than guessed.
- T2, T3, persistent voice enrollment, and prototype admission remain unchanged/disabled.

## Acceptance gate

Before this ADR is marked human-accepted:

1. production builder no longer opens Pocket3 audio through GStreamer;
2. `jarvis-voice` starts with vision + speaker + active-speaker shadow enabled;
3. Pocket3 → LiveKit → TV full duplex remains healthy;
4. normal Vision remains healthy simultaneously;
5. committed user turns create bounded canonical PCM windows with usable monotonic timestamps;
6. LR-ASD receives overlapping visual windows and produces diagnostic scores on real OWNER speech;
7. no threshold/prototype admission is enabled yet;
8. documentation is reconciled after the run.
