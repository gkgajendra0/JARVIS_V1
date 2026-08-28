# JARVIS V1 Current Architecture

This document describes only implemented, validated, and human-accepted architecture.
Future Step-2 wake/audio design remains in `CURRENT_PLAN.md` until approved and built.

## Accepted Product Slices

- Step 0 — Clean Foundation: accepted.
- Step 1 — Natural Conversational Core: accepted on 2026-08-28.
- Step 2 — not implemented.

## Runtime Entry Points

### Foundation entry point

`python -m jarvis` loads environment configuration, configures logging, and runs the
small synchronous `JarvisApp` lifecycle.

### Voice entry point

`lk agent console src/jarvis/voice/entrypoint.py` starts the local LiveKit console
transport. The entry point:

1. loads `JarvisConfig`;
2. configures logging;
3. constructs the selected realtime provider inside the voice composition boundary;
4. creates a JARVIS `ConversationSession` and LiveKit `AgentSession`;
5. starts canonical conversation lifecycle tracking;
6. connects the local console microphone/speaker transport;
7. converts finalized LiveKit conversation items into accepted JARVIS turns;
8. records clean close or failure state.

Voice mode is manually started. There is no wake-word or idle-listening runtime yet.

## Components and Ownership

### `src/jarvis/conversation.py`

Owns provider-independent canonical conversation truth:

- `ConversationRole` permits user and assistant turns;
- `ConversationTurn` validates non-empty accepted text and permits interruption only
  for assistant turns;
- `ConversationSession` owns created, active, closed, and failed lifecycle states;
- accepted turns are exposed as an immutable tuple view;
- provider/framework session history is not canonical JARVIS state.

Conversation state is session-only and is not persisted.

### `src/jarvis/voice/agent.py`

Owns the Step-1 JARVIS voice instructions and `JarvisVoiceAgent` composition:

- calm, concise JARVIS identity;
- English, Hindi, and Hinglish adaptation;
- direct answers without unnecessary spoken preambles;
- contextual follow-ups and corrections;
- truthful framing of unavailable memory, tools, research, and actions.

### `src/jarvis/voice/livekit_session.py`

Owns the LiveKit/provider integration boundary:

- explicitly selects `openai` or `gemini` from validated configuration;
- requires only the selected provider's API key;
- constructs provider-specific realtime model options;
- configures provider-owned turn detection while retaining LiveKit interruption
  handling;
- creates the LiveKit `AgentSession`;
- translates finalized `ChatMessage` events into canonical JARVIS turns exactly once;
- marks interrupted assistant turns as partial;
- maps terminal errors/close events to JARVIS conversation state;
- does not silently switch or fall back between providers.

Provider configuration currently includes:

| Provider | Model default | Voice default | Turn configuration |
| --- | --- | --- | --- |
| OpenAI | `gpt-realtime` | `marin` | far-field noise reduction; server VAD threshold `0.8`, 300 ms prefix, 500 ms silence |
| Gemini | `gemini-3.1-flash-live-preview` | `Charon` | low start/end sensitivity, 300 ms prefix, 800 ms silence |

These values are composition settings, not permanent JARVIS domain contracts.

### `src/jarvis/voice/entrypoint.py`

Owns local voice-session composition and startup sequencing. It does not own canonical
conversation data or provider intelligence.

### `src/jarvis/config.py`

Owns environment-backed configuration and validation:

- logging level;
- explicit realtime provider selection;
- provider-specific model and voice values;
- transcript logging toggle.

Secrets remain process environment values. They are not configuration fields, files,
or logged values.

### Foundation components

- `JarvisApp` owns the minimal non-voice application lifecycle.
- `logging_config` owns console logging setup.
- package imports retain no microphone/network/model startup side effects.

## External Dependencies

- Python 3.11 or newer;
- `livekit-agents[google,openai]==1.7.1`;
- LiveKit CLI for the local console transport;
- selected provider API access;
- Windows/PortAudio-visible microphone and speaker devices.

LiveKit Cloud, hosting, telephony, persistent storage, wake-word engines, local models,
tools, and HUD dependencies are not part of the accepted runtime.

## State Ownership

| State | Authoritative owner |
| --- | --- |
| Application lifecycle | `JarvisApp` |
| Environment configuration | `JarvisConfig` |
| Canonical accepted conversation | `ConversationSession` |
| Voice composition and event translation | JARVIS LiveKit boundary |
| Realtime operational context/audio generation | Selected provider and LiveKit |
| Persistent personal memory | Not implemented |
| Wake/idle/follow-up lifecycle | Not implemented |
| Identity/permissions/authority | Not implemented |
| Tools/capabilities/actions | Not implemented |

## Validation and Human Evidence

Automated validation currently passes 26 tests plus Ruff lint and format checks. Tests
cover foundation lifecycle, configuration, conversation contracts, duplicate-event
suppression, interruption representation, close/failure mapping, provider-specific key
requirements, explicit Gemini construction, and OpenAI VAD threshold configuration.

Real Windows tests established:

- local Tribit/Voicemeeter input and output operation;
- English, Hindi, and Hinglish conversation;
- contextual follow-ups and correction;
- real interruption handling;
- truthful failure when OpenAI credit was exhausted;
- Gemini provider replacement through configuration only;
- no false interruption/restart in the final bounded Gemini silent-response test;
- truthful denial of persistent memory and computer-control capability.

Known residual evidence limit: OpenAI's final post-tuning VAD/prompt values have not been
rerun after credit exhaustion. This is recorded rather than treated as a completed test.

## Current Limitations

- voice mode requires manual console startup and explicit device selection;
- Voicemeeter is currently required on the tested Tribit path to bridge sample-rate
  compatibility;
- there is no wake word, automatic idle/follow-up lifecycle, speaker identity, durable
  memory, tool execution, or background service;
- Gemini Free Tier is preview/cost-optimized development infrastructure and has provider
  privacy/availability constraints;
- provider transcripts may contain recognition errors; canonical state records accepted
  provider text and does not reconstruct unheard audio independently.

## Architecture Update Rule

Add Step-2 architecture here only after research, an accepted decision, human-approved
architecture, implementation, automated validation, and real human acceptance.
