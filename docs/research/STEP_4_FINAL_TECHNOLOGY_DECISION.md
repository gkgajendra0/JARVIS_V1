# Step 4 — Final Technology Decision

## Status

**FINAL RESEARCH TECHNOLOGY DECISION — PROPOSED FOR HUMAN APPROVAL.**

**THIS DOCUMENT DOES NOT AUTHORIZE PRODUCTION STEP-4 IMPLEMENTATION.**

Step-4 technology research is complete enough to stop technology selection and move to the architecture approval gate. The remaining open items are controlled implementation/acceptance gates, not reasons to restart the technology search.

This decision consolidates the measured evidence in:

- `STEP_4_LIVE_CONTEXT_PERSONAL_MEMORY_RESEARCH.md`;
- `STEP_4_TEMPORAL_FRESHNESS_PROVENANCE_REQUIREMENTS.md`;
- `STEP_4_RETRIEVAL_TECHNOLOGY_DECISION.md`;
- `STEP_4_MEMORY_EXTRACTION_PROVISIONAL_TIE.md`;
- `STEP_4_SQLCIPHER_DPAPI_WINDOWS_RESULT.md`;
- `STEP_4_SQLCIPHER_417_WINDOWS_RESULT.md`;
- `STEP_4_SELF_KNOWLEDGE_CONTINUOUS_LEARNING_REQUIREMENTS.md`;
- `STEP_4_SELF_KNOWLEDGE_SBOM_WINDOWS_RESULT.md`;
- `STEP_4_BAKEOFF_RESULTS.md`.

The research-first rule remains binding: commodity mechanics use mature technology; JARVIS custom code is restricted to JARVIS-specific truth ownership, lifecycle, authority, privacy, context release, and integration.

---

## 1. Decision summary

The proposed Step-4 production technology foundation is:

```text
accepted JARVIS conversation / events
            |
            +--> LiveContext
            |    RAM / session scoped / transient
            |
            +--> MemoryCandidateExtractor
            |    provider-native structured output
            |    + explicit Pydantic contract
            |    + replaceable OpenAI / Gemini adapters
            |
            v
      JARVIS MemoryPolicy
      JARVIS MemoryService
            |
            v
   SQLCipher 4.17.0 Community
   SQLite relational canonical store
   + FTS5 derived lexical index
   + encrypted embedding records
            |
            v
 deterministic lookup first
        + FTS5
        + Qwen3-Embedding-0.6B / 256d
        + equal RRF
        + top-3 Qwen3-Reranker-0.6B BF16
            |
            v
      ContextAssembler
  authority/time/sensitivity/token budget
            |
            v
   turn-scoped realtime context

SelfKnowledgeProvider
  = runtime/config + accepted repo/ADRs/policies/tests
    + JARVIS Capability Registry
    + CycloneDX 1.7 dependency inventory
    + verified incident/episode evidence
```

Permanent ownership rule:

> **The model, provider, retrieval model, database library, SBOM tool, and self-knowledge source may propose, retrieve, rank, summarize, or report. JARVIS alone owns canonical memory truth and what context is released to a model.**

---

## 2. Canonical storage — SELECT SQLite relational semantics

### Decision

Use SQLite relational tables as the canonical Step-4 memory truth model.

Use FTS5 only as a derived lexical/search representation inside the same database boundary.

### Evidence

The real JARVIS Windows-machine 30,000-record bake-off demonstrated:

- required current-versus-history temporal semantics;
- historical change versus correction behavior;
- exact lookup p95 approximately `0.0186 ms`;
- English/Hindi/Hinglish FTS p95 below approximately `4.7 ms`;
- FTS5 secure-delete support;
- explicit forget reaching zero canonical rows and zero normal FTS hits;
- approximately 16.9 MB database size at the test scale.

### Rejected/deferred

Do not add as the Step-4 canonical store without new measured need:

- XTDB;
- Graphiti/Zep graph runtime;
- Qdrant;
- LanceDB;
- PostgreSQL/pgvector;
- Mem0 as memory owner;
- provider-native conversation history as memory owner.

Graphiti/Zep temporal ideas remain useful patterns, not a required runtime.

---

