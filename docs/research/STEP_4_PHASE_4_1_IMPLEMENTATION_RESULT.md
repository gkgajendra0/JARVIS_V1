# Step 4 — Phase 4.1 Canonical Memory Kernel Implementation Result

## Status

**AUTOMATED IMPLEMENTATION VALIDATION COMPLETE — PHASE 4.1 KERNEL CLOSED FOR FURTHER FEATURE WORK**

Phase 4.1 implemented and automatically validated the deterministic canonical semantic-memory kernel approved by the active implementation contract.

This result does **not** mark all of Step 4 complete. Real human use, correction, human acceptance, documentation reconciliation, and protected-main merge still remain at the overall Step-4 lifecycle level.

It also does not authorize model-driven memory admission, embedding retrieval, episodic/reflection memory, or provider-owned canonical state.

---

## 1. Implemented scope

Phase 4.1 now contains:

- stable JARVIS-owned conversation/session/turn provenance identifiers;
- canonical SQLite schema + ordered/hash-verified migrations;
- SQLCipher fail-closed production database factory;
- Windows DPAPI protected SQLCipher master-key sidecar;
- crash-safe key/database initialization state machine;
- one serialized writer connection on a dedicated thread;
- one serialized reader connection on a separate dedicated thread;
- deterministic semantic assertion lifecycle;
- current-truth view;
- FTS5 external-content index with synchronization/rebuild/secure-delete coverage;
- physical forget semantics;
- deterministic exact canonical reader surface;
- shared DB-row decoder into strongly typed domain records.

No LLM is in the canonical write path.

---

## 2. Important implementation files

### Conversation/provenance boundary

- `src/jarvis/conversation.py`
- `src/jarvis/voice/livekit_session.py`

Canonical accepted turns own stable JARVIS `session_id`, `turn_id`, accepted UTC timestamp, role, text, interruption state, and optional provider `external_item_id`.

Provider IDs remain source metadata only.

### Canonical store

- `src/jarvis/memory/migrations/0001_initial.sql`
- `src/jarvis/memory/migration_runner.py`
- `src/jarvis/memory/database.py`
- `src/jarvis/memory/worker.py`
- `src/jarvis/memory/assertions.py`
- `src/jarvis/memory/provenance.py`
- `src/jarvis/memory/storage_rows.py`
- `src/jarvis/memory/lifecycle.py`
- `src/jarvis/memory/query.py`
- `src/jarvis/security/dpapi.py`

### Test evidence

- `tests/test_memory_migrations.py`
- `tests/test_memory_database.py`
- `tests/test_memory_worker.py`
- `tests/test_memory_lifecycle.py`
- `tests/test_memory_query.py`
- existing Windows DPAPI/security regression tests.

---

## 3. Migration and FTS behavior

Automated tests prove:

- migrations are ordered and contiguous;
- `PRAGMA user_version` and the migration SHA-256 ledger agree;
- migration drift/mismatch is fatal;
- schema constraints are enforced;
- current-state view excludes closed assertions;
- FTS5 insert/update/delete synchronization works;
- deliberate FTS desynchronization can be repaired with `rebuild`;
- FTS secure-delete is enabled;
- core SQLite `secure_delete` is enabled;
- English/Hindi values work in measured SQLCipher FTS tests.

No vector database is introduced.

---

## 4. Canonical lifecycle behavior

`MemoryLifecycleService` separates:

- `create`
- `historical_change`
- `correct`
- `retract`
- `verify`
- `expire`
- `forget`

Measured semantics include:

- historical change preserves the old value as superseded historical truth and opens a replacement validity interval;
- correction marks the inaccurate prior assertion retracted rather than valid history;
- verify changes verification metadata without changing the value;
- expiry closes current validity;
- transaction failure rolls back the entire lifecycle mutation;
- concurrent async callers are serialized by the writer worker;
- English, Hindi, and Hinglish values round-trip without lifecycle special cases.

---

## 5. Forget/privacy behavior

Forget is a physical canonical purge, not a hidden state.

For a forgotten semantic assertion:

- prior operation rows for that target are removed;
- the canonical assertion row is deleted;
- its FTS entry is deleted by the synchronized FTS path;
- a provenance source used only by the forgotten assertion is removed;
- a provenance source shared by surviving assertions is retained;
- semantic-memory source rows reject copied raw `evidence_text` by default;
- the remaining forget tombstone carries no plaintext content fingerprint;
- canonical/current and FTS lookup return zero for the forgotten assertion.

The implementation therefore avoids a shared-source failure where forgetting one assertion could otherwise leave its plaintext copied inside a provenance row used by another assertion.

---

## 6. Crash-safe SQLCipher key state machine

Canonical DPAPI purpose:

```text
memory-sqlcipher-master-key-v1
```

Validated states:

```text
DB absent + sealed key absent
    -> generate 32-byte key
    -> DPAPI seal key
    -> create/key/verify DB

DB absent + sealed key present
    -> DPAPI unwrap existing key
    -> retry DB initialization with same key

DB present + sealed key present
    -> normal open

DB present + sealed key absent
    -> FAIL CLOSED before DB driver open
```

Failure cleanup:

- failed brand-new key+DB initialization removes the new DB artifacts and newly created key sidecar;
- failed key-only crash retry removes only newly created DB/WAL/SHM artifacts and preserves the pre-existing sealed key;
- DB-only state is never silently reset or overwritten.

---

## 7. Dedicated connection ownership

`SerialConnectionWorker` owns exactly one DB connection on one dedicated thread.

Phase 4.1 uses:

```text
writer worker
    1 thread
    1 connection
    migrations + serialized writes/lifecycle

reader worker
    1 different thread
    1 connection
    deterministic canonical reads
```

