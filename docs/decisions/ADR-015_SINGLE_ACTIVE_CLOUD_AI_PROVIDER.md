# ADR-015 — Single Active Cloud-AI Provider

## Status

**ACCEPTED — 2026-09-05**

## Context

JARVIS supports multiple cloud-AI ecosystems so the owner can change provider over time. The earlier runtime exposed separate provider selectors for realtime conversation and Phase-4.4 memory-candidate extraction. That made configurations such as Gemini voice plus OpenAI memory technically possible.

That flexibility is undesirable for production JARVIS because it creates:

- multiple API billing/subscription relationships for one assistant;
- credential/configuration drift across subsystems;
- harder debugging when one role silently uses a different provider;
- avoidable provider-specific failure modes and quota/account management;
- a growing risk that future reasoning/tool/memory roles each add their own provider switch.

The owner requires one active cloud-AI provider/account at a time. A provider may expose different models for different capabilities, so this requirement is about the provider/account boundary, not forcing one exact model ID to perform incompatible jobs.

## Decision

Production JARVIS has exactly **one active cloud-AI provider** selected by:

`JARVIS_AI_PROVIDER`

Supported values currently are:

- `gemini`
- `openai`

All production cloud-intelligence roles must remain inside that provider family/account:

```text
JARVIS_AI_PROVIDER
       |
       +-> realtime conversation
       +-> deterministic scripted cloud TTS
       +-> structured memory-candidate extraction
       +-> future cloud reasoning roles
       +-> future provider-backed AI tools
```

Different model IDs inside the selected provider are allowed when capability requires it. For example, a Gemini Live realtime model and a Gemini structured-output model may coexist under the same Google API project/key.

A production subsystem may not independently select another cloud-AI provider.

## Credential ownership

`src/jarvis/ai_provider.py` is the sole production owner of provider-to-credential resolution:

- Gemini -> `GOOGLE_API_KEY`
- OpenAI -> `OPENAI_API_KEY`

Provider-specific adapters receive the already-selected provider credential explicitly where the SDK allows it.

API keys remain outside `machine.json` and are never persisted by JARVIS machine configuration.

## Adapter boundaries

Direct provider SDK imports are restricted to narrow adapter modules:

- `src/jarvis/voice/livekit_session.py` — realtime conversation;
- `src/jarvis/voice/scripted_speech.py` — deterministic scripted TTS;
- `src/jarvis/memory/extractors.py` — structured memory-candidate extraction.

Core memory, authority, conversation, context, identity, vision, and policy code must not depend directly on OpenAI or Gemini SDKs.

CI scans production source to prevent scattered credential reads, independent memory-provider selectors, or provider SDK imports outside approved adapter boundaries.

## Configuration migration

Existing installations may still contain `JARVIS_REALTIME_PROVIDER`. It remains a read-only migration alias so accepted owner-PC configuration does not break abruptly.

New configuration persists `JARVIS_AI_PROVIDER`. `jarvis-setup` migrates the legacy selector into the canonical setting and removes the legacy selector from newly saved machine state.

`JARVIS_REALTIME_PROVIDER` must not be used for new architecture or new documentation except when describing migration/history.

## What is not covered by this rule

The one-provider rule applies to **cloud-AI inference/intelligence calls**, not every network request JARVIS can make.

The following remain independent because they are local capability assets/infrastructure rather than subscription-backed AI inference providers:

- pinned model/checkpoint downloads from GitHub;
- pinned model assets from Hugging Face;
- pinned MediaPipe/Google Storage artifacts;
- OpenVINO/model release artifacts;
- Git/GitHub development-control traffic;
- local RF-DETR, CAM++, LR-ASD, SFace, MiniFAS, wake-word, and other local inference.

Any future external service that performs paid/cloud intelligence must be classified against this ADR before integration.

## Research exception

Research harnesses may compare multiple providers/models when a technology decision genuinely requires it. Research credentials and results do not change the production one-provider rule, and cross-provider bake-offs are not a production runtime dependency.

When the owner has already selected an active provider for normal JARVIS operation, implementation acceptance should prefer validating suitable models **inside that provider family** instead of requiring a second provider account solely for comparison.

## Consequences

### Positive

- one production AI billing/account relationship at a time;
- easier troubleshooting and quota/cost attribution;
- provider switching is an intentional top-level operation;
- memory and future AI roles cannot silently create extra subscriptions;
- provider-specific code remains replaceable behind thin adapters.

### Trade-off

The active provider must offer adequate models/APIs for each required capability. If it lacks a mandatory capability, JARVIS must fail truthfully or revisit this ADR explicitly; it must not silently fall back to a second paid provider.

## Enforcement

Automated enforcement includes `tests/test_ai_provider_policy.py`, which protects:

- centralized credential ownership;
- absence of an independent memory-candidate provider selector;
- provider SDK import boundaries;
- legacy-provider migration behavior.

This ADR is a durable architecture constraint for future JARVIS steps.
