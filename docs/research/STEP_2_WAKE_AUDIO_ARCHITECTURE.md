# Step 2 Wake and Audio Architecture Proposal

**Date:** 2026-08-28  
**Status:** PROPOSED — HUMAN APPROVAL REQUIRED  
**Implementation:** NOT AUTHORIZED

## Decision Summary

Replace the development-only `lk agent console` audio transport with one roomless,
JARVIS-owned local audio runtime. Keep the validated Step-1 `AgentSession`, provider
adapters, VAD settings, canonical conversation state, and interruption behavior.

Use `livekit-wakeword==0.2.1` only for its stateless `WakeWordModel` inference API. Do
not use its microphone-owning `WakeWordListener`. Keep Porcupine behind the same
detector contract as the immediate fallback if the custom ONNX model cannot pass real
acceptance testing.

## Runtime Shape

```text
Windows input (one open stream)
        |
LiveKit RTC MediaDevices + shared APM
        |
JARVIS LocalAudioRuntime (48 kHz mono)
        |-- rolling 2.5 s buffer
        |-- 16 kHz wake window -> WakeDetector while IDLE
        `-- pre-roll + live PCM -> AgentSession while ACTIVE

AgentSession output
        |
JARVIS LocalAudioOutput
        |
LiveKit RTC paired output + APM reverse stream
        |
