# Step 4 — Phase 4.2 Live Context and Context Assembler Implementation Decisions

## Status

**IMPLEMENTATION CONTRACT — BLOCKED ON PHASE 4.1 REAL SQLCIPHER GATE**

This document narrows the owner-approved Step-4 architecture into concrete Phase-4.2 implementation choices. It does not authorize Phase-4.2 runtime implementation until the exact Phase-4.1 real Windows SQLCipher/DPAPI gate for the crash-safe key contract passes.

It does not authorize model-driven memory writes, implicit memory admission, embedding retrieval, or provider-owned canonical context.

## Research-first source check

Implementation details were refreshed immediately before this contract was written against current authoritative documentation and the repository boundary:

- Python `collections.deque`: https://docs.python.org/3/library/collections.html
- Python monotonic clock: https://docs.python.org/3/library/time.html
- LiveKit chat context: https://docs.livekit.io/agents/logic/chat-context/
- LiveKit pipeline nodes/hooks: https://docs.livekit.io/agents/logic/nodes/
- LiveKit Python API: https://docs.livekit.io/reference/python/livekit/agents/index.html
- Gemini token counting: https://ai.google.dev/api/tokens
- Gemini Live API best practices/context compression: https://ai.google.dev/gemini-api/docs/live-api/best-practices
- OpenAI Realtime context truncation: https://platform.openai.com/docs/api-reference/realtime

Repository inspection confirms that `ConversationSession` already owns accepted JARVIS turns with stable `session_id`, `turn_id`, `accepted_at`, interruption state, and optional provider `external_item_id`. `LiveKitConversationBridge` is the provider boundary that converts committed LiveKit messages into canonical JARVIS turns.

---

## 1. Authority boundary

`LiveContext` is JARVIS-owned, provider-independent, process-local session state.

It is **not**:

- LiveKit `ChatContext`;
- `AgentSession.history`;
- Gemini Live session history;
- OpenAI Realtime conversation state;
- durable semantic memory;
- an LLM summary.

Canonical flow:

```text
provider committed message
        -> LiveKitConversationBridge
        -> ConversationSession.accept_turn()
        -> accepted ConversationTurn
        -> LiveContext.observe_turn()
```

Only accepted JARVIS turns may enter canonical LiveContext recent-turn history.

Provider history can be synchronized from JARVIS state later, but provider history never outranks or mutates canonical LiveContext.

---

## 2. No new live-context framework

Do not add LangGraph, Mem0, cachetools, or another state/memory framework for Phase 4.2.

Reasons:

- JARVIS already owns session lifecycle and accepted turns;
- live context is small, typed, and process-local;
- Python provides mature bounded deque and monotonic timing primitives;
- a generic TTL cache does not implement JARVIS concepts such as active goal, topic, unresolved work, provenance, or precedence;
- introducing another framework would create a second state owner.

Use only Python standard-library structures for the canonical live-context core.

---

## 3. Recent accepted turns

Use `collections.deque(maxlen=...)` for the recent accepted-turn tail.

Rules:

- store immutable `ConversationTurn` objects, not copied provider messages;
- preserve JARVIS `turn_id`, accepted timestamp, role, text, and interruption state;
- newest accepted turns displace oldest turns when the configured bound is reached;
- the bound is an implementation policy input, not a durable-memory policy;
- recent-turn eviction never creates durable memory;
- closing/failing the conversation makes the LiveContext disposable.

The initial core must accept the turn bound as configuration rather than hiding an unchangeable magic constant in the data structure.

---

## 4. TTL state and monotonic expiry

Use `time.monotonic_ns()` (injectable in tests) for TTL/expiry decisions.

Wall-clock timestamps may still be carried for human-readable provenance when needed, but wall-clock time must not determine in-process expiry because system-clock corrections must not resurrect or prematurely expire live state.

Phase-4.2 typed live-state categories:

- `active_goal` — zero or one current goal;
- `active_topic` — zero or one current topic;
- `entities` — keyed session entities currently relevant;
- `unresolved_work` — keyed pending question/action/decision items;
- `interaction_context` — temporary interaction/style state only.

Each non-turn entry must carry at least:

- stable live-context key;
- value/text payload;
- source `turn_id` or explicit runtime source reference when available;
- set-at monotonic timestamp;
- optional expiry monotonic timestamp;
- priority/importance class only if deterministic and explicitly assigned by the caller.

No mood/emotion inference is made durable. Temporary interaction context expires or disappears with the session.

---

## 5. No automatic semantic extraction in Phase 4.2

Phase 4.2 does **not** infer goal/topic/entities/unresolved work from arbitrary user text using an LLM.

The live-state core exposes deterministic setters/removers so later trusted runtime components can supply state explicitly.

During the first Phase-4.2 implementation slice, automatic bridge behavior is limited to observing accepted conversation turns. This keeps the phase independent of the Phase-4.4 candidate extractor and prevents a model from silently becoming the canonical live-state writer.

---

## 6. ContextAssembler ownership and precedence

`ContextAssembler` is JARVIS-owned and provider-independent.

It receives only already-governed inputs, initially:

- current accepted turn / current request reference where applicable;
- non-expired LiveContext state;
- bounded recent accepted turns.

Later phases may add accepted durable-memory retrieval as another input, but the assembler itself never searches provider history or writes memory.

Initial deterministic precedence:

```text
explicit current user turn / current request
    > unresolved work directly tied to the current session
    > active goal
    > active topic
    > explicitly supplied relevant entities
    > temporary interaction context
    > older recent accepted turns
```

The current user turn is never displaced by older LiveContext state.

