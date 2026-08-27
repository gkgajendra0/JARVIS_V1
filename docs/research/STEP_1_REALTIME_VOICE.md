# Step 1 Realtime Voice Technology Research

**Status:** COMPLETE — paper research accepted for architecture planning  
**Date:** 2026-08-27  
**Active slice:** Step 1 — Natural Conversational Core

## Required Behaviour

Step 1 must prove a manually started, natural, realtime, multi-turn spoken conversation on the local Windows JARVIS machine.

Required behaviour:

- local microphone input and speaker output;
- English, Hindi, and Hinglish, including natural code-switching;
- contextual follow-ups, corrections, and topic changes;
- natural interruption/barge-in and coherent continuation;
- clean session startup, cancellation, and shutdown;
- truthful provider, network, and audio failure;
- JARVIS-owned canonical accepted conversation truth;
- no wake word, durable memory, tools/actions, cloud deployment, telephony, or fallback voice stack.

The objective is conversational presence, not a command bot or broad agent platform.

## Research Method

The decision uses paper research rather than implementing every candidate. Evidence considered:

- current official product and API documentation;
- framework architecture and current integration support;
- Windows/local-audio development path;
- interruption and transcript semantics;
- provider and framework maintenance activity;
- developer issues and user reports as supporting, non-authoritative evidence;
- relevant old-JARVIS code, tests, and failure lessons;
- cost and replacement boundaries.

Real human testing remains a completion requirement for the selected stack. Paper research does not prove Hindi/Hinglish quality, perceived latency, or behavior on the target audio hardware.

## Architecture Pattern

Native speech-to-speech is the preferred primary pattern:

```text
User audio
-> native realtime audio model
-> assistant audio
```

This better fits low-latency conversational presence, natural turn-taking, acoustic cues, and interruption than making Step 1 coordinate separate STT, text-LLM, and TTS services.

A cascaded `STT -> LLM -> TTS` stack remains a possible future resilience path. It is not Step 1 scope.

## Candidate Summary

| Candidate | Strengths | Weaknesses for Step 1 | Classification |
| --- | --- | --- | --- |
| LiveKit Agents + OpenAI Realtime | Documented local console using computer microphone/speakers; device selection; echo-cancellation controls; mature realtime media; synchronized/truncated transcripts; Python; future provider plugins | Room/participant concepts add framework weight; provider integrations can break during API transitions | **ADOPT LiveKit; WRAP OpenAI** |
| Pipecat + OpenAI Realtime | Python-native voice pipelines; strong provider breadth; Smart Turn/VAD; interruption and transcript aggregators; BSD-2 license | Current primary quickstart is browser/WebRTC; local raw microphone/speaker and echo behavior is less clearly supported for this exact desktop path; fast-moving APIs | **REJECT for Step 1; preserve as replacement candidate** |
| OpenAI Agents SDK/direct Realtime | First-party path; fewer layers; native speech-to-speech and interruption support | Python server path uses WebSocket; JARVIS would own more playback, audio-device, truncation, and failure mechanics | **REJECT as primary; preserve as lower-level fallback** |
| LiveKit Agents + Gemini Live | Same LiveKit media advantages; documented broad multilingual support and natural language switching; native audio | Existing OpenAI access makes it an additional provider account; session compression/resumption requirements; model/version churn | **PRESERVE as first provider replacement candidate** |
| Custom realtime media bridge | Maximum control | Rebuilds commodity audio, buffering, interruption, reconnect, and transport mechanics | **REJECT** |
| Cascaded STT -> LLM -> TTS | Explicit intermediate text; independently replaceable stages | More components, latency, coordination, and failure modes than required for Step 1 | **DEFER to resilience work** |
| VaaniYantra | Demonstrates the value of native S2S for an Indian-language voice product | Product-specific; complete published stack was not independently verified; telephony and healthcare workflow are irrelevant | **REFERENCE EVIDENCE ONLY** |

## Why LiveKit Agents

LiveKit provides the strongest documented match for the exact local Step-1 environment:

- `lk agent console` talks to an agent through the computer microphone and speakers without requiring LiveKit Cloud;
- input/output audio-device selection is explicit;
- console recording and acoustic echo cancellation controls are available;
- realtime models and cascaded voice pipelines share one agent framework;
- OpenAI Realtime and Gemini Live are supported through provider plugins;
- synchronized assistant transcription stops and truncates when playback is interrupted;
- the media layer can later serve browser/mobile/remote clients without becoming JARVIS product authority.

LiveKit Cloud is not selected or required for Step 1. The open-source local framework is the selected commodity layer.

Official references:

- https://docs.livekit.io/reference/developer-tools/livekit-cli/agent/
- https://docs.livekit.io/agents/multimodality/text/
- https://docs.livekit.io/agents/logic/turns/
- https://docs.livekit.io/agents/models/realtime/
- https://docs.livekit.io/agents/models/realtime/plugins/openai/
- https://docs.livekit.io/agents/models/realtime/plugins/gemini/

## Why OpenAI Realtime Initially

OpenAI Realtime is selected as the initial native speech-to-speech provider because:

- it is designed for low-latency natural conversation, turn-taking, and barge-in;
- current official integrations exist in LiveKit;
- the user already has an OpenAI API account used by old JARVIS;
- using the existing account avoids introducing another provider before the primary path is proven;
- provider-specific behavior can remain behind the accepted replacement boundary.

