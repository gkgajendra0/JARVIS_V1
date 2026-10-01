# Interactive Owner-Input Voice Handoff — 2026-09-30

## Status

**IMPLEMENTED IN DRAFT PR #245 — NOT YET OWNER-MACHINE ACCEPTED OR MERGED**

This note records the research conclusion, regression mechanism and implementation
contract for proactive voice collection when durable JARVIS Work is
`WAITING_FOR_OWNER`.

## Product requirement

A background WorkItem may genuinely need information only the owner can provide, for
example a device platform, pairing confirmation, PIN, physical-world observation or
protected decision.

The intended voice-first behavior is:

```text
WorkItem -> WAITING_FOR_OWNER
        -> JARVIS proactively asks the pending question
        -> microphone remains active
        -> owner answers without another wake word
        -> answer is bound to the exact waiting WorkItem
        -> DBOS receives durable owner-input message
        -> WorkItem resumes
        -> proactive interaction closes naturally
        -> local wake detection resumes
```

Progress/completion notifications are not questions and remain one-way.

## Evidence and root cause

The known-good TV capability run on protected-main revision
`3d7dcac2cb2431e5ccc44f0a4d0eeab46e43879f` showed the desired conversational
behavior. JARVIS asked for the Hisense TV model/OS and the owner answered directly.
The realtime transcription rendered the short answer imperfectly as "It's wider.",
yet the same active conversation retained the preceding question and JARVIS correctly
continued the waiting work.

The same source revision also exposed the actual audio race. Background scripted TTS
checked that the realtime agent was listening, but that check and physical audio write
were not atomic. A realtime playback began after the check and before the background
TTS captured its first frame. Both speech paths then attempted to own the same
MediaDevices output and the background path failed with an InvalidState capture error.

PR #238 fixed physical speech ownership by introducing a shared lease and moving
background delivery to an exclusive idle boundary. That removed the race, but it also
turned `OWNER_INPUT` into one-way standalone speech:

```text
idle -> open speech-only session -> ask question -> close session -> resume wake
```

The question and reply therefore no longer shared LiveKit/Gemini conversational
context, and the owner had to wake JARVIS again before answering.

PR #243 changed standalone lifecycle speech to the accepted Gemini 3.8 Live lane but
correctly retained PR #238's speech-ownership lease. It did not create the owner-input
regression.

## Existing architecture retained

No new orchestration system is introduced.

- `WorkItem` remains canonical background-work truth.
- DBOS remains durable execution and human-in-the-loop message transport.
- `WorkState.WAITING_FOR_OWNER` remains the canonical unresolved dependency.
- `WorkRuntime.submit_owner_input()` continues to send the response to the exact
  DBOS execution through the durable `owner-input` topic.
- `WorkDelivery` remains notification/interaction transport, not canonical owner
  attention truth.
- Phase-10A `OwnerAttentionItem` remains the durable higher-level owner-attention
  model where applicable.
- The shared voice `_speech_ownership` lease remains mandatory.

This follows the accepted Phase-9 and Phase-10A decision to keep DBOS/WorkItem and
reject a second orchestration/control plane.

## LiveKit technology decision

LiveKit Agents 1.8.3 already provides strong primitives for structured conversational
work, including `AgentTask`. It was evaluated for this interaction.

For the current runtime trigger, direct adoption of `AgentTask` is not appropriate:
in pinned 1.8.3, an `AgentTask` is an inline task that is awaited from an existing
Agent tool/on-enter/on-exit activity context. JARVIS's trigger originates instead from
the independent durable Work delivery loop while no live AgentSession exists.
Invoking AgentTask from that loop would require private LiveKit activity APIs or an
artificial wrapper solely to enter inline-task context.

The implementation therefore uses only public, already-adopted LiveKit primitives:

- one normal `AgentSession`;
- the same accepted realtime provider and voice;
- one active microphone/output session;
- one deliberately constrained Work tool;
- canonical conversation turns through the existing LiveKitConversationBridge.

