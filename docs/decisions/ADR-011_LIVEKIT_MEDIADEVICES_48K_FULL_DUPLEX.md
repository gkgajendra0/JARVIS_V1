# ADR-011 — LiveKit MediaDevices 48 kHz Full-Duplex Conversation Audio

**Status:** Accepted — supersedes ADR-010 for conversation audio  
**Date:** 2026-09-01

## Context

Live JARVIS acceptance disproved the production suitability of the GStreamer/Tribit Bluetooth conversation path selected in ADR-010. Although isolated GStreamer WebRTC AEC measurements showed strong echo suppression, real Gemini Live conversation still produced repeated false user turns containing fragments of JARVIS's own speech. A later custom Silero barge-in gate also falsely admitted residual assistant audio and is therefore not part of the production design.

Research of the installed/current LiveKit Python SDK identified `rtc.MediaDevices` as the supported full-duplex local-device helper. When `open_input(enable_aec=True)` and `open_output()` are created from the same `MediaDevices` instance, LiveKit owns the WebRTC AudioProcessingModule capture path, reverse speaker stream, and PortAudio delay estimator.

The current LiveKit helper uses fixed 480-sample APM frames, i.e. 10 ms at 48 kHz. A 44.1 kHz render path therefore cannot be used safely for the validated AEC loop. The Tribit Bluetooth A2DP endpoint exposed 44.1 kHz and produced persistent self-echo in live conversation.

## Decision

Use LiveKit `rtc.MediaDevices` for the canonical JARVIS conversation audio path:

- Pocket 3 microphone capture at 48 kHz mono.
- WebRTC AEC enabled by LiveKit.
- LiveKit noise suppression, high-pass filter, and automatic gain control enabled.
- Physical conversation output must accept 48 kHz.
- `open_input()` and `open_output()` must use the same `MediaDevices` instance so the official reverse-stream AEC wiring is preserved.
- The currently accepted physical render endpoint is the NVIDIA HDMI `24'TV` output at 48 kHz.
- The production runtime fails closed when the selected conversation output cannot accept 48 kHz.

The paired GStreamer Pocket 3 pipeline remains separate and is retained only for synchronized raw video/audio sensor evidence required by Step-3 active-speaker diagnostics. It no longer owns conversation playback, conversation AEC, or provider microphone audio in the production builder.

## Acceptance evidence

The exact Pocket 3 microphone + TV/NVIDIA 48 kHz path was tested with Gemini Live.

### Silence while JARVIS speaks

JARVIS completed a detailed Snowflake architecture response without producing fake user transcripts from its own speech.

### Real human barge-in

A deliberate user interruption stopped JARVIS and was accepted as a real user turn.

### Control comparison

With the Tribit Bluetooth output path, the transcript repeatedly contained assistant speech as user turns, including fragments such as `and separate storage`, `Pardon me?`, and `You interrupted.` The TV/48 kHz run removed that behavior.

This proves the architecture requirement that matters: assistant speech does not self-trigger, while real double-talk/barge-in remains functional.

## Rejected approaches

### GStreamer full-duplex conversation AEC with Tribit Bluetooth

Rejected for production conversation audio after live acceptance failure. ADR-010 remains useful as historical research and isolated DSP evidence, but its conversation-audio decision is superseded by this ADR.

### Custom Silero barge-in gate

Rejected. Residual assistant speech was classified as user speech in a real run. JARVIS will not maintain a hand-built echo/barge-in classifier for a problem already owned by RTC/audio-processing stacks.

### 44.1 kHz MediaDevices output

Rejected with the current LiveKit helper. Its fixed 480-sample APM framing requires 48 kHz for a 10 ms frame and produced a native APM panic when used with 44.1 kHz output.

### Commercial voice-isolation layer

Deferred. ai-coustics/Krisp-class primary-speaker isolation remains a challenger only if the validated WebRTC AEC path later proves insufficient in a different acoustic environment.

## Architecture

```text
Pocket 3 microphone @ 48 kHz
        |
        v
LiveKit MediaDevices
WebRTC AEC + NS + HPF + AGC
        |
        v
Gemini Live / AgentSession
        |
        v
LiveKit MediaDevices OutputPlayer @ 48 kHz
        |
        v
NVIDIA HDMI -> 24'TV speakers
```

Independent Step-3 evidence path:

```text
Pocket 3 paired raw A/V
        |
        v
GStreamer synchronized sensor capture
        |
        +--> vision
        +--> raw audio for LR-ASD / active-speaker diagnostics
```

## Consequences

- `JARVIS_AUDIO_OUTPUT_DEVICE` is the canonical conversation render selector.
- `JARVIS_AUDIO_OUTPUT_WASAPI_DEVICE` is no longer used by the production conversation path.
- A selected 44.1 kHz-only Bluetooth endpoint fails closed instead of silently degrading AEC.
- GStreamer remains valuable for synchronized perception but is no longer coupled to assistant playback.
- The old paired GStreamer/custom barge-in implementation is retained only as historical/rollback code until the integrated production run confirms that MediaDevices and raw paired GStreamer capture can coexist on the Pocket 3 endpoint; after that acceptance it should be removed rather than maintained in parallel.

## Final integration gate

Before deleting the historical paired conversation implementation, run `jarvis-voice` with Step-3 active-speaker sensing enabled and confirm that Windows allows the raw GStreamer sensor capture and LiveKit MediaDevices microphone capture to coexist on the Pocket 3 endpoint. If that passes, remove the obsolete paired conversation and custom barge-in modules/tests in the same cleanup change.
