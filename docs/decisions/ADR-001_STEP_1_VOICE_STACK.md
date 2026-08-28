# ADR-001: Step 1 Realtime Voice Stack

**Status:** ACCEPTED FOR ARCHITECTURE DESIGN  
**Date:** 2026-08-27  
**Decision owner:** Human-approved JARVIS planning

## Amendment: Gemini development provider (2026-08-28)

Repeated OpenAI Realtime development testing exhausted paid API credit. The existing
provider-replacement trigger for cost has therefore fired.

Gemini Live is **ADAPTED through the existing LiveKit boundary as a development-only
provider** using `gemini-3.1-flash-live-preview`. Selection is explicit through
`JARVIS_REALTIME_PROVIDER`; JARVIS does not automatically fall back or switch providers.
OpenAI remains the final Step-1 acceptance provider until a separate human decision
changes that status.

This amendment does not create a second conversation architecture. Both providers feed
the same LiveKit-to-JARVIS canonical conversation bridge. Provider-specific keys,
models, voices, and protocol settings remain in the composition boundary.

The Gemini model is preview software. Its Free Tier reduces development API cost, but
Free Tier content may be used by Google to improve its products. Development tests must
therefore avoid private or sensitive personal data. A Gemini pass does not replace the
short final OpenAI-specific acceptance run.

## Context

Step 1 must deliver a manually started, natural, realtime, multi-turn local voice conversation on Windows. It must support English, Hindi, Hinglish, contextual follow-ups, corrections, interruption, clean lifecycle handling, truthful failure, and JARVIS-owned canonical conversation truth.

Step 1 excludes wake word, durable memory, tools/actions, cloud deployment, telephony, and fallback voice stacks.

Old JARVIS proved useful behaviour but also demonstrated the cost of custom audio/session orchestration, overlapping conversation owners, global voice state, and a large STT-to-TTS chain.

Paper research compared LiveKit Agents, Pipecat, OpenAI first-party/direct paths, Gemini Live, custom media bridges, and cascaded voice pipelines. The supporting record is `docs/research/STEP_1_REALTIME_VOICE.md`.

## Decision

1. **ADOPT LiveKit Agents** as the Step-1 commodity realtime media and session framework.
2. **WRAP OpenAI Realtime** as the initial native speech-to-speech provider through LiveKit's provider integration.
3. JARVIS retains authoritative ownership of canonical accepted conversation truth, product lifecycle truth, personality, and truthful failure/interruption representation.
4. LiveKit and OpenAI session/history objects remain operational state and must not become JARVIS core domain types.
5. Use LiveKit locally. **Do not require LiveKit Cloud, hosting, telephony, or remote clients in Step 1.**
6. Preserve Gemini Live as the first provider replacement candidate if OpenAI fails Hindi/Hinglish, latency, reliability, cost, availability, or maintenance requirements.
7. Preserve Pipecat and a direct provider path only as reconsideration candidates, not simultaneous Step-1 implementations.
8. Do not implement a cascaded STT -> LLM -> TTS fallback in Step 1.
9. Pin exact dependency/model versions during implementation planning; do not encode model names into permanent JARVIS domain contracts.
10. Implementation remains blocked until the Step-1 architecture is reviewed and explicitly approved.

## Alternatives Considered

### Pipecat + OpenAI Realtime

Strong provider-neutral Python voice framework with excellent pipeline, turn, interruption, and transcript capabilities. Not selected because the exact local Windows microphone/speaker and echo path is less directly documented than LiveKit's console path for this slice.

### OpenAI Agents SDK or direct Realtime WebSocket

Thinner first-party surface, but it would leave more audio-device, playback, truncation, and failure mechanics under JARVIS ownership.

### LiveKit Agents + Gemini Live

Strong multilingual native-audio candidate. Not selected initially because an existing OpenAI API account is already available and OpenAI Realtime is adequate on paper. Gemini is the first replacement candidate if real multilingual acceptance fails.

### Custom realtime media bridge

Rejected because it recreates commodity streaming, buffering, interruption, reconnection, and audio-device behavior.

### Cascaded STT -> LLM -> TTS

Deferred because it adds latency, coordination, providers, and failure modes not needed to prove the primary conversational experience.

### Old-JARVIS runtime

Rejected as architecture. Required behavior and failure lessons will be rewritten against clean V1 boundaries.

## Why This Choice

- Best documented local microphone/speaker development path.
- Built-in device selection, AEC controls, recording, turn handling, and synchronized transcripts.
- Supports both OpenAI Realtime and Gemini Live behind provider plugins.
- Avoids custom media infrastructure while preserving future provider replacement.
- Reuses the user's existing OpenAI API account.
- Costs nothing locally except provider API usage.
- Provides a credible path to future browser/mobile/remote media without authorizing that scope now.

## Consequences and Tradeoffs

Positive:

- less custom audio and interruption machinery;
- provider replacement remains feasible;
- canonical JARVIS truth remains separate;
- future realtime clients can reuse the media framework;
- Step 1 has one selected implementation path.

Negative:

- LiveKit room/session concepts add framework weight;
- plugin/provider upgrades may introduce compatibility breakage;
- OpenAI usage is paid separately from ChatGPT;
- Hindi/Hinglish quality remains a human acceptance risk;
- exact interrupted transcript mapping requires architecture work;
- local success does not automatically prove later cloud/remote behavior.

## Replacement Boundary

JARVIS core must depend on JARVIS-owned conversation and lifecycle contracts, not LiveKit or OpenAI classes.

The Step-1 composition layer may construct the selected LiveKit/OpenAI adapter. That adapter translates:

- JARVIS session commands into LiveKit/provider operations;
- finalized user/assistant events into proposed JARVIS accepted turns;
- interruption/playback state into truthful JARVIS outcomes;
- provider/audio failures into JARVIS failure categories;
- shutdown/cancellation into deterministic resource cleanup.

Replacing OpenAI should require a provider adapter/configuration change within the realtime boundary, not changes to canonical JARVIS conversation state.

Replacing LiveKit is a larger media-framework change and may require a new realtime adapter, but must not require rewriting JARVIS product logic.

## Reconsideration Triggers

Reconsider the provider if:

- Hindi/Hinglish or code-switching fails human acceptance;
- perceived latency or interruption behavior is unacceptable;
- Realtime API access, reliability, privacy, pricing, or model availability becomes unsuitable;
- LiveKit's provider plugin cannot expose sufficient finalized-turn/interruption evidence.

Evaluate Gemini Live first when provider reconsideration is triggered.

Reconsider LiveKit if:

- local Windows audio cannot work reliably;
- echo/self-interruption remains unacceptable;
- canonical transcript and lifecycle requirements cannot be represented truthfully;
- framework concepts leak unavoidably into JARVIS core;
- dependency complexity materially exceeds the value provided.

Evaluate Pipecat or a direct provider adapter according to the exact failure that triggered reconsideration.
