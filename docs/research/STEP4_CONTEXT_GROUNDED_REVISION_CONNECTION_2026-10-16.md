# Step 4.4 — Context-grounded revision research connection (2026-10-16)

**Draft, offline synthetic-only. No owner-machine deployment, Gemini quota,
production SQLCipher access, autonomous memory updates, memory-context
injection, Jev routing, or D8 activation.**

## What was already working

- Core encrypted SQLCipher/DPAPI durable storage and explicit remembers
  were accepted on the owner's Windows machine in Step-4 evidence.
- The existing Qwen3-Embedding and Qwen3-Reranker retrieval stack already
  has baseline measurements; do NOT benchmark or replace them again.
- The incumbent `MemoryExtractionProposal` and Gemini/OpenAI native schema
  adapters already extract single utterances.
- Draft research PRs #264–266 validate review-only typed revision decisions,
  current canonical metadata/source lineage, and proposed predicate matching.

## This PR: the narrowly missing connection

One new `contextual_revision_shadow` research coordinator composes:
1. One **canonical accepted latest owner turn** from
   `ConversationSession`/`ConversationTurn`, rejecting invalid,
   interrupted/other-source, explicit memory-control, secret or oversized
   content before a model call.
2. Up to three recent **accepted USER-only** prior turns (assistant
   messages cannot become owner evidence), filtering explicit controls,
   locally recognizable secrets and long material.
3. Up to three **existing `RetrievalCandidate`** objects (expected
   from the already accepted Qwen/FTS5 retrieval path, not recomputed
   here). Only standard-sensitivity, active, `personal/owner`, bounded
   text values are eligible.
4. Each retrieval's assertion ID is checked against the existing
   **read-only canonical metadata and provenance resolver**. A stale,
   sensitive, untrusted, duplicate or mismatched target is rejected
   before any contextual model call.
5. A deliberately **opt-in**, injectable `extract_contextual` method
   interprets the current turn in this bounded context. Its structured
   proposal is again gated against the verified retrieval predicate
   allowlist and PR #266's canonical review-only policy. A model's
   ungrounded target always needs clarification; it cannot select
   an arbitrary other predicate.
6. The returned object contains **disposition + reason code only**,
   never the retrieved memory value, an update command, or an assertion ID.

The opt-in adapters subclass our existing native
`GeminiMemoryCandidateExtractor`/`OpenAIMemoryCandidateExtractor`,
reuse exactly `MemoryExtractionProposal`, `store=False`, and native
structured-output clients. Their contextual prompt explicitly treats past
turns as data rather than commands and requires the new value to be
supported by the *current* utterance.

The existing plain `extract(text=...)` runtime behavior stays unchanged.
No factory or producer in live memory/voice routes imports this module.

## Tests and limits

Offline synthetic SQLite tests use existing `MemoryLifecycleService` and
`CanonicalRevisionSnapshotReader` with a separate query-only reader.
Fake-client tests exercise the actual Gemini Interactions/OpenAI Responses
request schemas without making a network call.

These tests demonstrate **plumbing and defensive fail-closed controls**;
they do NOT measure model semantic understanding. In particular:

- The module **accepts caller-selected retrieval candidates**; it does
  not independently choose which memories matter. A retrieval ranking
  miss can still cause `NEEDS_CLARIFICATION`.
- A caller's retrieval object could be inconsistent with the canonical
  **value** despite matching ID; the metadata resolver does not
  independently read value text. This limits the contract to trusted,
  internal retrieval results. A future production integration needs
  an atomic or otherwise authoritative content-binding proof.
- Sensitive/private/local-only facts cannot be sent through this
  research helper even if cloud access is otherwise allowed. Recognition
  of complex secrets is not proven exhaustive; input must be sanitized
  before any external model test.
- Explicit owner-command recognition uses the existing 4.3 heuristic.
  An informal correction containing "galat" or "wrong" could be
  classified as explicit control; the ownership and policy boundary
  needs a separate study rather than bypassing explicit-memory checks.
- Concurrent memory changes after the resolver's snapshot need recheck
  in the authoritative writer transaction before a future mutation.
- Existing Gemini extractor's exposed 18-case tests are already
  development evidence; do not recycle them as unseen acceptance data.
- Before future provider evaluation, get explicit owner approval, a
  new blinded corpus and narrow synthetic-only egress permission.
- Until all these independent gates pass, no passive context release,
  durable automatic admission or production voice activation is allowed.

## Engineering status

Research seam only, **off by default** (`allow_model_calls=False`).
Run the new deterministic regression tests and repository Code Quality CI.
A green CI proves syntactic correctness / contract behavior in mocks,
not improved Hindi/Hinglish memory accuracy.

Next independent milestone: prove that relevant retrieval candidates
are actually selected and semantic correction detection improves on
**new** owner-held cases with strong no-memory/no-context baselines.