## 3. Temporal model — SELECT JARVIS-owned bitemporal-style lifecycle

### Decision

Use relational valid-time plus system/record-time semantics.

A memory must distinguish at minimum:

- when the information was valid/true;
- when JARVIS learned/recorded it;
- when it was last verified;
- whether it is active, superseded, retracted, expired, or deleted;
- which stronger/newer assertion superseded it;
- provenance/source authority.

### Required semantic distinctions

These operations are not aliases:

- **historical change** — old value was genuinely true before, remains historical;
- **correction** — an earlier belief was inaccurate and is replaced in JARVIS's knowledge timeline;
- **retraction** — a prior assertion is invalidated and must not be treated as historical truth merely because it was once stored;
- **forget** — canonical content and every derived searchable representation are physically removed according to policy.

### Current-truth rule

Do not implement `latest updated_at wins`.

Conceptual precedence remains:

```text
explicit current owner correction / statement
    > current authoritative runtime/config source where applicable
    > recent verified accepted memory
    > older verified accepted memory
    > inference/reflection candidate
    > external/untrusted content
```

Authority, temporal validity, state, freshness, and sensitivity are evaluated before semantic similarity.

---

## 4. Encryption — SELECT SQLCipher 4.17.0 + Windows DPAPI

### Decision

Use:

- SQLCipher `4.17.0 community`;
- SQLite baseline `3.53.3` in the researched build;
- maintained `sqlcipher3` DB-API binding surface;
- reproducible JARVIS-owned Windows build from exact upstream source commits;
- random 32-byte database key;
- Windows DPAPI user-scope protection with purpose binding;
- no plaintext key/passphrase file.

Leading build inputs from the successful research gate:

- SQLCipher source commit `810db22f575ee7cf94ea96a3e91622b5fcece3dc`;
- `sqlcipher3` wrapper commit `14fc263`;
- JARVIS package version `0.6.2+jarvis.sqlcipher4170`.

The first successful substantive wheel was:

`sqlcipher3-0.6.2+jarvis.sqlcipher4170-cp311-cp311-win_amd64.whl`

with SHA-256:

`a2eb76cdb067df0d1354b29a8b2dca046b148482b11659e6c4df40c40031489b`.

That digest identifies that exact artifact only. Future rebuilds need their own manifest/digest and verification.

### Security behavior already demonstrated

The current-engine gate passed:

- SQLCipher active;
- correct-key read/write;
- wrong-key blocking;
- standard SQLite without key blocking;
- DPAPI seal/unseal and wrong-purpose rejection;
- no raw key in sealed DPAPI blob;
- FTS5 under encryption;
- WAL;
- `TEMP_STORE=2` / memory temp behavior;
- secure delete;
- integrity checks;
- deliberate ciphertext-corruption detection;
- same-user/same-machine backup + restore;
- forget from canonical + FTS;
- synthetic plaintext/key leak scans;
- enhanced `cipher_memory_security=ON` subprocess probe.

### Recovery boundary

The selected local key architecture is intentionally **same Windows user / same machine**.

Portable disaster recovery is not silently solved by copying the encrypted database and DPAPI blob to another machine. A portable recovery/export design, if desired later, requires explicit owner approval and must not weaken the local key boundary.

---

## 5. Async database access — SELECT thin JARVIS worker adapter over `sqlcipher3`

### Decision

Do **not** use ordinary `aiosqlite.connect()` for the encrypted production store.

Current `aiosqlite` `connect()` constructs its connection using Python's standard-library `sqlite3.connect()`. Using that normal path would bypass the selected SQLCipher DB-API.

`aiosqlite.Connection` exposes a callable connector at a lower layer, but SQLCipher is not its documented first-class integration and Step 4 does not need to depend on an unsupported coupling merely to save a small amount of scheduling code.

Do not adopt the newer `aiosqlcipher` fork as a foundational dependency: the already-proven `sqlcipher3` path plus Python's standard concurrency primitives has a smaller supply-chain and maintenance surface.

### Production boundary

Implement a small JARVIS-owned asynchronous store adapter using:

- the proven synchronous `sqlcipher3` DB-API connection;
- one dedicated single-thread worker/executor for the canonical writer connection;
- initially one dedicated single-thread worker/executor for the read/retrieval connection;
- each connection created and used on its own worker thread so DB-API thread affinity is preserved;
- short transactions;
- WAL for reader/writer coexistence;
- model extraction/embedding/reranking outside database transactions.

This adapter owns only scheduling/thread affinity. It does **not** implement a database, ORM, query language, cache, or transaction system.

If future measured read concurrency justifies more readers, add a bounded read pool without changing `MemoryStore` semantics.

---

## 6. Candidate extraction — SELECT typed provider-swappable structured output

### Decision

Use:

```text
accepted source text
 -> MemoryCandidateExtractor protocol
 -> provider-native structured output
 -> Pydantic validation
 -> MemoryCandidate
 -> JARVIS MemoryPolicy
```

Pydantic must become an explicit Step-4 dependency when implementation starts rather than relying on a transitive LiveKit dependency.

### Provider disposition

Current quality evidence remains a **provisional tie**:

- OpenAI `gpt-5.6-terra`: full 24-case run completed, strong safety behavior, zero false durable writes and zero missed durable candidates on the corpus;
- Gemini `gemini-3.8-flash`: 5/5 core-exact on the same five successfully shared cases, but free-tier quota prevented a fair 24-case comparison.

Therefore:

- no final provider winner is declared;
- both remain replaceable adapters;
- provider choice is configuration, not memory architecture;
- later full Gemini evidence may break the tie without changing `MemoryCandidateExtractor` or canonical data.

### Authority boundary

Schema validity is not truth.

The extractor cannot directly write the database. It can only create a candidate for deterministic JARVIS policy/lifecycle handling.

---

## 7. Retrieval — SELECT deterministic + hybrid local retrieve/fuse/rerank

### Decision

Use the measured retrieval pipeline:

```text
eligible canonical memory
  (authority + state + time + freshness + sensitivity filters)
            |
            +--> exact deterministic lookup when possible
            |
            v
SQLite FTS5 lexical rank
        +
Qwen3-Embedding-0.6B semantic rank
JARVIS query instruction / 256 dimensions
        |
        v
Equal-weight Reciprocal Rank Fusion
research default k=60
        |
        v
Top 3 eligible candidates
        |
        v
Qwen3-Reranker-0.6B CrossEncoder
model-default BF16
        |
        v
exact score tie -> RRF rank -> stable memory ID
```

Measured top-3 reranking reached Recall@1/Recall@3/MRR = `1.0` on the fixed research corpus. Top-5 regressed, so candidate window `3` is selected for the first production implementation.

### Semantic model deployment

Make the semantic retrieval stack an explicit Step-4/local-model dependency group, not an accidental transitive dependency:

- `sentence-transformers==6.0.1` from the validated research environment;
- `transformers==5.16.1` from the validated research environment;
- Qwen model artifacts pinned/integrity-managed using the same general model-asset discipline already used elsewhere in JARVIS.

Before production merge, the implementation branch must re-check current package/model provenance and freeze exact artifact hashes/revisions rather than relying only on model names.

### No vector database

No Qdrant/LanceDB/sqlite-vec/vector service is selected.

Embeddings are a **derived representation**, not canonical truth.

Initial design:

- store normalized 256-dimensional embedding payloads and model/version metadata inside the encrypted SQLCipher database;
- maintain a process-local contiguous NumPy search matrix/cache derived from accepted eligible memory;
- exact cosine/dot-product ordering is acceptable for the first expected personal-memory scale;
- the cache/index is disposable and rebuildable from canonical accepted records.

A corpus-scale acceptance benchmark must be run before broad semantic retrieval release. If measured p95/resource behavior becomes inadequate, reopen only the **derived vector-index implementation** decision; do not reopen the canonical-store decision.

### No production abstention threshold yet

Do not invent a reranker logit cutoff.

The larger Step-4 acceptance corpus must calibrate:

- absent-answer behavior;
- ambiguous queries;
- stale/superseded near matches;
- adversarial/poisoned candidates;
- English/Hindi/Hinglish paraphrases;
- irrelevant-memory injection.

