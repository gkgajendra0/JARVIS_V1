# Step 4 — Phase 4.1 Canonical Memory Kernel Implementation Decisions

## Status

**IMPLEMENTATION CONTRACT — ACTIVE**

This document narrows the owner-approved Step-4 architecture into concrete Phase-4.1 implementation choices. It does not reopen the selected technologies and does not authorize model-driven memory writes.

## Research-first source check

Implementation details were rechecked immediately before coding against current authoritative documentation:

- SQLite FTS5: https://www.sqlite.org/fts5.html
- SQLite WAL: https://www.sqlite.org/wal.html
- SQLite isolation/concurrency: https://www.sqlite.org/isolation.html
- SQLite PRAGMAs: https://www.sqlite.org/pragma.html
- Zetetic SQLCipher API: https://www.zetetic.net/sqlcipher/sqlcipher-api/

These sources confirm the implementation rules below.

---

## 1. Migration/versioning decision

Use **ordered packaged SQL migrations**, not an ORM migration framework.

Migration files live under:

`src/jarvis/memory/migrations/`

Naming:

```text
0001_initial.sql
0002_....sql
```

JARVIS tracks migration state using both:

- `PRAGMA user_version` as the compact current schema version;
- `jarvis_schema_migration(version, name, sha256, applied_at)` as the auditable ledger.

SQLite explicitly reserves `user_version` for application use and does not interpret it itself.

Rules:

- migration versions are contiguous and strictly increasing;
- migration file SHA-256 is recorded when applied;
- an already-applied version whose current packaged hash differs is a fatal schema-integrity error;
- database version newer than the application is a fatal compatibility error;
- migration ledger and `user_version` disagreement is fatal;
- no destructive auto-downgrade;
- migrations execute transactionally and update ledger + `user_version` in the same migration transaction.

No Alembic/ORM is added because there is no ORM domain model and the required migration surface is small, deterministic SQL.

---

## 2. Production SQLCipher open contract

Production memory has **no plaintext SQLite fallback**.

Connection order:

```text
open DB-API connection
 -> PRAGMA key with exact random 32-byte raw-key blob
 -> SELECT count(*) FROM sqlite_master
 -> verify SQLCipher version/provider
 -> apply connection hardening
 -> run/verify migrations
```

Zetetic documents that the key must be supplied before the first database operation and that a real schema read is required to discover an incorrect key.

Production engine gate for this phase:

- SQLCipher must report `4.17.x` / `4.17.0 community` compatible current engine;
- missing `PRAGMA cipher_version` is fatal;
- older published `sqlcipher3` wheel carrying SQLCipher 4.12 is not silently accepted;
- no standard-library `sqlite3` production fallback.

The selected package remains the reproducible JARVIS SQLCipher 4.17 build already proven in research. Phase 4.1 code therefore lazy-loads the DB-API binding and fails clearly when the accepted production artifact is not installed, rather than adding the older PyPI wheel as a normal runtime dependency.

---

## 3. Database key lifecycle

Use the shared `jarvis.security.KeyProtector` boundary created in Phase 4.0A.

Purpose:

`memory-sqlcipher-master-key-v1`

Initialization states:

```text
DB absent + sealed key absent -> generate 32 random bytes, DPAPI-seal, create DB
DB absent + sealed key present -> reuse the sealed key and create DB (crash-safe initialization retry)
DB present + sealed key present -> normal open
DB present + sealed key absent -> FAIL CLOSED
```

Never write the raw key to disk, configuration, logs, migration metadata, or observability events.

A failed key unwrap never causes JARVIS to silently replace the database with a new empty one.

---

## 4. Connection hardening

After the SQLCipher key has been proven, apply/verify:

```text
PRAGMA foreign_keys = ON
PRAGMA journal_mode = WAL
PRAGMA synchronous = FULL
PRAGMA temp_store = MEMORY
PRAGMA secure_delete = ON
PRAGMA cipher_memory_security = ON
```

The accepted custom SQLCipher 4.17 build already passed the isolated `cipher_memory_security=ON` probe.

Do not copy the research leak harness's `wal_autocheckpoint=0` setting into production. SQLite's normal WAL checkpointing is retained initially and may be tuned only from measurements.

---

## 5. Worker/concurrency boundary

SQLite permits concurrent readers in WAL mode but still has one writer at a time.

Phase 4.1 therefore uses a tiny thread-affinity worker abstraction rather than `aiosqlite`:

```text
writer worker: 1 thread / 1 connection / serialized writes+migrations
reader worker: 1 thread / 1 connection / deterministic reads
```

Connections are created and used on their owning worker thread.

The worker is infrastructure only; it does not own memory semantics. `MemoryService` remains the future mutation owner.

No general-purpose connection pool is introduced.

---

## 6. Phase-4.1 canonical tables

Only tables needed by the deterministic semantic-memory kernel are introduced now.

### `memory_source`

Minimum provenance/evidence required to explain a durable assertion.

### `semantic_assertion`

Versioned facts/preferences/rules with valid-time + system-time fields, verification/freshness/sensitivity, lifecycle state, and supersession linkage.

The public canonical ID remains a UUID-style text `assertion_id`.

For stable FTS5 external-content row mapping, the SQLite table also owns an internal `assertion_rowid INTEGER PRIMARY KEY`. This is storage plumbing only and is never the public memory identity.

### `memory_operation`

Lifecycle operation metadata. It must not retain forgotten plaintext.

### `semantic_assertion_fts`

Derived FTS5 external-content index over `semantic_assertion.normalized_text`.

Not created in Phase 4.1:

- `memory_candidate` (Phase 4.4);
- embeddings (Phase 4.5);
- episode/reflection schema (Phase 4.6).

---

## 7. FTS5 synchronization and delete semantics

Use an **external-content FTS5 table** synchronized by deterministic INSERT/DELETE/UPDATE triggers.

SQLite documents external-content tables plus triggers as the normal synchronization pattern and provides the `rebuild` command for reconstructing the derived index.

Rules:

- canonical `semantic_assertion` is truth;
- FTS is derived/rebuildable;
- INSERT trigger indexes new normalized text;
- DELETE trigger issues the FTS5 external-content delete command using OLD values;
- UPDATE trigger deletes OLD text then inserts NEW text;
- startup/diagnostic code can issue `rebuild` if consistency verification fails.

Privacy hardening requires both:

```text
INSERT INTO semantic_assertion_fts(semantic_assertion_fts, rank)
VALUES('secure-delete', 1)
```

and:

```text
PRAGMA secure_delete = ON
```

SQLite explicitly warns that FTS5 secure-delete alone prevents SQL-level reconstruction of removed terms but core secure-delete is also required to reduce file-level recovery of deleted content.

---

## 8. Temporal storage contract

Store timestamps as normalized UTC ISO-8601 text generated by JARVIS domain code.

Semantic assertion lifecycle fields:

```text
valid_from
valid_to
system_from
system_to
last_verified_at
state
supersedes_id
```

Semantics:

- historical change closes valid time of an actually-true previous assertion and creates a successor;
- correction closes the old **system belief**, not genuine historical truth;
- retraction marks the prior assertion invalid without inventing a replacement;
- expiration is not deletion;
- forget physically removes content.

A safe `current_semantic_assertion` view centralizes the current-active predicate instead of duplicating it across callers.

---

## 9. Explicit forget transaction

Phase 4.1 forget is deterministic and synchronous with durable success.

Within one governed writer operation:

1. resolve canonical assertion;
2. DELETE the canonical row (FTS trigger removes derived lexical representation);
3. remove source/evidence rows that are no longer referenced and are eligible for deletion;
4. write only non-content operation metadata permitted by policy;
5. verify zero canonical hits;
6. verify zero FTS hits/row mapping;
7. commit;
8. checkpoint/maintenance only where measured/required, outside unnecessary conversational critical path.

JARVIS must never report success before the transaction and verification succeed.

---

## 10. Test strategy

Cross-platform CI uses standard SQLite only as a **schema/lifecycle test engine**, never as a production fallback. The production SQLCipher factory is separately unit-tested for key-first ordering/fail-closed checks and receives real Windows SQLCipher validation through the accepted Windows packaging/security gate.

Required tests before Phase 4.1 closes:

- migration ordering/hash/version integrity;
- schema constraints/current view;
- FTS trigger synchronization and rebuild;
- FTS secure-delete option + core secure-delete configuration;
- new fact/current exact lookup;
- historical change;
- correction;
- retraction;
- verification without value mutation;
- expiration;
- physical forget + zero FTS result;
- forgotten plaintext absent from operation metadata;
- wrong/missing SQLCipher engine fails closed;
- missing sealed key with existing DB fails closed;
- worker thread affinity/serialization;
- all Step-1/2/3 regression tests remain green.

No LLM is needed to pass any Phase-4.1 test.
