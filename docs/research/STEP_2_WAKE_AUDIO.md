# Step 2 Wake, Session, and Audio Research

**Date:** 2026-08-28  
**Status:** RESEARCH AND AUDIO TOPOLOGY RESOLVED — HUMAN REVIEW REQUIRED  
**Implementation:** NOT AUTHORIZED

## Required Outcome

JARVIS must detect its wake name locally, preserve the user's immediate request, enter
the accepted Step-1 realtime conversation, support follow-ups and barge-in, return to
idle, and recover cleanly from echo, background audio, device, provider, and shutdown
faults.

The detector is only one part of Step 2. Microphone ownership and lossless transition
from idle detection to active conversation are the harder architecture problem.

## Evidence Sources

- LiveKit wakeword documentation:
  https://docs.livekit.io/agents/multimodality/audio/wakeword/
- LiveKit wakeword implementation and benchmark:
  https://github.com/livekit/livekit-wakeword
- LiveKit wakeword model and listener APIs:
  https://github.com/livekit/livekit-wakeword/tree/main/src/livekit/wakeword/inference
- Official LiveKit wakeword desktop example:
  https://github.com/livekit-examples/hello-wakeword
- LiveKit Python RTC raw-track and local media-device APIs:
  https://docs.livekit.io/transport/media/raw-tracks/
- Picovoice Porcupine documentation:
  https://picovoice.ai/docs/porcupine/
- openWakeWord implementation/documentation:
  https://github.com/dscripka/openWakeWord
- sherpa-onnx keyword spotting documentation:
  https://k2-fsa.github.io/sherpa/onnx/kws/index.html
- V1 legacy map and accepted Step-1 research, which preserve relevant old-JARVIS
  wake-tail, follow-mode, audio ownership, AEC, device, and lifecycle failure evidence.

## Candidate Comparison

| Candidate | Strengths | Weaknesses | Preliminary classification |
| --- | --- | --- | --- |
| LiveKit WakeWord | Apache-2.0; local ONNX inference; Python 3.11+ Windows client; custom synthetic training; same vendor/ecosystem as accepted media layer; accepts 16 kHz PCM; official benchmark reports 0.08 false positives/hour and 86.1% recall for its evaluated `hey livekit` model | New in 2026; custom `JARVIS` model still requires training/evaluation; its convenience listener opens its own microphone and therefore cannot own audio in JARVIS | **ADAPT model API; REJECT convenience listener** |
| Picovoice Porcupine | Mature lightweight offline detector; Windows/Python; custom phrase model trains in seconds; strong vendor accuracy claims; no training dataset required | Requires Picovoice account/AccessKey and licensed proprietary runtime; custom models are platform-specific; adds a second vendor boundary; same microphone handoff problem remains | **PRESERVE as primary challenger** |
| openWakeWord | Apache-2.0; Windows ONNX; simple Python; 16-bit/16 kHz PCM; optional VAD and user-specific verifier | Public project updates are older; Windows noise-suppression support is weaker; LiveKit's published like-for-like benchmark reports much higher false positives and lower recall than its conv-attention successor | **REJECT as primary; model compatibility fallback** |
| sherpa-onnx KWS | Open-source; Windows; offline; open-vocabulary phrases without retraining; adjustable boosting and trigger thresholds | Operates more like tiny constrained ASR; requires model/token/keyword-file management; larger integration/tuning surface than a branded binary classifier; no evidence it solves audio ownership better | **REJECT as primary; reconsider if custom-model training fails** |
| Cloud ASR phrase matching | No wake-model training | Continuous cloud audio, recurring cost, latency, privacy exposure, network dependency, and semantic false triggers | **REJECT** |
| Old-JARVIS wake/audio runtime | Existing failure evidence and tests | Overlapping state, large controllers, duplicated audio/conversation ownership, and brittle follow-mode coordination | **REJECT runtime; ADAPT behavioural tests only** |

Vendor benchmark numbers are evidence for candidate selection, not proof on GK's Tribit,
Voicemeeter, room noise, television audio, accent, or chosen `JARVIS` phrase.

## Preliminary Technology Direction

Use **LiveKit WakeWord as the detector candidate** because it is local, open-source,
Windows/Python compatible, model-compatible with openWakeWord, and aligned with the
accepted LiveKit stack. Train a custom English `JARVIS` classifier and tune it using
real positive speech plus television/background negatives from the target room.

Do not adopt its official cloud/client topology automatically. JARVIS does not need
LiveKit Cloud merely to add a local wake name.

Porcupine remains the immediate replacement if the selected open model cannot meet the
real false-accept/false-reject gate without excessive training effort.

## Resolved Audio Topology

The current `lk agent console` transport remains a Step-1 development harness. It must
not become the Step-2 product runtime because the console owns audio outside the JARVIS
lifecycle boundary.

The selected topology is a **roomless, JARVIS-owned local audio runtime**:

1. LiveKit RTC `MediaDevices` opens one configured microphone and one speaker at the
   validated device rate, initially 48 kHz mono for the current Voicemeeter path.
2. Its paired input/output processing retains one WebRTC audio-processing module for
   echo cancellation, noise suppression, high-pass filtering, and automatic gain.
