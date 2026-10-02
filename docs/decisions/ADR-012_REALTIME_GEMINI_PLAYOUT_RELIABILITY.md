# ADR-012 — Realtime Gemini Playout Reliability Without Regressing WebRTC AEC

**Status:** Proposed / implementation under owner-machine acceptance  
**Date:** 2026-10-02  
**Supersedes:** none  
**Preserves:** ADR-011 LiveKit MediaDevices 48 kHz full-duplex AEC architecture

## Context

ADR-011 established the production voice topology after physical tests showed that JARVIS could hear its own speaker output and create false user turns. The accepted fix was to keep microphone capture and physical speaker render on the same LiveKit `rtc.MediaDevices` instance so WebRTC's AudioProcessingModule receives the exact reverse render stream and delay estimate used for AEC.

In October 2026 physical runs showed a different failure mode: Gemini Live generated complete utterances, but local playback contained audible gaps. Logs showed repeated `AudioMixer ... timeout, ignoring` warnings while utterances later completed with `interrupted=False`, and playback diagnostics sometimes started with only tens of milliseconds queued.

The same runtime also contained synchronous capability-catalog discovery on the realtime asyncio loop. While a GICC goal was waiting for capability acquisition, reconciliation could repeatedly call `CapabilityRuntime.refresh_catalog()`; Windows discovery sources may execute bounded synchronous subprocesses.

## Research findings

1. Gemini remains the speech source. The failure is downstream of Gemini generation.
2. ADR-011's same-`MediaDevices` AEC topology remains necessary and must not be bypassed.
3. Widening AudioMixer's private stream timeout is symptom tolerance, not playout protection.
4. LiveKit's own realtime duplex playback work uses bounded prebuffering to prevent realtime-paced model audio from underrunning during normal network/scheduling jitter.
5. Realtime audio must not share an event loop with blocking discovery/subprocess work.

## Decision

### 1. Preserve the ADR-011 audio topology

JARVIS continues to use:

```
Gemini Live PCM
    ↓
JARVIS AudioOutput
    ↓
rtc.AudioSource
    ↓
rtc.LocalAudioTrack
    ↓
MediaDevices OutputPlayer
    ↓
physical 48 kHz speaker

same MediaDevices instance:
microphone → WebRTC APM ← exact speaker reverse stream
```

No separate scripted TTS or alternate conversation voice is introduced.

### 2. Add a bounded 300 ms segment-head prebuffer

The head of each new Gemini audio segment is held until either:

- 300 ms of canonical 48 kHz mono PCM is available, or
- the segment flushes before 300 ms, in which case the complete short segment is released immediately.

After priming, subsequent frames continue through the normal MediaDevices OutputPlayer path. The prebuffer does not replace AudioSource, OutputPlayer, AEC, NS, HPF, AGC, or the physical device clock.

### 3. Interruption remains immediate and fail-closed

If `clear_buffer()` occurs before the prebuffer is released, all primed PCM is discarded and zero stale audio is sent to the speaker.

If interruption occurs after playout starts, the existing AudioSource queue is cleared and the playback result is reported as interrupted.

### 4. Do not override LiveKit's private AudioMixer timeout

JARVIS returns to the upstream `MediaDevices.open_output()` implementation. Reliability must come from correct playout buffering and realtime scheduling isolation, not from modifying private mixer internals.

### 5. Keep blocking capability discovery off the realtime loop

GICC no longer refreshes capability discovery simply because a goal remains in `WAITING_CAPABILITY`.

A refresh occurs only when exact EngineeringChange/Phase-9 lineage says the continuation is eligible to resume, and the synchronous refresh executes with `asyncio.to_thread()`.

## Non-negotiable regressions

Owner-machine acceptance fails if any of these occur:

- JARVIS's own speaker audio creates a fake user turn.
- Real owner speech can no longer interrupt JARVIS naturally.
- AEC, NS, HPF, or AGC is bypassed.
- Gemini Live is replaced by a separate TTS path for normal/lifecycle speech.
- The 48 kHz validated endpoint contract is weakened.
- Prebuffered speech continues after an interruption.
- Background GICC/Phase-9 work causes recurring active-speech starvation.

## Acceptance evidence required

1. Smooth startup greeting.
2. Smooth normal multi-sentence Gemini response.
3. Smooth proactive/background notification while work runtimes are active.
4. Long JARVIS speech with owner silent produces no fake transcript/self-interruption.
5. Owner interrupts during speech and JARVIS stops naturally.
6. Logs show the expected prebuffer margin at segment start.
7. No recurring active-speech AudioMixer starvation pattern.
8. CI passes full pytest, Ruff, Windows Hello, Windows Phase 6/7/8/9 replay and acceptance suites.

## Rollback

The change is isolated on `fix/realtime-voice-reliability`. Rollback restores the parent revision without changing ADR-011's original production AEC architecture.
