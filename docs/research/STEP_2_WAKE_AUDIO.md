# Step 2 Wake, Session, and Audio Research

**Date:** 2026-08-28  
**Status:** PAPER RESEARCH COMPLETE — HUMAN REVIEW REQUIRED  
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
| LiveKit WakeWord | Apache-2.0; local ONNX inference; Python 3.11+ Windows client; built-in PortAudio listener; custom synthetic training; same vendor/ecosystem as accepted media layer; accepts 16 kHz PCM; official benchmark reports 0.08 false positives/hour and 86.1% recall for its evaluated `hey livekit` model | New in 2026; custom `JARVIS` model still requires training/evaluation; official end-to-end example uses a separate client and LiveKit room/cloud pattern; does not by itself solve local console microphone handoff or wake-tail preservation | **ADAPT — leading detector candidate, pending architecture proof** |
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

## Blocking Architecture Question

The current `lk agent console` transport owns the microphone during an active voice
session. A wake listener also needs the microphone while idle. Starting both listeners
concurrently would recreate the old-JARVIS dual-acquisition failure. Closing the wake
listener and then opening the console can lose the words immediately after `JARVIS` and
cause repeated device/sample-rate churn.

Architecture must choose and prove one of these shapes:

1. one JARVIS-owned continuous audio front end that routes 16 kHz PCM to wake detection
   while idle and to the accepted realtime transport while active;
2. an on-device wake client and a separate LiveKit agent room, only if a local/self-hosted
   topology remains small and does not force LiveKit Cloud;
3. a sequential exclusive-device handoff only if bounded pre-roll/wake-tail buffering
   can be transferred without clipping the user's first request.

No detector should be integrated before this ownership decision.

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
- wake response begins within 750 ms of accepted detection on the target PC;
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
- the official client/room example does not prove the desired local-only topology;
- solving AEC completely in software may be impossible with the current Bluetooth
  speakerphone profile and physical room path.

## Recommendation

Approve **ADAPT LiveKit WakeWord** as the detector direction and **PRESERVE Porcupine as
the measured fallback**. Next, design the single-microphone/audio-handoff architecture.
Do not implement until that architecture is reviewed and explicitly approved.
