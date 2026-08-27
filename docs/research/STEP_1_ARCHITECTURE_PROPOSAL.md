# Step 1 Architecture Proposal

**Status:** READY FOR HUMAN REVIEW — IMPLEMENTATION NOT AUTHORIZED  
**Date:** 2026-08-27  
**Technology decision:** `docs/decisions/ADR-001_STEP_1_VOICE_STACK.md`

## Purpose

Define the smallest architecture that can prove JARVIS holds a natural local English/Hindi/Hinglish voice conversation using LiveKit Agents and OpenAI Realtime without recreating old-JARVIS state sprawl.

This is a proposed architecture. `docs/CURRENT_ARCHITECTURE.md` must not change until implementation, automated validation, and human acceptance succeed.

## Research Findings That Constrain the Design

Current LiveKit documentation establishes:

- `lk agent console` runs locally against the computer microphone and speakers and supports device selection, AEC controls, recording, and graceful interruption;
- `AgentSession` owns its operational initializing/starting/running/closing lifecycle;
- realtime providers should normally use their provider-side turn detection;
- `conversation_item_added` fires when a user or assistant item is committed to LiveKit chat history;
- committed `ChatMessage` items expose role, text, and `interrupted`;
- `user_input_transcribed` can be delayed for realtime models and must not create a second canonical turn path;
- synchronized output transcription is truncated when assistant playback is interrupted;
- error events distinguish recoverable from unrecoverable failures;
- session close drains pending speech/transcripts and closes I/O.

Relevant official references:

- https://docs.livekit.io/reference/developer-tools/livekit-cli/agent/
- https://docs.livekit.io/agents/logic/sessions/
- https://docs.livekit.io/reference/agents/events/
- https://docs.livekit.io/agents/logic/turns/
- https://docs.livekit.io/agents/models/realtime/
- https://docs.livekit.io/agents/models/realtime/plugins/openai/
- https://docs.livekit.io/agents/multimodality/text/

Important limitation: a synchronized frontend transcript and a committed LiveKit chat item are operational evidence, not automatically JARVIS product truth. The bridge proposes accepted turns to the JARVIS session, which validates and owns them.

## Proposed Runtime

```text
User command
lk agent console src/jarvis/voice/entrypoint.py
        |
        v
LiveKit AgentServer / local console
        |
        v
AgentSession + OpenAI RealtimeModel
        |
        +--> local microphone/speaker
        |
        +--> LiveKit events
                 |
                 v
        LiveKitConversationBridge
                 |
                 v
        JARVIS ConversationSession
```

The LiveKit CLI is the Step-1 manual start surface. `python -m jarvis` remains the accepted Step-0 lifecycle command and must continue to pass its existing tests. Step 2 may deliberately unify the user-facing voice/session entry lifecycle; Step 1 must not pre-build that work.

## Proposed Production Files

Only these additions are justified:

```text
src/jarvis/conversation.py
src/jarvis/voice/__init__.py
src/jarvis/voice/agent.py
src/jarvis/voice/livekit_session.py
src/jarvis/voice/entrypoint.py
```

Existing files changed only where required:

```text
src/jarvis/config.py
pyproject.toml
README.md
```

No provider registry, plugin manager, service locator, event bus, repository layer, transcript database, fallback manager, audio abstraction hierarchy, or custom state machine is justified in Step 1.

## Component Responsibilities

### `conversation.py`

Pure Python domain state with no LiveKit/OpenAI imports.

Proposed types:

- `ConversationRole`: user or assistant;
- `ConversationTurn`: normalized non-empty text, role, and interrupted flag;
- `ConversationStatus`: created, active, closed, or failed;
- `ConversationSession`: ordered accepted turns and guarded lifecycle transitions.

Required invariants:

- a session starts once;
- turns can be accepted only while active;
- only user/assistant roles are accepted;
- empty/whitespace-only turns are rejected;
- interrupted assistant output is retained only as partial text with `interrupted=True`;
- closed/failed sessions reject new turns;
- failure and clean close remain distinct;
- no raw provider event or SDK type enters domain state.

A session identifier is allowed only for local correlation. There is no persistence or durable transcript in Step 1.

### `voice/agent.py`

One lightweight LiveKit `Agent` subclass containing only the Step-1 voice instructions:

- identity: JARVIS;
- concise spoken responses;
- calm, direct behavior;
- naturally follow the user's English, Hindi, or Hinglish;
- preserve context and accept corrections;
- do not claim tools, memory, current research, or actions;
- no greeting script or hardcoded conversation routing.

