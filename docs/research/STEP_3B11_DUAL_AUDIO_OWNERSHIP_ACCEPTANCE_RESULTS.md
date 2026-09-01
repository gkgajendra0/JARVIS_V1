# Step 3B.11 — Pocket3 Dual-Audio Ownership Acceptance Results

Status: **REJECTED — DUAL MICROPHONE OWNERSHIP IS NOT A VIABLE PRODUCTION BOUNDARY**

Date: 2026-09-02

## Purpose

The first production integration candidate kept LiveKit `rtc.MediaDevices` as the conversation microphone owner while also opening the physically paired Pocket3 audio endpoint in a GStreamer `wasapi2src` graph for raw synchronized LR-ASD evidence.

The goal of this acceptance run was to prove that both consumers could coexist on the real Windows/Pocket3 machine before deleting the historical conversation-audio experiments.

## Machine configuration at acceptance

- Conversation input: `Capture Input terminal (OsmoPocket3)` via Windows WASAPI at 48 kHz.
- Conversation output: `24'TV (NVIDIA High Definition Audio)` via Windows WASAPI at 48 kHz.
- Realtime provider: Gemini.
- Vision: enabled.
- Speaker shadow: enabled.
- Active-speaker shadow: enabled.
- LR-ASD: official pinned AVA checkpoint, integrity-verified and loaded on CUDA.

Startup configuration/preflight passed completely before the integration failure.

## Test A — GStreamer first, LiveKit/PortAudio second

Observed production startup sequence:

```text
Vision/GStreamer paired AV starts
        ↓
Pocket3 raw audio/video active
        ↓
LiveKit MediaDevices resolves Pocket3 microphone
        ↓
sounddevice.InputStream open
        ↓
PaErrorCode -9996: Invalid device
```

Important observations:

- Vision produced a real first frame.
- LR-ASD loaded successfully on CUDA.
- the persisted TV selector was correctly honored;
- GStreamer reported the paired Pocket3 AV source active;
- the failure occurred exactly when LiveKit attempted to open the Pocket3 microphone after GStreamer audio ownership had started.

## Test B — PortAudio first, GStreamer second

A bounded diagnostic opened the exact Pocket3 WASAPI microphone with `sounddevice.InputStream` first at 48 kHz. The stream became active successfully.

Then `GStreamerPairedAVSource` attempted to enter PLAYING.

Observed result:

```text
1. PortAudio input: Capture Input terminal (OsmoPocket3)
2. PortAudio started: active=True
3. GStreamer paired AV start
        ↓
RuntimeError: paired AV pipeline did not reach PLAYING
```

The diagnostic closed both resources cleanly afterward.

## Conclusion

The real Pocket3/Windows stack does not provide a reliable production boundary in which LiveKit/PortAudio and GStreamer independently open the same Pocket3 microphone endpoint.

Changing acquisition order merely changes which consumer fails:

```text
GStreamer first  → LiveKit microphone open fails
PortAudio first  → GStreamer paired AV start fails
```

Therefore **dual microphone ownership is rejected**.

This is not treated as an LR-ASD model failure, a Gemini failure, or a TV-output failure. It is a local media ownership/integration failure.

## Replacement direction

Keep exactly one Pocket3 microphone owner:

```text
Pocket3 microphone
        ↓
LiveKit MediaDevices only
WebRTC AEC + NS + HPF + AGC
        ↓
canonical timestamped user PCM
        ├── wake / conversation
        ├── speaker shadow
        └── LR-ASD audio evidence

Pocket3 video
        ↓
existing OpenCV Vision camera source
        ↓
timestamped exact frame + track/head sequence
        └── LR-ASD visual evidence
```

Both existing paths use monotonic timestamps inside JARVIS. LR-ASD remains diagnostic/non-authoritative until score-distribution acceptance.

The replacement deliberately avoids:

- opening a second microphone;
- writing temporary WAV/video files;
- creating another AEC implementation;
- restoring the failed GStreamer conversation-audio architecture;
- maintaining two microphone timelines when one accepted canonical timeline already exists.

## Remaining acceptance requirement

The replacement single-owner path must now prove on the real machine that:

1. `jarvis-voice` starts with vision + active-speaker shadow enabled;
2. LiveKit MediaDevices retains the proven Pocket3 → TV full-duplex behavior;
3. normal Vision runs simultaneously without opening Pocket3 audio;
4. real user turns produce timestamped canonical speaker windows;
5. exact Vision track/head frames overlap those windows sufficiently for LR-ASD scoring;
6. no active-speaker threshold or voice-prototype admission is promoted yet.

Only after that run may Step 3B.11 proceed to score-distribution scenarios.