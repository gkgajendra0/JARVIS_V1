# Project Conversation Memory — build plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement task-by-task. Current pass is documentation only; implementation awaits the owner's next instruction.

**Goal:** preserve named project conversations and relevant personal context across sleep, restart and project switches, without adding a separate memory-model request by default.

**Architecture:** existing Gemini interprets/answers; an awaited recorder appends canonical events to existing encrypted workers; stable project/thread routing and source-aware retrieval prepare context before generation. Keep all successful current authority, lifecycle and voice protections.

**Tech Stack:** existing Python 3.11, LiveKit/Gemini, SQLCipher/DPAPI, local retrieval, pytest. No new model or memory service selected.

**Spec:** [implementation contract](../../PROJECT_CONVERSATION_MEMORY.md). It owns product semantics, bounds and proposed acceptance targets.

## Global constraints

- Reuse existing canonical SQLCipher connection/key; no plaintext fallback or serialized grants.
- Record accepted eligible source turns independently of model-selected memory updates.
- Preserve original event identity/order, including identical text at different times.
- Stable thread/project identity is distinct from a transport session and survives retirement/sleep/restart.
- Preserve existing personal-memory sources/currentness and correction/forget/authority boundaries.
- Zero standalone cloud extraction/query-planning/background-summary calls by default.
- External memory <=6,000 estimated text tokens; default <=one archive search plus one deeper source read per request.
- Model/query/schema validity is not permission or factual correctness.
- Keep installed checkout and settings unchanged; use the isolated source/profile.
- Reuse prior technology evidence. No new vendor/model sweep, paid test expansion or dependency upgrade without a concrete need.

## Review focus

- Late transcripts/proactive generation must not produce answers before actual context delivery.
- Silent best-effort observer failure must not be mistaken for a durable commit.
- Delayed assistant/tool callbacks remain in the original project after a switch.
- Corrections/forget/revoke invalidate pending retrieval, inference and audio.
- A missed update, stale summary or failed search must not hide original history or be called true absence.

## Task 0: Pin the transport contract and implementation seam

**Files:** `tests/test_project_memory_transport.py` (new), `docs/research/PROJECT_MEMORY_TRANSPORT_CONTRACT.md` (new); inspect `voice/livekit_session.py`, `context_sync.py`, `gemini_transport.py`, `personal_context.py` and the installed pinned adapter.

**Interface:** `dispatch(prepared_reply: PreparedProjectReply)` must expose a request ID and context revision. Task 1 defines the production packet type; use a fixture type here until then.

- [ ] Add a failing ordered-event test requiring `transcript_accepted -> archive_committed -> context_delivered -> generation_started -> audio_released`, plus transport recreation, interruption and switch invalidation. Buffering already-generated uninformed speech fails this contract.
- [ ] Run `python -m pytest tests/test_project_memory_transport.py -q -o addopts=''`; distinguish the current reproduced failure from missing test infrastructure.
- [ ] Inspect pinned native capabilities and record one qualified path. Use the spec's controlled speech/text/TTS fallback only if the native path cannot pass. Record credential/SDK limitations precisely; do not resolve them by silent model/account upgrades.
- [ ] Commit the contract/seam and findings. No declaration of live qualification from fake transport output.

## Task 1: Durable source archive and required recorder

**Files:** new `memory/project_conversations.py`, `memory/project_conversation_store.py`, `memory/migrations/0005_project_conversations.sql`, `tests/test_project_conversation_store.py`, `tests/test_project_conversation_recording.py`; modify `memory/runtime.py`, `voice/livekit_session.py`, `tests/test_memory_migrations.py`. Add scoped history permission through `authority/conversation_history.py`, `authority/service.py`, `capabilities/runtime.py` if the current issuer does not authorize the explicit history scope. Do not widen plan permission silently.

**Interfaces:** frozen `ProjectSelection(project_id: str, thread_id: str, revision: int)`, `ConversationReceipt(event_id: str, thread_id: str, sequence: int, revision: int, status: str)`, `PreparedProjectReply(request_id: str, selection: ProjectSelection, source_ids: tuple[str,...], context: str, revision: str, estimated_tokens: int)`. Async `ProjectConversationStore.append_event(selection, event, *, permit, expected_revision) -> ConversationReceipt`; async `RequiredConversationRecorder.record(conversation, turn, routing_receipt) -> ConversationReceipt`.

- [ ] RED tests: schema-4 migration/reopen, separate identical-text events, duplicate callback idempotency, tool/partial-assistant roles, transaction rollback, failed-write status and revoke during commit.
- [ ] Run `python -m pytest tests/test_project_conversation_store.py tests/test_project_conversation_recording.py tests/test_memory_migrations.py -q -o addopts=''` and verify expected failures.
- [ ] Implement the spec's four tables on canonical workers, durable receipt/revision and awaited recorder. Verify migration numbering against current branch before creating it. Bind events to immutable request selection, not latest global selection. Keep optional observers separate.
- [ ] GREEN tests; verify storage failure prevents dependent dispatch and never reports saved. Commit.

## Task 2: Project routing, persistent thread selection and local memory tools

**Files:** new `memory/project_routing.py`, `voice/project_memory_tools.py`, `tests/test_project_routing.py`, `tests/test_project_memory_tools.py`; modify `voice/canonical_active_speaker_runtime.py`, `voice/agent.py` and the selected transport seam.

**Interfaces:** async `ProjectRouter.resolve(conversation, turn, *, proposed_name=None) -> ProjectRoutingDecision`; async `commit_selection(decision, *, permit, expected_revision) -> ProjectSelection`. Typed tool methods `search_conversation_memory(project_id, query)` and `read_conversation_sources(source_ids)` consume current server-owned request/scope binding. Search results carry eligible source IDs, dates, revisions and coverage status.

