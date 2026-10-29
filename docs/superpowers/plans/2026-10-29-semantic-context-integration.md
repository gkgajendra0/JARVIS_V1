# Semantic conversational-state integration — 29 October 2026

## Status

Candidate implementation: `src/jarvis/memory/conversation_semantics.py` and
`tests/test_conversation_semantics.py`. Standalone reducer only; **not enabled**
in production. Do not merge this draft as a complete conversational-intelligence
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
