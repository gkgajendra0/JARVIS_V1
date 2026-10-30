# Workspace conversations and personal memory

**SUPERSEDED design alternative — 31 October 2026.** Retained for provenance. The owner selected [Gemini with native project conversations and local memory](../../PROJECT_CONVERSATION_MEMORY.md). Its [current build plan](../plans/2026-10-31-project-conversation-memory.md) governs future implementation. The broader archive/projection/outbox/UI design below is not the selected first-delivery scope.

Date: 2026-10-30. Status: concrete design for owner review; no product implementation or activation claimed.

## Intent and existing decision

Jarvis must preserve a discussion such as the Nepal trip across protected-response retirement, actual sleep, process restart, and intervening projects. The owner must be able to inspect the active workspace and saved discussion. Relevant established personal facts must remain available across projects without combining their message histories.

The October 19 native-extension decision and October 22 technology review remain the baseline. Reuse their component experiments; do not repeat the vendor comparison. This design extends conversation ownership and capture. It does not claim a new retrieval winner.

## Inspected implementation and failure

- `ConversationSession` owns accepted turns but is ephemeral and recreated for voice sessions.
- `LiveKitConversationBridge._notify_accepted_turn` invokes synchronous observers, catches their exceptions, and continues. This observer mechanism cannot promise durable recording before a reply.
- `EncryptedTopicCheckpointStore` stores title, goal, constraints and steps, not the full discussion.
- `TopicContinuity.prepare` persists model-proposed patches. Omitting the tool/patch omits the update; improving search cannot recover absent source text.
- `PersonalContextSession.prepare_topic` waits up to three seconds for the accepted transcript. It is reached only if the model invokes the tool.
- Gemini realtime currently owns response timing. `context_sync.py` expressly forbids assuming all configured models support mid-session context replacement.
- Native trace restored Nepal trip with empty constraints, goal and steps. This proves missing restored content, not the exact historical cause of every missing field.

## Approaches and selection

1. Continue tool-selected field checkpoints: smallest change, but cannot preserve an entire discussion when the model omits updates. Reject as the archive.
2. Replace the primary runtime with an external memory/agent framework: possible, but prior experiments do not justify migrating storage, authority, voice and task state. Reject for this change.
3. Extend native Jarvis with a durable event archive, named workspaces, source-linked projections and a mandatory response preparation boundary. Recommended; consistent with the existing native-extension decision.

The owner has accepted the architectural direction and requested a concrete plan. Details below are implementation proposals, not already approved implementation or proven performance.

## Product contract

- “Let's plan my Nepal trip” creates/selects a named workspace and acknowledges the selection.
- All subsequent accepted conversation turns remain in its current thread until an explicit switch or an owner-confirmed ambiguous transition. Unrelated small talk does not silently switch projects.
- “Switch to interview preparation” closes the current segment and selects another workspace atomically with the switching turn's routing record. The command and its acknowledgement belong to the destination; routing metadata records the previous workspace without copying its content.
- Unknown/new discussion starts in a visible General workspace; the owner need not invent a name for every question. General history is not automatically injected into named workspaces.
- Sleep closes a listening segment. Automatic protected-response retirement closes only a transport session. Neither deletes or changes the selected thread. The durable last selection is retained; after restart Jarvis says which workspace is resumed before using it. A named request selects its workspace instead. Selection metadata stays local until current-owner authorization.
- “Status of my Nepal trip” restores that workspace's current decisions, tasks and supporting history before the substantive answer. A project can contain multiple threads, but the default is to resume its latest open thread. “New conversation in Nepal trip” creates another thread.
- Duplicate names/ambiguous trips produce one clarification with no guessed switch. Name lookup uses normalized exact names and explicit aliases, not unrestricted fuzzy selection.
- “What topic are we discussing?”, “Show my projects”, “What did you save?” and “Where did that come from?” expose selection, retention and source messages.
- Confirmed personal facts can inform relevant projects. Mentioning a rental car never establishes ownership. An assistant suggestion never becomes an owner decision. Only verified tool success establishes executed task completion; an owner report is labelled owner-reported completion.
- Recorded ASR text is evidence of the accepted transcript, not proof the recognizer heard correctly. Owner corrections supersede it for current answers while preserving the correction history unless deleted.

## Data and ownership

Add migration `0005_workspace_conversations.sql` to the existing SQLCipher connection and migration ledger. No second database/key. Tables are application-owned:

- `conversation_workspace`: immutable UUID, owner scope, display name, normalized name, state, revision.
- `conversation_workspace_alias`: normalized explicit alias to workspace; collisions require clarification.
- `conversation_thread`: UUID, workspace UUID, title, created/last-active times, state, revision.
- `conversation_segment`: transport session UUID, thread UUID, start/end and reason; many segments per thread.
- `conversation_event`: immutable event UUID, thread UUID, monotonic sequence, kind, source turn/tool ID, parent request ID, timestamp, text/result, interrupted flag, admission status and source generation. Unique source identity prevents duplicated callbacks. Corrections append events; explicit deletion can remove content.
- `conversation_selection`: owner scope, selected workspace/thread, revision and pause state. No grant/permit serialization.
- `conversation_projection`: thread/workspace summary and structured state, source event IDs, covered sequence and policy/model versions. Compare-and-swap publication prevents old work overwriting corrections.
- `conversation_entity_link`: workspace to existing canonical entity/assertion IDs with source event IDs. No duplicate personal-fact database.
- `conversation_outbox`: transactionally queued projection/index work, source sequence, revision, retry state and idempotency key.
- `conversation_tombstone`: deleted scope/generation and minimal non-content identifiers, blocking resurrection by queued work.

Use full-text search over eligible archived event text in the same encrypted database, alongside existing personal-fact retrieval. Existing embedding infrastructure is optional and only used where vectors exist. A provider receives bounded, authorized evidence, never raw database access.

## Recording and failure contract

Introduce an awaitable required recorder separate from best-effort observers. Once a final canonical turn is accepted, archive it under an immutable routing receipt, commit its outbox item, and obtain a durable receipt before dispatching its substantive reply. Preserve original transcript text when policy permits; store an omission marker when existing content policy blocks retention. Do not silently present a partial archive as complete.

This requires a conversation-retention authority scope: current plan-only learning permission is not automatically permission to retain arbitrary dialogue. Extend the existing approval/permit owner with `memory:conversation_history`, scoped to owner/workspaces, supported by current unlocked-session authority. Local persistence and provider release remain distinct permissions. No additional per-turn consent prompts once authorized. Lock/revoke stops new writes/releases; no stored handle is authority after restart. Existing excluded-secret handling remains enforced and omission is visible.

If recording fails, keep the turn pending in memory, report unsaved status, and do not claim continuity or dispatch a context-dependent response. Retry the same event ID, never create a second event. Pending RAM cannot survive a hard crash: promise only data with a committed receipt, and expose last committed sequence. No waiting for sleep to flush the main archive.

Tool intent/results are archived through a separate tool-event adapter, correlated with the request. An interrupted assistant response is stored as interrupted/partial and never as fully delivered or an executed action.

## Mandatory response context

`WorkspaceConversationCoordinator.prepare_reply` performs selection, durable turn recording, current-state lookup, relevant personal-fact lookup and bounded source retrieval before model generation. Model-selected save tools cease being the primary history path.

The packet contains active IDs/revisions, recent messages, latest eligible project projection, uncovered tail after that projection, selected original source excerpts, relevant canonical personal facts, conflicts/missing information and source references. A stale/failed summary cannot hide recent unsummarized events. For current facts, explicit corrections/validity outrank similarity scores. Historical queries can intentionally retrieve superseded values with dates.

Proposed initial budget: 6,000 estimated text tokens for external memory per answer, with 1,200 reserved for recent/uncovered turns, 1,200 for project state, 1,200 for personal facts, and 2,400 for source excerpts. Unused budget is shared; truncation and uncovered ranges are explicit. Use a calibrated token estimator, not an unqualified character count. A missing answer triggers bounded deeper archive paging inside the same request, up to two additional pages within that 6,000-token budget. Never translate failed/partial retrieval into “you never told me.” Thresholds are tunable acceptance parameters, not claimed optima.

Revalidate selection, source generation, suppression and authorization before provider dispatch and audio release. A newer utterance/switch invalidates the previous request. The existing response/audio protection remains authoritative.

## Voice transport qualification: first engineering gate

Before implementing a full voice rollout, construct a pinned-SDK transport contract test that proves (a) final transcript acceptance, (b) archive commit, (c) context delivery, and (d) response generation in that exact order, without an optional model-selected tool. Test two turns, a workspace switch, an interruption and a new transport session.

