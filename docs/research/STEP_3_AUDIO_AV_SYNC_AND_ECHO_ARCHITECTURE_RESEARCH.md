# Step 3 — Audio/AV Synchronization and Echo Architecture Research

Status: **PROPOSED — RESEARCH/DESIGN ONLY — NO RUNTIME CHANGE ACCEPTED**

Date: 2026-08-31

Base revision: `9f302bd`

## Why this work exists

Real-machine integration revealed three separate problems that must not be conflated:

1. synchronized active-speaker evidence requires source-owned audio/video timing;
2. full-duplex conversation requires JARVIS playback to be removed from microphone input without destroying genuine user barge-in;
3. the realtime provider must not be the first component deciding whether residual JARVIS playback is user speech.

The Pocket 3 + DJI Mic Mini offline recording showed healthy synchronized A/V and healthy LR-ASD scores. Promoting the Pocket 3 audio endpoint directly into the current realtime conversation path exposed severe self-echo through the Tribit speaker. Therefore the physical hardware is not the sole problem; the live audio architecture must explicitly own render reference, near-end activity, source timing, and provider activity signaling.

## Source-owned audio rule

Every AV source owns paired audio intended for AV-sensitive inference.

```text
Pocket3 video -> Pocket3 paired audio
Lenovo video  -> Lenovo paired audio
```

LR-ASD/active-speaker scoring must not silently consume a globally selected conversation microphone if that microphone belongs to another physical source.

Conversation audio may be routed independently when needed, but AV-sensitive evidence remains bound to paired source audio and accepted synchronization health.

## Capture-once / branch-later principle

For each active microphone source, physical capture should occur once and then fan out through explicit branches.

```text
paired microphone capture
        ↓
source timestamp preserved once
        ↓
        ├── synchronized evidence branch
        │       └── active-speaker / sync diagnostics
        │
        └── speech branch
                ↓
              AEC
                ↓
        noise suppression / HPF / AGC as accepted
                ↓
              VAD / activity classification
                ↓
          wake / realtime provider / speaker ID
```

No second microphone should be opened merely for speaker or active-speaker work.

## Render-reference bus

JARVIS owns the exact PCM it sends to the physical speaker. That rendered signal must be available as an explicit echo-reference stream.

```text
JARVIS generated speech
        ↓
canonical render stream
        ├── physical output -> Tribit
        └── render-reference bus -> echo canceller
```

The render-reference bus is source-independent; each microphone/AEC path can consume it with source/output-specific timing state.

## Echo cancellation

Primary mature technology candidate: WebRTC Audio Processing Module / AEC3 through the existing LiveKit-compatible boundary.

The existing JARVIS path already feeds render audio into WebRTC APM. The architecture problem is not that echo cancellation is absent; it is that the current design lacks a complete source/output health and activity boundary for heterogeneous devices such as Bluetooth speaker output + USB/wireless camera microphone input.

AEC must be treated as a measurable provider rather than a binary on/off flag.

Desired diagnostics include where available:

- reported capture/render delay;
- residual echo likelihood;
- echo-return loss / enhancement;
- divergent-filter health;
- underrun/overrun/timing discontinuity counters.

NVIDIA Maxine Audio Effects AEC is retained as a benchmark challenger if WebRTC AEC3 cannot meet real-machine acceptance on the target hardware path. JARVIS must not build a custom echo-cancellation algorithm.

References:
- https://webrtc.googlesource.com/src/+/refs/heads/main/modules/audio_processing/g3doc/audio_processing_module.md
- https://docs.nvidia.com/maxine/afx/latest/AboutTheEffects/AboutAcousticEchoCancellation.html

## Do not solve echo by muting the microphone

Permanent behavior must preserve genuine full-duplex barge-in.

Rejected shortcut:

```text
JARVIS speaking -> mute microphone
```

This prevents the user from naturally saying "Jarvis, stop" or interrupting a long response.

Required target behavior:

```text
JARVIS speaking + user silent
        ↓
ECHO_ONLY / no near-end speech
        ↓
no user turn, no interruption

JARVIS speaking + user speaks
        ↓
DOUBLE_TALK / genuine near-end activity
        ↓
user turn preserved, JARVIS may be interrupted
```

## JARVIS-owned near-end activity

The realtime provider should not be the first layer deciding whether microphone activity represents the user.

Target flow:

```text
microphone
    ↓
AEC / cleanup
    ↓
local near-end activity classifier
    ↓
USER_SPEECH / ECHO_ONLY / DOUBLE_TALK / AMBIGUOUS
    ↓
JARVIS turn/activity controller
    ↓
realtime provider
```

Silero VAD is already available in JARVIS and remains the first mature near-end speech primitive. Additional mature turn-taking/noise-isolation systems such as Krisp VIVA may be evaluated only if the accepted WebRTC AEC + local VAD path remains inadequate.

## Provider-controlled activity signaling

