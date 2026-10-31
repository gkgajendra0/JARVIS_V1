# Hosted runtime versus custom workspace memory

**HISTORICAL alternative; NOT SELECTED.** The owner’s API-cost constraint and final architecture choice supersede the hosted-runtime recommendation below. [Current contract](../PROJECT_CONVERSATION_MEMORY.md): Gemini plus automatic local conversations and existing encrypted memory/retrieval. Do not implement a hosted migration from this research.

Date: 2026-10-30. Status: researched recommendation for owner review, not an implemented migration or measured performance winner.

**Superseded recommendation:** The owner subsequently clarified that existing API bills are already too high. The hosted OpenAI runtime is not the current recommended baseline. See `LOCAL_MEMORY_REPOSITORY_REVIEW_2026-10-30.md` for the requested cost-constrained repository review. The capability findings below remain historical research; no hosted migration was authorized or implemented.

## Decision

Given the owner's explicit preference for reusing working systems and avoiding a long custom-framework project, qualify an OpenAI managed agent session as the project conversation engine. Keep existing Jarvis voice/device/action boundaries and canonical encrypted personal memory. Use one managed session per project/thread, a local project/session mapping and local source mirror, and explicit tools for relevant personal facts and approved local actions. Start with `environment.type: none`; there is no need to provision a cloud computer merely to answer project questions or call Jarvis functions.

This is a change in recommendation supported by newly inspected managed-runtime documentation. The earlier answer described only the Conversations API and missed the more complete hosted harness. A durable message store alone does not provide a complete personal assistant. The earlier seven-task native framework plan remains an unimplemented reference, not the recommended first build.

Do not claim this is ChatGPT Projects or consumer ChatGPT memory exposed by API. It is a documented hosted agent runtime with sessions and context management, integrated with Jarvis-owned personal memory and local capabilities.

## Verified primary-source findings

### OpenAI Conversations/Responses

Conversations stores messages, tool calls and outputs under a durable ID. Its items are not subject to the ordinary response object's 30-day TTL. Stored conversation history is still constrained by a model's context window. Chaining responses does not make historical input tokens free. Server-side Responses compaction exists and produces an opaque compacted representation; it is not an inspectable personal-fact database.

Do not assume every desired combination of Conversations, compaction options, models and the installed SDK is supported without checking the actual adapter. Conversation storage is a useful lower-level option, but not the complete runtime the owner asked to reuse.

### OpenAI managed Agents API

The official overview says OpenAI manages sessions, orchestration, context compaction and recovery through the managed Codex harness. Sessions can be resumed; saved items can be retrieved after a disconnect. The architecture explicitly supports no execution environment and application-handled function tools. Consequently Jarvis can retain its local authority/action runtime rather than surrendering the computer to a hosted shell.

The quickstart requires an application API key with `api.agents.read`, `api.agents.write`, and `api.responses.write`; examples use `OpenAI-Beta: agents=v1`. Documentation establishes capability, not account access or pinned-SDK compatibility. Models/tools are metered; OpenAI-hosted sandboxes have additional rates if used. The current data-control table lists `/v1/agents` application state as retained until deletion. None of these facts establishes cross-session autobiographical memory or successful voice latency on the owner's PC.

### Gemini Interactions and managed Antigravity agent

Interactions supports server-side history through `previous_interaction_id`, including the configured `gemini-3.5-flash-lite` in its listed models. Current documented retention is 1 day for free tier and 55 days for paid tier; shorter configured paid retention is also possible. This cannot be the only indefinite project archive.

The managed Antigravity agent is a real alternative: it owns an agent loop and automatic compaction, supports custom functions, and has free/paid quotas. Current documentation labels it preview, says function calling requires stateful continuation, and lists unsupported audio/video/document input and unsupported structured output. A saved managed-agent definition starts a fresh fork of its base environment on a new invocation; continuing a discussion requires preserving the interaction and environment identities. It is not Gemini Live with permanent personal memory enabled.

### Voice session persistence is distinct

OpenAI Realtime documents a current-session conversation with a maximum session duration; Gemini Live documents compression and resumption tokens valid for two hours after session termination. LiveKit warns that native realtime transcripts can arrive after the assistant response and requires agent-controlled turn detection for its pre-reply retrieval hook. Therefore neither a conversation ID nor a resumption handle alone integrates a durable project brain with the current voice path.

## Fit comparison (engineering inference, not benchmark scores)

