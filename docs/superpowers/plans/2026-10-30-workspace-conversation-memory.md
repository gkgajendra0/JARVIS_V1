# Workspace Conversation Memory Implementation Plan

**SUPERSEDED implementation proposal — 31 October 2026.** Do not execute this broader plan. Read the [current contract](../../PROJECT_CONVERSATION_MEMORY.md) and [31 October build plan](2026-10-31-project-conversation-memory.md). Preserve this proposal as history; no listed product implementation was performed by writing it.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve project discussions across sleep, restart and topic switches, with relevant source-linked personal context delivered before answers.

**Architecture:** Native encrypted conversation archive plus stable workspaces/threads, an application-controlled recording/context boundary, and asynchronous rebuildable projections. Reuse existing personal memory/retrieval and authority. Qualify the pinned voice transport before committing to its response path.

**Tech Stack:** Python 3.11, existing SQLCipher/DPAPI workers, LiveKit 1.8.3, configured Gemini/provider credentials, existing UI and pytest.

**Spec:** `docs/superpowers/specs/2026-10-30-workspace-conversation-memory-design.md` (proposed details awaiting review).

## Global Constraints

- No vendor bake-off or replacement canonical memory service.
- No second database/key or serialized authority handles.
- Keep `E:\Jarvis\App` unchanged until isolated acceptance.
- Automatic protected-response retirement must not close the durable thread.
- Application-controlled recording/context preparation must not depend on model-selected save tools.
- Conversation retention uses an explicit scope; do not relabel arbitrary dialogue as plan data.
- Only committed events are promised durable; unsaved/policy-omitted content is visible.
- Archive writes never wait for model extraction; source-linked projections are rebuildable.
- Preserve configured provider/account/budget boundaries. No silent new paid service.
- Proposed external-memory budget is 6,000 estimated text tokens; archive contents are not limited to that budget.

## Review Focus

- Delayed transcript and native proactive generation: prove generation occurs after context preparation.
- Protected retirement versus sleep/restart: durable thread IDs survive all three.
- New speech/switch during queued work: stale events/results cannot cross workspace boundaries.
- Correction/delete during consolidation: old workers cannot recreate or release obsolete content.
- Recording/provider failures: expose missing coverage and never claim an unsaved turn was saved.

## Task 1: Freeze transport and lifecycle contract

**Files:** Create `tests/test_workspace_transport_contract.py`, `docs/research/WORKSPACE_TRANSPORT_CONTRACT_2026-10-30.md`; inspect `src/jarvis/voice/livekit_session.py`, `context_sync.py`, `gemini_transport.py`, `gemini_live_model.py` and pinned installed adapter source. No runtime behavior change in this task.

**Interfaces:** Specify an awaitable `dispatch(prepared_reply)` boundary with an observable dispatch ID/revision. `PreparedWorkspaceReply` is defined in Task 2; contract fixtures can use a typed local fake until then.

- [ ] Add contract assertions: ordered events are `transcript_accepted`, `archive_committed`, `context_prepared`, `provider_dispatched`, `audio_released`; two successive turns and a new segment retain thread ID; switch invalidates prior response. Native generation before preparation is failure even if audio is muted.
- [ ] Run `python -m pytest tests/test_workspace_transport_contract.py -q -o addopts=''` against the existing transport adapter; preserve the expected failing capability result, distinguishing fake transport evidence from live-provider evidence.
- [ ] Record supported pinned APIs and a binary outcome: qualify native controlled dispatch or select the spec's controlled STT/text/TTS fallback. Record exact configured-adapter/credential prerequisites and unsupported capabilities. No SDK upgrade or extra service as an implicit fix.
- [ ] Commit the contract and capability evidence. End task with one selected integration path, not an unresolved choice.

## Task 2: Durable archive, authority and required recorder

**Files:** Create `src/jarvis/memory/workspace_contracts.py`, `workspace_store.py`, `src/jarvis/authority/conversation_history.py`, `src/jarvis/memory/migrations/0005_workspace_conversations.sql`; modify `memory/runtime.py`, `authority/service.py`, `capabilities/runtime.py`, `voice/livekit_session.py`; tests `test_workspace_store.py`, `test_workspace_recording.py`, `test_memory_migrations.py`.

**Interfaces:** Frozen dataclasses `WorkspaceSelection(workspace_id, thread_id, revision)`, `ArchiveReceipt(event_id, thread_id, sequence, revision, status)`, `PreparedWorkspaceReply(request_id, selection, source_event_ids, context, revision, estimated_tokens)`; integer revisions and UUID string identities. `WorkspaceStore.append_event(selection, event, *, permit, expected_revision) -> ArchiveReceipt` is async. `RequiredConversationRecorder.record(conversation, turn, routing_receipt) -> ArchiveReceipt` is async; it does not replace optional observers.

