# Step 4 — Implementation Research and Phased Plan

## Status

**RESEARCH PROPOSAL — NOT AN APPROVED ARCHITECTURE AND NOT AUTHORIZATION TO IMPLEMENT RUNTIME MEMORY.**

This document turns the Step-4 requirements into an implementation-research plan. It is a companion to:

- `STEP_4_LIVE_CONTEXT_PERSONAL_MEMORY_RESEARCH.md`
- `STEP_4_SELF_KNOWLEDGE_CONTINUOUS_LEARNING_REQUIREMENTS.md`
- `STEP_4_TEMPORAL_FRESHNESS_PROVENANCE_REQUIREMENTS.md`

The research-first rule remains binding: use proven current technology and established patterns where they solve the problem well; keep custom JARVIS code limited to product-specific ownership, authority, policy, lifecycle, and integration boundaries.

## 1. Current JARVIS integration boundary

Current V1 already has the right place to begin:

- `src/jarvis/conversation.py` owns accepted provider-independent conversation turns and the conversation lifecycle.
- `src/jarvis/voice/livekit_session.py` converts committed provider/LiveKit conversation items into canonical JARVIS turns.
- OpenAI/Gemini/LiveKit remain conversation/provider integrations, not memory owners.
- `src/jarvis/identity/crypto.py` already contains AES-GCM envelope-encryption and Windows-DPAPI key-protection primitives, but memory must not couple directly to the identity package.

### Required provenance change before durable memory

`ConversationTurn` currently contains only role, text, and interruption state. Durable memory needs stable JARVIS provenance independent of provider IDs.

Research direction:

- add a stable JARVIS `session_id` to `ConversationSession`;
- add a stable JARVIS `turn_id` and `accepted_at` timestamp to accepted turns;
- optionally preserve a provider/external item ID as source metadata, never as canonical identity;
- use built-in UUIDs unless measurement demonstrates a real requirement for another identifier scheme;
- do not persist the entire raw voice transcript merely to obtain provenance.

If a turn results in durable memory, retain the minimum evidence span required to support the memory plus stable source references and an evidence hash.

## 2. Implementation principle: thin JARVIS policy over mature primitives

The current strongest direction is **not** a large memory framework owning JARVIS state.

Commodity technology should own commodity mechanics:

- relational transactions and indexing;
- full-text search;
- encryption;
- JSON-schema validation;
- model-generated structured candidate extraction;
- optional embeddings/vector search;
- generated dependency inventory.

JARVIS must own the product-specific part:

- what is allowed to become canonical memory;
- source authority;
- current truth versus historical truth;
- correction, supersession, retraction, expiration, verification and forgetting;
- sensitivity/context-release policy;
- self-knowledge authority;
- audit/lifecycle operations;
- provider-independent interfaces.

## 3. Technology research conclusions

### 3.1 Canonical storage: SQLite is the strongest first-cut candidate

SQLite remains the preferred technology to validate for the canonical local truth store because JARVIS V1 is a single-user, local-first Windows assistant with low write concurrency.

Useful proven properties:

- ACID transactions and relational constraints;
- no separate database service;
- WAL mode permits readers and a writer to proceed concurrently, while retaining a single-writer model;
- FTS5 supplies built-in full-text search/BM25;
- external-content FTS5 indexes can be synchronized with triggers and rebuilt from canonical tables;
- straightforward backup, inspection and migration.

This is a candidate, not yet an approved final decision.

Sources:
- https://www.sqlite.org/wal.html
- https://www.sqlite.org/fts5.html

### 3.2 Bitemporal semantics: use the solved pattern, not necessarily the heavy database

XTDB demonstrates that the temporal problem is already solved cleanly as two different timelines:

- **valid time** — when a fact is/was true in the real world;
- **system/record time** — when the database/JARVIS knew or recorded that version.

XTDB provides these semantics natively and is valuable as a reference implementation/pattern. However XTDB runs as a JVM/server-oriented database and adds a materially larger operational boundary than SQLite for the current single-machine assistant.