Until that gate passes, broad automatic semantic-memory prompt injection remains feature-gated. Explicit memory inspection/recall can still return bounded evidence with provenance.

---

## 8. Live context — SELECT JARVIS RAM/session ownership

### Decision

Live/session context is not a database feature and not provider history.

First implementation keeps `LiveContext` in process memory, scoped to the JARVIS conversation/session lifecycle.

It may contain only bounded working state such as:

- current goal/task;
- active topic/project/entities;
- current-session constraints/corrections;
- unresolved work/pending next step;
- recent accepted turn references/text needed for coherence;
- transient interaction/emotion signal.

### Persistence rule

Session close or process exit does **not** automatically promote LiveContext to durable memory.

A new process starts a new LiveContext. Cross-session continuity comes only from accepted durable semantic/episodic memory.

Persisted crash-resume TTL context is deferred until real use demonstrates a need.

---

## 9. Context release — SELECT one JARVIS ContextAssembler

### Decision

`ContextAssembler` is the sole boundary that decides what Step-4 information reaches the realtime model.

It combines only eligible evidence from:

- current LiveContext;
- accepted durable memory;
- authoritative self-knowledge when relevant.

Before release it enforces:

- authority/source class;
- active/retracted/deleted state;
- current vs historical temporal intent;
- freshness;
- sensitivity/local-only rules;
- relevance;
- strict memory-count/token budget;
- provenance metadata needed for conflict resolution.

### LiveKit/provider integration

Use the current LiveKit turn lifecycle to inject retrieved context **for the current response turn**, rather than permanently copying memory packets into provider conversation history.

Current LiveKit APIs support chat-context updates and per-turn context augmentation. The implementation must integration-test the exact pinned LiveKit `1.7.1` behavior for both configured realtime providers before acceptance.

Static JARVIS instructions remain separate. Do not depend on dynamically injecting `system` messages into provider chat history as the memory mechanism.

---

## 10. Sensitivity and context-release classes — SELECT explicit policy vocabulary

Step 4 needs a sensitivity class independent from source authority.

Initial architecture vocabulary:

- `STANDARD` — ordinary accepted memory; may be released to the configured model when relevant and policy permits;
- `PRIVATE` — encrypted local memory requiring stricter relevance/minimization before cloud release;
- `LOCAL_ONLY` — may be stored/retrieved locally but must not be sent to a cloud model;
- `SECRET_PROHIBITED` — credentials/tokens/password-like secret material is rejected from normal personal-memory storage/context.

Exact classifier rules are an implementation policy artifact and require tests. The architecture invariant is that `ContextAssembler` must enforce the class before any provider call.

---

## 11. Self-knowledge — SELECT CycloneDX 1.7 + JARVIS Capability Registry

### Decision

Use:

- CycloneDX `1.7` generated dependency inventory;
- `cyclonedx-bom==7.3.1` as the researched generator;
- a small JARVIS-owned declarative Capability Registry for product semantics;
- accepted repo/ADR/policy/code/test references and SHA-256 fingerprints;
- direct runtime/config reads for current dynamic truth;
- incident/episode memory for verified historical outcomes;
- learned observations only as lower-authority evidence.

The successful Windows spike measured:

- 92 installed target-runtime components;
- 8 research capability declarations;
- 45 authoritative source fingerprints;
- zero failed registry/SBOM validation checks.

### Authority rule

```text
current runtime/config
    > cached/historical runtime memory

accepted repo / architecture / ADR / capability declaration
    > generated summary
    > learned inference

verified incident evidence
    > reflection summary
    > inferred pattern
```

No self-knowledge source grants code-modification or deployment authority.

### Not Step 4

Do not implement in Step 4:

- autonomous repair;
- autonomous dependency upgrades;
- autonomous code rewriting;
- protected-main merge;
- deployment/rollback authority;
- expansion of existing authority levels.

---

## 12. What JARVIS must own versus delegate

### JARVIS owns

- accepted source/provenance identity;
- LiveContext;
- memory candidate contract;
- source-trust policy;
- admission decision;
- temporal lifecycle;
- correction/supersession/retraction/forget semantics;
- sensitivity/context-release policy;
- canonical `MemoryService` mutation boundary;
- context assembly/token budget;
- self-knowledge authority resolution;
- capability semantics;
- acceptance benchmarks and gates.

