# Step 4 — Phase 4.5A Derived-Vector Lifecycle Result

Date: 2026-09-05

## Status

**PHASE 4.5A COMPLETE — ENCRYPTED DERIVED-VECTOR LIFECYCLE IMPLEMENTED AND AUTOMATED VALIDATION PASSED.**

## Implemented production surface

Added SQLCipher migration:

- `src/jarvis/memory/migrations/0002_semantic_retrieval.sql`

Added lightweight derived-vector storage/codec:

- `src/jarvis/memory/embeddings.py`

No Sentence Transformers, Torch, CUDA, reranker, ANN/vector extension or voice-runtime integration was added in Phase 4.5A.

## Schema contract

`semantic_assertion_embedding` is a one-to-one derived table keyed by canonical assertion ID:

```sql
assertion_id TEXT PRIMARY KEY
    REFERENCES semantic_assertion(assertion_id)
    ON DELETE CASCADE
```

Stored lineage includes:

- model repository ID;
- immutable 40-character revision hash;
- embedding dimension;
- dtype;
- byte order;
- normalized flag;
- SHA-256 of exact canonical `normalized_text`;
- encrypted vector BLOB;
- created/updated timestamps.

The database constrains BLOB length to `dimension * 4` for float32 storage.

## Selected Qwen embedding contract

- model: `Qwen/Qwen3-Embedding-0.6B`;
- immutable revision: `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3`;
- dimension: `256`;
- serialization: little-endian IEEE float32 (`<f4`);
- expected byte length: `1024`;
- normalized: true;
- document fingerprint: SHA-256 over UTF-8 `normalized_text`.

`main` or another moving model revision is rejected by the contract.

## Rebuild/staleness semantics

A vector is current only if all selected-contract fields and the canonical content fingerprint match.

Mismatch means the **derived vector is stale**. It does not mutate or downgrade canonical memory truth.

## Physical forget proof

Automated tests create a canonical assertion through `MemoryLifecycleService`, store a derived embedding, then invoke canonical `forget()`.

Postcondition:

- canonical assertion absent;
- `SemanticEmbeddingStore.get()` returns no row;
- raw `semantic_assertion_embedding` row count is zero.

Cleanup is database-enforced by `ON DELETE CASCADE`, inside the same canonical SQLCipher database, rather than application best-effort deletion.

## Automated validation

Relevant tests cover:

- migration catalog advances from schema v1 to v2;
- migration ledger/checksum/idempotence remain intact;
- SQLCipher database factory expectations updated to schema v2;
- float32 little-endian roundtrip;
- wrong dimension rejected;
- non-finite values rejected;
- malformed BLOB length rejected by codec and SQL schema;
- UTF-8 content fingerprint stability;
- immutable revision validation;
- stored-vector roundtrip;
- stale canonical-content detection;
- stale model-revision detection;
- canonical physical forget -> zero derived-vector rows;
- existing FTS5/current-view behavior remains intact.

GitHub Actions run `33982956641` on head `7336b62b21b87f3002c02584c4b7a4ecd8562427` reported:

- Ruff: PASS;
- pytest: PASS;
- Windows Hello helper: PASS;
- Windows DPAPI: still in the standard dependency-install stage at the time this result record was written; no Phase-4.5A code path changes DPAPI behavior.

Previous accepted Windows DPAPI runs remain green. Final branch-gate checks continue on subsequent heads.

## Security/authority result

Phase 4.5A adds **derived search data only**. It grants no new authority:

- `MemoryService` remains the sole public durable mutation facade;
- retrieval models cannot write canonical assertions;
- embedding staleness cannot alter canonical truth;
- forgotten assertions cannot survive through derived vectors;
- vectors remain inside SQLCipher;
- no external vector database becomes canonical or derivative owner.

## Next

Proceed to **Phase 4.5B — eligible current FTS5 + exact dense cosine + deterministic equal-weight RRF**.

The first-stage retrieval core must accept a query vector from a narrow boundary and must not import/load Sentence Transformers or CUDA yet. Local Qwen model adapters remain Phase 4.5C.