Research direction: adapt proven bitemporal semantics to the JARVIS canonical schema and benchmark/query them in SQLite rather than selecting XTDB merely to avoid writing temporal columns.

Sources:
- https://docs.xtdb.com/about/time-in-xtdb.html
- https://docs.xtdb.com/intro/what-is-xtdb.html

### 3.3 Candidate extraction: Pydantic contract + native provider structured output

Both current Gemini and OpenAI APIs support schema-constrained structured output. Pydantic can generate JSON Schema and validate the returned candidate.

The smallest replaceable design is therefore:

```text
accepted source text
      |
      v
MemoryCandidateExtractor protocol
      |
      +--> OpenAI structured-output adapter
      +--> Gemini structured-output adapter
      +--> future/local adapter
      |
      v
Pydantic-validated MemoryCandidate
      |
      v
JARVIS MemoryPolicy
```

The model only proposes structured candidates. Validation does **not** make a candidate true, and the extractor never gets direct database write authority.

Current direction is to avoid adopting PydanticAI/Instructor/LangGraph solely for this narrow task unless a later spike demonstrates a concrete advantage that outweighs another provider/runtime abstraction.

Sources:
- https://openai.com/index/introducing-structured-outputs-in-the-api/
- https://ai.google.dev/gemini-api/docs/structured-output
- https://pydantic.dev/docs/validation/2.12/concepts/json_schema/

### 3.4 Async SQLite access: aiosqlite is a practical candidate

`aiosqlite` executes SQLite operations through a shared worker thread/request queue per connection so database work need not block the asyncio event loop.

Research direction:

- short transactions;
- model extraction outside database transactions;
- WAL mode;
- benchmark a dedicated writer connection plus a separate read/retrieval connection so critical-path recall is not unnecessarily queued behind writes.

Source:
- https://github.com/omnilib/aiosqlite

### 3.5 Semantic/vector retrieval: optional, derived and benchmark-gated

Do not start by installing a vector database.

Retrieval ordering to measure:

1. deterministic structured/current-fact lookup;
2. authority/status/sensitivity/temporal filtering;
3. SQLite FTS5/BM25;
4. embeddings only where semantic paraphrase recall materially improves the benchmark;
5. reranking only if its measured gain justifies latency and complexity.

If vectors are justified:

- Qdrant is mature and remains a candidate derived index, never canonical truth;
- `sqlite-vec` is attractive for a one-database design but is still evolving rapidly and current alpha development/issues make it a technology to spike, not silently make foundational;
- embedding runners/models must be measured on JARVIS English/Hindi/Hinglish data rather than selected from leaderboard scores.

Sources:
- https://qdrant.tech/documentation/quick-start/
- https://github.com/asg017/sqlite-vec/blob/main/site/getting-started/installation.md

### 3.6 Encryption: required decision before storing real personal memory

SQLCipher remains the mature whole-database SQLite encryption family. Current official SQLCipher releases remain active in 2026. However the Python/Windows packaging path needs a controlled provenance/licensing spike.

A third-party `sqlcipher3` 0.6.2 package published January 2026 provides CPython 3.11 Windows x86-64 wheels, but PyPI reports those files were not uploaded using Trusted Publishing. Therefore availability alone is not sufficient reason to trust the package for JARVIS personal memory.

JARVIS already has user-scoped Windows DPAPI key-protection code. If SQLCipher is selected, a likely pattern is a random database key protected by DPAPI, but the generic crypto primitives should live behind a neutral security boundary rather than importing identity internals.

Before selection, test:

- official/commercial SQLCipher packaging versus vetted third-party build/source build;
- licensing and upgrade path;
- DPAPI-wrapped database key lifecycle;
- backup/export/recovery after OS/account changes;
- corruption and wrong-key behaviour;
- FTS/vector plaintext leakage outside the encrypted boundary.

