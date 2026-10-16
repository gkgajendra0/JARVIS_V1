# Step 4.4 content-bound contextual review (2026-10-16)

**Research-only / draft / no production path or owner private-data use.**

PR #267 demonstrated a bounded, opt-in connection from already existing
`ConversationSession`, `RetrievalCandidate`, Gemini/OpenAI structured
extraction and canonical metadata review. Its first implementation verified
retrieved assertion identity/provenance/lineage but consumed the text value
directly from the caller's retrieval object. That was not sufficient content
integrity evidence: a stale or forged `RetrievalCandidate` could carry a
different text value while preserving an actual current assertion ID.

## New safety requirement and implementation

The injected `CanonicalRevisionSnapshotReader.verify_exact_content` now
executes **one** serialized read-only operation:

1. Resolve an exact current assertion with verified owner provenance,
   sensitivity, ancestry and unambiguous version.
2. Require exact canonical assertion ID.
3. Query `value_type`, `value_json`, and `normalized_text` for that
   current assertion; compare to the caller's candidate text and normalized
   text, serialized using the same existing `canonical_value_json` helper.
4. Return only a boolean. Memory values never leave this reader as outputs;
   the call writes no database rows.

`review_contextual_revision_shadow` invokes that verifier **before**
building any model context; forged values, altered normalization and stale
assertion IDs are skipped rather than transmitted to the extractor.

Tests are isolated disposable SQLite fixtures and synthetic owner turns. The
full production retrieval stack, Qwen models, Jev, Gemini and any owner-memory
API paths are not run or retested.

## Deliberate boundaries

- This content proof is valid at the **time of read**, not a lock across
  an LLM call. Future writes must check the same canonical assertion ID,
  version and contents within the authoritative writer transaction.
- It does **not** prove a retrieved memory is relevant to the new utterance.
  Relevance remains an independent research and blind acceptance milestone.
- External model egress of actual owner texts/memories is **not authorized**;
  this work is synthetic only.
- The context extractor is disabled unless a caller explicitly opts in and
  is not wired into `MemoryCandidateCoordinator` or LiveKit.
- Cross-lingual reference resolution accuracy and Phase 4.3 explicit-intent
  boundary interaction remain open. Do not treat successful unit tests as
  evidence of real-world multilingual reliability.