Windows speaker (one open stream)
```

No idle audio leaves the process. A provider session and cloud audio begin only after
an accepted wake event.

## Components and Ownership

| Component | Responsibility | Must not own |
| --- | --- | --- |
| `VoiceRuntimeController` | Authoritative `STOPPED/IDLE/ACTIVATING/ACTIVE/RECOVERING` state; wake acceptance; session start/end; timeouts; cleanup ordering | PCM processing, provider history, canonical turns |
| `LocalAudioRuntime` | Open/validate one input and output; shared APM; continuous processed frames; resampling; ring buffer; routing; resource closure | Wake policy, provider session lifecycle, conversation truth |
| `WakeDetector` | Score supplied 16 kHz windows and emit a debounced detection | Microphone access, state transitions, provider startup |
| `SessionAudioInput` | LiveKit `AudioInput` backed by a bounded queue; accept pre-roll then live frames | Device access, wake inference |
| `LocalAudioOutput` | LiveKit `AudioOutput`; paired speaker playback; flush, clear, pause/resume accounting needed by interruption handling | Assistant text truth, lifecycle policy |
| existing LiveKit boundary | Build and run the selected realtime model/session; translate accepted events | Wake state, device acquisition |
| `ConversationSession` | Canonical accepted user/assistant turns for one active conversation | Wake/audio/provider operational state |

The detector and realtime provider remain replaceable independently. Neither contract
contains LiveKit room concepts.

## State Transitions

| From | Event | To | Required action |
| --- | --- | --- | --- |
| `STOPPED` | application start and devices validated | `IDLE` | Open local audio once; start local wake scoring. |
| `IDLE` | accepted, non-debounced wake detection | `ACTIVATING` | Disable wake scoring; freeze activation pre-roll; create one new conversation/provider session. |
| `ACTIVATING` | session input attached | `ACTIVE` | Enqueue 750 ms pre-roll, then live frames, in timestamp order. |
| `ACTIVATING` | provider/start failure | `RECOVERING` | Close partial session, clear output and queues, record truthful failure. |
| `ACTIVE` | explicit `go to sleep`/`end session` or inactivity | `IDLE` | Stop provider input, drain/cancel output, close provider session, clear wake window, apply cooldown, resume scoring. |
| `ACTIVE` | `stop` during assistant speech | `ACTIVE` | Treat as barge-in/cancel response, not automatic session exit. |
| any running state | device failure | `RECOVERING` | Stop cloud input immediately and close device/session resources deterministically. |
| `RECOVERING` | local audio successfully reopened | `IDLE` | Resume locally and expose the recovery truthfully. |
| any running state | shutdown | `STOPPED` | Close provider first, then output, router tasks, input, model executor. |

Only `VoiceRuntimeController` may change lifecycle state. Duplicate wake detections in
`ACTIVATING` or `ACTIVE` are ignored.

## Audio and Buffer Rules

- Open the validated device path at 48 kHz mono; never try to open the Tribit input
  directly at the wake model's 16 kHz rate.
- Device selection uses configured stable names/IDs resolved through the runtime's
  device enumeration. LiveKit CLI indices such as `16` and `4` are not persisted as
  product configuration because they belong to the console's enumeration.
- Consume processed input in 10 ms frames and retain at most 2.5 seconds in memory.
- Resample locally to 16 kHz and score a rolling two-second window every 80 ms while
  idle. Run model inference in exactly one worker thread so it cannot block audio I/O.
- On detection, send the newest 750 ms of processed 48 kHz audio before live frames.
  This intentionally may include the wake word; preserving the request is more
  important than removing the name. The value is configurable and must be tuned only
  if real tests show clipping or excess leading noise.
- Every queue is bounded. Input overflow is a visible session failure/metric, never an
  unbounded memory backlog or silent success.
- Wake windows and pre-roll are memory-only and cleared on transition, failure, and
  shutdown. They are never logged or persisted.

## Echo, Noise, and Interruption Boundary

LiveKit RTC `MediaDevices` owns WebRTC APM configuration. The same APM instance must
process microphone input and receive the actual speaker render stream. This preserves
AEC, noise suppression, high-pass filtering, and automatic gain across idle and active
modes.

`LocalAudioOutput` must implement LiveKit's `AudioOutput` contract:

- `capture_frame` buffers provider audio for physical playback;
- `flush` reports completion only after audible playout;
- `clear_buffer` discards pending playout immediately and reports interruption;
- playback position is conservative and never claims buffered but unheard audio;
- output closure occurs before APM/input closure.

Wake scoring is disabled throughout `ACTIVATING` and `ACTIVE`. Before returning to
`IDLE`, output is empty, the wake window is cleared, and a one-second configurable
post-output cooldown prevents assistant tail/self-echo from becoming a new wake event.

Voicemeeter remains a deployment workaround for the tested Tribit profile, not a
JARVIS architectural component. The runtime must also work with a directly compatible
device when one is available.

## Follow-up and Exit Semantics

- Initial request deadline: eight seconds after activation if no genuine user speech
  begins.
- Follow-up window: fifteen seconds after assistant physical playout completes.
- Genuine local/provider user-speech-start pauses the deadline while that utterance is
  in progress; it does not extend it indefinitely.
- A finalized accepted user turn and assistant physical playout completion are genuine
  conversational activity. Provider keepalives, partial internal updates, silence,
  wake scores, and output buffer writes are not.
- If speech starts but no accepted turn completes within fifteen seconds, treat it as a
  failed/empty utterance and return to the prior bounded deadline rather than staying
  active forever.
- `go to sleep` and `end session` are explicit exit intents. Bare `stop` interrupts the
  current response and leaves the follow-up session active.

These initial timeout values are configuration defaults for human acceptance, not
permanent product doctrine.

## Failure and Cleanup Order

1. Stop routing new microphone frames to the provider.
2. Cancel/close the active provider `AgentSession` and translate its terminal state.
3. Clear pending output and complete interruption accounting.
4. Close per-session input queues/tasks and the `ConversationSession`.
5. Clear pre-roll/wake buffers and reset detector debounce state.
6. On recoverable provider failure, keep healthy local audio open and return to `IDLE`.
7. On audio-device failure, close output before input/APM, retry only through an
   explicit bounded recovery path, and stop truthfully if reopening fails.

No exception path may leave a provider session receiving audio while JARVIS reports
`IDLE` or `STOPPED`.

## Dependencies and Assets

Runtime dependencies proposed for the first implementation:

- existing `livekit-agents[google,openai]==1.7.1` and its pinned RTC dependency;
- `livekit-wakeword==0.2.1` without the `listener` extra;
- one versioned custom `JARVIS` conv-attention ONNX classifier plus its recorded SHA-256.

Training dependencies and source recordings are development-only. Personal recordings,
room captures, and generated datasets must not be committed. The exported classifier
may be committed only after license, size, provenance, and real evaluation evidence are
recorded.

## Validation Required After Approval

### Automated

- controller transition table, duplicate-wake rejection, and invalid-state behavior;
- one audio source feeding wake and session routing without a second device opener;
- exact pre-roll/live ordering and bounded queues;
- timeout rules cannot be extended by silence or provider-only events;
- output flush versus interruption accounting;
- cleanup ordering for provider, device, cancellation, and shutdown failures;
- detector replacement using a fake detector and Porcupine-compatible contract;
- no imports or construction open audio/network/model resources as side effects.

### Real Windows acceptance

- 20 immediate `Jarvis, <request>` trials with no clipped request beginning;
- 19/20 detections across approved distances/volumes;
- at most one false activation in a two-hour representative TV/background trial;
- zero self-wakes in 20 assistant-response cycles;
- 20 wake -> conversation -> idle -> wake cycles;
- barge-in stops audible playout within the accepted bound and records only delivered
  output conservatively;
- unplug/reconnect, provider failure, Ctrl+C, and application stop leave no audio or
  worker resources active;
- confirm no network/provider session exists while `IDLE`.

## Known Downsides

- JARVIS must maintain two small LiveKit I/O adapters because `lk agent console` cannot
  be the background product runtime.
- The output adapter and wake-tail boundary are sensitive code and need focused real
  device validation.
- A custom one-word `JARVIS` model may still false-trigger on television; a longer
  phrase or Porcupine fallback may be required by measured evidence.
- Provider startup occurs after wake, so the first response is slower than keeping a
  paid/cloud session permanently connected. This is the correct privacy/cost tradeoff.
- AEC quality remains hardware/room dependent even with correct software ownership.

## Approval Requested

Approve this architecture for implementation. Approval authorizes the bounded Step-2
runtime, detector model provisioning, automated tests, and real Windows acceptance. It
does not authorize speaker identification, memory, tools, remote rooms, or Step 3.