No tools, handoffs, memory, knowledge retrieval, or capability code.

### `voice/livekit_session.py`

Own the selected integration boundary.

Responsibilities:

- construct the JARVIS `ConversationSession`;
- construct/configure LiveKit `AgentSession` with OpenAI Realtime;
- subscribe to LiveKit committed-conversation, error, and close events;
- translate committed `ChatMessage` items into JARVIS turns;
- use LiveKit item identity to prevent duplicate event acceptance;
- mark assistant items from `item.interrupted`;
- treat `user_input_transcribed` as diagnostics only, never a second turn writer;
- distinguish recoverable provider warnings from terminal failure;
- close/fail canonical state exactly once;
- expose the canonical in-memory session for tests and optional local inspection;
- never persist raw audio, provider payloads, or transcripts.

This module may import LiveKit/OpenAI SDK types. No other core/domain module may do so.

### `voice/entrypoint.py`

Composition only:

- validate configuration before starting audio;
- create the LiveKit `AgentServer`;
- define one RTC/session entrypoint;
- create the selected model/session bridge;
- start the JARVIS voice agent;
- rely on LiveKit for local console I/O and graceful signal handling.

It must not contain domain rules or transcript parsing.

## State Ownership

| State | Authority |
| --- | --- |
| JARVIS application baseline lifecycle | Existing `JarvisApp` |
| Live voice/media connection | LiveKit `AgentSession` operationally |
| OpenAI realtime protocol/session | OpenAI plugin operationally |
| Accepted Step-1 conversation record | JARVIS `ConversationSession` |
| Turn acceptance/validation | JARVIS domain state |
| SDK-event translation/deduplication | LiveKit bridge |
| Personality instructions | JARVIS voice agent |
| Persistent memory | Not implemented |
| Tools/actions | Not implemented |

There are two lifecycle scopes, not two competing owners:

- `AgentSession` owns commodity media/provider resource lifecycle;
- `ConversationSession` owns product truth about whether the conversation is active, closed, or failed.

## Canonical Turn Policy

Use only LiveKit `conversation_item_added` committed chat messages.

Acceptance algorithm:

1. Ignore non-`ChatMessage` items.
2. Ignore roles other than user/assistant.
3. Ignore already-seen LiveKit item identities.
4. Normalize surrounding whitespace without rewriting content.
5. Reject empty text.
6. Map role.
7. Copy the LiveKit `interrupted` flag.
8. Commit through `ConversationSession.accept_turn()`.
9. Mark the LiveKit identity seen only after successful acceptance.

Do not infer interruption by text length, timing, or user speech. Do not merge duplicate-looking content because a user may intentionally repeat themselves. Do not write turns from both transcription and history events.

If current SDK behavior proves that a committed interrupted assistant item contains generated rather than played text, the architecture review reopens before acceptance; JARVIS must not claim it knows exactly what was heard.

## Turn Detection and Interruption

Initial configuration:

- use OpenAI Realtime semantic VAD through the LiveKit plugin;
- keep interruption enabled;
- do not add Silero VAD, LiveKit turn detector, or a separate STT model;
- do not enable speculative/preemptive generation unless the selected realtime path requires it;
- let LiveKit stop playback when the provider signals interruption;
- record committed assistant output using LiveKit's `interrupted` evidence.

Reason: LiveKit documents that its text turn detector requires a separate STT stream with realtime models. Adding STT would add cost and a second transcript path before a real failure demonstrates the need.

## Configuration

Extend `JarvisConfig` only with non-secret voice settings actually required by Step 1:

- realtime model identifier;
- voice identifier;
- optional transient transcript display for human testing.

`OPENAI_API_KEY` remains an environment secret consumed at the integration boundary. Validate that it is present before microphone acquisition, but do not store it in a repr-visible configuration object and never log it.

Provide `.env.example` names only if a repository example is required. Never add a real `.env` or key.

Exact model/voice defaults and dependency versions are pinned during implementation after a clean resolver/install check against current official documentation. Permanent domain code must not depend on model names.

## Dependency Boundary

Expected production dependency:

- `livekit-agents[openai]` in the current officially supported compatible release line.

Do not install:

- Pipecat;
- a separate OpenAI Agents SDK;
- raw audio libraries;
- standalone VAD/STT/TTS;
- LiveKit Cloud SDKs not pulled by the required package;
- dotenv solely to read environment variables;
- a DI framework;
- a persistence library.

Development dependencies should remain small:

- pytest;
- Ruff for format/lint/unused-code basics;
- one static type checker only if it works cleanly with the selected SDK types.

