# Step 4 — Live Context and Personal Memory Research

## Status

**RESEARCH IN PROGRESS — NO STEP-4 STORAGE, MEMORY FRAMEWORK, EMBEDDING MODEL, OR ARCHITECTURE IS APPROVED BY THIS DOCUMENT.**

This document records requirements recovery and current-technology research for Step 4. It is intentionally research-only. Runtime implementation must not begin until the architecture is selected and approved.

## Scope recovered from JARVIS V1

Step 4 owns:

- CAP-008 — Live Session Context
- CAP-009 — Long-Term Personal Memory
- CAP-010 — Episodic Memory
- CAP-011 — Semantic Memory
- CAP-012 — Reflection and Session Learning
- CAP-013 — Emotional Interaction Context

The permanent V1 constraints materially narrow the solution space:

1. JARVIS owns canonical personal-context and memory truth.
2. Provider history/cache is not canonical JARVIS memory.
3. Models may propose memory candidates but may not directly mutate durable canonical memory.
4. Live/session context and durable memory are separate responsibilities.
5. Not every utterance becomes durable memory.
6. Explicit current user input outranks passive inference and older memory.
7. Durable facts require provenance, timing/freshness, correction, supersession, and deletion semantics.
8. Temporary emotion/interaction state is transient by default.
9. Secrets are not normal model context.
10. Storage/retrieval/model providers must remain replaceable.
11. Full transcripts/provider payloads must not be retained merely because they are available.
12. There must be one authoritative owner for context/memory rather than a second agent or duplicate brain.

## Current repository boundary

`src/jarvis/conversation.py` already owns provider-independent accepted conversation turns and the conversation lifecycle. It does **not** currently own durable memory and there is no competing V1 memory subsystem.

One Step-4 design requirement follows from this inspection: durable provenance needs stable session/turn/event identifiers. `ConversationTurn` currently contains role, text, and interruption state only, so Step 4 must add or derive stable provenance identifiers without transferring conversation authority to a memory framework.

## Legacy lessons recovered

The old JARVIS behaviour is useful evidence, not architecture to preserve.

The legacy map preserves these product goals:

- working/session memory → live context;
- episodic memory → meaningful past events/work;
- semantic memory → durable facts/preferences with conflict handling;
- reflection → non-authoritative memory candidates;
- emotional context → temporary interaction state;
- confirmed-memory paths → selective, governed persistence.

The current old-repository `jarvis/memory.py` is specifically **not** suitable as the V1 design. It stores a JSON dictionary, overwrites facts/preferences by key, keeps a fixed recent-history list, and injects all facts/preferences into prompt context. It lacks provenance, temporal validity, confidence, supersession, selective retrieval, robust deletion semantics, and structured source trust.

## Research question: should an existing AI-memory framework own Step 4?

### Mem0

Current Mem0 provides managed and open-source memory, semantic/hybrid retrieval, metadata, update/delete APIs, and direct import with `infer=False`.

Important 2026 changes:

- the current V3 extraction path is ADD-only and retrieval is hybrid (semantic + BM25 + entity matching);
- `infer=True` asks Mem0's LLM pipeline to extract memory from conversations;
- `infer=False` can bypass extraction and store supplied content directly;
- update/delete/history APIs exist;
- graph memory is no longer part of the current OSS V3 path and is a Platform feature.

**Assessment:** useful commodity retrieval/storage ideas, but Mem0 must not become JARVIS's canonical memory authority. Its normal inferred-memory flow gives the framework/model authority to decide what becomes memory, and its own record/update semantics do not by themselves implement JARVIS's required provenance/temporal/supersession policy. `infer=False` makes Mem0 more adaptable as a derived retrieval layer, but at that point much of the product-critical memory lifecycle still belongs to JARVIS.

**Current disposition:** `ADAPT / BENCHMARK`, not canonical owner.

Sources:

- https://docs.mem0.ai/api-reference/memory/add-memories
- https://docs.mem0.ai/platform/features/direct-import
- https://docs.mem0.ai/migration/oss-v2-to-v3
- https://docs.mem0.ai/core-concepts/memory-operations/update
- https://docs.mem0.ai/core-concepts/memory-operations/delete

### Graphiti / Zep

Graphiti is an open-source temporal knowledge-graph framework. Its strongest architectural idea for JARVIS is the temporal treatment of facts: episodes are incrementally transformed into entities/relationships while old relationships can be invalidated rather than simply overwritten. The associated Zep research reports strong long-term-memory results and large latency improvements versus baselines.

This directly informs JARVIS's need for:

- event/episode provenance;
- fact validity intervals;
- distinction between when something was true and when JARVIS learned it;
- retaining useful historical truth without treating it as current truth.

However, Graphiti is a materially heavier subsystem: graph database + LLM extraction/entity resolution + graph retrieval. Current 2026 releases are active and improving, but recent release notes/issues also show extraction-hallucination defenses, Cypher-injection hardening, and MCP/queued-ingestion reliability issues. That is unacceptable as an unexamined canonical truth owner.

**Current disposition:** `ADAPT TEMPORAL MODEL`; potentially benchmark later as a **derived** episodic/context graph, not first-cut canonical storage.

Sources:

- https://help.getzep.com/graphiti/getting-started/welcome
- https://github.com/getzep/graphiti/releases
- https://arxiv.org/abs/2501.13956

### Letta

Letta is a stateful-agent runtime with agent-editable memory concepts and newer filesystem-oriented persistent memory approaches.

JARVIS already has its own conversation, provider, identity, authority, and future capability-runtime boundaries. Introducing Letta as the memory owner would effectively introduce another stateful agent/runtime and transfer memory mutation authority to that layer.

**Current disposition:** `REJECT AS STEP-4 OWNER`.

### LangGraph / LangChain memory

LangGraph usefully distinguishes thread-scoped short-term memory from long-term cross-thread stores, and its documentation discusses semantic/episodic/procedural memory.

Those are useful concepts, but adopting an agent orchestration framework solely to obtain memory would duplicate runtime/control responsibilities already owned by JARVIS.

**Current disposition:** `ADAPT CONCEPTS; REJECT AS CORE STEP-4 FRAMEWORK`.

### Cognee / Memobase

Both are relevant memory/profile systems and remain worth feature-level comparison. Their automatic extraction/profile-building behaviour is useful evidence but again cannot be allowed to become JARVIS's durable write authority.

**Current disposition:** `BENCHMARK/ADAPT ONLY` unless later research proves they can operate cleanly below a JARVIS-owned lifecycle boundary.

## Research question: canonical local storage

### SQLite + FTS5

SQLite remains the strongest first-cut candidate for the **canonical local truth store** because it provides:

- transactional relational storage;
- one local file and minimal operations burden;
- deterministic constraints and migrations;
- exact structured lookup;
- FTS5 full-text search with BM25 ranking;
- easy inspection, backup, and rebuild of derived indexes;
- no server process required.

This is not a final selection yet, but it fits JARVIS better than making a vector database or graph database the canonical truth source.

Source:

- https://www.sqlite.org/fts5.html

### Qdrant

Qdrant is mature and offers a convenient local mode plus the same conceptual API as a server deployment. It is attractive as a **derived vector index** if vector search proves necessary.

However, a second physical store introduces synchronization/rebuild work. If used, JARVIS should treat it as disposable/rebuildable from canonical records, never as the sole source of truth.

Current Qdrant local mode is intended for smaller-scale local/test use; server deployment adds operational/security surface.

**Current disposition:** `CANDIDATE DERIVED VECTOR INDEX`, not canonical store.

### LanceDB

LanceDB provides embedded vector search, FTS, filtering, and hybrid retrieval and therefore has an attractive single-process deployment model. Current issue history nevertheless shows hybrid/filter edge cases, and JARVIS's correction/supersession/provenance lifecycle maps more naturally to relational canonical data.

**Current disposition:** `BENCHMARK`, not current canonical favourite.

### pgvector/PostgreSQL

Technically strong and transactionally attractive, but unnecessarily heavy for a single-user local-first Windows assistant at the present Step-4 scale.

**Current disposition:** `DEFER` unless later scale/concurrency needs justify PostgreSQL.

## Encryption research

Whole-database encryption is desirable because Step 4 will hold personal information.

SQLCipher is the mature SQLite-compatible encryption candidate. It supports encrypted SQLite databases, keying/rekeying, page HMAC integrity checks, and encrypted database export/migration. However, Zetetic's current 2026 Python-on-Windows guidance is not turnkey: it points Python users to the commercial Windows package plus `pysqlcipher3` integration, with the Python boundary outside normal support.

Therefore SQLCipher cannot be selected blindly simply because it is mature. We still need to compare:

- SQLCipher Windows/Python packaging and licensing burden;
- Windows DPAPI-backed key handling;
- selective encrypted values versus whole-database encryption;
- operational recovery/backup implications;
- whether Windows filesystem/account protection plus field encryption is sufficient for the first local-only release.

Sources:

- https://www.zetetic.net/sqlcipher/sqlcipher-api/
- https://www.zetetic.net/sqlcipher/sqlcipher-python/

## Retrieval research

The first Step-4 design should **not** assume vector search is the answer to every memory query.

Recommended research ordering:

1. deterministic exact/structured lookup for known facts/entities/keys;
2. temporal/status/scope/privacy filtering;
3. FTS5 lexical/BM25 retrieval;
4. embeddings only where semantic paraphrase recall produces a demonstrated gain;
5. reranking only if benchmark evidence shows it is worth the latency/complexity.

This is important because personal memory is often structured. “What bike do I own?”, “what did I decide about X?”, and “what was my latest preference?” should not depend on approximate nearest-neighbour retrieval when a canonical current fact can be queried exactly.

## Embedding model research

If Step 4 requires local semantic retrieval, current strong candidates include BGE-M3 and Qwen3-Embedding.

### Qwen3-Embedding-0.6B

Current official model information:

- 0.6B parameters;
- 100+ languages;
- 32K context;
- output dimension configurable from 32 to 1024;
- Apache-2.0;
- Sentence Transformers support;
- official ONNX export is available;
- strong MTEB results for its size.

This is particularly relevant because JARVIS conversations are not guaranteed to be clean English; Hindi/Hinglish and cross-lingual retrieval matter.

Source:

- https://huggingface.co/Qwen/Qwen3-Embedding-0.6B

### BGE-M3

BGE-M3 remains a strong multilingual option:

- 100+ languages;
- up to 8192-token inputs;
- dense, sparse, and multi-vector retrieval support;
- 1024-dimensional dense embeddings.

Source:

- https://huggingface.co/BAAI/bge-m3

**Current disposition:** do not choose from leaderboard numbers alone. Build a small JARVIS-specific multilingual retrieval bake-off using English, Hindi, and Hinglish paraphrases before selecting an embedding model or deciding embeddings are required at all.

## Memory-security research

Persistent memory is now a first-class security boundary, not just a personalization feature.

2026 research demonstrates several relevant failure modes:

- a single poisoned durable write can influence many later sessions;
- systems that write/retrieve memory more aggressively can be more exploitable;
- malicious external content can cause fabricated user memories to be stored and later activated;
- persistent memory files can carry prompt-injection payloads into future sessions;
- safety degradation can increase as contaminated memory accumulates over time.

This validates a strict source-trust policy:

### Proposed source classes for research/benchmarking

1. **Explicit owner memory command** — e.g. “remember that …”
2. **Explicit owner correction/forget command**
3. **Direct user-stated fact/preference in accepted conversation**
4. **JARVIS inference/reflection** — candidate only, never self-authoritative
5. **Assistant/model output** — never evidence of a user fact by itself
6. **External tool/web/file/email/repository content** — untrusted for personal-memory writes by default

External content must never become a durable personal fact merely because an LLM saw it in context.

Research sources:

- https://arxiv.org/abs/2606.04329
- https://arxiv.org/abs/2605.15338
- https://arxiv.org/abs/2605.17830
- https://arxiv.org/abs/2607.14611

## Memory-type boundary hypothesis

This is a research hypothesis, not an approved implementation.

### Live context

In-memory/session-scoped authoritative state such as:

- current goal/task;
- active topic/entities;
- unresolved question;
- recent accepted turns required for coherence;
- pending work/decision;
- temporary interaction state.

Live context should expire naturally and should not become durable merely because the session ends.

### Semantic memory

Canonical durable user facts/preferences/state that are useful across sessions.

Each record likely needs:

- stable ID;
- subject/scope;
- predicate/key;
- typed value;
- provenance/source ID;
- source class;
- learned/recorded timestamp;
- valid-from / valid-to where meaningful;
- confidence/verification state;
- active/superseded/retracted state;
- superseded-by link;
- sensitivity class;
- created/updated timestamps.

### Episodic memory

Meaningful past events/outcomes/milestones, not raw conversation storage.

Examples:

- a project decision and why it was made;
- a completed task and result;
- a travel event;
- an issue, attempted fix, and outcome;
- a significant preference change with time context.

Research on long-conversation retrieval supports storing coherent meaningful segments/events rather than treating every raw turn as a memory unit.

### Reflection

A non-authoritative process that can produce:

- candidate facts;
- candidate episodes;
- achievements/issues/decisions/next steps;
- possible contradictions requiring resolution.

Reflection output is **not memory truth** until the JARVIS memory policy accepts it.

### Emotional interaction context

