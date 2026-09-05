# Step 4 — Bake-off Results

## Status

**RESEARCH BAKE-OFFS COMPLETE FOR FINAL ARCHITECTURE APPROVAL.**

This document records measured evidence for the Step-4 technology decision. Results distinguish between reference-environment measurements and measurements from the real JARVIS Windows machine.

Research harnesses deliberately live under `tools/research`; no runtime memory under `src/jarvis` is implemented by these bake-offs.

Final consolidation:

- `docs/research/STEP_4_FINAL_TECHNOLOGY_DECISION.md`
- `docs/research/STEP_4_ARCHITECTURE_PROPOSAL.md`

---

## 1. SQLite temporal + FTS bake-off — COMPLETE

### Purpose

Test whether SQLite can satisfy the important canonical-memory mechanics before adding a temporal database server, graph database, or vector database:

- current fact lookup;
- valid-time history;
- system/learned-time history;
- historical change versus correction;
- FTS5 English/Hindi/Hinglish lexical retrieval;
- explicit-forget deletion from canonical + derived FTS representations;
- low-latency local lookup at a scale much larger than the expected early personal-memory corpus.

### Reference-environment result

Initial research execution used Python's built-in SQLite 3.46.1 with 30,000 synthetic fact records.

Temporal semantics passed all tested assertions:

1. old system-time queries recover what JARVIS believed then;
2. genuine preference changes preserve the old value for its historical valid-time interval while a new value becomes current;
3. later corrections can change the current best-known historical truth while old system-time queries still recover the earlier mistaken belief.

Reference latency was approximately:

| Query | p50 | p95 |
|---|---:|---:|
| Exact structured current-fact lookup | 0.008 ms | 0.009 ms |
| FTS5 English | 3.25 ms | 4.84 ms |
| FTS5 Hindi | 3.45 ms | 5.12 ms |
| FTS5 Hinglish | 2.89 ms | 3.20 ms |

These reference numbers were not acceptance thresholds.

### Real JARVIS Windows-machine result — PASS

The owner reran the same harness on the actual JARVIS Windows/Python 3.11 environment on 2026-09-04.

Environment/result highlights:

- SQLite: `3.45.1`;
- seed records: `30,000`;
- temporal semantics: all tested assertions passed;
- FTS5 `secure-delete`: supported;
- explicit forget: zero canonical rows and zero normal FTS hits after deletion;
- database size: `16,928,768` bytes (~16.9 MB decimal).

Measured latency:

| Query | p50 | p95 | Maximum observed |
|---|---:|---:|---:|
| Exact current-fact lookup | 0.0165 ms | 0.0186 ms | 0.2087 ms |
| FTS5 English | 4.0938 ms | 4.6056 ms | 6.1346 ms |
| FTS5 Hindi | 4.3506 ms | 4.6950 ms | 6.0042 ms |
| FTS5 Hinglish | 3.7851 ms | 3.9048 ms | 4.1437 ms |

### SQLite disposition

**KEEP SQLITE + FTS5 AS THE CANONICAL/LEXICAL FOUNDATION. DO NOT ADD XTDB/QDRANT/GRAPHITI/LANCEDB TO THE RUNTIME WITHOUT MEASURED NEED.**

Reason:

- required bitemporal semantics were demonstrated on the real machine;
- lookup/FTS latency is comfortably low at the tested scale;
- secure-delete is available;
- tested forget path removed canonical and FTS representations;
- WAL matches the expected same-host, low-write-concurrency workload;
- a heavier database would add operational/security/synchronization surface without demonstrated benefit.

Harness:

- `tools/research/step4_memory_sqlite_bakeoff.py`

---

## 2. Multilingual retrieval-quality bake-off — TECHNOLOGY SELECTION COMPLETE

Detailed decision:

- `docs/research/STEP_4_RETRIEVAL_TECHNOLOGY_DECISION.md`

### Why semantic retrieval was tested