3. A JARVIS audio router continuously consumes the processed local track. It retains a
   bounded rolling buffer and resamples a copy to 16 kHz for wake inference while idle.
4. JARVIS calls the stateless `WakeWordModel.predict()` API on a sliding two-second
   window every 80 ms in one inference executor. It does not use `WakeWordListener`,
   because that convenience class opens a second PyAudio microphone.
5. On accepted detection, the router disables wake scoring, starts one existing
   `AgentSession`, supplies a custom LiveKit `AudioInput`, and first sends bounded
   pre-roll followed by live frames from the same uninterrupted capture.
6. A custom LiveKit `AudioOutput` writes provider frames through the paired local output
   path, reports playback completion, and clears buffered audio for barge-in.
7. When the conversational lifecycle ends, the provider session closes, output drains,
   the wake buffer is cleared, a short post-output cooldown is applied, and the same
   microphone stream returns to idle wake scoring without reopening the device.

This topology uses no LiveKit room, LiveKit Cloud, local LiveKit server, second
microphone opener, or idle provider connection.

### Evidence that the topology is viable

- LiveKit Agents 1.7.1 `AgentSession` accepts developer-supplied `AudioInput` and
  `AudioOutput`; room I/O is not required when those are present.
- LiveKit RTC `MediaDevices` exposes local PortAudio capture/playback with shared AEC,
  noise suppression, high-pass filtering, and automatic gain control.
- A local API probe against the pinned LiveKit RTC dependency proved that two
  `AudioStream` consumers can read one local `AudioSource`/track and that LiveKit can
  resample the same 48 kHz frame to a 16 kHz consumer without a room.
- The wake model is stateless and officially expects a rolling approximately two-second
  16 kHz window. Its official listener uses 80 ms frames and already runs inference in
  a single-thread executor; JARVIS preserves those timing choices while replacing only
  microphone ownership.

### Rejected topology alternatives

| Topology | Decision | Reason |
| --- | --- | --- |
| Official `hello-wakeword` client plus room | **REJECT** | Closes the wake listener, plays a chime, waits 1.5 seconds, opens conversation audio separately, assumes a LiveKit server, and does not transfer the wake tail. |
| Concurrent wake listener and `lk agent console` | **REJECT** | Two microphone owners, device contention, inconsistent AEC, and duplicate audio. |
| Sequential listener-to-console handoff | **REJECT** | Reopens the device and cannot transfer already captured immediate-request audio. |
| Self-hosted LiveKit room | **REJECT for Step 2** | Adds server, token, room, and network lifecycle without solving a requirement of this local desktop slice. |
| One JARVIS-owned local audio runtime | **ADAPT** | Preserves AEC and barge-in, keeps idle audio local, retains wake-tail, and gives one component deterministic ownership. |

The full proposed component and state design is recorded in
`docs/research/STEP_2_WAKE_AUDIO_ARCHITECTURE.md`.

## Old-JARVIS Lessons Applied

- exactly one component may own active microphone acquisition;
- speech following the wake phrase must not be lost;
- provider updates and silence must not extend follow mode indefinitely;
- speaker output must not self-wake or create false barge-in;
- invalid session state must stop acquisition;
- wake acknowledgement must not repeat stale content;
- cancellation, playback completion, device failure, and provider failure are different
  outcomes;
- retain old failure scenarios as tests, not the old voice controller.

## Proposed Acceptance Gates for Architecture Review

These values require human approval before implementation:

- no cloud streaming while idle;
- one microphone owner at every instant;
- no lost first-request words after wake in 20 consecutive trials;
- wake-to-active routing completes within 250 ms on the target PC, excluding provider
  first-response latency, which must be measured and reported separately;
- at most one false activation during a two-hour TV/background-audio trial;
- at least 19/20 correct detections across normal distance/volume trials;
- zero self-wakes from JARVIS playback in 20 response trials;
- follow-up expiry cannot be extended by silence/provider-only events;
- device/provider failure releases resources and returns to a truthful recoverable state;
- wake -> conversation -> idle -> wake cycle succeeds 20 consecutive times.

## Risks

- `JARVIS` is a common name in media and may false-trigger from television content;
- a one-word phrase is less distinctive than a longer phrase such as `Hey JARVIS`;
- synthetic training results may not transfer to GK's accent, room, or speakerphone;
- the current Voicemeeter path exposes different logical devices and sample rates;
- the newest LiveKit wakeword library has less production history than Porcupine;
- the custom local LiveKit `AudioInput`/`AudioOutput` adapters require focused tests for
  buffering, playout accounting, immediate clear, and deterministic closure;
- solving AEC completely in software may be impossible with the current Bluetooth
  speakerphone profile and physical room path.

## Recommendation

Approve **ADAPT LiveKit WakeWord 0.2.1 model inference**, **ADAPT LiveKit RTC 1.1.15
local media**, and **PRESERVE Porcupine as the replacement fallback**. Approve the
roomless single-microphone architecture in
`docs/research/STEP_2_WAKE_AUDIO_ARCHITECTURE.md`. Do not implement until that
architecture is explicitly approved.