- [ ] Write failing tests for migration from schema 4, transaction rollback, duplicated source IDs, interrupted assistant events, tool events with request correlation, permission revoke before commit and process reopen. Assert a repeated callback returns the same receipt/sequence.
- [ ] Run `python -m pytest tests/test_workspace_store.py tests/test_workspace_recording.py tests/test_memory_migrations.py -q -o addopts=''`; confirm missing archive functionality fails.
- [ ] Implement spec tables using the existing reader/writer workers. Atomically append event, advance revision and queue outbox work. Integrate a distinct conversation-history grant with existing owner authority and canonical capability registry; do not accept a learning grant as unrestricted transcript authority.
- [ ] Add required async recorder boundary. Archive failures set unsaved state and prevent workspace response dispatch. Leave best-effort observers' existing unrelated behavior intact. Store policy omission events explicitly. Bind assistant/tool events to originating request selection, never whichever workspace is selected when a late callback arrives.
- [ ] Run the task tests to GREEN and commit the independently testable archive.

## Task 3: Persistent routing and lifecycle

**Files:** Create `memory/workspace_routing.py`; modify `voice/canonical_active_speaker_runtime.py`, `memory/runtime.py`; tests `test_workspace_routing.py`, `test_workspace_lifecycle.py`.

**Interfaces:** `WorkspaceRouter.resolve(request, *, current, proposed_name=None) -> RoutingDecision` (async); `RoutingDecision` has `status` (`selected`, `clarification_required`, `general`), optional selection, matched name and previous selection ID. `commit_selection(decision, *, expected_revision, permit)` is async and transactional with the routing event. `open_segment(selection, session_id)` and `close_segment(session_id, reason)` do not close threads.

- [ ] RED tests: Nepal follow-ups, switch command routing, General default, duplicate names, explicit aliases, two Nepal trips, automatic response retirement, sleep, restart with authorization, unnamed resume acknowledgement and stale switch race.
- [ ] Run `python -m pytest tests/test_workspace_routing.py tests/test_workspace_lifecycle.py -q -o addopts=''` to verify missing behavior fails.
- [ ] Implement stable IDs, normalized lookup and revision-bound selection. The LLM can propose a title/intent; the application validates against the accepted request and requires clarification for ambiguous selection. Persist the prior selection locally; do not persist grants.
- [ ] GREEN task tests, then commit.

## Task 4: Context preparation and provider dispatch

**Files:** Create `memory/workspace_context.py`, `voice/workspace_conversation.py`; modify `voice/personal_context.py`, `voice/agent.py`, selected transport from Task 1 and protected audio integration; tests `test_workspace_context.py`, `test_workspace_delivery.py`.

**Interfaces:** `WorkspaceConversationCoordinator.prepare_reply(conversation, turn, *, routing_receipt, authorize) -> PreparedWorkspaceReply` is async. It consumes archive receipts, routing decisions and canonical personal-fact projections. `dispatch(prepared_reply)` from Task 1 accepts only a current packet; `validate_current(prepared_reply)` checks selection/source/authority revisions again before audio.

- [ ] RED: exact provider payload includes Nepal's accepted vehicle/permit discussion; immediate next turn works with summarizer disabled; another project's unrelated messages are absent; a delayed transcript cannot bind to an earlier source; selection switch/revoke/correction invalidates queued dispatch/audio.
- [ ] Run `python -m pytest tests/test_workspace_context.py tests/test_workspace_delivery.py tests/test_workspace_transport_contract.py -q -o addopts=''`; preserve failures.
- [ ] Build bounded packets with recent/uncovered turns, project state, selected originals and existing eligible personal facts. Implement explicit coverage/missing flags and at most two additional source pages within 6,000 estimated tokens. Use full-text queries with workspace/owner filters; do not feed conversation events into the assertion retriever without an adapter.
- [ ] Wire required recorder -> router -> context -> qualified dispatch. Retire the model-selected topic update tool as the archive writer in workspace mode; keep legacy mode separate. Text and voice use the same coordinator. No unsupported `update_chat_ctx` assumption.
- [ ] GREEN tests and commit. This task's provider-payload assertion is mandatory; a coordinator return value alone is insufficient evidence.

## Task 5: Source-linked project state and personal links

**Files:** Create `memory/workspace_projection.py`, `workspace_outbox.py`; modify existing learning admission integration, `memory/learning_reconciliation.py` only where needed; tests `test_workspace_projection.py`, `test_workspace_personal_links.py`.

**Interfaces:** `WorkspaceProjectionWorker.process_next(*, authorize) -> ProjectionReceipt | None` is async; receipts include covered sequence and projection revision. `link_personal_assertion(workspace_id, assertion_id, source_event_ids, *, permit)` only references an existing canonical assertion; learning proposals still enter existing admission.