FTS5 was fast but missed low-overlap semantic paraphrases, including cases equivalent to:

- “Which device gives Jarvis eyes?” versus the stored camera fact;
- “Meri bike kaunsi hai?” versus the stored motorcycle fact;
- Hindi/Hinglish research-first-rule paraphrases.

Therefore semantic retrieval addresses a measured lexical-recall gap rather than being added by convention.

### Model comparison on the actual RTX 5060 Ti

#### Qwen3-Embedding-0.6B — default 1024

- Recall@1: `0.7647`;
- Recall@3: `1.0000`;
- MRR: `0.8824`;
- GPU query p50: ~61 ms;
- peak CUDA allocation: ~1.29 GB decimal.

#### BGE-M3

- Recall@1: `0.8824`;
- Recall@3: `0.9412`;
- MRR: `0.9265`;
- GPU query p50: ~23.4 ms;
- peak CUDA allocation: ~2.33 GB decimal.

BGE was faster and stronger at rank 1, but Qwen used roughly 1 GB less GPU memory and retained all positive memories within the top 3.

### Qwen JARVIS-specific optimization

A JARVIS-memory-specific query instruction plus 256-dimensional output measured:

- Recall@1: `0.8824`;
- Recall@3: `1.0000`;
- MRR: `0.9412`;
- query p50: ~63 ms;
- 256-dimensional vectors (4x smaller than 1024-d for derived vector storage/search).

### First-stage hybrid fusion

Equal-weight Reciprocal Rank Fusion (RRF) over FTS5 + Qwen-256 measured:

- Recall@1: `0.9412`;
- Recall@3: `1.0000`;
- MRR: `0.9608`;
- end-to-end p50: ~61.6 ms;
- p95: ~67.0 ms.

A semantic-weight sweep demonstrated that no single global static weight safely resolved every disagreement, so the design does not overfit a static fusion weight to the small corpus.

### Second-stage reranking

`Qwen/Qwen3-Reranker-0.6B` over the top 3 fused candidates measured:

- candidate recall: `1.0000`;
- Recall@1: `1.0000`;
- Recall@3: `1.0000`;
- MRR: `1.0000`;
- rerank p50: ~68.8 ms in the initial top-3 harness;
- end-to-end p50: ~130.9 ms;
- end-to-end p95: ~150.0 ms;
- combined embedder + reranker peak CUDA allocation: roughly 2.35 GiB in the initial reranker harness.

Top-5 reranking regressed Recall@1 to `0.9412`, so the selected candidate window is **3**.

### BF16 versus FP32 reranker precision

| Precision | Recall@1 | Recall@3 | MRR | p50 | p95 | Peak CUDA | Exact top-score ties | Order/repeat instability |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Default BF16 | 1.0000 | 1.0000 | 1.0000 | 68.33 ms | 76.00 ms | ~2.31 GiB | 2 | 0 |
| Forced FP32 | 1.0000 | 1.0000 | 1.0000 | 62.40 ms | 67.88 ms | ~3.48 GiB | 0 | 0 |

BF16 remained fully deterministic across repeats/reversed candidate order. FP32 cost about 1.17 GiB additional peak CUDA allocation merely to remove deterministic exact-score ties.

### Selected retrieval technology

```text
structured / temporal / authority / sensitivity filtering
        |
        +---- exact deterministic lookup when possible
        |
        v
SQLite FTS5 lexical rank
        +
Qwen3-Embedding-0.6B semantic rank
(JARVIS memory instruction, 256-d)
        |
        v
Equal-weight RRF (research k=60)
        |
        v
Top 3 eligible candidates
        |
        v
Qwen3-Reranker-0.6B CrossEncoder
(default BF16)
        |
        v
exact-score tie -> RRF rank -> stable ID
        |
        v
JARVIS policy/context assembler
```

### Boundaries