Sources:
- https://www.zetetic.net/sqlcipher/
- https://www.zetetic.net/blog/
- https://pypi.org/project/sqlcipher3/

### 3.7 Self-knowledge: generate inventory where standards already exist

JARVIS should not manually maintain a list of every installed dependency/version. CycloneDX 1.7 / ECMA-424 already defines a machine-readable BOM format for software, hardware, services, dependencies and AI/ML models.

Research direction:

- use a generated CycloneDX SBOM as one authoritative source for installed dependency/version inventory;
- keep JARVIS-specific capability/architecture semantics in a small explicit registry/source layer;
- aggregate repo/docs/ADRs/config/runtime/capability registry/SBOM/incidents instead of duplicating all of them into free-form memory;
- learned self-observations remain evidence-backed hypotheses and cannot overwrite declared architecture.

Source:
- https://ecma-international.org/publications-and-standards/standards/ecma-424/

## 4. Proposed minimal architecture to validate

```text
accepted JARVIS conversation/event
          |
          +----> LiveContext (RAM/session/TTL)
          |
          +----> MemoryCandidateExtractor
                  (replaceable model + Pydantic schema)
                            |
                            v
                JARVIS MemoryPolicy/Lifecycle
          accept / reject / merge / supersede /
            retract / verify / expire / forget
                            |
                            v
                   Canonical Local Store
                      SQLite candidate
                    /        |         \
             structured     FTS5      provenance /
                facts       derived    operations
                  |          index
                  +----- retrieval -----+
                            |
                     ContextAssembler
                            |
               small evidence-rich packet
                            |
                    realtime provider
```

Self-knowledge should enter through a separate source-aggregation boundary:

```text
repo / architecture docs / ADRs ----\
config / current runtime ------------\
capability registry ------------------ > SelfKnowledgeProvider
CycloneDX generated inventory -------/
incident memory ---------------------/
learned observations ----------------/
```

The `SelfKnowledgeProvider` resolves authority/freshness; it is not another agent or a second canonical brain.

## 5. Canonical data-model direction

Avoid one giant generic JSON memory table. The following relational responsibilities are worth validating.

### 5.1 `memory_source`

Purpose: minimal durable provenance.

Candidate fields:

- `source_id`
- `source_class`
- `canonical_ref` (session/turn/event/document/config/etc.)
- `source_created_at`
- `observed_at`
- `authority_class`
- minimal `evidence_text` when required
- `evidence_hash`

Do not use this table as a raw transcript/provider-payload archive.

### 5.2 `semantic_fact`

Purpose: versioned personal/project/self facts.

Candidate fields:

- stable fact/version ID
- subject/scope
- predicate/key
- typed value / normalized value
- source ID
- valid-from / valid-to
- recorded/system-from / recorded/system-to
- last-verified-at
- state: active/superseded/retracted
- supersedes link
- sensitivity
- confidence/verification state

### 5.3 `episode`

Purpose: meaningful outcomes/events, not every turn.

Candidate content:

- episode type
- title/summary
- occurrence period
- source references
- project/component/entity
- decision/outcome/lesson
- sensitivity/state

Incident episodes should be able to represent:

`symptom -> evidence -> root cause -> attempted fixes -> accepted fix -> tests -> outcome`.

### 5.4 `memory_candidate`

Purpose: staging/quarantine for model proposals.

Candidate fields:

- candidate ID/type/payload
- source ID
- extractor/provider/model/version
- proposed-at
- admission state
- rejection reason

Candidate content must not be returned by normal canonical recall before acceptance.

### 5.5 `memory_operation`

Purpose: lifecycle/audit metadata.

Operations include remember, merge, supersede, retract, verify, expire and forget.

Important privacy rule: an audit trail must not retain the plaintext of a memory that the user explicitly requested to forget. It may retain non-content operational metadata if policy allows.

### 5.6 canonical views/indexes

Create safe query surfaces such as `current_fact` so callers do not have to reimplement temporal/status filters every time.

