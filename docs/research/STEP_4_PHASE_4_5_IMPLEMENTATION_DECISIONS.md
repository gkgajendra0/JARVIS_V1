# Step 4 — Phase 4.5 Production Retrieval Implementation Decisions

Date: 2026-09-05

## Status

**IMPLEMENTATION CONTRACT APPROVED FOR PHASE 4.5A–E.**

This document translates the measured Phase-4.5 retrieval research into production boundaries. It does not grant retrieval any memory-mutation or truth authority.

## Research inputs

Selected local stack:

- canonical store: SQLCipher 4.17.0 / SQLite 3.53.3;
- lexical retrieval: SQLite FTS5;
- embedding: `Qwen/Qwen3-Embedding-0.6B`;
- embedding revision: `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3`;
- embedding output: normalized 256-dimensional Matryoshka vectors;
- query instruction: JARVIS memory-specific English retrieval instruction from the measured bake-off;
- fusion: equal-weight RRF, `k=60`, FTS window `10`;
- reranker: `Qwen/Qwen3-Reranker-0.6B`;
- reranker revision: `e61197ed45024b0ed8a2d74b80b4d909f1255473`;
- rerank candidate window: top 3;
- reranker precision: model-default BF16;
- exact reranker-score tie: preserve first-stage RRF rank, then stable memory ID;
- vector search: exact local cosine initially;
- ANN/vector extension: not approved until a scale benchmark demonstrates need;
- abstention threshold: not approved until larger calibration corpus is measured.

The revision pins are immutable full Hugging Face commit hashes. Production code must not silently follow `main` for either model.

## External implementation checks

Current upstream documentation confirms:

1. Sentence Transformers exposes `encode_query()` and `encode_document()` as retrieval-specific APIs, supports `normalize_embeddings` and `truncate_dim`, and exposes a `revision` constructor argument.
2. Hugging Face accepts full commit hashes in `revision`; full hashes are preferred for immutable snapshot selection.
3. SQLite `ON DELETE CASCADE` deletes dependent child rows when a parent assertion is physically deleted.
4. NumPy supports explicit dtype byte-order metadata and `frombuffer` reconstruction; stored vector bytes therefore use an explicit little-endian float32 contract instead of host-native endian.

References:

- https://sbert.net/docs/package_reference/sentence_transformer/model.html
- https://www.sbert.net/docs/sentence_transformer/usage/usage.html
- https://huggingface.co/docs/huggingface_hub/guides/download
- https://www.sqlite.org/foreignkeys.html
- https://numpy.org/doc/stable/reference/generated/numpy.dtype.newbyteorder.html
- https://numpy.org/doc/stable/reference/generated/numpy.frombuffer.html

## Authority and data-flow boundaries

Permanent pipeline:

```text
canonical query/context need
    |
    +-> exact deterministic current lookup when key is known
    |
    +-> eligible current canonical assertions only
           |
           +-> FTS5 lexical rank
           +-> Qwen dense rank
           |
           v
        equal RRF
           |
           v
        top 3 eligible candidates
           |
           v
        Qwen reranker BF16
           |
           v
        calibrated release/abstention
           |
           v
        ContextAssembler
           |
           v
        active Gemini provider
```

Retrieval models may **only order already-eligible canonical evidence**. They may not:

- create or mutate semantic assertions;
- mark a claim verified;
- override explicit correction/retraction/forget;
- resurrect deleted/superseded/expired memory;
- change source authority;
- relax sensitivity/release policy;
- become a second canonical truth store.

`MemoryService` remains the sole public durable mutation facade. `ContextAssembler` remains the sole model-context release boundary.

## Phase 4.5A — derived-vector schema/lifecycle

Create an encrypted SQLCipher table named `semantic_assertion_embedding`.

Required logical fields:

- `assertion_id` — parent canonical assertion and primary identity;
- `model_id` — exact model repository ID;
- `model_revision` — full immutable revision hash;
- `dimension` — embedding dimension;
- `dtype` — serialization dtype identifier;
- `byte_order` — explicit byte order identifier;
- `normalized` — whether vector is unit-normalized;
- `content_sha256` — fingerprint of the exact text representation embedded;
- `embedding_blob` — raw vector bytes inside SQLCipher;
- `created_at` / `updated_at` — system metadata.

Key rule:

```sql
assertion_id TEXT PRIMARY KEY
    REFERENCES semantic_assertion(assertion_id)
    ON DELETE CASCADE
```

Physical canonical forget must therefore remove the derived vector in the same SQLCipher transaction via FK cascade. Tests must prove zero vector rows after forget.

### Vector serialization contract

Store exactly:

- IEEE float32;
- little-endian (`<f4`);
- C-contiguous one-dimensional vector;
- exactly 256 elements for the selected production model;
- exactly 1024 bytes for a 256d float32 vector;
- finite numeric values only;
- normalized flag true for selected Qwen production vectors.

The storage layer validates dimension/byte length/dtype before insert and after read. Do not pickle NumPy arrays.

### Rebuild/version semantics

