# Step 4 Phase 4.1 — Canonical Memory Lifecycle Contract

## Status

**IMPLEMENTATION CONTRACT — derived from the approved Step-4 architecture and refreshed against current SQLite documentation before lifecycle code.**

This contract narrows Phase 4.1 behavior for semantic-memory lifecycle operations. It does not enable LLM auto-write, implicit admission, provider-owned memory, or broad context injection.

## Authoritative existing requirements

The approved Step-4 requirements distinguish:

- historical change;
- correction;
- retraction;
- verification;
- expiry;
- explicit forget/deletion.

They must not collapse into a generic update. Current truth and historical truth are different, and a newer weak source does not automatically outrank stronger evidence.

## Transaction boundary

Every multi-row lifecycle mutation executes through the single serialized writer connection in one explicit `BEGIN IMMEDIATE` transaction.

Reasons:

- SQLite permits one writer at a time;
- `BEGIN IMMEDIATE` obtains the write transaction before mutation work begins;
- all assertion/source/operation changes commit atomically or roll back together;
- readers on separate WAL connections may continue to see the previous committed snapshot until commit.

No lifecycle method performs model/provider calls while a database transaction is open.

## Source evidence retention rule

`memory_source.evidence_text` is **NULL by default for personal semantic memory**.

JARVIS must not copy an accepted raw conversation turn into the durable memory database merely to support provenance. Provenance is carried by:

- `source_id`;
- `canonical_ref` such as stable JARVIS session/turn identity;
- source timestamps;
- authority class;
- sensitivity;
- optional `evidence_hash` where justified;
- optional external reference where appropriate.

Why this is mandatory:

One accepted source turn may produce multiple independent assertions. If the whole utterance were copied into one shared source row, forgetting one assertion could leave its plaintext inside evidence retained for another assertion. Avoiding copied raw utterance text keeps selective forget physically enforceable.

If a future use case truly requires durable plaintext evidence, it needs a separately approved evidence model with ownership/deletion semantics granular enough to erase the forgotten content. Phase 4.1 does not invent that model.

## Operation log privacy rule

`memory_operation` is lifecycle metadata, not a shadow transcript or shadow memory store.

- operation rows never store assertion plaintext;
- `reason_code` is a bounded semantic code, not free-form copied user text;
- `content_fingerprint` is optional and must be removed when the target assertion is forgotten;
- operation target IDs may remain only where they contain no forgotten content;
- a final forget tombstone may retain the random assertion ID and operation timing/type, with `content_fingerprint = NULL`;
- audit metadata must never defeat an explicit forget request.

## Create

Create inserts:

- one provenance source if it does not already exist;
- one new semantic assertion with a stable JARVIS assertion ID;
- `state = active`;
- `system_from = now`;
- `system_to = NULL`;
- caller-supplied/derived valid-time semantics;
- one content-free lifecycle operation record.

A create operation does not silently supersede an existing current assertion. Conflict resolution belongs to explicit lifecycle policy/service methods.

## Historical change

Use when the previous assertion **was true** and has now legitimately changed.

Atomically:

1. require the target assertion to be current/active;
2. close the old real-world interval with `valid_to = effective_at`;
3. close its current system representation with `system_to = now`;
4. set old `state = superseded`;
5. insert the replacement as `active`, normally with `valid_from = effective_at` and `supersedes_id = old assertion_id`;
6. write one `historical_change` operation targeting the replacement ID.

The old row remains eligible only for historical retrieval, never current-state retrieval.

## Correction

Use when a stored assertion was inaccurate rather than a formerly true historical state.

Atomically:

1. require the target assertion to be current/active;
2. set old `state = retracted`;
3. set old `system_to = now`;
4. do **not** reinterpret the old assertion as valid historical truth;
5. insert the corrected assertion as `active` with explicit valid-time supplied by the caller/policy where known;
6. set the new row's `supersedes_id` to the corrected assertion ID;
7. write one `correct` operation targeting the new assertion ID.

Historical retrieval must exclude `retracted` assertions from truth results.

## Retraction

Use when the owner or higher-authority policy says an assertion was wrong and there is no replacement value.

Atomically:

- require current/active target;
- set `state = retracted`;
- set `system_to = now`;
- retain provenance/lifecycle evidence required to explain that a bad assertion once existed;
- write a `retract` operation.

A retracted assertion is neither current truth nor historical truth.

## Verify

Verification confirms truth without changing the asserted value.

Atomically:

- require a non-retracted, non-forgotten assertion;
- set `verification_state = verified`;
- set `last_verified_at = verification time`;
- update representation timestamp;
- write a `verify` operation.

Verification does not manufacture a new value and does not reset `valid_from`.

## Expire

Use when a time-bounded assertion reaches its end without a replacement.

Atomically:

- require current/active target;
- set `state = expired`;
- set `valid_to = effective expiry time`;
- set `system_to = now`;
- write an `expire` operation.

Expired assertions may be historical evidence but are not current truth.

## Explicit forget

Forget is a **physical purge**, not a lifecycle state. There is intentionally no `forgotten` assertion state.

Within one write transaction:

1. resolve the target assertion and its source ID;
2. delete prior `memory_operation` rows whose `target_id` identifies that assertion, removing any historical content fingerprint associated with it;
3. physically `DELETE` the semantic assertion;
4. rely on the tested FTS5 delete trigger to remove the derived lexical entry;
5. delete the source row only if no remaining assertion depends on it and no retained provenance requirement needs it;
6. if the source remains because it is shared, it must contain no copied forgotten plaintext under the source-evidence rule above;
7. insert one content-free `forget` operation with the forgotten random assertion ID, timing/type/result metadata, and `content_fingerprint = NULL`;
8. commit atomically.

After commit, verify:

- canonical assertion count for the ID is zero;
- FTS result for a unique test marker is zero;
- current view returns zero;
- no operation row for the old assertion retains a content fingerprint or plaintext field.

Storage hardening after forget:

- SQLite core `PRAGMA secure_delete = ON` is enabled before deletion;
- FTS5 persistent `secure-delete` is enabled by migration;
- WAL checkpoint/compaction policy is performed outside the mutation transaction where appropriate;
- `VACUUM` remains an explicit maintenance/hardening action rather than being forced into every interactive forget transaction.

SQLite's documentation states that core secure-delete overwrites deleted content and that FTS5 secure-delete must be combined with core `secure_delete` to protect deleted full-text entries in the database file. SQLite also documents `VACUUM` as an additional cleanup option after deletes/updates.

## Forbidden shortcuts

Phase 4.1 lifecycle code must not:

- overwrite a current row in place to represent historical change;
- treat correction as historical truth;
- retain a hidden `forgotten` row;
- retain forgotten plaintext in an operation/audit table;
- copy full accepted conversation turns into durable `memory_source.evidence_text` by default;
- let retrieval/ranking code mutate lifecycle state;
- let an LLM/provider write directly to the canonical tables;
- run provider/model calls inside DB transactions.

## Required tests before this lifecycle slice is accepted

At minimum:

- create -> current;
- historical change -> old historical + new current;
- correction -> old retracted, not historical truth + new current;
- retraction -> no current result and no replacement;
- verify -> same value, newer verification timestamp;
- expire -> historical only;
- forget -> canonical zero + FTS zero + prior operation fingerprint removed;
- shared-source selective forget -> unrelated assertion survives and no forgotten plaintext remains in source;
- rollback-on-mid-transition failure;
- concurrent async callers remain serialized through the writer worker;
- English/Hindi/Hinglish content round-trips without changing lifecycle semantics.

No acceptance result should be claimed until these automated tests and the real SQLCipher adapter gate pass.