This is not a claim that OpenAI has proven superior Hindi/Hinglish quality. That must pass human acceptance. Gemini Live becomes the first replacement candidate if OpenAI does not meet multilingual, latency, reliability, cost, or maintenance requirements.

Official references:

- https://developers.openai.com/api/docs/guides/voice-agents
- https://developers.openai.com/api/docs/guides/realtime-conversations
- https://developers.openai.com/api/docs/pricing

## VaaniYantra and Gemini Evidence

The supplied VaaniYantra handover describes a natural Hindi/English appointment-call demonstration and attributes its preferred path to Gemini Live native speech-to-speech with a separate cascaded fallback.

The useful lesson is native S2S first, not copying VaaniYantra, telephony, healthcare workflows, or a custom WebSocket bridge. The exact VaaniYantra implementation was not independently verified and is therefore not used as authoritative selection evidence.

Gemini Live remains technically credible because Google documents:

- realtime bidirectional native audio;
- interruption support;
- broad language coverage and natural switching;
- context compression and session resumption;
- LiveKit and Pipecat integrations.

Constraints include the normal 15-minute audio-only session limit without compression, periodic connection/session management, model/version churn, and provider-specific conversation-role semantics.

Official references:

- https://ai.google.dev/gemini-api/docs/live-api/capabilities
- https://ai.google.dev/gemini-api/docs/live-api/session-management
- https://docs.livekit.io/agents/integrations/google/

## Old-JARVIS Evidence

Relevant old-JARVIS voice work shows why commodity realtime mechanics should not be rebuilt:

- a giant composition/runtime module coordinated voice, authentication, memory, skills, repair, and awareness;
- STT, TTS, recorder, speaker authentication, barge-in, follow-mode, continuity, context guardian, response composition, and global flags shared overlapping state;
- provider/audio failures could pressure invalid lifecycle states;
- interruption, playback completion, silence, endpointing, and self-echo required explicit coordination;
- ordinary conversational references accumulated custom continuity and pronoun logic.

Behaviour worth preserving:

- one owner for active audio acquisition;
- interruption must stop playback promptly;
- interrupted output must not be recorded as fully delivered;
- shutdown and failures must release resources;
- silence/provider activity must not keep a session alive indefinitely;
- conversation should handle corrections and references without custom rule-engine sprawl.

The old runtime is evidence, not an architecture to copy.

## Ownership Boundary

### JARVIS owns

- canonical accepted conversation truth;
- interaction lifecycle truth;
- personality and product behaviour;
- accepted interruption and failure representation;
- provider selection/configuration;
- future capability authority.

### LiveKit owns operationally

- local media acquisition/playback mechanics;
- realtime transport and buffering;
- SDK session mechanics;
- low-level interruption and transcript synchronization;
- provider-plugin integration.

### OpenAI owns operationally

- native speech understanding and generation;
- provider-side realtime conversation processing;
- provider turn-detection/interruption signals;
- provider session state.

LiveKit/OpenAI operational history is not permanent JARVIS product truth.

## Cost

For local Step 1:

- LiveKit Agents open-source framework: no charge;
- local microphone/speaker and console: no charge;
- LiveKit Cloud: not required and not selected;
- hosting/telephony/additional STT/TTS: not required;
- OpenAI Realtime API: usage-based charge on the existing API account.

The ChatGPT subscription does not include API usage. API keys must remain outside Git in environment configuration. Any key previously committed to old Git history must be revoked and replaced.

## Risks

- English/Hindi/Hinglish quality is unproven until human testing.
- WebSocket/provider interruption semantics may differ from LiveKit transcript delivery.
- Echo behavior depends on the real microphone/speaker setup and AEC path.
- LiveKit adds concepts that must not leak into JARVIS core state.
- Provider/plugin API evolution can cause compatibility breaks; versions must be pinned.
- OpenAI Realtime operating cost can exceed cheaper providers.
- Existing API access does not guarantee Realtime quota or billing readiness.
- Canonical accepted-turn mapping must be proven during architecture and validation.

## Required Acceptance Evidence

Only the selected stack will be implemented initially. Completion still requires:

- several-minute English, Hindi, and Hinglish conversation;
- natural code-switching;
- contextual follow-ups and corrections;
- early/mid/late interruption;
- transcript fidelity after interruption;
- clean startup and shutdown;
- controlled provider/network/audio failure;
- acceptable perceived latency and cost;
- no duplicate conversation/context owner.

If the selected stack fails a requirement materially, reconsider Gemini Live first, then Pipecat or a lower-level provider path based on the failure.

## Final Research Decision

- **ADOPT** LiveKit Agents as the Step-1 local realtime media/session framework.
- **WRAP** OpenAI Realtime as the initial native speech-to-speech provider.
- **REWRITE** required old-JARVIS conversation behaviour on the clean V1 foundation.
- **REJECT** the old voice runtime and custom realtime media bridge.
- **REJECT for Step 1** Pipecat and direct-provider orchestration, while preserving them as replacement candidates.
- **PRESERVE** Gemini Live as the first provider replacement candidate.
- **DEFER** cascaded STT/LLM/TTS, fallback providers, LiveKit Cloud, hosting, telephony, wake word, memory, and tools.

The next stage is Step-1 architecture design. Implementation remains unauthorized until that architecture receives human approval.
