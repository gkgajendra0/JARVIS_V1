# Semantic conversational-state integration — 29 October 2026

## Status

Candidate components:
- `src/jarvis/memory/conversation_semantics.py` — canonical grounded reducer
  with an epoch/turn-order fence.
- `src/jarvis/memory/semantic_pipeline.py` — bounded async ingestion that
  requires a rotating authorization binding; no additional wait on the
  synchronous accepted-turn callback.
- `tests/test_conversation_semantics.py` and
  `tests/test_semantic_pipeline.py` — focused behavior and concurrency tests.

These components are **not enabled** in production. Do not merge this draft as a complete conversational-intelligence
fix.

This branch starts from merged main `488954a6`. A prior, uncommitted isolated
checkout called `feat/conversational-intelligence-v1` was described in chat,
but its bytes are not on GitHub and cannot be assumed present here. Reconcile
any recoverable changes before overlapping voice/session/persistence edits.

## Contract

- Voice owns canonical accepted USER turns. Assistant output, provider proposals,
  wake false triggers, and interruptions cannot silently become owner statements.
- The semantic extractor can propose topic, goal, constraint, pending step,
  correction, completion, and forget operations. The reducer validates exact
  evidence spans and original canonical turn identity.
- Literal support is distinguished from semantic interpretations. Neither proves
  that upstream speech transcription was accurate.
- The reducer holds only bounded **transient** state. No direct provider calls,
  SQLCipher writes, plaintext filesystem writes, or model-context release.
- Every actual release requires existing owner-read authorization, source binding,
  sensitivity checks, and one-response retirement where applicable.
- An unlocked runtime session is not sufficient authorization for every new
  protected memory read.
- Named-topic resumption after a new wake must be explicit; do not proactively
  replay old history or unrequested private context.
- Durable checkpoints, if retained, must use the existing encrypted canonical
  memory authority, including transactional forget/suppression and in-flight
  write cancellation. Do not duplicate or bypass that layer.

## Remaining engineering work (not done)

1. Reconcile earlier uncommitted continuity/checkpoint code, or reproduce its
   behavior on this source revision with regression-first changes.
2. Add a provider-independent parser for structured semantic proposals and a
   typed adapter to the existing realtime model/tool pipeline. Do not add a
   blocking extraction model call to every spoken turn.
3. Feed permitted current-user turns into the fast conversation path immediately,
   independent of asynchronous permanent-memory extraction.
4. Assemble bounded, authorized topic state together with recent dialogue and
   relevant personal memories. Keep the evidence and interpretation distinct.
5. Enforce speaker/owner-session lock, revoke, expiry, protected response
   retirement, provider fallback, and interruption/epoch fences in the adapter.
6. Add cross-session and cross-restart source-backed named-topic resumption
   through encrypted checkpoints and same-transaction tombstones.
7. Expand semantic scope only after adversarial privacy cases and Hindi/Hinglish
   corrections pass; never rely solely on a list of sensitive keywords.
8. Fix actual voice quota/microphone issues separately so provider failures
   cannot contaminate conversational testing.

## Required tests

- Seven-turn Nepal conversation: Jimny, permits sorted, unrestricted budget,
  route planning, correction, and continuation.
- Same live thread; deliberate protected-response retirement; transport
  reconnect; separate wake without topic; explicit Nepal resume; process restart.
- Conflicting dates, low-confidence ASR transcript, Hindi/Hinglish corrections,
  a completed task, a forged assistant claim, and stale async proposals.
- Forget versus in-flight save, category suppression then re-enable, Windows lock,
  failed Hello, denied read, and no private replay after consent retirement.
- Benchmark p95 added context overhead **after implementation**, before broader
  owner voice acceptance, per owner direction.

## Rollout gate

Do not merge until scoped and whole-repository automated tests pass on the exact
head, Windows SQLCipher/DPAPI authority checks pass, and the owner accepts normal
Gemini Live conversation behavior. Do not assert production readiness from this
module's unit tests alone.

