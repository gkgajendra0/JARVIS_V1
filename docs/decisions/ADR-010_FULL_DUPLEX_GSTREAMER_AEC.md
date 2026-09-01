# ADR-010 — Full-Duplex GStreamer WebRTC AEC Media Fabric

**Status:** Accepted — implementation integrated, live JARVIS acceptance pending  
**Date:** 2026-09-01

## Context

The paired DJI Pocket 3 microphone hears JARVIS speech played through the physical room speaker. In realtime conversation this acoustic echo can be interpreted as new user speech, causing false barge-in/self-interruption.

The previous paired-audio implementation attempted to solve this in Python by playing through PortAudio, resampling the rendered PCM back to the WebRTC Audio Processing Module reverse stream, estimating output/capture delay, and calling `process_reverse_stream()`/`process_stream()` manually. The underlying WebRTC APM is mature, but JARVIS was taking responsibility for the hardest part: keeping the far-end reference, Bluetooth render latency, capture timing, and processing delay aligned across separate audio systems.

The active Step 3B sensor architecture already requires one GStreamer source to own the physically paired Pocket 3 video + microphone capture for synchronized active-speaker evidence. A second microphone owner would violate that architecture.

## Decision

Use one GStreamer full-duplex media graph as the paired JARVIS acoustic front end.

The graph owns:

- Pocket 3 microphone capture through `wasapi2src`.
- JARVIS speaker PCM through `appsrc`.
- the exact far-end reference through `webrtcechoprobe`.
- WebRTC acoustic echo cancellation through `webrtcdsp`.
- physical speaker render through `wasapi2sink`.
- paired video capture in the existing GStreamer graph.

The playback reference is normalized to 48 kHz mono before `webrtcechoprobe`. Physical render conversion happens **after** the echo probe, allowing the current 48 kHz JARVIS/Pocket 3 canonical format to coexist with the Tribit XSound Plus 2 44.1 kHz Bluetooth render endpoint.

The microphone splits into two semantically distinct branches:

1. **Raw paired PCM** — retained for synchronized LR-ASD/active-speaker evidence.
2. **AEC-cleaned PCM** — canonical for wake detection, conversation/VAD, realtime-provider input, and speaker-identity shadow analysis.

The two branches must not be silently substituted for each other.

The initial production DSP settings intentionally match the validated baseline:

- `echo-cancel=true`
- `noise-suppression=false`
- `gain-control=false`
- `high-pass-filter=false`

Noise suppression, gain control, and other processing may be evaluated independently later; they are not bundled into the AEC migration because preserving human double-talk/barge-in is more important than maximizing suppression.

The paired full-duplex path requires an explicit Windows WASAPI IMMDevice render endpoint through `JARVIS_AUDIO_OUTPUT_WASAPI_DEVICE`. It fails closed when that endpoint is not configured instead of following the mutable Windows default render device.

Deprecated WebRTC DSP timing flags such as `delay-agnostic` and `extended-filter` are not enabled. The current GStreamer/WebRTC implementation owns echo timing inside the shared media graph.

## Evidence

The isolated hardware acceptance test used the actual Pocket 3 microphone and Tribit XSound Plus 2 Bluetooth speaker. The Pocket 3 capture path was 48 kHz; the Tribit physical render endpoint negotiated 44.1 kHz.

In the controlled speaker-only region, AEC reduced measured RMS by roughly **40–52 dB** in multiple one-second windows. During the controlled human-speech region, raw versus cleaned speech level differed by only roughly **0.5–0.8 dB**, showing that the microphone was not merely muted while the speaker was active.

This validates the architecture baseline. Final acceptance still requires a real JARVIS/Gemini conversation run with spoken output and deliberate human interruption.

## Alternatives considered

### Continue the custom Python/LiveKit APM reverse-stream path

Rejected for the paired production path. WebRTC APM itself is appropriate, but manually reconstructing physical render timing across PortAudio, Bluetooth, resampling, and GStreamer capture creates unnecessary synchronization responsibility and had already produced unstable self-echo behavior.

### Windows endpoint/native AEC

Not selected as the primary architecture because behavior depends on endpoint/driver support and would not give JARVIS one explicit cross-device media fabric for Pocket 3 capture plus Tribit playback.

### Noise suppression only

Rejected. Noise suppression does not have the exact far-end reference needed to distinguish JARVIS speech from near-end human speech.

### Commercial AEC stacks

Krisp/NVIDIA-class solutions remain possible future challengers, but they add licensing/platform coupling without first exhausting the mature WebRTC AEC already available in the installed GStreamer stack.

## Why this choice

- Uses mature WebRTC AEC instead of inventing echo cancellation.
- Gives the AEC the exact far-end JARVIS PCM reference.
- Keeps capture and render in one GStreamer clock/media domain.
- Preserves the single-owner Pocket 3 sensor invariant.
- Preserves raw synchronized audio for LR-ASD while providing a separate conversational clean signal.
- Handles the real 48 kHz Pocket 3 / 44.1 kHz Bluetooth speaker combination.
- Removes the custom delay-estimation/reverse-stream burden from the paired production path.

## Consequences and tradeoffs

- Paired Step 3B operation now depends on the GStreamer `webrtcdsp`, `webrtcechoprobe`, and WASAPI2 plugins being present.
- The physical output endpoint must be configured explicitly and may need refreshing if Windows creates a new Bluetooth endpoint identity after device re-pairing.
- Playback buffering/interruption semantics now cross the LiveKit `AudioOutput` abstraction and GStreamer `appsrc`; live acceptance must verify flush/barge-in behavior.
- The non-paired `LocalAudioRuntime` remains as an independent fallback path and is not migrated by this ADR.

## Replacement boundary

The paired runtime consumes a GStreamer-backed audio output plus canonical 48 kHz mono cleaned PCM. A future AEC engine can replace the DSP internals if it preserves:

- one physical microphone owner,
- exact far-end reference,
- synchronized raw A/V evidence,
- clean conversation PCM,
- human double-talk preservation,
- bounded latency and interruption semantics.

## Reconsider when

Revisit this decision if real JARVIS acceptance shows any of the following despite correct endpoint selection:

- repeated self-interruption from residual JARVIS speech,
- human barge-in is materially suppressed,
- unacceptable Bluetooth/render latency,
- GStreamer playback flush is unreliable,
- raw Pocket 3 A/V synchronization regresses,
- a clearly superior supported AEC stack provides materially better double-talk performance with equal or lower integration complexity.

A later decision may move realtime-provider activity truth to the local Silero/JARVIS turn controller. That is deliberately separate from this AEC migration.
