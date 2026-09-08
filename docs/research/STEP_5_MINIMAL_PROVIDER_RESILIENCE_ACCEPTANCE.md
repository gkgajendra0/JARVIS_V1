# Step 5 — Minimal Provider Resilience Acceptance

Date: 2026-09-08

## Status

**ACCEPTED — BOUNDED STEP-5 CLOSURE**

The owner deliberately reduced Step 5 to a minimal provider-resilience foundation that is useful now. Full local/offline conversational fallback remains explicitly deferred.

## Accepted behavior

The production voice runtime now has a JARVIS-owned deterministic provider-resilience boundary for unrecoverable realtime-provider failures.

It classifies bounded failure kinds including quota exhaustion, rate limiting, authentication/permission problems, unavailable/rejected models/requests, provider 5xx/service failures, timeouts, connection loss, and unknown terminal provider failures.

The terminal path is:

```text
realtime provider terminal ErrorEvent
 -> deterministic JARVIS classification
 -> degraded provider-health state
 -> privacy-safe bounded reason/status log
 -> Windows-local deterministic status speech
 -> explicit session close
 -> existing outer voice lifecycle returns toward wake/idle
```

The local failure announcement is independent of Gemini/OpenAI TTS. On Windows it uses `System.Speech.Synthesis.SpeechSynthesizer` to create a temporary mono PCM WAV and streams that PCM through JARVIS's already-selected audio output.

## Authority / architecture boundaries

- provider/model text does not decide failure or recovery policy;
- raw provider response bodies are not exposed in normal spoken status or bounded failure logs;
- no canonical conversation, memory, identity, or authority state is duplicated;
- no second cloud provider is silently selected;
- no local LLM is installed or loaded;
- no automatic cloud-to-local handoff is claimed;
- a later healthy realtime agent state marks provider health recovered;
- the existing `VoiceRuntimeController` remains the outer wake/active/recovering owner.

## Automated evidence

Implementation PR: #23

Exact implementation head used for owner smoke before documentation-only reconciliation:

`455252a4ab0e2c7928f28353c2e0cde0ea955d2d`

Code Quality run `34237260767` passed:

- Ruff format/lint;
- full pytest;
- Windows DPAPI;
- Windows Hello helper.

Tests cover failure classification, provider-health transitions, recoverable-vs-terminal realtime events, local announcement/close behavior, and local status PCM playback.

## Owner-machine evidence

Owner command:

```powershell
python tools\research\step5_provider_resilience_owner_smoke.py
```

Observed physical output:

`24'TV (NVIDIA High Definition Audio) @ 48000 Hz`

Observed deterministic message:

`Sir, Gemini's API quota is exhausted. Cloud conversation is temporarily unavailable. I am returning to wake mode.`

Observed script result:

`STEP5_SMOKE_STATUS: PASS`

The owner explicitly confirmed that the message was audibly heard through the real configured speaker.

## Deferred scope

The following remain deliberately deferred and are not prerequisites for moving to Step 6:

- Ollama/local LLM installation or selection;
- local conversational LLM handoff;
- local/offline STT;
- local/offline conversational TTS;
- complete network-offline spoken conversation;
- cloud-to-cloud automatic failover;
- startup without cloud credentials based on a local intelligence stack.

Research on those options is retained in `STEP_5_RESILIENCE_RESEARCH_AND_ARCHITECTURE_PROPOSAL.md` and may be reopened later if the product need justifies it.

## Closure decision

The accepted subset satisfies the current need: JARVIS can diagnose a terminal cloud-conversation failure, communicate a truthful reason locally without depending on the failed provider, close safely, and preserve the existing wake/session/state architecture.

Step 5 therefore closes **bounded**, with full offline survival deferred rather than falsely marked complete.