Gemini Live supports disabling automatic activity detection and allowing the client to send explicit activity start/end events. This is a strong target architecture because JARVIS knows its own render stream and local activity state, while the remote provider does not.

Conceptual provider-neutral contract:

```text
RealtimeActivityController
- user_activity_started(timestamp)
- user_audio(frame)
- user_activity_ended(timestamp)
```

Provider adapters map this contract to Gemini/OpenAI/local realtime semantics.

This keeps echo/user-activity policy inside JARVIS and avoids provider-specific acoustic behavior becoming core architecture.

References:
- https://ai.google.dev/api/live
- https://ai.google.dev/gemini-api/docs/live-api/capabilities

## Wake-word boundary

Current testing also confirmed an older independent behavior: wake-word pre-roll can allow the wake phrase itself to enter the realtime session, producing a normal user turn such as `Jarvis` -> `Yes, sir`.

This is not a Pocket 3-specific echo problem and must not be mixed into AEC work.

Permanent wake behavior should preserve one-shot commands while suppressing wake-only leakage:

```text
"Jarvis"
    ↓
wake candidate
    ↓
no meaningful post-wake speech
    ↓
enter attentive/listening state without fabricating a conversational command

"Jarvis, explain quantum computing"
    ↓
wake candidate + meaningful post-wake speech
    ↓
retain command content without truncation
```

This requires an explicit wake-to-session boundary design after the source/audio foundation is stable.

## Synchronization health

Being exposed by one physical webcam does not guarantee that Windows video/audio callbacks share the same hardware clock. Each AV source needs observable synchronization health.

Conceptual state:

```text
AVSyncHealth
- source_id
- current offset estimate
- drift estimate
- timestamp discontinuities
- maximum visual/audio gap
- coverage
- state: HEALTHY / DEGRADED / UNHEALTHY / UNKNOWN
```

AV-sensitive inference requires accepted health. If timing becomes unhealthy, active-speaker scoring returns insufficient rather than guessing.

## GStreamer candidate

GStreamer is the leading candidate for replacing independent ad-hoc capture ownership with one clocked multimedia graph per AV source.

Candidate Windows elements include Media Foundation video capture and WASAPI audio capture. GStreamer provides pipeline clocks, running-time timestamps, and audio clock-slaving/resampling behavior intended for live A/V synchronization.

The migration must be compatibility-first:

- existing RF-DETR/tracking/SFace/MiniFAS consumers continue receiving normal in-memory frames;
- existing audio consumers continue receiving canonical PCM through adapters;
- old OpenCV/sounddevice/LiveKit capture remains available until the new source passes acceptance;
- no big-bang replacement.

## Active-speaker provider ranking after this research

The provider contract remains JARVIS-owned.

### LR-ASD

Retained as an open-source provider already integrated and proven healthy on an isolated synchronized Pocket 3 recording. No production threshold is accepted.

### NVIDIA Maxine Active Speaker Detection

Promoted to a serious Windows-local challenger because the current Maxine AR SDK exposes active-speaker detection with synchronized A/V inputs, tracking/speaking outputs, and synchronization tolerance controls on supported NVIDIA GPUs.

A real-machine bake-off must decide whether its runtime/licensing/integration characteristics are better than LR-ASD for JARVIS.

No switch is accepted merely from documentation or benchmark claims.

References:
- https://docs.nvidia.com/maxine/ar/latest/API/Architecture/using-ar-features.html
- https://docs.nvidia.com/maxine/ar/latest/API/Architecture/properties.html

## Multi-speaker diarization

If a selected active-speaker provider requires diarized audio in multi-person scenes, mature streaming diarization such as NVIDIA Streaming Sortformer may be benchmarked behind a separate provider boundary. It is not a prerequisite unless the chosen active-speaker design actually needs it.

## Required acceptance scenarios

Before any new full-duplex/audio architecture replaces the current known-good route, test at minimum:

```text
A. user silent while JARVIS speaks
B. user interrupts JARVIS while JARVIS speaks
C. user speaks while JARVIS silent
D. TV/phone playback while OWNER visible
E. JARVIS playback only while OWNER visible
F. Pocket3/Mic Mini interaction source
G. Lenovo interaction source when hardware exists
H. temporary paired-mic loss
I. temporary video loss
J. synchronization discontinuity/drift
K. wake-only phrase
L. wake phrase + command in one utterance
```

Acceptance requires no false user turns from JARVIS playback, preserved genuine barge-in, no silent cross-source audio substitution, and explicit fail-closed states for unhealthy AV evidence.

## Security and learning boundary

Echo-cleaned speech, speaker similarity, active-speaker results, VAD state, and source health are evidence only.

JARVIS playback must never be admitted into OWNER speaker prototypes. Ambiguous/double-talk audio must never bootstrap OWNER identity. No new source/audio inference directly changes protected-action authority.

## Decision status

**PROPOSED.**

The next action is a migration plan and bounded real-machine technology bake-offs. No runtime provider replacement is accepted by this document.
