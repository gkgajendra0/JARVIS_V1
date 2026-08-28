# ADR-002: Step 2 Wake and Local Audio Runtime

**Status:** ACCEPTED — IMPLEMENTATION AUTHORIZED

**Date:** 2026-08-28

**Decision owner:** Human-approved JARVIS planning

## Context

Step 2 must add local wake detection, preserve speech immediately following the wake
name, retain natural follow-ups and barge-in, and return to idle without streaming room
audio to a provider. The Step-1 `lk agent console` path is a development harness: it
owns microphone and speaker access outside JARVIS and cannot transfer wake-tail audio.

The supporting comparison and full approved design are recorded in
`docs/research/STEP_2_WAKE_AUDIO.md` and
`docs/research/STEP_2_WAKE_AUDIO_ARCHITECTURE.md`.

## Decision

1. **ADAPT LiveKit WakeWord 0.2.1** through its stateless `WakeWordModel` API.
2. **REJECT its `WakeWordListener`** because that convenience class opens a second
   microphone.
3. **ADAPT LiveKit RTC local media** into one roomless, JARVIS-owned audio runtime with
   shared input/output APM processing.
4. Keep one 48 kHz mono device stream open and derive a local 16 kHz wake-inference
   stream through controlled resampling.
5. Retain a 2.5-second memory-only ring buffer and send 750 ms pre-roll before live
   frames when activation begins.
6. Supply custom LiveKit `AudioInput` and `AudioOutput` adapters to the accepted
   Step-1 `AgentSession`; do not require a LiveKit room, Cloud, or local server.
7. Disable wake scoring during activation and conversation. Clear output and wake
   buffers and apply a one-second cooldown before returning to idle.
8. Preserve Porcupine behind the detector boundary as the first fallback if the custom
   ONNX classifier fails real acceptance.
9. Keep `ConversationSession` authoritative for accepted turns and a new JARVIS
   controller authoritative for wake/session lifecycle.
10. Keep personal wake recordings and generated training data out of the repository.

## Alternatives Considered

- Official LiveKit wakeword client plus room: rejected because it closes/reopens audio,
  waits after detection, loses immediate-request continuity, and adds room/server state.
- Concurrent wake listener and console: rejected because it creates two microphone
  owners and inconsistent echo handling.
- Sequential listener-to-console handoff: rejected because captured wake-tail cannot be
  transferred reliably.
- Self-hosted LiveKit server: rejected for this local slice because it adds
  infrastructure without satisfying an additional requirement.
- Porcupine primary: not selected because it adds an account, AccessKey, proprietary
  runtime, and platform-specific classifier, but remains the operational fallback.

## Why This Choice

- one authoritative device owner;
- no provider connection or network audio while idle;
- no lost immediate request caused by reopening the microphone;
- retains LiveKit AEC, noise processing, interruption, and provider integration;
- no room/server dependency;
- detector and provider can be replaced independently.

## Consequences and Tradeoffs

JARVIS must maintain two focused local LiveKit I/O adapters and validate their buffer,
playout, interruption, and cleanup behavior. A custom one-word classifier may still
false-trigger on television. Provider startup after wake adds latency compared with a
permanently connected paid session. AEC quality remains dependent on the real device
and room.

The runtime must fail clearly when the configured ONNX model or audio device is absent.
Step 2 cannot be marked complete until the custom model and real Windows audio path pass
the documented acceptance trials.

## Replacement Boundary

`WakeDetector` receives PCM and emits detections; it never owns a microphone or starts a
provider. The local audio runtime owns PCM and devices but not wake policy or canonical
conversation state. The lifecycle controller owns state transitions but not provider
history. The existing LiveKit boundary owns provider construction and event translation.

Replacing the wake detector must not change audio ownership, the provider adapter, or
canonical conversation state. Replacing the realtime provider must not change idle wake
detection or local device ownership.

## Reconsideration Triggers

Reconsider LiveKit WakeWord if the trained `JARVIS` classifier cannot meet false-accept
and recall gates on the target Windows machine. Evaluate Porcupine first.

Reconsider the local media topology if the pinned RTC APIs cannot provide conservative
playout accounting, prompt barge-in, deterministic cleanup, or acceptable AEC without
private SDK internals. Do not add a room/server unless a concrete requirement needs it.
