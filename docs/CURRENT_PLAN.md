# JARVIS V1 Current Plan

## Active Step

**Step 2 — Wake, Voice Session, and Audio Robustness**

## Current Stage

**IMPLEMENTATION AUTHORIZED — IN PROGRESS**

Step 1 was human-accepted on 2026-08-28 after automated validation and real Windows
voice testing. Its accepted running architecture is recorded in
`docs/CURRENT_ARCHITECTURE.md`.

The Gemini development path passed the final false-interruption and truthfulness
checks. OpenAI also passed earlier multilingual, contextual, interruption, and failure
smoke tests; its post-tuning VAD/prompt settings remain available but were not rerun
after paid credit was exhausted. That provider-specific recheck does not block Step 2
and must not be represented as completed.

Step lifecycle:

```text
REQUIREMENTS
-> RESEARCH
-> TECHNOLOGY DECISION
-> ARCHITECTURE
-> HUMAN APPROVAL
-> IMPLEMENTATION
-> AUTOMATED VALIDATION
-> REAL HUMAN USE
-> CORRECTION IF NEEDED
-> HUMAN ACCEPTANCE
-> DONE
```

## Step 2 Objective

Allow JARVIS to wait locally for its wake name, enter the accepted realtime
conversation naturally, support follow-up turns and barge-in, and return to idle
without audio ownership, echo, device, timeout, or lifecycle faults.

Step 2 must extend the accepted Step-1 conversation foundation. It must not create a
second conversation owner or replace the working realtime stack without evidence.

## Required Behaviour

### Wake and Session Entry

- recognize the approved JARVIS wake name without rigid command phrasing;
- keep idle wake detection local where technically practical;
- avoid streaming continuous idle-room audio to a cloud provider;
- preserve speech immediately following the wake name so the user's request is not
  clipped or discarded;
- start exactly one conversational session for one accepted wake event;
- reject duplicate/replayed wake events during an active session.

### Conversational Presence

- allow natural follow-up turns after the initial request;
- keep the session active only while real conversational activity justifies it;
- return to idle after an accepted inactivity/end condition;
- allow an explicit spoken or application stop path;
- wake again cleanly after the prior session closes.

### Audio Robustness

- one authoritative component owns microphone acquisition at any time;
- JARVIS speaker output must not repeatedly trigger wake detection or false user turns;
- user barge-in must stop or truncate assistant output truthfully;
- expected room noise, TV audio, and ordinary silence must not create uncontrolled
  session churn;
- supported input/output devices and sample rates must be validated before session use;
- device disconnect, provider failure, cancellation, and shutdown must release audio
  resources and return to a truthful state.

### State and Ownership

- JARVIS owns wake/session lifecycle truth;
- the existing `ConversationSession` remains the canonical accepted-turn owner;
- LiveKit/provider objects remain operational state;
- exact state names, interfaces, buffering strategy, and wake technology are architecture
  decisions to make after research.

## Explicit Non-Scope

- owner voice authentication or speaker identification;
- camera/presence authentication;
- durable personal memory;
- tools, capabilities, or computer control;
- local/offline conversational LLM, STT, or TTS fallback;
- HUD redesign;
- cloud deployment, telephony, browser/mobile clients, or remote rooms;
- arbitrary always-streaming cloud microphone mode;
- Step-3 permissions, audit, or identity architecture;
- speculative future audio framework abstractions.

## Required Research

Research must use current primary documentation and relevant old-JARVIS evidence. It
must compare credible candidates without preselecting technology in this plan.

Answer at minimum:

1. Which maintained local wake-word engines support Windows, Python, a custom JARVIS
   wake name, acceptable latency, and the required license/cost?
2. Can the engine use the actual 16 kHz Tribit/Voicemeeter input path reliably, or is a
   controlled resampling boundary required?
3. How should one microphone stream feed idle wake detection and then hand off to
   LiveKit without two components opening the device concurrently?
4. How much pre-roll/wake-tail audio must be buffered so the first request is complete?
5. Which component owns idle, wake, active-conversation, stopping, failure, and recovery
   transitions?
6. How should follow-up expiry distinguish real user activity from provider updates,
   silence, echo, and TV/background speech?
7. What AEC/noise/device behavior should remain in LiveKit, provider configuration,
   Windows/Voicemeeter, or a small JARVIS audio boundary?
8. Which old-JARVIS tests and failure lessons should be rewritten rather than copied?
9. What measurable false-accept, false-reject, wake latency, barge-in, and cleanup gates
   are realistic on the actual Windows machine?

## Relevant Old-JARVIS Evidence

Inspect only wake/audio/session material, especially:

- custom wake-word research and recordings;
- wake-tail/pre-roll handling;
- follow-mode expiry and session-state tests;
- microphone ownership and invalid-state acquisition failures;
- AEC/self-hearing/false-barge-in evidence;
- device selection, sample-rate, disconnect, cancellation, and cleanup tests;
- lessons from keyword-only interruption and large voice-state controllers.

The old runtime is evidence, not architecture to import.

## Architecture Gate

Before implementation, the proposal must define:

- one wake/session lifecycle owner;
- one microphone acquisition owner and handoff model;
- wake detector replacement boundary;
- pre-roll/wake-tail buffering boundary;
- follow-up timeout semantics;
- interaction with the accepted LiveKit/provider session;
- echo/noise/device responsibility boundaries;
- failure and deterministic cleanup paths;
- exact dependencies and pinned versions;
- tests mapped to old failure evidence and Step-2 acceptance requirements.

Human approval is required after this architecture is documented. No Step-2 production
code or dependency is authorized before that approval.

## Human Acceptance Scenarios

Step 2 must eventually prove on the real Windows machine:

1. wake JARVIS by name from idle and speak the request without losing its beginning;
2. complete multiple follow-up turns without repeating the wake name unnecessarily;
3. return to idle after the approved inactivity/end behavior;
4. wake again successfully after returning to idle;
5. interrupt JARVIS naturally and continue;
6. play ordinary TV/background audio without uncontrolled false activations;
7. hear JARVIS through the Tribit speaker without repeated self-wake/self-interruption;
8. recover truthfully from input/output device and provider failures;
9. stop cleanly with no microphone or worker left active;
10. confirm idle privacy and expected local/cloud audio boundaries.

## Completion Gate

Step 2 is `DONE` only after research, a recorded decision, approved architecture,
implementation, automated validation, real human acceptance, cleanup, and documentation
reconciliation all pass.

## Immediate Next Action

**Implement the accepted decision in
`docs/decisions/ADR-002_STEP_2_WAKE_AUDIO_RUNTIME.md`, run automated validation, and
then stop for the documented real Windows wake/audio acceptance tests. Step 2 remains
in progress until those tests and documentation reconciliation pass.**
