# Step 4.4 — Canonical revision snapshot research adapter (2026-10-16)

**Draft, synthetic-only validation. This does not enable autonomous memory,
allow automatic writes, or activate D8.**

## Source of truth audited

The existing canonical memory stores `semantic_assertion.assertion_id`
and `supersedes_id` for replacement history. It does **not** have a
numeric assertion version. `current_semantic_assertion` exposes active
records. Each assertion carries a `source_id` referencing
`memory_source` with source class, authority, sensitivity and canonical
reference. The existing `CanonicalMemoryReader` is read-only but
exposes value-bearing records, not provenance joining.

## What this PR adds

`CanonicalRevisionSnapshotReader` is a **research-only** helper
accepting an injected existing `SerialConnectionWorker`. It creates
no connections and does not look up a database path itself. Its queries:

1. Look up exactly the supplied subject scope / subject / predicate
   in the current-only assertion view.
2. Reject absent, multiple or source/sensitivity-ineligible records
   rather than picking an arbitrary matching assertion.
3. Join `memory_source` metadata without reading actual assertion
   values, normalized text or source evidence. Owner direct and
   owner explicit records require matching source authority.
4. Verify there is no active successor; walk the bounded `supersedes_id`
   chain for a consistent subject/predicate to derive the *chain length*
   (not a durable numeric version). Reject a missing, mismatched,
   cyclic or overlong chain.
5. Yield an opaque `CanonicalRevisionWitness` containing the genuine
   persisted source reference, not an invented `canonical:` prefix.

The existing review contract can now consume actual synthetic-record
metadata for a verified lifecycle **review**, while retaining
`meaning_equivalent_verified=None`. **No semantic equivalence is
inferred, no external LLM is run, no update is authorized, and no memory
values are returned.**

The test suite writes only **disposable synthetic SQLite fixture
records** via the existing canonical lifecycle, then queries through
a separate SQLite `mode=ro` and `PRAGMA query_only` worker. It
asserts true correction chains, stale/retracted records, untrusted
provenance, sensitivity restriction and ambiguous exact identifiers.

## Important limits

- This is not connected to production SQLCipher, DPAPI, voice pipeline,
  `MemoryService` or `ContextAssembler`. Live owner records are never
  loaded or exported.
- The injected connection worker needs an independent, trustworthy
  read-only binding before any owner-machine experiment. Do not pass
  a production writer or open a live memory path casually.
- The "latest" check describes the snapshot at query time, **not
  atomic concurrency control for a future write**. A future mutation
  would require authoritative revalidation and explicit owner approval.
- Exact subject/predicate equality is not multilingual semantic
  matching; the LLM extractor can still fail to identify a correction.
- The source's self-described class and authority originate from
  canonical persisted metadata. This is not independent verification
  of conversational intent, consent, or semantic content.
- The arbitrary historical `c11/c12/c13/c18` development labels remain
  exposed: do not claim accuracy improvements based on this contract.

## Next gate

Add an independent turn-to-canonical-target resolver for ambiguous
owner utterances, safe semantic duplicate verification, and blinded
Hindi/Hinglish corrections. For answer use, require real controlled
no-memory vs selected-memory tests. No auto-admission or passive injection
before separate production acceptance.

D8 is a separate deferred track: complex TV device capability acquisition
exceeded the reliable end-to-end autonomy demonstrated so far; bounded
self-evolution has not been ruled out.