FTS/vector structures remain derived and rebuildable from accepted canonical records. Explicit forget must purge them.

## 6. Memory admission policy to validate

Start conservative and earn automation with measurement.

| Source/event | Initial policy direction |
| --- | --- |
| Explicit owner “remember this” | High-authority durable operation after validation |
| Explicit owner correction | High-authority supersede/retract operation |
| Explicit owner “forget this” | High-authority deletion operation |
| Direct stable fact/preference in accepted user speech | Candidate; auto-admit only after precision benchmark |
| JARVIS inference/reflection | Candidate/hypothesis only |
| Assistant/model output | Cannot independently establish user truth |
| Web/email/file/repository/tool content | Untrusted for personal-memory writes by default |

This is how JARVIS can continuously learn without making every sentence permanent truth.

## 7. Runtime efficiency design

### Critical response path

Keep only what is needed for the next answer:

- cheap LiveContext update;
- bounded retrieval;
- deterministic filters before broad semantic search;
- strict context/token budget;
- no long model extraction or embedding generation inside a SQLite write transaction.

### Background/non-critical path within the running process

For implicit memory candidates, extraction may be queued after the user-facing response path. This is process-local async work, not an external promise of background delivery.

### Explicit operations

For `remember`, `correct`, and `forget`, durable commit should complete before JARVIS claims that the operation succeeded.

### Cache/index strategy

- canonical SQLite rows are source of truth;
- derived FTS/vector indexes must be rebuildable;
- no duplicate ungoverned provider memory;
- cache only results whose authority/freshness rules are preserved.

## 8. Phased implementation plan

### Phase 4.0 — Contracts and bake-off harness

No runtime personalization yet.

- add/validate stable provenance IDs and timestamps;
- define Pydantic/domain contracts;
- build a synthetic JARVIS memory benchmark corpus;
- run storage/temporal/encryption/retrieval spikes;
- decide technology from measured evidence.

**Gate:** no canonical store implementation proceeds until the spikes answer the open technology questions.

### Phase 4.1 — Canonical memory kernel

- provider-independent domain models/protocols;
- migrations and canonical store;
- bitemporal semantic facts;
- provenance;
- episodes/incidents;
- lifecycle operations: merge/supersede/retract/verify/forget;
- safe current-fact queries;
- extensive unit/property tests;
- still no automatic LLM memory writing.

### Phase 4.2 — Live Context and Context Assembler

- session/TTL current context;
- recent accepted turns;
- active goal/topic/entities/unresolved work;
- strict token budget;
- no automatic durable promotion;
- integrate at the JARVIS conversation/provider boundary.

### Phase 4.3 — Explicit memory operations

Implement and validate user-visible behavior for:

- remember;
- correct/change;
- forget;
- inspect/recall what JARVIS remembers.

This produces a useful safe memory system before implicit learning is enabled.

### Phase 4.4 — Structured candidate extraction and admission policy

- MemoryCandidate schema;
- Pydantic validation;
- native OpenAI/Gemini structured-output adapters behind a protocol;
- direct-user-fact extraction;
- candidate staging/quarantine;
- source-trust rules;
- benchmark false durable-write rate before enabling any automatic admission.

### Phase 4.5 — Retrieval bake-off and optional semantic extension

Compare on real JARVIS-style English/Hindi/Hinglish cases:

- structured lookup only;
- structured + FTS5;
- embedding candidates;
- optional hybrid retrieval;
- Qdrant versus in-SQLite vector option only if vectors prove useful.

Do not let vector similarity determine current truth; temporal/authority/sensitivity/state filters remain first-class.

### Phase 4.6 — JARVIS self-knowledge foundation

- `SelfKnowledgeProvider` contract;
- authoritative repo/architecture/ADR/config/runtime sources;
- generated CycloneDX dependency inventory;
- explicit capability registry;
- incident/repair-memory linkage;
- learned observations with evidence/confidence;
- source authority/freshness resolution.