Session/TTL-bound interaction signal only. It must not become a durable label such as “the user is angry/depressed/etc.” from transient inference.

## Correction, supersession, and forgetting hypothesis

A correct memory system must distinguish these operations:

- **update/correction:** new explicit user information supersedes old current truth;
- **historical change:** old value may remain as historical truth if useful (“used to live in X, now lives in Y”);
- **retraction:** user says a prior fact was wrong, so it should not remain as historical truth merely because it once existed in the database;
- **forget/delete:** user requests erasure; canonical content and derived searchable representations must be deleted, not merely hidden from normal retrieval.

Derived FTS/vector indexes must be rebuildable and must obey deletion.

## Evaluation research

Step 4 must be evaluated as a memory system, not merely unit-tested as CRUD.

Relevant public benchmarks:

- **LongMemEval:** information extraction, multi-session reasoning, temporal reasoning, knowledge updates, abstention.
- **LoCoMo:** very long conversational memory across many sessions, QA and event summarization.
- **LoCoMo-Plus:** evaluates latent goals/constraints beyond simple factual recall.
- recent 2026 memory-safety work: poisoning and longitudinal contamination.

Sources:

- https://arxiv.org/abs/2410.10813
- https://arxiv.org/abs/2402.17753
- https://arxiv.org/abs/2602.10715

### Proposed JARVIS-specific acceptance dimensions

Do not set arbitrary numeric thresholds before measuring a baseline. The harness should at minimum measure:

- relevant-memory recall;
- irrelevant-memory injection rate;
- stale/superseded-memory recall rate;
- correction success;
- explicit-forget zero-recall verification;
- provenance correctness;
- temporal reasoning correctness;
- abstention when evidence is absent;
- false durable-write rate;
- memory-poisoning resistance by source class;
- privacy/sensitivity filter correctness;
- retrieval token budget;
- write/extraction latency;
- retrieval p50/p95 latency;
- restart persistence and index rebuild correctness.

The benchmark corpus must contain English, Hindi, Hinglish, paraphrases, corrections, preference changes, contradictions, stale facts, explicit forget requests, adversarial assistant/tool content, and multi-session events.

## Smallest architecture currently worth validating

No final architecture is selected, but current evidence points toward validating this minimal shape before adopting a larger memory platform:

```text
accepted JARVIS conversation/events
              |
              +--> LiveContext (session/TTL only)
              |
              +--> MemoryCandidateExtractor (replaceable model; proposal only)
                            |
                            v
                 JARVIS Memory Policy / Lifecycle
                    | accept / reject / merge /
                    | supersede / retract / delete
                    v
              canonical local store
                 SQLite candidate
                    |
          +---------+----------+
          |                    |
       FTS5 index        optional vector index
       derived            derived/rebuildable
          \                    /
           +---- retrieval ----+
                  policy
                    |
        small provenance-rich context packet
                    |
             realtime provider
```

The key architectural point is that commodity technology may implement storage, embeddings, search, extraction, or reranking, but **none of those components owns the truth of what JARVIS remembers**.

## Current research direction

The current strongest hypothesis is:

- **JARVIS-owned memory lifecycle/service** as sole authority;
- **SQLite** as canonical local store candidate;
- **FTS5** as baseline retrieval;
- **Qwen3-Embedding-0.6B vs BGE-M3 vs no-vector baseline** in a JARVIS multilingual bake-off;
- vector DB only as a derived index if the bake-off proves value;
- Graphiti's bi-temporal/provenance ideas adopted at the data-model level, not necessarily its full runtime;
- explicit candidate/write policy and source trust to resist memory poisoning;
- session emotion/context kept transient;
- public memory benchmarks adapted into a smaller JARVIS-specific acceptance harness.

## Research still required before architecture approval

1. Decide exact canonical data model and distinguish correction vs historical change vs retraction vs deletion.
2. Benchmark no-vector/FTS5 against local embedding candidates on JARVIS-style English/Hindi/Hinglish retrieval.
3. Decide encryption/key-management approach for Windows/Python.
4. Define memory candidate schema and deterministic acceptance/confirmation policy.
5. Define sensitivity classes and what must never be sent to a cloud provider.
6. Define live-context compaction and session-resume semantics without promoting transient state.
7. Define memory retrieval packet/budget for the realtime provider.
8. Build Step-4 benchmark scenarios before selecting thresholds.
9. Re-check whether Mem0 `infer=False` or another library offers enough commodity value as a derived index to justify the dependency over simpler SQLite-native retrieval.
10. Produce an architecture proposal/ADR only after the above evidence is collected.
