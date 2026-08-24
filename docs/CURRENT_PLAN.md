# JARVIS V1 Current Plan

## Active Step

**Step 1 — Natural Conversational Core**

Step 0 repository bootstrap is complete at baseline commit:

`c626d863b5be7821da467175a0c466fdd90ca185` — `Bootstrap clean JARVIS V1 foundation`

## Current Stage

**REQUIREMENTS / PLANNING**

Implementation is **not started** and is not authorized by this document update.

Step lifecycle:

```text
REQUIREMENTS
-> RESEARCH
-> TECHNOLOGY DECISION
-> ARCHITECTURE
-> IMPLEMENTATION
-> AUTOMATED VALIDATION
-> REAL HUMAN USE
-> CORRECTION IF NEEDED
-> HUMAN ACCEPTANCE
-> DONE
```

## Step 1 Objective

Build the smallest conversational foundation that proves JARVIS can hold a natural, realtime, multi-turn spoken conversation before wake word, persistent memory, computer actions, tools, proactivity, or HUD are added.

The goal is not a command bot and not a large agent framework. The goal is conversational presence.

## Target User Experience

A manually started JARVIS voice session should allow the user to:

- speak naturally without rigid command phrases;
- continue across multiple turns;
- use English, Hindi, and Hinglish naturally;
- refer to earlier conversation context using ordinary language;
- correct JARVIS or change topic naturally;
- interrupt JARVIS while it is speaking where supported by the chosen realtime stack;
- continue normally after interruption;
- end the session cleanly;
- receive concise, natural spoken responses consistent with the JARVIS personality.

Examples of behaviour, not phrase rules:

```text
User: What is the capital of Germany?
JARVIS: Berlin.
User: What's its population?
```

JARVIS should understand the follow-up from conversation history without a custom pronoun-resolution subsystem.

```text
JARVIS: Munich is a city in—
User: Nahi, Berlin ki baat karte hain.
```

The active conversation should yield to the user's correction and continue on Berlin.

## Required Behaviour

### Conversation

- natural multi-turn dialogue;
- contextual follow-ups;
- topic changes and corrections;
- clarification only when ambiguity materially blocks a correct answer;
- no hardcoded command-phrase routing as the primary conversation mechanism;
- no separate Continuity/ContextGuardian/topic/pronoun engine merely to do what normal model conversation history already handles well.

### Language

- English;
- Hindi;
- Hinglish;
- language switching within a session when natural.

### Voice Interaction

- local microphone input;
- local speaker output;
- realtime or sufficiently low-latency spoken interaction;
- user interruption/barge-in where supported;
- clean audio/session startup and shutdown;
- errors must not leave the application in a stuck conversation state.

### Canonical Conversation Truth

JARVIS must own the accepted conversation record rather than treating a provider/framework's internal operational context as permanent product truth.

The minimum planned domain shape is:

```text
ConversationTurn
    role
    content
    timestamp
    interrupted

ConversationSession
    session_id
    status
    turns
```

Exact fields may change during architecture design, but the ownership principle is fixed: provider/framework operational state is not the canonical JARVIS record.

### Interaction Lifecycle

There should be one clear owner coordinating start/stop of the active interaction and synchronization of finalized accepted turns into `ConversationSession`.

The current working name is `InteractionService`; final naming is an architecture detail, not a requirement.

### Personality

Step 1 should already establish the basic JARVIS interaction identity:

- calm and composed;
- concise by default in speech;
- respectful and natural;
- comfortable in English/Hindi/Hinglish;
- no fake certainty;
- no fake capabilities;
- no unnecessary security friction for ordinary conversation.

## Explicit Step 1 Non-Scope

Do not implement any of the following during Step 1 unless a demonstrated blocker proves a minimal dependency is unavoidable:

- wake word;
- always-listening background mode;
- owner voice authentication;
- camera/presence authentication;
- persistent personal memory;
- semantic/episodic memory;
- memory frameworks;
- notes;
- tools/function calls;
- capability runtime;
- browser automation;
- web research/current affairs;
- files/project retrieval;
- computer/application/device actions;
- email/calendar;
- reminders/scheduling;
- proactive monitoring;
- background autonomy;
- self-repair/self-improvement;
- HUD/UI redesign;
- local LLM/local STT/local TTS fallback stack;
- broad future scaffolding;
- old-JARVIS runtime imports.

## Old JARVIS Evidence Relevant to Step 1

When Step-1 research/architecture begins, inspect only old material relevant to conversation and voice, especially:

- realtime/voice/session code;
- follow-mode and turn-management tests;
- barge-in/interruption tests;
- audio-device ownership/fallback tests;
- echo/AEC/self-hearing evidence;
- conversation continuity behaviour;
- personality/response-contract lessons;
- issue log entries involving voice-state coordination, wake-tail capture, follow-up expiry, and semantic fallback errors.

Do not reopen unrelated old memory, capability, repair, HUD, or autonomy code during Step 1.

## Known Old-JARVIS Lessons Applied Now