- [ ] RED tests: Nepal follow-ups, General default, exact alias, duplicate trips requiring clarification, explicit switch command routing, retirement versus sleep, restart/reauthorization, and late callbacks pinned to original request.
- [ ] Run `python -m pytest tests/test_project_routing.py tests/test_project_memory_tools.py -q -o addopts=''` to confirm the missing behavior fails.
- [ ] Implement stable IDs, atomic selection changes, strict scope filtering and bounded archive search using existing retrieval components with an event adapter. Give Gemini concise project tools/instructions; never accept arbitrary SQL/file paths or model-chosen unauthorized scope. Preserve recent selected-thread context when no search is needed.
- [ ] GREEN tests including project-source isolation and duplicate-text history; commit.

## Task 3: Context-before-answer, personal facts and grounded state

**Files:** new `memory/project_context.py`, `voice/project_conversation.py`, `tests/test_project_context.py`, `tests/test_project_memory_delivery.py`; modify `voice/personal_context.py`, relevant provider/audio protection and existing learning reconciliation only where required.

**Interfaces:** async `ProjectConversationCoordinator.prepare_reply(conversation, turn, *, routing_receipt, authorize) -> PreparedProjectReply`; `validate_current(packet) -> bool` checks current request, project/source/personal versions and authority before dispatch/audio. Source-linked state updates use existing admitted proposals; archive history remains the fallback.

- [ ] RED: exact provider payload includes saved Nepal details without structured update proposals; restart and project switching restore the correct sources; shared personal vehicle fact does not import interview history; correction invalidates old response; denied/failed/partial retrieval is distinct from no-match.
- [ ] Run `python -m pytest tests/test_project_context.py tests/test_project_memory_delivery.py tests/test_project_memory_transport.py -q -o addopts=''`; confirm expected failures.
- [ ] Implement bounded recent/uncovered history, current optional project state, source excerpts and relevant canonical personal context. Enforce token/search bounds and usage accounting; keep separate extraction disabled. Do not promote assistant suggestions, hypothetical rentals or tool intent to confirmed facts/actions.
- [ ] Connect awaited capture -> router -> context -> qualified dispatch -> guarded audio. Recheck on switch/new speech/correction/forget/revoke. Actual provider payload is the test assertion, not merely a local packet.
- [ ] GREEN tests; commit. A synthetic transport test is not a real Gemini quality pass.

## Task 4: Inspection, correction/forget integration and isolated entrypoint

**Files:** new `memory/project_controls.py`, `voice/project_memory_lab.py`, `tools/windows/Start-JarvisProjectMemoryLab.ps1`, `tests/test_project_memory_controls.py`, `tests/test_project_memory_lab.py`, `docs/project-memory-acceptance.md`; modify canonical memory lifecycle and existing lab helpers only as needed.

**Interfaces:** async `inspect_project(project_id, *, authorize) -> ProjectInspection`, `forget_project(project_id, *, expected_revision, permit) -> DeletionReceipt`. Inspection reports source timeline, selected thread, committed sequence, coverage and omissions/failures.

- [ ] RED: inspect active project/sources, pause retention, correction/current-versus-historical query, forget/restart, late-write non-resurrection, independent personal facts survive, and legacy checkpoint import does not fabricate transcript.
- [ ] Run `python -m pytest tests/test_project_memory_controls.py tests/test_project_memory_lab.py -q -o addopts=''`; confirm missing behavior fails.
- [ ] Implement authenticated local/voice inspection and canonical lifecycle. Keep private history out of existing unauthenticated UI projection feeds. Use isolated marked profiles and exact clean source commits; launcher never changes the installed checkout or fetches implicitly.
- [ ] GREEN tests; commit. Full private-history dashboard remains deferred.

## Task 5: Acceptance, cost/latency evidence and review

**Files:** new `tests/project_memory/` deterministic and model-evaluation fixtures, update `docs/project-memory-acceptance.md`, `docs/PROJECT_STATE.md` and `docs/CURRENT_PLAN.md` with actual evidence.

- [ ] Freeze the spec's 200-event/10-project/30-segment replay plus fault injection. Run `python -m pytest tests/project_memory/ -q -o addopts=''`; require all integrity/boundary cases to pass.
- [ ] Freeze 60 development and 40 held-out source-labelled model questions before any inference. Use existing authorized provider access only; no paid budget expansion follows from this document. Record unavailable/unrun cases instead of synthetic success.
- [ ] Run scoped existing learning, memory, conversation, semantic and provider-guard tests plus Ruff and migration/Windows SQLCipher CI. Do not retry or indirectly bypass the rejected telemetry-triggering full-suite command. Record unrelated failures separately.
- [ ] Measure actual request/token/audio counts, cold/warm local/provider stages and proposed latency targets. Record sample counts, baseline comparison, errors and held-out source correctness. Do not promise savings from local persistence alone.
- [ ] Request one independent final review; reproduce/fix important findings. Publish draft changes with an expected-head lease and exact-head CI evidence.
- [ ] Owner-machine acceptance executes the full spec sequence with stage diagnostics. Keep merge and installed activation separate; only mark each goal accepted when its evidence exists.

## Status and handoff

Documentation-only cleanup is complete when these documents, navigation, preserved research and PR scope agree and are committed/published. No build checkbox is complete yet. The owner's next instruction starts Task 0 inline in the isolated worktree. Do not reopen provider/backend/model selection without recording a concrete blocker against this contract.