- no dedicated vector database selected;
- embeddings are derived/rebuildable;
- no production reranker-score/abstention threshold has been invented;
- broad automatic semantic prompt injection remains calibration-gated;
- retrieval never overrides source authority, temporal state, sensitivity, correction, or forget.

---

## 3. Structured memory-candidate extraction — COMPLETE / PROVISIONAL PROVIDER TIE

Detailed result:

- `docs/research/STEP_4_MEMORY_EXTRACTION_PROVISIONAL_TIE.md`

### Fixed corpus

The 24-case corpus covered:

- explicit remember;
- direct facts;
- weak preference/transient/style distinctions;
- mood;
- historical change;
- correction;
- forget;
- retraction;
- assistant/web/email poisoning;
- quoted-memory traps;
- uncertain future statements;
- episode decisions;
- self/incident observations;
- secrets;
- stale external-source conflicts;
- English/Hindi/Hinglish.

### OpenAI Terra full run

`gpt-5.6-terra` completed all 24 cases:

- schema valid: `24/24`;
- intent accuracy: `0.9167`;
- candidate-type accuracy: `0.9167`;
- durable flag accuracy: `1.0000`;
- core exact: `0.8750`;
- false durable writes: `0`;
- missed durable candidates: `0`;
- explicit-operation recall: `0.8750`;
- untrusted-source handling: `1.0000`;
- secret policy: `1.0000`;
- p50 latency: ~2136.6 ms;
- p95 latency: ~3389.3 ms.

The three non-exact cases were taxonomy/lifecycle-label disagreements; they did not create unsafe durable writes on the corpus.

### Gemini shared evidence

`gemini-3.8-flash` successfully completed the first five shared/evaluable cases before free-tier quota blocked the remaining 19.

On the same five shared cases:

- Terra: `5/5` core-exact;
- Gemini: `5/5` core-exact;
- false durable writes: `0` for both;
- missed durable candidates: `0` for both.

### Disposition

**PROVISIONAL QUALITY TIE ON SHARED EVIDENCE.**

This is not a claim that Gemini passed the full 24-case suite. It means provider selection remains swappable and does not block the architecture.

Selected extraction architecture:

```text
accepted text
 -> MemoryCandidateExtractor protocol
 -> provider-native structured output
 -> explicit Pydantic validation
 -> MemoryCandidate
 -> JARVIS MemoryPolicy
```

Provider output is proposal only. Schema validity never implies truth.

---

## 4. SQLCipher + Windows DPAPI encryption/package gate — COMPLETE

Detailed current-engine result:

- `docs/research/STEP_4_SQLCIPHER_417_WINDOWS_RESULT.md`

### Selected current engine/build direction

- SQLCipher `4.17.0 community`;
- SQLite baseline `3.53.3`;
- SQLCipher source commit `810db22f575ee7cf94ea96a3e91622b5fcece3dc`;
- `sqlcipher3` wrapper commit `14fc263`;
- Python 3.11 x64 Windows;
- JARVIS package version `0.6.2+jarvis.sqlcipher4170`;
- random 32-byte database key;
- Windows DPAPI user-scope + purpose binding.

First substantive CI build produced:

`sqlcipher3-0.6.2+jarvis.sqlcipher4170-cp311-cp311-win_amd64.whl`

SHA-256 for that exact artifact:

`a2eb76cdb067df0d1354b29a8b2dca046b148482b11659e6c4df40c40031489b`.

### Security/functional assertions — PASS

The current-engine harness passed:

- SQLCipher active;
- DPAPI round trip;
- wrong-purpose rejection;
- raw key absent from sealed blob;
- FTS5 English/Hindi;
- canonical write/read;
- memory temp store;
- secure delete;
- WAL;
- cipher integrity;
- no synthetic plaintext/key leakage in DB/WAL/SHM/key artifacts;
- standard SQLite without key blocked;
- wrong SQLCipher key blocked;
- same-user/same-machine encrypted backup/restore;
- deliberate ciphertext corruption detected;
- forget removes canonical + FTS representations;
- final leak scan clean;
- enhanced `cipher_memory_security=ON` subprocess probe passed on 4.17.0.