This keeps LiveKit replaceable behind JARVIS-owned lifecycle and avoids private
framework coupling. AgentTask remains a useful future primitive for sub-flows that
originate inside an already-active Agent activity.

## Implementation contract

### One-way deliveries

`PROGRESS`, `COMPLETION`, ordinary `FAILURE` and current blocker notifications keep
the accepted exclusive-idle one-way speech path.

### OWNER_INPUT

When an `OWNER_INPUT` delivery is current and JARVIS reaches the exclusive idle
boundary:

1. acquire the existing shared speech-ownership lease;
2. disable local wake detection so JARVIS cannot hear its own proactive question as a
   wake event;
3. open one realtime AgentSession with microphone and speaker active;
4. generate the pending Work question inside that same session;
5. expose only `continue_background_work`;
6. bind that tool to the exact delivery `work_id`;
7. leave the microphone active while the owner answers;
8. preserve the canonical USER utterance as the actual durable response;
9. on successful DBOS owner-input submission, allow one brief acknowledgement;
10. close the proactive interaction and resume local wake detection.

If the model attempts to target a different WorkItem, the bound tool fails closed.

If the owner does not answer, the WorkItem remains `WAITING_FOR_OWNER`, the delivery
is not falsely marked complete, and a bounded durable retry is scheduled.

A local speech fallback is not considered successful owner-input collection because
it has no reply channel.

## Why short answers work again

The pending question and the next USER utterance are once again part of one canonical
conversation. Therefore an imperfect short transcript such as "It's wider." is
interpreted with the immediately preceding TV-platform question available as context.

The model may use that context to understand the conversational meaning, but the
durable response sent into Work remains the accepted canonical USER utterance. The
model cannot invent hidden owner text.

## Startup reconciliation for legacy/stale owner-input deliveries

The first owner-machine acceptance after this change reused a WorkItem created by the
older one-way notification runtime. Canonical Work was still
`WAITING_FOR_OWNER`, but its original `OWNER_INPUT` delivery had already been marked
`DELIVERED` when the question was spoken. Because delivery event identity is
deduplicated by `(work_id, event_key)`, the new interactive transport correctly had no
pending record to consume on restart.

That state is inconsistent under the new contract: an owner-input interaction is not
delivered until the owner's response is durably submitted.

Work-runtime startup therefore now reconciles this invariant:

```text
WorkItem == WAITING_FOR_OWNER
        +
current OWNER_INPUT delivery == DELIVERED
        ↓
reopen the same delivery_id/event_key as PENDING
        ↓
interactive voice transport can ask again
```

The repair is idempotent, does not create duplicate WorkItems or duplicate delivery
identities, and does not affect already-pending owner prompts. It also provides
self-healing if the same inconsistent state is ever produced again.

## Required invariants

- exactly one JARVIS speech producer owns the physical speaker;
- proactive owner-input never requires a second wake word;
- the microphone remains active after JARVIS asks;
- the answer is bound to the exact waiting WorkItem;
- multiple waiting tasks cannot cause target guessing;
- no model-generated text substitutes for canonical owner speech;
- DBOS/WorkItem remains restart-safe durable truth;
- unanswered questions remain unresolved and retryable;
- progress/completion speech does not become unnecessarily conversational;
- provider failure cannot be misreported as owner-input success.

## Acceptance target

The owner-machine acceptance scenario is the real Phase-9 TV path:

```text
Owner: "Jarvis, I want to watch Transporter on my TV."
...
JARVIS proactively: "Which platform does your Hisense TV use: VIDAA, Roku, or Android TV?"
Owner: "VIDAA."        # no wake word
JARVIS: brief acknowledgement
...
same exact WorkItem resumes
```

Acceptance must also show:

- no second JARVIS voice overlaps the question or acknowledgement;
- the owner answer appears as a canonical USER turn in the proactive session;
- `continue_background_work` submits against the exact waiting WorkItem;
- Work leaves `WAITING_FOR_OWNER`;
- wake detection resumes after the interaction;
- an unanswered prompt does not falsely resolve the WorkItem.
