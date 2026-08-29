# JARVIS V1 Current Architecture

This document describes implemented, validated, and human-accepted architecture only.

## Accepted Product Slices

- Step 0 — Clean Foundation: accepted.
- Step 1 — Natural Conversational Core: accepted on 2026-08-28.
- Step 2 — Wake, Voice Session, and Audio Robustness: accepted on 2026-08-29.

## Runtime Entry Points

- `python -m jarvis` runs the minimal non-voice foundation lifecycle.
- `jarvis-voice` runs the Step-2 product voice runtime: local idle wake detection,
  realtime conversation after activation, and return to idle.
- `lk agent console src/jarvis/voice/entrypoint.py` remains a Step-1 diagnostic harness;
  it is not the background wake runtime.

## Step-2 Runtime Flow

1. JARVIS opens one 48 kHz mono input stream and the selected output device.
2. While idle, microphone PCM stays local and feeds the wake detector through a
   controlled 16 kHz inference stream.
3. A threshold/debounce policy accepts one wake event and disables further wake
   scoring during activation and conversation.
4. Buffered wake-tail/pre-roll followed by live PCM enters one provider session.
5. LiveKit/provider events are translated into the canonical `ConversationSession`.
6. Explicit exit, inactivity, cancellation, or recoverable provider failure closes the
   active session and returns to local wake detection.

No realtime provider session exists while JARVIS is idle.

## Components and Ownership

### Canonical conversation

`src/jarvis/conversation.py` owns provider-independent session lifecycle and accepted
user/assistant turns. Provider history is operational state, not canonical JARVIS
truth. Conversation state is session-only and is not persisted.

### Wake detection

`src/jarvis/voice/wakeword.py` adapts LiveKit WakeWord model inference without using
its microphone-owning listener. It:

- receives PCM from the JARVIS audio owner;
- resamples 48 kHz mono audio to 16 kHz;
- evaluates a rolling two-second window every 80 ms;
- performs inference on one worker;
- applies confidence threshold, debounce, and a bounded detection queue.

The custom ONNX classifier is an external local asset and is not committed. The wake
detector owns neither the microphone nor provider activation.

### Local audio

`src/jarvis/voice/audio.py` owns the physical microphone and speaker lifecycle. It
provides:

- one LiveKit RTC `MediaDevices` input at 48 kHz mono with 10 ms frames;
- explicit `index:<PortAudio index>` selection when Windows exposes duplicate names;
- AEC, noise suppression, high-pass filtering, AGC, and reverse-stream processing;
- a 2.5-second memory-only ring buffer and 750 ms activation pre-roll;
- bounded capture/session queues, including a five-second capture buffer for provider startup;
- local output, pause/resume, clear, cleanup, and conservative interruption accounting.

### Wake/session lifecycle

`src/jarvis/voice/runtime.py` owns `STOPPED`, `IDLE`, `ACTIVATING`, `ACTIVE`, and
`RECOVERING` transitions. It starts a provider only after wake, rejects duplicate wake
events while active, applies bounded utterance/follow-up timeouts, accepts explicit
English/Hindi exit phrases, and restores idle detection after cleanup and cooldown.

### Voice intelligence boundary

`src/jarvis/voice/livekit_session.py` explicitly constructs either Gemini or OpenAI,
requires only the selected provider key, supplies initial instructions, maps finalized
events to canonical conversation state, and does not silently switch providers.

`src/jarvis/voice/agent.py` owns the concise JARVIS identity, truthful capability
framing, wake-only acknowledgement rule, and English/Hindi/Hinglish response routing.

`src/jarvis/config.py` owns validated environment configuration for provider, model,
voice, wake model/threshold, device selection, audio buffering, and session timeouts.
Secrets stay in process/user environment values and are not logged or committed.

## External Dependencies

- Python 3.11 or newer;
- `livekit==1.1.15`;
- `livekit-agents[google,openai]==1.7.1`;
- `livekit-wakeword==0.2.1`;
- one selected realtime-provider account/key;
- a local compatible wake-word ONNX model;
- Windows/PortAudio-visible audio devices.

LiveKit Cloud, a local LiveKit server, persistent memory, tools, and computer-control
dependencies are not part of the accepted runtime.

## Authoritative State

| State | Owner |
| --- | --- |
| Foundation lifecycle | `JarvisApp` |
| Environment configuration | `JarvisConfig` |
| Physical microphone/speaker | JARVIS local audio runtime |
| Wake inference | `WakeDetector` implementation |
| Wake/idle/active/recovery lifecycle | `VoiceRuntimeController` |
| Canonical accepted conversation | `ConversationSession` |
| Provider construction/event translation | JARVIS LiveKit boundary |
| Realtime inference and operational context | Selected provider/LiveKit |
| Identity, permissions, durable memory, tools | Not implemented |

## Validation and Human Evidence

Automated validation passes **52 tests** plus Ruff lint and formatting checks.

Real Windows use established:

- custom ONNX wake-model loading and repeated accepted detections above the configured
  `0.82` threshold;
- Voicemeeter input/output routing through explicit PortAudio indices;
- idle -> wake -> Gemini conversation -> follow-up -> explicit sleep -> idle -> re-wake;
- preservation of the immediate request after wake;
- English, Hindi, and Hinglish conversation and contextual follow-ups;
- wake-only acknowledgement without a duplicate substantive response;
- polite and final-clause exit commands;
- return to idle after inactivity and recoverable provider/key failure;
- no recurrence of the bounded capture-queue overflow after the startup-buffer fix;
- truthful denial of persistent memory and computer-control capability.

Human acceptance explicitly waived the long endurance matrix. The two-hour TV test,
20-trial detection/self-wake/cycle sets, device unplug/reconnect, and measured
wake/barge-in latency remain unverified. They must not be represented as passed.

## Current Limitations

- wake accuracy is specific to the external model, room, devices, and threshold;
- TV/background false activation and long-run stability are not exhaustively measured;
- wake-word recognition does not identify or authenticate the speaker;
- Voicemeeter is required on the currently tested Tribit path;
- PortAudio indices may change after driver/device changes;
- provider service, cost, privacy, preview status, and network availability still apply;
- there is no persistent memory, identity/authority layer, tool execution, or background
  Windows service.

## Architecture Update Rule

Add Step-3 architecture only after research, a recorded decision, human-approved
architecture, implementation, automated validation, and real human acceptance.