1. Do not recreate a long STT -> Understanding -> Continuity -> ContextGuardian -> Brain -> Composer -> TTS chain with overlapping state ownership.
2. Do not introduce multiple conversation/context owners.
3. Do not solve ordinary references with large custom rule engines if model history already solves them.
4. Do not let an audio/session error leave acquisition running from an invalid state.
5. Do not let silence or provider updates extend follow-up windows indefinitely.
6. Do not let a fallback answer a different semantic question.
7. Do not repeatedly authenticate harmless conversation.
8. Do not let technology experiments expand Step-1 scope.

## Preliminary Technology Direction — Not Yet Re-Verified

Previous planning selected the following direction as the starting hypothesis:

- **ADAPT Pipecat** for commodity realtime interaction/media pipeline mechanics;
- **WRAP OpenAI Realtime** for the preferred online speech-to-speech intelligence path;
- keep JARVIS-owned canonical conversation state outside those providers.

A previous target model was `gpt-realtime-2.1`.

This is **not yet the final Step-1 technology decision for implementation**. Before coding, perform a bounded official-doc verification of current APIs, model availability, local audio support, finalized turn events, interruption semantics, transcription access, Windows requirements, dependencies, and language behaviour.

Do not broaden that research into every agent/voice framework unless a genuine blocker appears.

## Planned Responsibility Boundaries

These are requirements-level boundaries and may be refined after research:

| Responsibility | Planned owner |
| --- | --- |
| Canonical accepted conversation record | JARVIS `ConversationSession` |
| Interaction start/stop/coordination | JARVIS interaction lifecycle service |
| Realtime media/pipeline mechanics | Selected commodity realtime framework |
| Online speech-to-speech intelligence | Selected provider adapter |
| Provider operational context | Provider/framework internals |
| Persistent memory | Not implemented in Step 1 |
| Tools/actions | Not implemented in Step 1 |
| Wake lifecycle | Step 2 |
| Permission/approval system | Step 3 |

## Step 1 Research Gate

Before implementation, verify only what is required to build this slice:

1. current supported realtime conversation APIs;
2. current Pipecat/OpenAI Realtime integration shape if still selected;
3. exact package/import/configuration APIs;
4. Windows microphone/speaker support and prerequisites;
5. finalized user-turn events/transcription access;
6. finalized assistant-turn events;
7. interruption/barge-in semantics;
8. turn/VAD configuration and ownership;
9. English/Hindi/Hinglish practical behaviour;
10. dependency/version compatibility;
11. latency/cost/privacy implications important to Step 1;
12. fallback/error semantics needed to preserve canonical JARVIS state.

Research output should be stored in `docs/research/` and should end with the explicit technology decision.

## Architecture Gate

After research and before implementation, review the proposed Step-1 architecture for:

- duplicate ownership;
- unnecessary abstraction;
- provider SDK leakage into core domain/state;
- giant composition modules;
- phrase-specific intelligence logic;
- speculative future scaffolding;
- hidden memory/tool/authority scope creep;
- unnecessary framework stacking;
- recurrence of old-JARVIS conversation architecture problems.

Only then should implementation be approved.

## Planned Test Areas

Final tests will be designed after architecture, but Step 1 must cover at least:

- `ConversationSession` lifecycle/state contracts;
- accepted user/assistant turn recording;
- interruption representation where applicable;
- provider/framework event translation;
- startup/shutdown cleanup;
- provider/network/audio failure handling;
- no import-time microphone/network/model side effects unless explicitly required by final architecture;
- multilingual conversation smoke tests where automatable;
- regression of Step-0 lifecycle/import safety.

## Human Acceptance Scenarios

Step 1 is not done until real use works. Human testing should include:

1. manually start voice mode;
2. hold a several-minute multi-turn conversation;
3. ask contextual follow-ups without repeating subjects;
4. correct JARVIS mid-conversation;
5. switch between English, Hindi, and Hinglish;
6. interrupt a response and continue;
7. verify the canonical transcript matches accepted conversation turns;
8. encounter at least one controlled provider/audio failure and confirm JARVIS exits/degrades truthfully;
9. stop the session cleanly;
10. confirm the conversation feels materially more natural and simpler than old JARVIS.

## Step 1 Completion Gate

Step 1 may be marked `DONE` only when:

- the technology decision is researched and recorded;
- architecture passes the ownership/scope review;
- automated tests pass;
- real human usage passes the acceptance scenarios;
- no duplicate conversation/context authority exists;
- no wake/memory/tools/autonomy/HUD scope has leaked in;
- `CURRENT_ARCHITECTURE.md` is updated to the accepted running architecture;
- `ROADMAP.md` is reconciled;
- rejected/abandoned Step-1 implementation is cleaned up;
- the final diff is coherent and reviewable.

## Step 2 Boundary

Step 2 begins only after Step 1 is accepted. Step 2 owns wake word, conversational session entry/exit, follow-mode lifecycle, and broader audio robustness. It must reuse the accepted Step-1 conversation foundation rather than create another conversation owner.

## Immediate Next Action

**Documentation/planning checkpoint first.**

After this planning checkpoint is accepted, perform the bounded Step-1 technology verification. Do not implement Step 1 before that research and architecture review are complete.
