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

## 2026-10-03 owner-machine follow-up

The first combined owner-machine run after the provider-pressure and durable-recovery
changes materially narrowed the remaining failure surface.

### Evidence established

- long Gemini speech segments completed normally with no fixed-duration cutoff;
- the validated MediaDevices/WebRTC AEC path remained active;
- DBOS recovered canonical active work instead of failing on the historical terminal
  execution mismatch;
- provider-capacity cooldown prevented a new provider-hammering failure pattern;
- one microphone-ingress warning still reported 11 stale frames shed while the
  canonical asyncio loop had accumulated 1359 ms of scheduling lag;
- legacy Phase-9 WorkItems persisted before the governed architecture-revision fix
  could still restart in WAITING_FOR_OWNER and replay old model-authored approval
  questions;
- multiple WorkItems sharing the same provider-routing outage could each enqueue an
  owner-visible resource-blocker notification, causing repeated short realtime
  lifecycle sessions.

The 1359 ms sample proves canonical-loop starvation, but it does **not** by itself
prove that LiveKit AgentSession startup is the blocking operation. The warning occurred
while recovered background work and proactive notification sessions were active, so
the permanent correction is to remove known synchronous persistence/discovery work
from that loop and then re-test physically rather than replace the validated audio
topology on inference alone.

### Coordinated correction

The follow-up keeps the existing architecture intact and corrects lifecycle boundaries:

1. startup migrates legacy model-authored Phase-9 owner waits through the current
   EngineeringChange architecture-revision handler before owner deliveries are
   reopened; typed executor requests such as pairing/PIN input remain owner waits;
2. durable Work/EngineeringChange reads and writes used by realtime voice tools and
   notification delivery are dispatched off the canonical asyncio loop;
3. the periodic Work status scheduler performs its SQLite persistence tick on a worker
   thread rather than the realtime loop;
4. identical provider-routing blocker deliveries that are simultaneously due are
   coalesced into one owner notification while each durable delivery is still consumed;
5. no change is made to MediaDevices, AEC, provider-native barge-in, the 300 ms
   prebuffer, or the Phase-9/EngineeringChange/Phase-7/Phase-8 authority chain.

A separate dedicated Work event loop was considered and rejected for this correction.
The Work brain gate, DBOS callback path, shutdown semantics, and provider clients are
currently composed around the canonical loop; moving them wholesale would be a larger
architecture migration with new cross-loop failure modes. It is not justified unless
the next physical run still proves sustained loop starvation after known synchronous
boundaries are removed.

### Remaining physical gate

Software validation cannot prove the final hardware behavior. Before this ADR can move
from proposed to accepted, the exact tested revision must still prove:

- deliberate human barge-in produces a real interrupted JARVIS utterance;
- no legacy architecture-review owner prompt is replayed after restart;
- one shared provider-capacity outage does not produce a burst of repeated spoken
  blockers;
- normal speech plus active background work produces no recurring microphone-frame
  shedding or comparable event-loop scheduling stall;
- the deferred Phase-9 external-device path is exercised against a real target when
  provider capacity is available.

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