Primary path: current native realtime transport only if it demonstrably supports application-controlled response dispatch and context loading under its actual configuration. Do not merely buffer audio after the model has already generated an uninformed answer. Inspect the pinned adapter and existing guarded handoff before changing it.

Predetermined fallback if that contract cannot pass: workspace conversations use an explicit STT -> text LLM -> TTS pipeline controlled by the same coordinator. General existing voice remains available. Select compatible STT/TTS using existing configured credentials and installed adapters only after a capability probe; never silently enable a new billable service or change provider accounts. If no compatible configured pipeline exists, complete text acceptance and present the exact missing voice capability/provider requirement. That is a bounded integration decision, not another memory-engine comparison.

## Consolidation, personal context and inspectability

Archive writes never wait for extraction. An outbox worker builds source-linked project summaries/state and proposes durable personal facts through existing learning admission. It processes increments, retries provider failures, and cannot publish after source correction/deletion/permission changes. Persistent read-your-writes comes from the uncovered archive tail, not waiting for the worker.

Add an authenticated workspace view to the existing UI: active workspace, threads, timeline, current decisions/tasks, last committed sequence, projection coverage and pending/error state. Personal memory remains separately inspectable. Logs include request/event IDs, write receipt, selection, retrieval IDs and dispatch revision; no unredacted transcript logging by default. An explicit local diagnostic mode can show policy-cleared excerpts.

The existing UI server is a read-only loopback projection, not an authenticated private-history interface. Host-header validation is not owner authentication. Keep private history out of its general snapshot/event feed. The workspace view needs a dedicated current-owner-grant check on every read and a short-lived browser view session bound to that live grant; revoke/lock clears the view session and displayed history. A browser session is not a persisted authority grant. Destructive controls remain canonical voice/local controls in this release; existing UI POST/DELETE routes remain disabled.

Delete a conversation/project through canonical lifecycle: remove content, derived projections/indexes/entity links, invalidate caches and cancel outbox work in the same lifecycle transaction. Test removal and non-resurrection; do not claim that logical deletion proves forensic erasure from backups or SQLite free pages. Do not fabricate old transcript content from existing checkpoints: import only their existing fields as labelled legacy state.

## Acceptance and rollout

All values below are proposed release gates, not measured results.

- Deterministic archive/routing tests: 100% of 200 accepted eligible fixture turns are accounted for across 10 workspaces, 30 transport segments, duplicate callbacks, restart and injected write failure. Retained events and explicit policy omissions must reconcile exactly with receipts.
- Zero wrong-workspace source releases, stale corrected facts used as current, deleted content resurrection, assistant-suggestion promotion, or unverified completion claims in the release suite.
- Model evaluation: 60 frozen development questions and 40 held-out questions covering direct/indirect recall, corrections, cross-project entity links, time, unknowns, ASR ambiguity and mixed Hindi/English. Target at least 95% source-supported correctness on each set, with every critical boundary case passing. Preserve all failures; do not tune on held-out answers or treat this finite score as universal reliability.
- Performance on the same Windows machine/model/network: archive commit p95 <=100 ms, local context preparation p95 <=300 ms excluding provider/STT/authentication; report sample count, cold/warm runs, prompt tokens, provider calls and transcription/end-of-speech to first-audio latency. Target <=3 s p95 for simple warm recall and record failures instead of concealing wait time with filler. Failure of a target triggers measurement-led adjustment, not a success claim.
- Native acceptance: Nepal discussion -> sleep -> resume -> switch to interview -> restart -> named Nepal status -> correction -> inspect sources -> forget -> restart. Logs must show every stage, not just `ready`.
- Test first in the isolated source/profile. Keep `E:\Jarvis\App` unchanged. Existing main/profile activation follows successful evidence and owner acceptance.

## Explicit limits

Public product behavior demonstrates feasibility, not disclosure of ChatGPT/Gemini/Copilot internals or proof of perfect recall. This plan specifies a Jarvis implementation of the required behavior; it does not claim to copy their private architecture. Research and component tests are reused. New tests cover changed capture/routing/provider integration only.

Builder review: a fresh software-engineer reviewer found no important unanswered design questions. UI integration was subsequently clarified against the inspected read-only server: private archive data requires a dedicated authorization boundary and cannot enter the public projection feeds.