**Out of scope here:** autonomous repair, code modification, deployment or authority expansion.

### Phase 4.7 — Privacy/encryption/hardening

The encryption technology decision must occur before real personal data is trusted to the store; this phase name describes completion/hardening, not permission to defer privacy.

- encryption packaging/provenance spike;
- key protection/recovery;
- backup/restore;
- wrong-key/corruption handling;
- delete/forget verification across all derived indexes;
- memory poisoning/source-class tests;
- migration/rebuild tests.

### Phase 4.8 — Acceptance and real-use gate

Use LongMemEval/LoCoMo-inspired scenarios plus JARVIS-specific tests.

Measure at minimum:

- relevant recall;
- irrelevant injection;
- stale/superseded recall;
- correction success;
- explicit-forget zero-recall;
- provenance correctness;
- temporal questions;
- abstention when evidence is absent;
- false durable-write rate;
- poisoning/source-trust resistance;
- p50/p95 retrieval latency;
- extraction latency/cost;
- context token overhead;
- restart persistence;
- index rebuild correctness;
- English/Hindi/Hinglish behavior.

Do not invent arbitrary thresholds before establishing baselines. After the harness is measured, set acceptance thresholds from product risk and observed distributions.

## 9. Immediate research spikes before architecture approval

The next work should be narrowly scoped experiments, not feature implementation:

1. **SQLite temporal spike** — demonstrate valid/system timelines, correction, historical change, retraction and current-fact views.
2. **FTS5 retrieval spike** — exact/structured + lexical baseline on multilingual/paraphrased JARVIS cases.
3. **Structured extraction spike** — same Pydantic candidate schema through Gemini and OpenAI; measure validity, false candidates, latency and cost.
4. **Encryption spike** — verify trustworthy Windows/Python packaging, DPAPI key wrapping, backup/recovery and FTS behavior.
5. **Semantic retrieval spike only if FTS baseline misses materially useful cases** — compare lightweight/current multilingual embedding options and derived index choices.
6. **Self-knowledge spike** — generate/read CycloneDX inventory and define the smallest capability-registry/source-authority contract without duplicating repo/config truth.

Only after these spikes should Step 4 produce the final architecture/ADR for human approval.

## 10. Current proposed decision table

| Concern | Current leading direction | Status |
| --- | --- | --- |
| Canonical store | SQLite relational | Validate by spike; not approved |
| Temporal model | Bitemporal valid + system/record time | Strongly supported pattern |
| Full-text retrieval | SQLite FTS5 | Validate by bake-off |
| Vector retrieval | Optional derived index | Do not add until proven useful |
| Vector DB | Qdrant if separate index is justified | Deferred/bake-off only |
| In-SQLite vector | sqlite-vec | Experimental candidate only |
| Candidate schema | Pydantic | Strong candidate |
| Candidate extraction | Native provider structured output behind JARVIS protocol | Strong candidate |
| Async DB access | aiosqlite + WAL/short transactions | Benchmark candidate |
| Encryption | SQLCipher-family + protected key | Open security/packaging decision |
| Dependency self-inventory | CycloneDX/ECMA-424 | Strong candidate |
| Capability self-model | Small JARVIS registry + source aggregation | Needs schema research |
| Memory framework as brain | Mem0/Letta/LangGraph/etc. | Not recommended as canonical owner |
| Autonomous self-repair | Later consumer of Step-4 knowledge | Explicitly out of Step-4 runtime scope |

## 11. Architecture invariant

The implementation must preserve this invariant:

> **JARVIS may use external models/frameworks to propose, search, embed, rank, summarize or inventory information, but JARVIS itself remains the only authority that decides what canonical memory means, what is currently true, what can be released as context, what is forgotten, and how self-knowledge is trusted.**

That boundary is what lets the system improve over time without becoming locked to one provider or allowing a model/framework to silently redefine JARVIS or its user.