Embeddings are rebuildable derived artifacts. A stored vector is current only when all of these match the active embedding contract:

- model ID;
- immutable model revision;
- dimension;
- dtype;
- byte order;
- normalized flag;
- SHA-256 of the canonical embedding text.

Any mismatch means **stale derived vector**, not stale canonical memory. Recompute/replace the vector; never mutate canonical assertion truth because of a vector mismatch.

The embedded document representation is the canonical assertion's stored `normalized_text` for Phase 4.5. This keeps embedding lineage deterministic and already covered by canonical correction/supersession lifecycle.

## Phase 4.5B — first-stage retrieval

### Eligibility before ranking

Default semantic retrieval reads from `current_semantic_assertion`, not unrestricted history.

Before lexical/dense ranking, enforce at minimum:

- active/current assertion state;
- valid/system current semantics from the canonical view;
- source/authority eligibility supplied by JARVIS policy;
- sensitivity eligibility for the requested release target.

Historical retrieval is an explicit scope and must not leak into current retrieval by default.

### Lexical path

Use existing FTS5 `semantic_assertion_fts`. FTS is derived from canonical `normalized_text` and already follows insert/delete/update triggers.

FTS query construction must be parameterized and must not splice untrusted text into SQL syntax. Query normalization/escaping gets unit tests for punctuation, quotes, operators, Hindi and Hinglish.

### Dense path

- encode query with selected JARVIS retrieval instruction;
- normalized 256d vector;
- read only eligible current assertion vectors;
- exact dot product is valid cosine because both query/document vectors are normalized;
- deterministic descending score, then stable assertion ID.

Do not introduce a vector extension in Phase 4.5 base implementation.

### RRF

Fuse lexical and dense rank positions using equal-weight reciprocal rank fusion:

```text
score(d) = 1/(60 + lexical_rank) + 1/(60 + dense_rank)
```

A document present in only one ranker receives only that contribution.

Sort by fused score descending. For an exact fused-score tie, use semantic/dense rank first, then lexical rank, then stable assertion ID. This preserves the measured harness contract.

## Phase 4.5C — local model adapters

Heavy ML dependencies must sit behind narrow protocols so ordinary memory unit tests do not load CUDA/models.

Embedding adapter requirements:

- lazy load;
- selected model/revision constants exposed for lineage;
- Sentence Transformers `revision=<full hash>`;
- `trust_remote_code=False` unless a separately researched need is approved;
- `encode_document()` for assertion text;
- `encode_query()` with the measured JARVIS instruction;
- `normalize_embeddings=True`;
- `truncate_dim=256`;
- return validated float32 NumPy vectors at the storage boundary.

Reranker adapter requirements:

- lazy load;
- selected full revision pin;
- top 3 only;
- model-default BF16;
- deterministic exact-score tie -> preserve first-stage rank -> stable ID.

### GPU dependency boundary

Do not silently replace the accepted Step-3 Torch/CUDA stack just because the research venv used PyTorch `2.14.0+cu130`.

Production dependency reconciliation must first prove that the selected Sentence Transformers/Qwen path works alongside the existing vision/identity Torch stack on the owner machine. If a shared version change is needed, research and test it as a separate compatibility decision before changing Step-3 production pins.

## Phase 4.5D — abstention/release calibration

No production cutoff is selected from the 20-query technology corpus.

Build a larger calibration corpus with many more:

- true absent answers;
- ambiguous questions;
- near-miss distractors;
- stale/superseded history;
- corrected values;
- forgotten values;
- sensitivity boundaries;
- adversarial/poisoned text;
- English/Hindi/Hinglish paraphrases.

Measure release error rates and latency. Do not use `score > 0`, an arbitrary cosine threshold, or a guessed reranker cutoff.

## Phase 4.5E — ContextAssembler integration

Only retrieval results that pass JARVIS eligibility and calibrated release policy may become durable-memory context items.

Required context evidence should include enough metadata for inspection without copying raw provider history:

- assertion ID;
- canonical subject/predicate/value presentation;
- source/provenance reference;
- freshness/verification state;
- sensitivity;
- retrieval stage/rank metadata where useful for diagnostics.

`LOCAL_ONLY` and `SECRET_PROHIBITED` content never enter cloud provider context. Existing bounded context budgets remain authoritative.

## Tests required before owner acceptance

Automated tests must cover:

- migration upgrade from schema v1 to v2;
- vector serialization roundtrip and malformed BLOB rejection;
- stale vector detection for revision/content/dimension mismatch;
- canonical forget -> zero vector rows via cascade;
- correction/supersession -> old vector cannot enter current retrieval;
- FTS special-character safety;
- dense deterministic ranking;
- RRF measured tie policy;
- reranker exact-score tie policy;
- Hindi/Hinglish retrieval fixtures;
- sensitivity filtering before release;
- ContextAssembler remains sole provider release path;
- no retrieval code calls durable mutation methods.

Owner-PC acceptance occurs only after CI is clean and Phase 4.5D calibration has selected a measured release policy.