| Option | Engineering removed | Work still required | Decision for this owner priority |
|---|---|---|---|
| Seven-task native framework | Little hosted state management | Archive, summaries, orchestration, recovery, routing, UI and voice integration | Too broad as the first build |
| OpenAI Conversations/Responses | Hosted message history and available compaction primitives | Application response/tool loop, project/profile bridge, audio and recovery adapter | Credible lean alternative if managed harness brings no useful benefit |
| OpenAI managed Agents session | Hosted conversation/tool loop, compaction and session recovery | Project IDs, relevant personal-memory tools, source mirror, local action adapter and voice | Recommended first qualification target for maximum reuse |
| Gemini Interactions/managed Antigravity | Hosted history/agent loop with existing provider family | Retention recovery, preview/SDK limitations, personal/profile and voice integration | Credible second route; not indefinite memory by itself |
| Hindsight/Mem0/Graphiti as replacement | Particular extraction/retrieval functions | Missing source capture, project ownership, voice response ordering and canonical lifecycle | Previous experiments stand; do not reopen this comparison |

The OpenAI choice prioritizes reduced framework maintenance. It does not preserve a strict free-Gemini-first requirement automatically. If that is a hard constraint, prefer the smallest native archive/routing fix with existing Gemini; do not imply a new OpenAI dependency is free or automatically paid for by the user's subscription/credits.

## Minimum Jarvis integration

1. Project registry: local workspace/thread IDs mapped to hosted session IDs; explicit selection and ambiguity handling. Sleep must not change this mapping.
2. Local encrypted source mirror and submission journal: persist accepted source/hosted item identities, use idempotency keys, and reconcile an interrupted submission before retrying. Hosted compaction cannot become the sole copy of source wording. This is a small data integration, not the earlier custom summarization engine.
3. Existing personal memory through scoped read/learn/correct/forget functions. A relevant shared profile is supplied to each project; project chat histories are not globally merged. Durable inferences still pass source/admission policy.
4. Existing local capabilities exposed as narrowly authorized function tools. Hosted tool intent is not permission, and success is recorded only after an actual verified result.
5. Controlled voice bridge: accepted speech -> selected session/request -> answer -> existing TTS/output. The existing free-speaking Gemini session must not independently answer the same turn. Native speech-to-speech reuse is retained only if it can delegate substantive answering without racing the selected conversation engine.

## Finite qualification, not another vendor bake-off

Use an isolated synthetic text adapter before installing a voice migration. One Nepal session and one interview session, with a single shared vehicle/profile fixture. Verify ordinary follow-ups, process restart, switching away/back, correction, cited source recovery after forced compaction, unknown information, explicit forgetting, and retry after lost stream. Use the same local authorization and deletion boundaries as Jarvis.

Then attach the actual voice path and measure Hindi/English ASR, interruptions, end-of-speech to first audio, provider/model token usage, tool round trips and actual API cost. No paid calls, account changes, model changes, or installations were performed by this research. No latency or quality result is implied by the documentation.

Promote only if it gives a material reduction in custom framework responsibility while meeting the owner's actual conversation acceptance. If no, retain tested native components and report the specific failure; do not restart an unfocused technology search. Model quality can be evaluated later only after identical correct context reaches the model.

## Evidence and limits

Existing repository technology reviews and the native empty-Nepal trace were inspected and reused. No prior technology benchmark was rerun. Official pages were fetched directly because the web search connector returned errors. This is a source/capability comparison, not hands-on qualification of hosted agents.

Primary sources fetched 2026-10-30:

- https://developers.openai.com/api/docs/guides/conversation-state
- https://developers.openai.com/api/docs/guides/compaction
- https://developers.openai.com/api/docs/guides/agents-api/overview
- https://developers.openai.com/api/docs/guides/agents-api/architecture
- https://developers.openai.com/api/docs/guides/agents-api/quickstart
- https://developers.openai.com/api/docs/guides/agents-api/sessions
- https://developers.openai.com/api/docs/guides/your-data
- https://developers.openai.com/api/docs/guides/realtime-conversations
- https://ai.google.dev/gemini-api/docs/interactions
- https://ai.google.dev/gemini-api/docs/managed-agents-quickstart
- https://ai.google.dev/gemini-api/docs/antigravity-agent
- https://ai.google.dev/gemini-api/docs/live-api/session-management
- https://docs.livekit.io/agents/models/realtime/
- https://docs.livekit.io/agents/logic/nodes/