## Runtime wiring specification

The production integration point is `LiveKitConversationBridge.add_accepted_turn_observer`.
Attach `SemanticTurnPipeline.submit` only after canonical user-turn acceptance
and after a trusted, revocable owner authorization binding is available.
The configured producer must emit `SemanticProposal` objects, not write
memory. It must not block the accepted-turn callback. Do **not** use a raw
Windows username as the binding. It needs to change when owner authority
rotates and be invalidated immediately upon lock, revoke or protected response
retirement.

The pipeline enforces an epoch fence both before and after the asynchronous
producer completes. It does **not** currently expose any state to a model:
a separate gated adapter must use `ContextAssembler`, retain original
source IDs, apply field sensitivity classification, and respect one-response
protected-answer retirement.

A brief authenticated follow-up may reuse the current working thread as
authorized; a new wake-up must not inject the prior conversation until the
owner explicitly names the topic. For cross-day resumption use encrypted
checkpoint storage only, with fresh question-bound read consent and transactional
forget. No plaintext checkpoint fallback is permissible.

**Important:** A model-proposed value that quotes a canonical speech transcript
is grounded to that transcript, not independently verified against the audio.
The Jimny/Gemini misrecognition therefore remains a separate ASR integrity
problem; critical names/dates require reconciliation or confirmation before
durable promotion. This semantic reducer cannot solve it alone.


## 29 October continuation — code now present on draft PR #303

Implemented after the initial isolated reducer:
- \`MemoryRuntime.topic_checkpoints\` shares the canonical writer and reader
  workers, existing SQLCipher key and migration ledger; no second database.
- \`0004_conversation_topic_checkpoint.sql\` plus guarded checkpoint
  save/read/forget, a trusted snapshot admission callback, and commit-time
  rechecks of the canonical turn, owner permit, and privacy admission.
- \`read_named_snapshot()\` reconstructs an explicitly grounded, standard-
  sensitivity typed topic state from a named read, preserving the checkpoint
  revision source and time rather than treating the new request as provenance.
- \`current_fingerprint()\` invalidates protected topic responses after
  correction, overwrite, forget or plan-category suppression.
- \`SemanticContextProjector\` assembles a bounded model-context packet only
  after a named-topic question and independent authorization.
- \`SemanticVoiceAttachment\` is connected as an **optional** accepted-turn
  observer in \`CanonicalActiveSpeakerRuntimeController\`. It is disabled
  without explicit injected source-cleared producer and rotating owner binding,
  and it revokes transient state on bridge close.
- \`PersonalContextSession.resume_topic()\` and the conditional
  \`resume_conversation_topic\` function tool reuse existing fresh
  question-bound memory consent and protected audio lifecycle, with
  before/after snapshot-revision checks. The controller's
  \`semantic_topic_resume_enabled=False\` default keeps the feature off.

### Still mandatory before activation or merge

1. **No producer is configured by default.** An actual approved routed
   semantic inference client and trusted independent source-clearance
   classifier must be bound to the voice runtime; model sensitivity labels
   do not grant release or storage permission.
2. **No automatic checkpoint write is enabled.** The canonical learning
   authority must issue source-bound write permission, and the checkpoint
   admission callback must consult live plan suppression. The forget/control
   path must atomically invalidate queued saves and commit tombstones.
3. Voice follow-ups across deliberate protected-session retirement need a
   bounded, owner-authorized work-state handoff. Separate wake-ups must
   require topic mention; never automatically replay old private context.
4. Source revision and authorization must also be rechecked at actual
   provider/audio release; current topic tool leverages the normal protected
   response checker but requires native Windows qualification.
5. Full CI / Windows SQLCipher smoke / private owner voice acceptance are
   pending for exact final commit. Existing smoke/migration assertions were
   updated for schema v4; do not infer readiness from older commits.
6. Only after implementing these gates: benchmark latency, then run normal
   owner-spoken seven-turn Nepal acceptance and expanded adversarial tests.
