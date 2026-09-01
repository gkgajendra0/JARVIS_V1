# Step 3B.11 — Single-Owner Active-Speaker Integration Acceptance

Status: **REAL-MACHINE INTEGRATION ACCEPTED — SCORE-DISTRIBUTION BAKE-OFF NEXT**

Date: 2026-09-02

## Accepted runtime boundary

The real JARVIS machine accepted the ADR-013 replacement architecture:

```text
Pocket3 microphone @ 48 kHz
        ↓
LiveKit rtc.MediaDevices only
WebRTC AEC + NS + HPF + AGC
        ↓
canonical timestamped JARVIS user PCM
        ├── realtime conversation
        ├── speaker-shadow diagnostics
        └── LR-ASD active-speaker audio

Pocket3 video
        ↓
normal OpenCV Vision source
        ↓
timestamped Vision frame + track/head sequence
        ↓
LR-ASD active-speaker visual input
```

No second Pocket3 microphone owner is opened.

## Real-machine startup result

`jarvis-voice` passed consolidated startup preflight with:

- wake model: accepted ONNX `jarvis` model;
- realtime provider: Gemini with available credential;
- conversation microphone: `Capture Input terminal (OsmoPocket3)` at 48 kHz;
- conversation output: `24'TV (NVIDIA High Definition Audio)` at 48 kHz;
- speaker/vision dependency: passed;
- pinned LR-ASD AVA checkpoint: passed;
- active-speaker dependency: passed.

Runtime then started successfully with all of the following active at the same time:

- LiveKit MediaDevices full-duplex audio;
- WebRTC AEC + NS + HPF + AGC;
- integrated Pocket3 Vision;
- RF-DETR person detection;
- persistent tracking;
- head detection;
- voice wake detection;
- Gemini realtime conversation;
- speaker-shadow turn capture;
- LR-ASD active-speaker shadow provider on CUDA;
- Vision lock and PTZ follow controls.

This closes the device-contention failure that rejected dual PortAudio/GStreamer Pocket3 audio ownership.

## Observed functional evidence

During the accepted run:

- Vision changed from 0 to 1 visible tracked person.
- JARVIS correctly answered that one person was currently visible.
- An explicit command successfully locked the only head-confirmed person (`track 0`).
- Follow mode was explicitly armed and Vision reported follow active.
- Canonical LiveKit speaker-shadow captures produced normal quality-gate results.
- LR-ASD produced real scored windows instead of startup/device failures.

Representative accepted LR-ASD observations included:

```text
window=2.74s | visual=60/60@21.70fps | audio_features=240
mean=0.3426 | median=0.1367 | min=0.0040 | max=0.9505

window=1.98s | visual=45/45@23.08fps | audio_features=180
mean=0.0040 | median=0.0029 | min=0.0016 | max=0.0085

window=3.99s | visual=89/89@22.26fps | audio_features=356
mean=0.7443 | median=0.9030 | min=0.1472 | max=0.9969
```

These values are **diagnostic observations only**. They demonstrate functioning synchronized inference; they do not establish an accepted active-speaker threshold.

## Safety / authority state

The accepted run preserved all fail-closed boundaries:

- `active_speaker_confirmed=False` remains hard-coded during this bake-off stage;
- CAM++ prototype admission remains disabled;
- LR-ASD scores do not grant OWNER identity;
- face/liveness evidence does not independently grant T2;
- T2 `CORROBORATED_OWNER` remains disabled;
- protected-action authority is unchanged.

## Important behavior noted during the run

JARVIS verbally stated that it could not confirm the visible person's identity even though the internal OWNER-context bridge reported fresh live-owner context. This is a tool/agent capability-exposure issue, not evidence that the identity pipeline is absent. Identity output must only be exposed to the agent through an explicitly accepted bounded tool/predicate; no authority semantics are changed by this observation.

## Vision preview observation

The integrated `OpenCVVisionObserver` already renders the exact canonical JARVIS interpretation (tracks, heads, selected target, follow state, framing and PTZ command), but the accepted run did not show the window because preview was opt-in through `JARVIS_VISION_PREVIEW`.

Post-acceptance correction: production integrated Vision now enables that existing preview by default when Vision is active. An explicit `JARVIS_VISION_PREVIEW=false` remains available for headless/quiet runs.

## Next acceptance work

Proceed to the bounded 3B.11 score-distribution / negative-scenario bake-off:

1. OWNER visible + OWNER speaking;
2. OWNER visible + TV/off-camera speech;
3. JARVIS playback only;
4. OWNER voice replay from another device;
5. OWNER + second visible person, each speaking independently;
6. overlap/background speech;
7. temporary head/face loss;
8. timestamp-offset sensitivity.

Only after those distributions establish a safe temporal rule may `ACTIVE_OWNER_SPEAKER` be promoted from diagnostic output. Prototype admission and T2 remain disabled until their separate acceptance gates pass.
