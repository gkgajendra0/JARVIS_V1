# JARVIS V1 Current Plan

## Active Step

**Step 1 — Natural Conversational Core**

Step 0 repository bootstrap is complete at baseline commit:

`c626d863b5be7821da467175a0c466fdd90ca185` — `Bootstrap clean JARVIS V1 foundation`

## Foundation Reconciliation Status

**COMPLETE — STEP 1 ARCHITECTURE APPROVED; IMPLEMENTATION VALIDATED; HUMAN TESTING PENDING**

Before beginning implementation, JARVIS V1 has now been reconciled against the old JARVIS repository's authoritative capability inventory, strategic roadmap, runtime architecture, tests, issue/failure evidence, memory/context systems, capability/authority work, world-awareness work, HUD, diagnostics, skill/evolution/repair work, and relevant historical experiments.

The permanent V1 product catalogue has a destination for every old authoritative CAP-001 through CAP-036. Old CAP-036 autonomous development agents are deliberately retired as an implementation pattern while their useful self-diagnosis/self-improvement goal is preserved under governed future capabilities.

The reconciliation also established:

- a dependency-correct roadmap rather than a direct copy of the old build order;
- a minimal common capability-runtime foundation before broad safe-read/action expansion;
- permanent truthfulness and semantic-fidelity requirements;
- graduated trust and proportional action-risk expectations;
- explicit privacy/data-lifecycle principles;
- provider/model/framework replacement boundaries;
- a final product definition of JARVIS as a coherent Personal Intelligence Runtime;
- preservation of old product intent without preserving old documentation or architecture sprawl.

No further broad old-repository audit is required before Step 1. When a later subsystem becomes active, only the old evidence relevant to that subsystem should be revisited.

## Current Stage

**IMPLEMENTED — AUTOMATED VALIDATION COMPLETE; REAL HUMAN TESTING REQUIRED**

The Step-1 architecture was explicitly approved on 2026-08-27. The bounded implementation is now present and has passed automated validation. Step 1 is not complete until real Windows voice testing and human acceptance succeed.

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

The exact data structures, fields, and names will be decided after research during architecture design. The fixed requirement is that provider/framework operational state is not the canonical JARVIS record.

### Interaction Lifecycle

There must be one clear JARVIS-owned lifecycle boundary coordinating interaction start/stop and synchronization of finalized accepted turns into JARVIS's canonical conversation record.

The exact component structure and naming will be decided after research during architecture design.

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

## Accepted Technology Direction

Paper research and human review selected the initial Step-1 direction:

- **ADOPT LiveKit Agents** for local realtime media/session orchestration;
- **WRAP OpenAI Realtime** as the initial native speech-to-speech provider;
- keep JARVIS-owned canonical conversation and lifecycle truth outside LiveKit/OpenAI operational state;
- use the existing OpenAI API account, with API usage as the only required Step-1 operating cost;
- do not require LiveKit Cloud, hosting, telephony, fallback STT/TTS, wake word, memory, or tools;
- preserve Gemini Live as the first provider replacement candidate if OpenAI fails multilingual, latency, reliability, cost, or availability requirements;
- preserve Pipecat and direct-provider orchestration as reconsideration candidates, not simultaneous implementations.

Evidence and reasoning:

- `docs/research/STEP_1_REALTIME_VOICE.md`
- `docs/decisions/ADR-001_STEP_1_VOICE_STACK.md`
- `docs/research/STEP_1_ARCHITECTURE_PROPOSAL.md`

The proposed architecture is now ready for human review. Implementation still requires explicit human approval.

## Planned Responsibility Boundaries

These are requirements-level boundaries and may be refined after research:

| Responsibility | Planned owner |
| --- | --- |
| Canonical accepted conversation record | JARVIS-owned conversation state; exact design pending architecture |
| Interaction start/stop/coordination | One JARVIS-owned lifecycle boundary; exact design pending architecture |
| Realtime media/session mechanics | LiveKit Agents, behind a JARVIS-owned replacement boundary |
| Online speech-to-speech intelligence | OpenAI Realtime initially, behind the provider boundary |
| Provider operational context | Provider/framework internals |
| Persistent memory | Not implemented in Step 1 |
| Tools/actions | Not implemented in Step 1 |
| Wake lifecycle | Step 2 |
| Permission/approval system | Step 3 |

## Step 1 Research Gate

**COMPLETE.** The accepted evidence is recorded in `docs/research/STEP_1_REALTIME_VOICE.md` and the decision in `docs/decisions/ADR-001_STEP_1_VOICE_STACK.md`.

The research covered:

1. current supported realtime conversation APIs;
2. integration shape, platform compatibility, and replacement boundaries of credible candidates;
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

The architecture stage must resolve exact packages, pinned versions, event mappings, and local audio composition without reopening the accepted stack unless a documented blocker triggers reconsideration.

## Architecture Gate

**COMPLETE.** The bounded proposal in `docs/research/STEP_1_ARCHITECTURE_PROPOSAL.md` was explicitly approved on 2026-08-27.

The approved architecture was reviewed for:

- duplicate ownership;
- unnecessary abstraction;
- provider SDK leakage into core domain/state;
- giant composition modules;
- phrase-specific intelligence logic;
- speculative future scaffolding;
- hidden memory/tool/authority scope creep;
- unnecessary framework stacking;
- recurrence of old-JARVIS conversation architecture problems.

Implementation was authorized only within the approved Step-1 boundary.

## Planned Test Areas

Final tests will be designed after architecture, but Step 1 must cover at least:

- canonical conversation lifecycle/state contracts;
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

**Run the documented Step-1 voice acceptance scenarios on the real Windows JARVIS machine.**

Automated validation currently passes 22 tests plus Ruff lint and format checks. Human testing must verify English/Hindi/Hinglish quality, contextual follow-ups, interruption truth, controlled failure handling, and clean microphone/speaker shutdown. Record failures before changing architecture or adding dependencies.