### Disposition

**KEEP SQLCIPHER 4.17.0 + DPAPI.**

Do not use the older published Windows wheel as the production default merely because installation is easier. Use the pinned/reproducible current-engine JARVIS build path and retain/hash-verify accepted artifacts.

Portable disaster recovery remains explicitly deferred; the proven local key model is same-user/same-machine.

---

## 5. Self-knowledge / CycloneDX + Capability Registry — COMPLETE

Detailed result:

- `docs/research/STEP_4_SELF_KNOWLEDGE_SBOM_WINDOWS_RESULT.md`

Successful Windows research run measured:

- CycloneDX specification: `1.7`;
- `cyclonedx-bom==7.3.1` tool path;
- target-runtime SBOM components: `92`;
- research capability declarations: `8`;
- authoritative source fingerprints: `45`;
- failed validation checks: `[]`.

### Selected self-knowledge authority model

```text
current runtime/config
    = current configured truth

accepted repo architecture/ADR/policy/code/tests
    = declared architecture truth

JARVIS Capability Registry
    = stable product capability semantics/references

CycloneDX SBOM
    = generated dependency evidence

verified incident/episode memory
    = learned historical evidence

learned observation/inference
    = lower-authority evidence only
```

### Disposition

**KEEP CYCLONEDX 1.7 + MAINTAINED GENERATOR + JARVIS-OWNED CAPABILITY REGISTRY.**

Do not build a custom dependency scanner/SBOM format or let an LLM-generated capability list become truth. Self-repair/self-modification remains outside Step 4.

---

## 6. Async encrypted DB access research — DISPOSITIONED

Normal `aiosqlite.connect()` constructs a standard-library `sqlite3` connection and therefore is not selected for the SQLCipher production store.

The final architecture uses a thin JARVIS thread-affinity async adapter over the proven synchronous `sqlcipher3` DB-API:

- one serialized writer connection on a dedicated single worker;
- initially one read/retrieval connection on its own worker;
- short transactions;
- WAL;
- extraction/embedding/reranking outside DB transactions.

The adapter owns scheduling/thread affinity only, not database semantics.

No ORM or new async-SQLCipher framework is introduced without measured value.

---

## 7. Research closure checklist

- [x] requirements and lifecycle research;
- [x] memory-framework landscape research;
- [x] SQLite bitemporal correctness spike;
- [x] SQLite/FTS reference + real-machine latency spike;
- [x] multilingual retrieval/model/fusion/reranker technology selection;
- [x] OpenAI/Gemini memory-candidate extraction bake-off and provider tie disposition;
- [x] SQLCipher/DPAPI Windows encryption architecture proof;
- [x] current SQLCipher 4.17 reproducible Windows build/security gate;
- [x] CycloneDX SBOM + JARVIS Capability Registry self-knowledge spike;
- [x] async encrypted DB boundary disposition;
- [x] consolidated final Step-4 technology decision;
- [x] final architecture proposal prepared for human approval;
- [ ] larger abstention/confidence calibration — implementation/acceptance gate, not technology-selection blocker;
- [ ] implicit auto-admission precision threshold — implementation/acceptance gate, default remains OFF;
- [ ] exact retained custom SQLCipher 4.17 artifact rerun on owner PC — implementation packaging acceptance;
- [ ] human architecture approval;
- [ ] production implementation;
- [ ] real-human acceptance;
- [ ] documentation reconciliation/ADR/protected-main merge.

## Immediate disposition

**STEP-4 TECHNOLOGY RESEARCH IS COMPLETE. THE NEXT LIFECYCLE GATE IS HUMAN APPROVAL OF `STEP_4_ARCHITECTURE_PROPOSAL.md`.**

No production Step-4 memory implementation begins before that approval.