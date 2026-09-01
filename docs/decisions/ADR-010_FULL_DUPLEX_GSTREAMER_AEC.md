# ADR-010 — Full-Duplex GStreamer WebRTC AEC Media Fabric

**Status:** SUPERSEDED FOR CONVERSATION AUDIO BY ADR-011  
**Original date:** 2026-09-01

> Historical decision record. The isolated GStreamer/WebRTC AEC experiment produced useful DSP evidence, but real JARVIS/Gemini conversation acceptance failed on the Tribit Bluetooth render path. `ADR-011_LIVEKIT_MEDIADEVICES_48K_FULL_DUPLEX.md` is the current production conversation-audio decision. GStreamer remains in the architecture only for synchronized raw Pocket3 A/V evidence used by Step-3 perception/active-speaker work.

## Original context

The paired DJI Pocket3 microphone hears JARVIS speech played through the physical room speaker. In realtime conversation this acoustic echo can be interpreted as new user speech, causing false barge-in/self-interruption.

The previous paired-audio implementation attempted to solve this in Python by playing through PortAudio, resampling rendered PCM back to the WebRTC Audio Processing Module reverse stream, estimating output/capture delay and calling `process_reverse_stream()`/`process_stream()` manually. The underlying WebRTC APM is mature, but JARVIS was taking responsibility for difficult far-end reference/timing alignment across separate audio systems.

Step 3B also required synchronized Pocket3 video + raw microphone capture for active-speaker evidence, which motivated investigating one GStreamer media graph.

## Original decision

The experiment used one GStreamer full-duplex graph for:

- Pocket3 microphone capture through `wasapi2src`;
- JARVIS speaker PCM through `appsrc`;
- far-end reference through `webrtcechoprobe`;
- WebRTC echo cancellation through `webrtcdsp`;
- physical speaker render through `wasapi2sink`;
- paired video capture in the same graph.

Raw microphone PCM was retained separately from AEC-cleaned PCM so LR-ASD/active-speaker work could preserve the physical capture timeline.

## Isolated evidence that originally motivated acceptance

The hardware experiment used the actual Pocket3 microphone and Tribit XSound Plus 2 Bluetooth speaker. Pocket3 capture was 48 kHz; the Tribit render endpoint negotiated 44.1 kHz.

In controlled speaker-only windows, measured AEC reduction was roughly 40–52 dB. In controlled human-speech windows, raw-vs-clean speech level differed by roughly 0.5–0.8 dB. This showed that GStreamer's WebRTC DSP could suppress a controlled echo signal without simply muting all microphone input.

That evidence remains valid as an **isolated DSP experiment**. It was not sufficient to prove production conversational behavior.

## Real acceptance failure

Subsequent real Gemini Live runs disproved this path as the production conversation architecture.

While JARVIS spoke through the Tribit Bluetooth path, the transcript repeatedly created fake user turns from JARVIS's own speech. Examples included fragments such as:

- `and separate storage`;
- `Pardon me?`;
- `You interrupted.`

A later custom AEC-clean local Silero barge-in gate also falsely admitted residual assistant audio after approximately the configured minimum speech duration. That gate is therefore rejected as a production solution as well.

The failure established that isolated dB suppression was not the acceptance criterion that matters. The real requirement is:

```text
JARVIS speaking + human silent
→ no user turn / no self-interruption

JARVIS speaking + real human interruption
→ real barge-in accepted
```

The GStreamer + Tribit Bluetooth conversation path did not meet the first requirement reliably.

## Replacement decision

ADR-011 selected the mature LiveKit `rtc.MediaDevices` full-duplex path with a native 48-kHz physical render endpoint.

Accepted production conversation path:

```text
Pocket3 microphone @ 48 kHz
        ↓
LiveKit MediaDevices
WebRTC AEC + NS + HPF + AGC
        ↓
Gemini Live / AgentSession
        ↓
LiveKit MediaDevices OutputPlayer @ 48 kHz
        ↓
NVIDIA HDMI → 24'TV speakers
```

The exact Pocket3 + TV/NVIDIA 48-kHz path passed real acceptance: long assistant speech completed without self-trigger and deliberate human barge-in still worked.

See `docs/decisions/ADR-011_LIVEKIT_MEDIADEVICES_48K_FULL_DUPLEX.md`.

## What remains from ADR-010

GStreamer remains valuable for synchronized perception:

```text
Pocket3 paired raw A/V
        ↓
GStreamer synchronized sensor capture
        ├── video → Vision / visual track sequence
        └── raw audio → LR-ASD / active-speaker diagnostics
```

It no longer owns production conversation playback, conversation AEC or provider microphone audio in the production runtime builder.

## Historical lessons retained

- Use mature RTC echo cancellation rather than inventing acoustic DSP or custom barge-in classifiers.
- Isolated suppression metrics do not replace real full-duplex conversational acceptance.
- Bluetooth/render timing can invalidate an otherwise reasonable AEC design on the actual hardware path.
- Raw synchronized sensor evidence and conversational audio do not need to share the same playback/AEC owner.
- Superseded experiments should remain documented long enough to preserve the reason they were rejected, then be removed from production code once replacement integration is proven.
