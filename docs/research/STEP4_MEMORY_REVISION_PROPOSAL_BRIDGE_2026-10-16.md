# Step 4.4 — From structured utterance proposals to canonical review (2026-10-16)

**Status: draft research, offline synthetic-only verification. No activation.**

## What this changes
The existing provider-backed `MemoryExtractionProposal` already has typed
`intent`, `candidate_type`, `subject`, `predicate`, `value`,
`durable_candidate` and `sensitivity` fields. Prior research built an
isolated `CanonicalRevisionSnapshotReader` that can verify current assertion
identity, source provenance and lineage in synthetic canonical-schema SQLite.

`review_extracted_revision_shadow()` connects these *actual type contracts*
without constructing an extractor, calling a provider, reading memory values,
opening any production database or mutating any record:

1. Require accepted direct owner input and normal-sensitivity model proposal.
2. Apply existing `MemoryCandidatePolicy` pre-admission gating.
3. Recognize only agreed `intent + candidate_type` combinations, not the
   provider's free-form text as authoritative metadata.
4. Restrict resolved subject to `owner` and target scope to `personal`.
5. Normalize a supplied predicate through the existing
   `canonical_memory_predicate`, then look up *metadata only*.
6. Reject missing/untrusted/stale/sensitive provenance and return no source
   references or stored memory values.
7. For an eligible, unambiguously current correction, return
   `CONFLICT_REVIEW`. For missing or ambiguous target, return
   `NEEDS_CLARIFICATION`. For an unanchored new candidate, return `REVIEW`.

Importantly, the model-proposed predicate is still a **hint**, not
independent proof that the natural-language utterance referred to this
existing memory. The reviewer cannot grant write permission or inject context.

## Offline synthetic test coverage
Existing SQLite lifecycle fixtures establish a small versioned correction
chain. New bridge tests submit typed proposals to that fixture:
- historical change, correction and retraction all become review-only for
  a valid unique target;
- a correction with no canonical target becomes clarification, not update;
- a new fact without existing target can be reviewed, not stored;
- two active assertions for the same exact key become clarification;
- private canonical assertions are not used for review;
- unaccepted turns, external content, non-durable proposals, inconsistent
  intent/type pairs and attempts to select another person never open
  a canonical reader.

**None of these assert improved model accuracy.** The proposed
`MemoryExtractionProposal` objects in tests are authored locally, rather
than extracted by Gemini from multilingual utterances.

## Gap before semantic conversation comprehension
The 18-case historical development evaluation exposed missed Hindi
semantic duplicates, Hinglish preference changes, English retractions and
unanchored corrections. This bridge cannot fix a model that returns
`NONE` or `TRANSIENT` before a valid review proposal is produced.
A next-stage evaluator must use *freshly authored, separately held out*
English, Hindi and Hinglish user turns, measure extractor recall with
no-gold-input prompts, and distinguish typed revision intent from a trusted
target match. Every cloud test needs explicit owner opt-in and free-tier
request accounting. No label tuning against the already exposed c11/c12/c13/c18.

Memory-store admission, owner confirmation, mutation CAS/race checks and
answer-context release remain out of scope. Do not merge this research
to main or resume D8 on the strength of these tests.