### Mature technology owns

- SQLCipher/SQLite transactions and encrypted pages;
- FTS5 lexical search;
- Python/OS concurrency primitives;
- provider-native schema-constrained generation;
- Pydantic schema validation;
- Sentence Transformers model execution;
- Qwen embedding/reranking models;
- NumPy vector math;
- CycloneDX dependency format/generation;
- Windows DPAPI local key sealing.

This is the intended research-first boundary: custom code exists only where JARVIS semantics are inherently product-specific.

---

## 13. Explicitly rejected architecture patterns

Do not build Step 4 as:

1. a large memory framework owning JARVIS truth;
2. a second stateful agent/runtime owning conversation memory;
3. provider conversation history treated as durable memory;
4. every utterance embedded and persisted automatically;
5. one generic JSON blob/table with overwrite-by-key semantics;
6. vector similarity used as truth/currentness;
7. an LLM writing the database directly;
8. external web/email/file/repo text establishing personal truth;
9. a graph/vector database introduced without measured need;
10. ordinary `aiosqlite.connect()` accidentally bypassing SQLCipher;
11. plaintext database keys or recovery passphrases stored beside the database;
12. a manually maintained dependency list instead of generated SBOM evidence;
13. an LLM-generated capability list treated as architecture truth;
14. durable mood/emotion labels inferred from transient interaction.

---

## 14. Remaining acceptance gates — not technology-search blockers

The following remain required before Step 4 can be called DONE:

1. **Exact custom SQLCipher 4.17 artifact on owner PC** — install the retained/hash-identified build in isolation and rerun the synthetic security harness once.
2. **Provenance migration** — stable JARVIS `session_id`, `turn_id`, and accepted timestamp without provider IDs becoming canonical IDs.
3. **Schema/lifecycle unit + temporal property tests** — current/history/correction/retraction/forget.
4. **LiveKit integration acceptance** — turn-scoped context on pinned `1.7.1`, both realtime providers.
5. **Semantic-scale benchmark** — process-local exact vector cache/search at realistic corpus size.
6. **Abstention/irrelevant-injection calibration** — larger multilingual/adversarial corpus before broad automatic semantic prompt injection.
7. **Implicit admission calibration** — automatic durable admission remains disabled until false-write precision is measured and accepted.
8. **Backup/recovery acceptance** — same-user/same-machine encrypted backup; portable recovery remains explicitly unsupported/deferred unless separately approved.
9. **Real human use** — remember/correct/forget/recall, stale memory, session continuity, privacy behavior.
10. **Documentation reconciliation + protected-main merge** only after owner acceptance.

These are implementation and acceptance controls. None currently justifies replacing the selected technology stack.

---

## 15. Final research disposition

**TECHNOLOGY RESEARCH: COMPLETE FOR STEP-4 ARCHITECTURE APPROVAL.**

Proposed locked foundation:

```text
Canonical store      = SQLCipher 4.17.0 / SQLite relational
Lexical index        = FTS5
Temporal semantics   = JARVIS bitemporal-style lifecycle
Async DB boundary    = thin dedicated worker(s) over sqlcipher3 DB-API
Extraction contract  = Pydantic + provider-native structured output
Extraction provider  = OpenAI/Gemini replaceable; provisional quality tie
Semantic retriever   = Qwen3-Embedding-0.6B / 256d
Fusion               = equal RRF, research k=60
Reranker              = Qwen3-Reranker-0.6B / BF16 / top 3
Vector storage       = encrypted derived embeddings + process-local NumPy exact index
Vector database      = none until scale evidence
Key protection       = Windows DPAPI user scope + purpose binding
Live context         = JARVIS RAM/session state
Context release      = one JARVIS ContextAssembler
Self-knowledge       = authoritative sources + Capability Registry + CycloneDX 1.7
Autonomous repair    = out of scope for Step 4
```

The next lifecycle gate is **human review of `STEP_4_ARCHITECTURE_PROPOSAL.md`**. Only explicit approval authorizes production Step-4 implementation.