Do not stack overlapping linters. A one-time high-confidence dead-code scan may support review, but no dead-code tool may delete event handlers or framework entrypoints automatically.

## Error Policy

| Condition | Required result |
| --- | --- |
| Missing API key/config | Fail before audio/session start |
| Recoverable LiveKit/provider error | Log metadata without secrets; keep session active |
| Unrecoverable provider error | Mark canonical session failed; allow LiveKit cleanup |
| Audio-device startup failure | No active canonical session and no leaked acquisition |
| Ctrl+C/cancellation | LiveKit closes I/O; canonical session closes once |
| Close after failure | Preserve failed state; do not overwrite as clean close |
| Malformed/empty provider item | Ignore or report safely; never corrupt turns |

No automatic provider fallback in Step 1.

## Automated Validation

### Pure unit tests

- session created/active/closed/failed transitions;
- repeated close/fail behavior;
- rejection of turns outside active state;
- empty and invalid-role rejection;
- ordered user/assistant acceptance;
- interrupted assistant representation;
- provider SDK types absent from `conversation.py`.

### Bridge tests

Using controlled event/message doubles or supported SDK test helpers:

- committed user item writes exactly once;
- committed assistant item writes exactly once;
- repeated same item ID is ignored;
- identical text with different IDs is retained;
- final transcription diagnostics do not write a turn;
- interrupted assistant maps to partial/interrupted turn;
- recoverable error does not fail;
- terminal error fails;
- close preserves failed state;
- shutdown closes once.

### Regression and quality commands

- existing Step-0 tests remain green;
- package import still has no audio/network/model side effect;
- `pytest`;
- `ruff check`;
- `ruff format --check`;
- selected static type check if adopted;
- clean dependency-resolution/install check on Python 3.11 and Windows.

No live API call belongs in normal unit tests.

## Human Acceptance

On the real JARVIS Windows machine:

1. start with `lk agent console src/jarvis/voice/entrypoint.py`;
2. select/verify microphone and speakers;
3. hold a several-minute English conversation;
4. switch naturally to Hindi and Hinglish;
5. use contextual follow-ups, corrections, and topic changes;
6. interrupt early, mid-sentence, and late;
7. compare the transient canonical record with what was actually heard;
8. test silence, fan/keyboard noise, and speaker echo;
9. force one provider/network failure;
10. stop with Ctrl+C and verify clean resource release.

Step 1 fails acceptance if OpenAI Hindi/Hinglish is materially unnatural, interruptions retain unspoken content as accepted truth, or audio/session resources remain active after exit.

## Ponytail Development Discipline

Ponytail is approved as an implementation-assistance plugin, not runtime code and not a correctness gate by itself.

Use:

- default `full` mode during implementation;
- `ultra` only for cleanup/refactoring when normal mode still overbuilds;
- `@ponytail-review` on every implementation diff;
- `@ponytail-audit` before final human acceptance.

Its decision ladder applies:

1. Does this need to exist?
2. Does the repository already solve it?
3. Does Python stdlib solve it?
4. Does LiveKit/OpenAI already solve it?
5. Can an installed dependency solve it?
6. Only then write the minimum code.

Never use Ponytail to remove validation, failure cleanup, secret handling, privacy controls, accessibility, or required tests.

Ponytail is installed in the developer's Codex environment, not committed as a JARVIS runtime dependency. Its Node lifecycle hooks must be inspected and explicitly trusted by the user.

Official source: https://github.com/DietrichGebert/ponytail

## Rejected Architecture

Do not build:

```text
AudioManager
-> VADManager
-> STTManager
-> UnderstandingEngine
-> ContinuityEngine
-> ContextGuardian
-> Brain
-> ResponseComposer
-> TTSManager
```

Do not introduce interfaces for hypothetical future providers beyond the real LiveKit integration boundary. When Gemini or another provider is actually added, extract the smallest common seam proven by both implementations.

## Implementation Order After Approval

1. Dependency resolution and pins.
2. Pure conversation domain and tests.
3. Minimal voice agent instructions.
4. LiveKit event bridge and tests.
5. Local entrypoint and configuration.
6. Import/lifecycle regressions.
7. Ruff/type/test gates.
8. Ponytail diff review and delete pass.
9. Local human English/Hindi/Hinglish testing.
10. Corrections, documentation reconciliation, and acceptance.

## Approval Decision Requested

Approve or reject this architecture as a whole before implementation.

Approval authorizes only the bounded Step-1 implementation described here. Any need for extra STT/TTS, persistence, tools, wake word, cloud deployment, UI/HUD, or a second provider must return to architecture review.