- [ ] RED: pending extraction does not lose recent context; worker retries are idempotent; old worker cannot publish after correction/delete; quoted assistant suggestions do not become owner facts; rental discussion does not become ownership; one confirmed vehicle can inform two projects without importing their chat histories.
- [ ] Run `python -m pytest tests/test_workspace_projection.py tests/test_workspace_personal_links.py -q -o addopts=''` and confirm missing functionality fails.
- [ ] Implement incremental outbox processing, source-backed summary/state and personal-link proposals. Publish using source generation and compare-and-swap. Record observed/valid times and explicit versus inferred status. Preserve existing canonical eligibility/correction semantics.
- [ ] GREEN tests and commit.

## Task 6: Inspection, deletion and legacy compatibility

**Files:** Create `memory/workspace_lifecycle.py`, `ui/workspace_view.py`, `tests/test_workspace_controls.py`, `tests/test_workspace_ui.py`, `voice/workspace_conversation_lab.py`, `tools/windows/Start-JarvisWorkspaceLab.ps1`; modify `ui/server.py`, `ui/runtime.py`, `ui/assets/index.html`, `ui/assets/ui.js`, `ui/assets/ui.css`, `memory/lifecycle.py` and existing lab helpers.

**Interfaces:** `inspect_workspace(workspace_id, *, authorize) -> WorkspaceInspection`; `forget_workspace(workspace_id, *, expected_revision, permit) -> DeletionReceipt`; both async. Inspection returns source timeline, state, committed sequence and projection coverage. Delete consumes the same scoped lifecycle permit and emits a tombstone generation.

- [ ] RED controls: show active project, enumerate threads, show stored sources, report unsaved/omitted turns, pause/resume retention, delete and restart, queued-worker non-resurrection, and import legacy checkpoint fields without invented transcript. UI tests deny private history without live owner authorization, clear on lock/revoke, and assert ordinary snapshot/events contain no archive text.
- [ ] Run `python -m pytest tests/test_workspace_controls.py -q -o addopts=''`; confirm missing behavior fails.
- [ ] Implement voice commands and dedicated grant-bound UI timeline/status reads in `ui/workspace_view.py`; do not treat loopback Host validation as authentication or add history to general snapshot/event feeds. Keep destructive HTTP routes disabled. Delete content, derived rows and index entries transactionally; invalidate caches and queued jobs. Preserve facts independently supported outside the deleted project. Expose that backup/forensic purge is separate from logical deletion.
- [ ] Add isolated `workspace_conversation_lab` entrypoint/launcher using existing lab root isolation and resume conventions; never change installed checkout automatically.
- [ ] GREEN tests and commit.

## Task 7: End-to-end evidence and release gate

**Files:** Create `tests/workspace/` contract/evaluation fixtures, `docs/workspace-conversation-acceptance.md`; extend CI with a scoped test job using existing dependency provisioning. Record model evaluations separately from deterministic tests.

**Interfaces:** Evaluation output includes case ID, expected sources, committed IDs, selection, retrieved IDs, actual dispatched revision, answer assertions, stage latency, provider calls/tokens, and failure reason. Store owner transcripts only in the isolated protected profile; commit synthetic fixtures and redacted aggregate evidence only.

- [ ] Add 200-turn/10-workspace/30-segment deterministic replay, fault injection and crash/reopen cases. Run `python -m pytest tests/workspace/ -q -o addopts=''`; require complete accounting and zero critical scope/correction/delete/completion violations.
- [ ] Freeze 60 development and 40 held-out model questions with source-supported grading before inference. Synthetic model tests require configured provider availability/budget; do not represent fake transports as actual model results. Reuse previous technology experiments instead of rerunning them.
- [ ] Run focused existing memory, learning, semantic, provider-guard, conversation and workspace suites, Ruff, migration and Windows SQLCipher CI. Do not retry/bypass the previously rejected telemetry-triggering full-suite command; use scoped safe checks and hosted CI.
- [ ] Measure proposed acceptance targets from the spec on the owner's Windows machine: storage/context p95, cold/warm reply latency, usage, source correctness and native restart script. Never claim unmeasured targets are achieved.
- [ ] Request one independent final review; fix important findings with reproducing regressions. Publish draft branch with expected-head lease and exact-head CI evidence. Keep installed activation blocked until actual acceptance passes.

## Self-review and execution status

Spec coverage: recording/authority (2), selection/lifecycle (3), retrieval/provider timing (1/4), consolidation and cross-project personal facts (5), inspect/delete/migration compatibility (6), quality/latency/native acceptance (7). Each review-focus failure has an owning test task. No product code has been changed by this plan.

Fresh builder review found no important unanswered questions. Self-review made UI paths concrete and required private-history authorization separately from the existing read-only projection server.

Remaining decisions are explicitly bounded: owner review of retention/product semantics and proposed release targets; Task 1 selects the supported voice dispatch path using actual pinned capabilities. No repeat vendor experiment is a dependency. Execution remains inline in the isolated worktree, consistent with prior session preference.