The assembler must produce an immutable `ContextPacket` with provenance references so provider adapters never need to guess where context came from.

---

## 7. Budgeting decision

LiveKit `ChatContext.truncate()` is item-count based and therefore cannot be the JARVIS context-budget authority.

Exact cross-provider token counting is also not available as one local portable primitive:

- Gemini exposes exact `countTokens` through a model/API call;
- realtime providers maintain their own token/audio history and provider-side truncation/compression;
- adding a network token-count call to every JARVIS turn would put avoidable latency and availability dependency on the critical response path.

Therefore Phase 4.2 introduces a replaceable local budget interface:

```text
ContextBudgetEstimator
    estimate_text(text) -> integer units
```

The first implementation uses a deliberately conservative local text estimator based on UTF-8 encoded byte length plus fixed JARVIS framing overhead. It is **not** presented as provider billing-token truth. The assembler strictly enforces its configured local budget; provider context-window truncation/compression remains a separate outer safety layer.

The estimator is replaceable so a later provider-specific local tokenizer can be introduced without changing LiveContext or ContextAssembler.

Do not call remote token-count APIs in the realtime critical path.

No single permanent production budget value is selected by this document. The core accepts an explicit budget policy and a small bake-off/real-session measurement will choose runtime defaults.

---

## 8. Provider translation boundary

LiveKit `ChatContext` is a **translation target**, not canonical state.

The provider adapter may translate a `ContextPacket` into ordinary user/assistant context items when a context refresh, handoff, provider restart, or controlled one-turn generation requires it.

Do not place changing LiveContext into the permanent JARVIS persona/instruction string.

Current LiveKit realtime behavior is important:

- `update_chat_ctx()` can update a running realtime session;
- realtime chat-context updates remove the agent instruction item before forwarding provider history;
- ordinary user/assistant history can be synchronized;
- `on_user_turn_completed` requires agent-side turn detection for realtime models.

JARVIS currently intentionally uses provider-native realtime turn detection. Phase 4.2 therefore must **not** switch VAD/turn detection merely to obtain a pre-reply context hook.

The first runtime integration observes accepted turns into LiveContext without mutating the realtime provider's chat history. Provider synchronization is a separate measured sub-slice with a real voice bake-off, so Step-1/2 conversation robustness is not silently reopened.

---

## 9. Provider context versus canonical live context

Provider-native context management remains useful but non-authoritative:

- OpenAI Realtime may truncate older conversation items when context limits are reached;
- Gemini Live can use context-window compression/sliding-window retention for long sessions;
- LiveKit can truncate `ChatContext` by recent item count.

Those mechanisms control provider execution cost/window size. They do not define JARVIS truth, TTL, live goal/topic state, or durable memory.

If provider history is lost/truncated/restarted, JARVIS must be able to rebuild an appropriate bounded context from canonical accepted turns + LiveContext rather than treating provider state as the source of truth.

---

## 10. Failure and privacy behavior

LiveContext is RAM-only in Phase 4.2.

Rules:

- no SQLite writes from LiveContext itself;
- no raw provider payload archive;
- no automatic promotion into semantic memory;
- no secret-bearing context item should be included in provider packets merely because it is present in local state;
- expired entries are excluded before assembly;
- provider-adapter failure does not corrupt canonical LiveContext;
- session close/failure permits immediate LiveContext disposal.

---

## 11. Test strategy before Phase 4.2 closes

Required automated tests:

- accepted `ConversationTurn` enters LiveContext exactly once;
- duplicate accepted `turn_id` is idempotent/rejected deterministically;
- bounded recent-turn eviction preserves newest turns and order;
- interrupted assistant turn metadata survives;
- monotonic TTL expiry and explicit removal;
- wall-clock changes cannot affect TTL tests;
- goal/topic/entity/unresolved-work setters do not create durable memory;
- current explicit turn has highest assembly precedence;
- expired entries never enter packets;
- budget enforcement is deterministic and never exceeds configured local units;
- low-priority/old context is removed before higher-priority/current context;
- packet output includes source references and contains no provider IDs as canonical identities;
- LiveKit translation contains only intended ordinary context messages and never rewrites base JARVIS instructions;
- bridge integration updates LiveContext only after `ConversationSession.accept_turn()` succeeds;
- no change to current provider-native turn-detection configuration;
- all Step-1/2/3 and Phase-4.1 regression tests remain green.

A controlled local/real-voice provider synchronization bake-off is required before any automatic `update_chat_ctx()` synchronization is enabled in production voice mode.

---

## 12. Initial Phase-4.2 implementation slices after the Phase-4.1 gate

### 4.2A — provider-independent live-context core

- `LiveContext` + typed transient entries;
- bounded accepted-turn tail;
- monotonic TTL;
- deterministic setters/removers;
- unit tests.

### 4.2B — provider-independent ContextAssembler

- immutable context packet;
- precedence/order;
- replaceable local budget estimator;
- deterministic trimming;
- unit tests.

### 4.2C — canonical bridge observation

- `LiveKitConversationBridge` observes the accepted `ConversationTurn` after canonical acceptance;
- no provider chat-history mutation yet;
- tests prove ordering and no regression.

### 4.2D — provider translation + measured synchronization bake-off

- translate a packet into supported LiveKit ordinary context items;
- test restart/handoff/context-refresh scenarios;
- run real OpenAI/Gemini realtime voice bake-off without changing native turn detection;
- only enable automatic provider synchronization if measurements show it is reliable and does not regress conversation/audio behavior.

No Phase-4.3 explicit durable-memory UX starts until 4.2 acceptance is recorded.