The implementation does not disable SQLite thread-affinity checks and does not share a connection across arbitrary asyncio executor threads.

`CanonicalMemoryReader` currently exposes only deterministic canonical reads:

- `get_current(assertion_id)`
- exact current lookup by `(subject_scope, subject, predicate)`

No embedding/reranking/retrieval-policy work is pulled forward from Phase 4.5.

---

## 8. Normal CI acceptance evidence

### Lifecycle gate

GitHub Actions run:

```text
33949790387
```

Result:

- Ruff: PASS
- pytest: PASS
- Windows Hello helper: PASS
- Windows DPAPI: PASS

### Current reader/key-recovery head gate

GitHub Actions run:

```text
33950361478
```

Result:

- Ruff: PASS
- pytest: PASS
- Windows Hello helper: PASS
- Windows DPAPI: PASS

This run includes the dedicated reader boundary and the formatted crash-safe database tests on the current implementation line.

---

## 9. Exact real Windows SQLCipher/DPAPI gate

Crash-recovery implementation commit:

```text
c16ca2f4d9809322e3bc22695a0a4263f228317f
Align memory key crash recovery contract
```

GitHub Actions workflow run:

```text
33950069031
Step 4 SQLCipher 4.17 Windows verification
```

Final result:

```text
SUCCESS
```

All workflow stages passed:

- pinned SQLCipher 4.17.0 wheel build;
- isolated Python 3.11 verification environment;
- full synthetic SQLCipher + Windows DPAPI bake-off;
- current-engine packaging gate;
- production memory adapter smoke;
- evidence artifact upload.

### Measured package/runtime

```text
sqlcipher3       0.6.2+jarvis.sqlcipher4170
SQLCipher        4.17.0 community
SQLite           3.53.3
cipher provider  openssl
OpenSSL          3.6.0 1 Oct 2025
cipher_status    1
FTS5 compiled    true
TEMP_STORE       2
journal_mode     wal
secure_delete    1
```

Enhanced `cipher_memory_security=ON` subprocess probe:

```text
PASS
PROBE_OK=1
```

Built Windows wheel:

```text
sqlcipher3-0.6.2+jarvis.sqlcipher4170-cp311-cp311-win_amd64.whl
SHA-256: 97d2c1e6c363ac1ba21ba16f919cdc87b897328d793ea17571cb2d2fa91bb7b9
```

Pinned sources:

```text
SQLCipher source commit: 810db22f575ee7cf94ea96a3e91622b5fcece3dc
sqlcipher3 wrapper:       14fc263
```

---

## 10. Full SQLCipher/DPAPI bake-off result

The exact run reported:

```text
status = PASS
```

Passed checks:

- SQLCipher present;
- DPAPI roundtrip;
- wrong DPAPI purpose blocked;
- raw key absent from DPAPI blob;
- FTS5 compiled;
- English FTS works;
- Hindi FTS works;
- canonical write/read;
- temp store memory;
- secure delete on;
- WAL mode;
- cipher integrity clean before test;
- no plaintext leak while WAL live;
- stdlib SQLite without key blocked;
- wrong SQLCipher key blocked;
- no plaintext leak after close;
- same-user/machine backup restore count;
- backup restore FTS;
- ciphertext corruption detected;
- forget canonical zero;
- forget FTS zero;
- cipher integrity clean after forget;
- no plaintext or raw-key leak final.

Leak scans:

```text
while_wal_live = {}
after_close    = {}
final          = {}
```

Corruption probe result:

```text
DatabaseError
```

The wrong-key HMAC/decryption errors visible in the workflow log are expected negative-test evidence, not workflow failures.

---

## 11. Production adapter smoke result

The production `SqlCipherMemoryDatabaseFactory` smoke on the exact crash-recovery commit reported:

```text
status = PASS
```

All checks were true:

- cipher status;
- SQLCipher version;
- SQLite version;
- migration version;
- single migration ledger row;
- FTS on first open;
- current assertion survives reopen;
- FTS survives reopen;
- protected key sidecar exists;
- stdlib plaintext SQLite open is blocked;
- synthetic marker is not visible in DB/WAL/SHM/key artifacts.

Reported leaks:

```text
[]
```

An earlier adapter run produced a false-negative because the SQLCipher wrapper surfaced `PRAGMA cipher_status` as string `"1"` while the smoke compared it to integer `1`. The production factory already normalized the value fail-closed. The smoke was corrected to the same normalization and the exact current gate above passed.

---

## 12. Packaging decision retained

The selected Windows production candidate remains the reproducible, pinned Community Edition build recipe already retained in the repository.

The build is reproducible from pinned SQLCipher/wrapper/tooling inputs and produces a JARVIS-marked wheel rather than silently treating a third-party PyPI wheel as the canonical production artifact.

Portable cross-machine disaster recovery remains a separate owner-approved design problem. DPAPI backup/restore evidence only proves the same-user/same-machine boundary; the sealed DPAPI blob is not claimed to be a portable recovery secret.

---

## 13. Deferred by design

Phase 4.1 intentionally does **not** implement:

- automatic memory extraction/admission;
- Pydantic extraction adapter;
- OpenAI/Gemini memory candidate generation;
- embeddings;
- semantic reranking;
- Qwen model runtime;
- episodic memory;
- reflection;
- emotion persistence;
- self-modification;
- provider-owned canonical memory.

Those remain in their approved later phases.

---

## 14. Phase transition

With the exact real Windows SQLCipher/DPAPI gate and normal CI gates green, the Phase-4.1 deterministic canonical-memory kernel is closed for further Step-4 feature development.

The next active implementation phase is:

```text
Phase 4.2 — Live Context and Context Assembler
```

Its implementation contract is recorded separately in:

`docs/research/STEP_4_PHASE_4_2_IMPLEMENTATION_DECISIONS.md`
