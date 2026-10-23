# Proposed amendment: controlled public Gemini Paid Live transport

Status: DRAFT FOR OWNER REVIEW, not approved or implemented. 23 October 2026.
This addresses the real Paid Live gap recorded in the Free/Paid implementation
report. It is not a second router, alternate brain or spending-policy relaxation.

## Problem and choices

The installed LiveKit Google plugin owns automatic reconnects after GoAway;
max_retry=0 does not stop those clean restarts. Its public events report a
connection after setup, too late to reserve every charged connection. A maximum
reply size alone does not bound an unlimited number of provider-driven turns.
Current production Paid Live therefore remains explicitly unavailable.

Options considered:

1. Keep the current bounded Work/Hands/memory candidate and Free-only voice.
   Safest immediate state, but does not complete requested Paid voice continuity.
2. Use a supported upstream pre-connect/turn-admission extension, if an exact
   version with both hooks is verified. No such installed/public hook has yet
   been found; no speculative package upgrade or vendor-private patch is approved.
3. Recommended research/implementation direction: add a narrow JARVIS-owned
   RealtimeModel/RealtimeSession adapter over the public Google GenAI Live API,
   used only for Paid handoff. Existing ModelRouter, governor, canonical bridge,
   tools, private guards, microphone ownership and physical output remain owners.
   This adds protocol/turn control responsibility and must earn its acceptance.

## Public support and open proof obligations

Google documents disabling automatic activity detection and sending client
activityStart/activityEnd. This makes the client responsible for speech
boundaries and pre-speech audio. At least500ms end-of-speech tolerance is advised;
retain the existing local Silero VAD and test Hindi/Hinglish/English pauses.
[Google Live capabilities](https://ai.google.dev/gemini-api/docs/live-api/capabilities).

LiveKit exposes RealtimeModel/RealtimeSession and
RealtimeCapabilities.can_disable_turn_detection as public interfaces.
[LiveKit API](https://docs.livekit.io/reference/python/livekit/agents/llm/).
Pinned interfaces must be characterized, not inferred from current web docs.

The documented Gemini3.8 Live limits are131072 input/65536 output tokens.
[Model card](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-live).
These are model limits, not proof of a total-session cost bound. Before Paid
admission, verify which configured output cap includes audio/text/thinking and
which messages can trigger another chargeable generation. Retain fail-closed
behavior for an unsupported model, tool behavior or pricing/usage dimension.

## Proposed transport contract

- One physical public client.aio.live.connect per transport instance, no hidden
  retry/resumption loop. Every new connection/context replay requires its own
  atomic shared-governor admission before entering the connection context.
  A Free project's provider resumption handle never crosses into Paid.
- Explicit bounded client-owned activity/response dispatch. Reserve before every
  activity end, text reply request or tool response that can trigger generation.
  Tool continuations are separately charged inference, not another action permit.
  Do not treat a later generation-created/audio callback as pre-send admission.
- Price conservative worst-case context and each charged modality from verified
  model/protocol limits and reviewed price/FX versions; do not invent an audio
  tokens-per-second hard bound. The existing35000paise cumulative shared ceiling
  remains. A large conservative reserve may temporarily reduce concurrency.
- Frame forwarding consumes only an already proven interval, with bounded PCM
  buffers and elapsed-time/quantity gates. Disk reservations/settlement stay off
  the realtime frame path. Video is denied until separately bounded and priced.
- Protocol/state machine validates raw usage, turn identity, duplicates,
  cumulative/per-turn semantics, caches and thinking dimensions. Missing final
  evidence retains the worst-case hold and blocks new Paid admission. Never
  subtract totals or assume missing dimensions are zero without a contract.
- GoAway/timeout/cancellation/close before complete usage is uncertain. A reconnect
  is a new bounded transport with new context admission, not reuse of a spent
  reservation. If all charging triggers cannot be bounded, remain unavailable.
- Keep the current public AgentSession.update_agent handoff and accepted canonical
  projection. Original session identity, tools, Authority permits, selected facts,
  source currentness, release budget and private expiry are not recreated/renewed.
- Free recovery is demand-driven at a safe boundary after input, playback and
  tools stop. Keep the same canonical context and one shared half-open lease.
  Do not add provider health-generation polling or interrupt active speech.
- Free normal/startup/lifecycle behavior and dedicated TTS stay as currently
  implemented. No external account, provider, key storage or billing changes.

## Acceptance before enabling real Paid voice

First offline: real pinned public protocol/schema conversion with fake WebSocket
transport; connection/turn/tool triggers each see a prior durable reserve; injected
GoAway cannot secretly reconnect; bound/ceiling/price/unknown/expiry/cancellation
and real multi-process contention; old epoch audio/tool/transcript/error fences;
current canonical context/forget/lock; full duplex interruption and pause handling;
confirmed/uncertain action counters remain1; Work/Hands/memory retain shared cost.
Run whole-repository regressions and one independent review of this amendment.

Only after offline proofs: separately request a bounded real Paid API experiment
with exact request count, duration and reviewed worst-case INR exposure. This
proposal does not authorize that experiment. Finally the owner uses the whole
normal JARVIS app and fictional multilingual facts/actions; no isolated mic test
or OFF-only run substitutes for enabled continuity acceptance.

## Approval scope and tradeoffs

Approving this draft would authorize a detailed executable plan and offline
implementation/review of option3. It does NOT authorize live Paid API calls,
activation, paid purchases, SDK-private patches, a price/FX assumption, deployment
or merge. Native execution preference is retained. Material tradeoff: Paid turn
boundaries become client-controlled, requiring new pause/barge-in qualification;
the Free provider path retains its existing behavior. Until verified, the current
Paid Live denial remains in place. Do not describe a proposed adapter as working.
