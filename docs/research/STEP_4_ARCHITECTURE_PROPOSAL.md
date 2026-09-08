# Step 4 — Live Context and Personal Memory Architecture Proposal

## Status

**ARCHITECTURE PROPOSAL — HUMAN APPROVAL REQUIRED BEFORE PRODUCTION IMPLEMENTATION.**

This proposal is the architecture gate that follows the completed Step-4 technology research. It does not modify `docs/CURRENT_ARCHITECTURE.md` because that file intentionally describes only accepted architecture that exists on protected `main`.

If approved, this document becomes the implementation blueprint. A durable ADR and `CURRENT_ARCHITECTURE.md` reconciliation occur only through the normal acceptance lifecycle.

Companion decision:

- `docs/research/STEP_4_FINAL_TECHNOLOGY_DECISION.md`

---

# 1. Goal

Build one JARVIS-owned context and memory system that provides useful continuity across conversations while preserving truth, privacy, freshness, correction, deletion, provider replaceability, and future self-diagnosis foundations.

Step 4 must deliver:

- CAP-008 Live Session Context;
- CAP-009 Long-Term Personal Memory;
- CAP-010 Episodic Memory;
- CAP-011 Semantic Memory;
- CAP-012 Reflection and Session Learning;
- CAP-013 Emotional Interaction Context.

It also lays the knowledge foundation for future self-diagnosis without implementing autonomous repair or self-modification.

---

# 2. Non-negotiable invariants

The implementation is invalid if any of these are violated.

1. **One durable memory owner.** `MemoryService` is the only production mutation facade for canonical Step-4 memory.
2. **Conversation ownership does not move.** `ConversationSession` remains the JARVIS owner of accepted conversation turns/lifecycle.
3. **Provider IDs are never canonical JARVIS IDs.**
4. **Live context is not durable memory.** Session state expires unless an explicit governed memory path accepts information.
5. **Models propose; JARVIS decides.** No extractor/reflection/retrieval model writes canonical truth directly.
6. **Retrieval does not establish truth.** Semantic similarity may rank only already-eligible canonical records.
7. **Explicit current owner input wins over stale/inferred memory.**
8. **Historical change, correction, retraction, and forget are different lifecycle operations.**
9. **Forget is physical for normal memory content.** Canonical content and derived FTS/embedding representations are removed; audit must not retain forgotten plaintext.
10. **Secrets are not normal memory/context.**
11. **Self-knowledge current truth comes from authoritative sources.** Memory cannot overwrite current runtime/config/code/accepted architecture.
12. **Context release has one owner.** `ContextAssembler` is the only Step-4 component that releases memory/self-knowledge to the model.
13. **No raw transcript archive.** Minimal evidence is retained only when needed for provenance.
14. **No duplicate vector/graph brain.** Derived indexes are rebuildable and disposable.
15. **Step 4 grants no new execution authority.** Identity/authority rules from Step 3 remain unchanged.
16. **Autonomous repair/code changes are out of scope.**

---

# 3. Top-level architecture

```text
                          JARVIS conversation runtime
                                    |
                         accepted provider item
                                    |
                                    v
                         ConversationSession
                  canonical accepted conversation truth
                  session_id / turn_id / accepted_at
                                    |
              +---------------------+----------------------+
              |                                            |
              v                                            v
         LiveContext                               Memory ingress
      RAM / session only                     explicit operation or
  goal/topic/entities/current                     candidate extraction
 constraints/unresolved work                         |
 transient interaction state                        v
              |                         MemoryCandidateExtractor
              |                         OpenAI / Gemini adapters
              |                         provider-native structured output
              |                                    |
              |                                    v
              |                           Pydantic candidate
              |                                    |
              |                                    v
              |                              MemoryPolicy
              |                         trust / sensitivity /
              |                      lifecycle / admission rules
              |                                    |
              |                                    v
              |                              MemoryService
              |                         sole durable write owner
              |                                    |
              |                                    v
              |                         SQLCipher 4.17 / SQLite
              |                      + FTS5 + derived embeddings
              |                                    |
              |                              MemoryRetriever
              |                      exact -> FTS+Qwen -> RRF
              |                      -> top3 Qwen reranker
              |                                    |
              +------------------+-----------------+
                                 |
                                 v
                         ContextAssembler
                 authority + temporal + freshness
                  + sensitivity + relevance + budget
                                 |
                    +------------+-------------+
                    |                          |
                    v                          v
            eligible memory            SelfKnowledgeProvider
                                      runtime/config/repo/ADRs
                                      capability registry/SBOM
                                      verified incidents
                    \                          /
                     +------------------------+
                                 |
                                 v
                     bounded turn-scoped packet
                                 |
                                 v
                         realtime provider
```

The provider receives evidence for reasoning; it never becomes the canonical memory store.

---

# 4. Ownership boundaries

## 4.1 `ConversationSession` — accepted conversation truth

Existing `src/jarvis/conversation.py` remains authoritative for accepted user/assistant conversation items.

Before durable memory is enabled, add JARVIS-owned provenance:

- `session_id` — stable per JARVIS conversation session;
- `turn_id` — stable per accepted turn;
- `accepted_at` — timezone-aware UTC timestamp;
- optional `external_item_id` / provider metadata for diagnostics/dedupe only.

Use standard UUID generation unless later evidence requires another ID format.

The conversation layer must not import a memory framework.

## 4.2 `LiveContext` — transient working state

Owns current-session working context only.

Examples:

- current task/goal;
- active project/topic;
- current entities;
- current-session constraints/corrections;
- unresolved question/next step;
- bounded recent accepted turns;
- transient interaction/emotion signal.

No automatic persistence on session close.

## 4.3 `MemoryService` — canonical durable memory truth

Only public mutation facade for:

- remember;
- historical change;
- correction;
- merge;
- supersede;
- retract;
- verify;
- expire;
- forget;
- accepted episode creation.

No provider adapter/store/retriever calls SQL mutation methods directly outside this service boundary.

## 4.4 `MemoryPolicy` — deterministic admission/lifecycle policy

Owns source trust and allowed transition decisions.

The policy is deterministic code/config, not an LLM prompt.

It decides whether a validated candidate is:

- rejected;
- quarantined/pending;
- accepted as a new semantic assertion;
- merged with an existing assertion;
- interpreted as historical change;
- correction;
- retraction;
- forget operation;
- episode candidate.

## 4.5 `MemoryRetriever` — ranking only

Receives already-eligible records or query constraints.

It may rank with exact lookup, FTS5, embeddings, RRF, and reranking. It cannot change lifecycle state or source authority.

## 4.6 `ContextAssembler` — sole context-release owner

Combines LiveContext, canonical memory, and authoritative self-knowledge into a bounded provider packet.

No other Step-4 component should independently append durable memory into provider context.

## 4.7 `SelfKnowledgeProvider` — authority-aware aggregation

Not a second database or agent.

It resolves self-knowledge from:

- current runtime/configuration;
- accepted repository architecture/code/ADRs/policies/tests;
- declarative Capability Registry;
- generated CycloneDX inventory;
- verified incident/episode memory;
- lower-authority learned observations.

---

# 5. Proposed production package boundaries

```text
src/jarvis/
  conversation.py                 # existing owner; add provenance IDs/timestamps

  security/
    __init__.py
    dpapi.py                      # neutral Windows DPAPI primitive
    key_material.py               # secure random key lifecycle / purpose constants

  memory/
    __init__.py
    types.py                      # enums/value objects/domain contracts
    provenance.py                 # source/provenance objects
    live_context.py               # RAM/session state
    candidates.py                 # MemoryCandidate contracts
    policy.py                     # deterministic admission/lifecycle rules
    service.py                    # sole durable mutation facade
    store.py                      # MemoryStore protocol
    sqlcipher_store.py            # canonical SQLCipher/SQLite implementation
    db_worker.py                  # thin thread-affinity async adapter
    migrations.py                 # migration runner / schema version
    retrieval.py                  # exact/FTS/semantic/RRF orchestration
    embedding.py                  # Qwen embedding adapter + derived cache
    reranker.py                   # Qwen reranker adapter
    context.py                    # ContextAssembler / release packet
    self_knowledge.py             # authority-aware aggregation
    capability_registry.py        # declarative registry loader/validator
    extraction.py                 # MemoryCandidateExtractor protocol
    extractors/
      __init__.py
      openai.py
      gemini.py

  memory/migrations/
    0001_initial.sql
    ...
```

Names may receive minor implementation-level refinement, but ownership boundaries above are architectural.

### Security refactor rule

The existing DPAPI primitive in `jarvis.identity.crypto` has already been proven. Do not clone it.

Implementation should extract/generalize the common DPAPI/key-protection primitive behind `jarvis.security`, then have both identity and memory depend on that neutral boundary. Preserve existing identity behavior/tests during the move.

---

# 6. Canonical data model

Do not use one giant JSON memory table.

The schema should use relational constraints and explicit lifecycle fields while allowing JSON only for typed values/payloads where useful.

## 6.1 `memory_source`

Purpose: minimum durable provenance needed to explain why a memory exists.

Proposed fields:

```text
source_id             TEXT/UUID PRIMARY KEY
source_class          TEXT NOT NULL
canonical_ref         TEXT NOT NULL
source_created_at     TIMESTAMP NULL
observed_at            TIMESTAMP NOT NULL
authority_class       TEXT NOT NULL
sensitivity           TEXT NOT NULL
evidence_text         TEXT NULL
evidence_hash         TEXT NULL
external_ref          TEXT NULL
created_at            TIMESTAMP NOT NULL
```

Rules:

- `canonical_ref` points to JARVIS session/turn/event/config/document/etc.;
- provider item IDs may appear only as optional external metadata;
- evidence text is the minimum supporting span, not full transcript storage;
- an evidence hash supports integrity/deduplication but never substitutes for authority.

## 6.2 `semantic_assertion`

Purpose: canonical versioned semantic facts/preferences/rules/state.

Proposed fields:

```text
assertion_id          TEXT/UUID PRIMARY KEY
subject_scope         TEXT NOT NULL
subject               TEXT NOT NULL
predicate             TEXT NOT NULL
value_type            TEXT NOT NULL
value_json            TEXT NOT NULL
normalized_text       TEXT NOT NULL
source_id             TEXT NOT NULL REFERENCES memory_source
valid_from            TIMESTAMP NULL
valid_to              TIMESTAMP NULL
system_from           TIMESTAMP NOT NULL
system_to             TIMESTAMP NULL
last_verified_at      TIMESTAMP NULL
state                 TEXT NOT NULL
supersedes_id         TEXT NULL
verification_state    TEXT NOT NULL
confidence            REAL NULL
freshness_class       TEXT NOT NULL
sensitivity           TEXT NOT NULL
created_at            TIMESTAMP NOT NULL
updated_at            TIMESTAMP NOT NULL
```

Candidate states include `ACTIVE`, `SUPERSEDED`, `RETRACTED`, `EXPIRED`. Deleted/forgotten content should not remain as a normal assertion state; it is physically removed.

Create a safe canonical query/view such as `current_semantic_fact` so callers do not repeatedly invent temporal predicates.

## 6.3 `episode`

Purpose: meaningful past event/outcome/decision/incident, not raw-turn history.

Proposed fields:

```text
episode_id            TEXT/UUID PRIMARY KEY
episode_type          TEXT NOT NULL
title                 TEXT NOT NULL
summary               TEXT NOT NULL
occurred_from         TIMESTAMP NULL
occurred_to           TIMESTAMP NULL
recorded_at           TIMESTAMP NOT NULL
scope                 TEXT NULL
project               TEXT NULL
component             TEXT NULL
capability_id         TEXT NULL
outcome               TEXT NULL
lesson                TEXT NULL
state                 TEXT NOT NULL
sensitivity           TEXT NOT NULL
verification_state    TEXT NOT NULL
created_at            TIMESTAMP NOT NULL
updated_at            TIMESTAMP NOT NULL
```

Use an `episode_source` join table when multiple provenance sources support one episode.

Incident episodes must be able to summarize:

```text
symptom -> evidence -> suspected/confirmed cause -> attempted actions
-> accepted repair -> validation -> outcome -> rollback information
```

Raw logs remain observability data, not durable memory.

## 6.4 `memory_candidate`

Purpose: quarantine/staging for model-generated proposals.

Proposed fields:

```text
candidate_id          TEXT/UUID PRIMARY KEY
source_id             TEXT NOT NULL
candidate_type        TEXT NOT NULL
intent                TEXT NOT NULL
payload_json          TEXT NOT NULL
extractor_provider    TEXT NOT NULL
extractor_model       TEXT NOT NULL
schema_version        TEXT NOT NULL
confidence            REAL NULL
proposed_at           TIMESTAMP NOT NULL
admission_state       TEXT NOT NULL
rejection_reason      TEXT NULL
resolved_memory_id    TEXT NULL
```

Candidate records are excluded from normal canonical recall until accepted.

Retention policy should prune rejected/transient candidates rather than accumulating them indefinitely.

## 6.5 `memory_operation`

Purpose: lifecycle/audit metadata without retaining forgotten plaintext.

Proposed fields:

```text
operation_id          TEXT/UUID PRIMARY KEY
operation_type        TEXT NOT NULL
target_kind           TEXT NOT NULL
target_id             TEXT NULL
source_id             TEXT NULL
occurred_at           TIMESTAMP NOT NULL
reason_code           TEXT NULL
result_state          TEXT NOT NULL
content_fingerprint   TEXT NULL
```

For explicit forget, retain only non-content operational metadata if policy allows. Do not retain the forgotten value/evidence text in an audit payload.

## 6.6 `memory_embedding`

Purpose: rebuildable semantic retrieval representation inside the encrypted database.

```text
memory_id             TEXT NOT NULL
memory_kind           TEXT NOT NULL
model_id              TEXT NOT NULL
model_revision        TEXT NOT NULL
dimension             INTEGER NOT NULL
vector_blob           BLOB NOT NULL
source_version        TEXT NOT NULL
created_at            TIMESTAMP NOT NULL
PRIMARY KEY(memory_id, model_id, model_revision)
```

Vectors are normalized float payloads. They are derived, purgeable, and rebuildable.

## 6.7 FTS5

Maintain derived FTS5 indexes for accepted semantic assertions and eligible episodes.

The implementation may use external-content FTS or explicitly synchronized tables, whichever gives the clearest tested delete/rebuild semantics.

Mandatory property: explicit forget results in zero normal FTS hits and zero derived embedding records for the forgotten content.

---

# 7. Temporal lifecycle algorithms

## 7.1 New accepted fact

```text
source -> validate -> policy accept
 -> insert source
 -> insert ACTIVE assertion
 -> derive FTS / embedding
```

## 7.2 Historical change

Example: `old provider` really was used until T2; `new provider` is used from T2.

```text
old assertion.valid_to = T2
old assertion.state = SUPERSEDED
new assertion.valid_from = T2
new assertion.state = ACTIVE
new.supersedes_id = old.id
```

The old assertion remains legitimate historical truth.

## 7.3 Correction

Example: owner says a stored value was inaccurate.

The previous belief is closed on the **system/record timeline** and replaced by the corrected assertion. It must not automatically be represented as something that was genuinely true historically.

Old system-time queries may still explain what JARVIS believed then, subject to privacy policy; current truth uses the corrected assertion.

## 7.4 Retraction

Close the prior assertion as invalid/retracted without manufacturing a replacement value. Normal current or historical-truth retrieval excludes it.

## 7.5 Forget

Within one governed transaction/operation boundary:

1. resolve target content;
2. delete dependent embedding rows;
3. delete FTS representation;
4. delete canonical assertion/episode content;
5. delete removable provenance/evidence content associated only with forgotten memory;
6. preserve only non-content operational metadata allowed by policy;
7. verify zero canonical + zero derived hits;
8. checkpoint/maintenance as appropriate without blocking the conversational critical path longer than necessary.

JARVIS must not say “forgotten” until the durable operation has succeeded.

---

# 8. Source trust and admission policy

Initial source classes and policy direction:

| Source | Durable behavior |
|---|---|
| Explicit OWNER `remember` | high-authority explicit operation after validation |
| Explicit OWNER correction/change | high-authority lifecycle operation |
| Explicit OWNER `forget` | high-authority deletion operation |
| Direct accepted OWNER/user fact or stable preference | candidate; implicit auto-admission initially disabled |
| Reflection/inference | candidate/hypothesis only |
| Assistant/model output | cannot establish personal truth by itself |
| Web/email/file/repository/tool content | untrusted for personal truth writes by default |
| Current runtime/config | authoritative dynamic self-knowledge source, not copied into personal memory as current truth |

Step-3 identity/authority evidence may later inform whether an operation is attributed to OWNER, but Step 4 does not promote any shadow biometric threshold or change execution authority.

---

# 9. Sensitivity policy

Initial vocabulary:

```text
STANDARD
PRIVATE
LOCAL_ONLY
SECRET_PROHIBITED
```

## `STANDARD`

Ordinary accepted memory. May be released to the configured model when relevant and allowed.

## `PRIVATE`

Encrypted local memory. Cloud release requires stronger relevance/minimization policy and must never be bulk-injected.

## `LOCAL_ONLY`

May participate in local deterministic/retrieval reasoning but must not cross the provider boundary.

## `SECRET_PROHIBITED`

Passwords, API keys, tokens, recovery secrets, and equivalent credential material are rejected from the normal memory/context system.

Source trust and sensitivity are separate dimensions. A statement may be explicit/high-authority but still local-only or prohibited.

---

# 10. LiveContext design

`LiveContext` is a bounded in-memory state object keyed to `session_id`.

Proposed state:

```text
session_id
active_goal
action/topic/project
entities
current_constraints
current_session_corrections
unresolved_items
recent_turn_refs
interaction_signal
updated_at
```

Rules:

- recent text is bounded;
- session correction immediately affects current interaction even before durable lifecycle processing where appropriate;
- inferred mood/emotion receives short session lifetime only;
- closing/failing the session clears the transient state;
- no automatic durable dump at shutdown;
- future persisted crash-resume context is a separate measured feature, not part of first implementation.

---

# 11. Memory extraction flows

## 11.1 Explicit memory command

For explicit `remember`, `correct`, `forget`, or memory inspection:

```text
accepted user turn
 -> explicit intent path
 -> structured candidate / deterministic parse where safe
 -> MemoryPolicy
 -> MemoryService durable operation
 -> verify result
 -> only then acknowledge success
```

This is synchronous with respect to the user's claim of success.

## 11.2 Implicit direct fact/preference

```text
accepted user turn
 -> user-facing response may proceed
 -> process-local candidate extraction
 -> validated candidate
 -> candidate quarantine
```

Initial rollout: **automatic durable admission OFF**.

The implementation/acceptance corpus must establish an owner-approved false-write threshold before the feature flag can be enabled.

## 11.3 Reflection/session learning

Reflection may summarize decisions, incidents, outcomes, or possible long-lived facts into candidates. It cannot establish canonical truth directly.

---

# 12. Retrieval architecture

## 12.1 Eligibility first

Before ranking, resolve:

- subject/scope;
- source authority;
- current/historical query intent;
- active/superseded/retracted state;
- valid-time/system-time constraints;
- freshness/last verification;
- sensitivity/context-release policy.

## 12.2 Exact deterministic lookup

Known fact keys/current-state questions should use canonical indexed SQL first.

Examples:

- currently selected configuration;
- one explicit preference key;
- latest accepted project state where a structured key exists.

## 12.3 Hybrid semantic path

When deterministic lookup is insufficient:

1. FTS5 lexical candidate ranking;
2. Qwen3-Embedding-0.6B query embedding, JARVIS retrieval instruction, 256d;
3. exact semantic rank from the process-local derived embedding matrix/cache;
4. equal RRF fusion (`k=60` research starting value);
5. top 3 candidates;
6. Qwen3-Reranker-0.6B BF16;
7. exact-score tie preserves RRF rank, then stable ID.

## 12.4 Derived embedding cache

At startup/lazy initialization:

- read accepted derived vectors from encrypted SQLCipher;
- build a contiguous NumPy matrix and stable ID mapping;
- apply incremental updates after accepted writes/forget;
- if cache is missing/corrupt, rebuild from canonical records/model;
- cache is never a truth source.

A realistic corpus-scale benchmark is mandatory before broad automatic semantic injection. If this exact-index path stops meeting resource/latency targets, only then benchmark an ANN/vector-engine derivative.

## 12.5 Abstention gate

No production reranker threshold exists yet.

Until larger calibration passes:

- deterministic facts may be automatically injected when unambiguous and eligible;
- explicit “what do you remember about X?” can return bounded candidates with provenance;
- broad semantic auto-injection remains feature-gated when confidence/ambiguity cannot be established safely.

---

# 13. ContextAssembler and provider integration

The model should receive a small evidence packet, not the memory database.

Conceptual packet:

```text
Live working context
- current goal / unresolved work / current-session constraint

Relevant accepted memory
- compact fact or episode summary
- whether current/historical
- source class
- verification/freshness metadata when material

Relevant self-knowledge
- direct authoritative current value/reference when needed

Conflict note
- explicit current user statement outranks older memory
```

## Turn-scoped injection

Integrate at the LiveKit user-turn boundary before response generation.

Preferred behavior:

```text
user turn completed
 -> update LiveContext
 -> determine context need
 -> bounded retrieval/self-knowledge lookup
 -> ContextAssembler
 -> add evidence to current turn context
 -> provider generates response
```

Do not persist the retrieved packet into provider history by default.

Static JARVIS instructions remain managed separately from dynamic memory evidence.

The exact pinned LiveKit `1.7.1` hook/context behavior must be covered by integration tests for OpenAI and Gemini realtime adapters before acceptance.

---

# 14. Self-knowledge architecture

```text
                     SelfKnowledgeProvider
                             |
       +---------------------+---------------------+
       |                     |                     |
current runtime/config   declared architecture    dependency inventory
(authoritative current)  repo/ADRs/policies       CycloneDX 1.7
                         capability registry
       |                     |                     |
       +---------------------+---------------------+
                             |
                  verified incident episodes
                             |
                  learned observations
                  (lower authority/evidence)
```

## Capability Registry

Production registry should minimally declare:

- stable capability ID;
- purpose;
- lifecycle state (`accepted`, `shadow`, etc.);
- authority effect (`none`, `evidence`, `governed_execution`);
- implementation references;
- dependencies;
- configuration/hardware requirements;
- structured health/test references;
- accepted ADR/source references;
- known limitations.

No raw arbitrary shell command fields, secrets, tokens, or free-form executable payloads.

## Drift

Authoritative path fingerprints may detect that a derived self-knowledge snapshot is stale. Drift detection triggers refresh/diagnostic evidence only; it grants no repair authority.

---

# 15. Database/key lifecycle

## 15.1 Location

Use a config-driven local application path, with the default architecture direction equivalent to:

```text
%LOCALAPPDATA%\JARVIS\memory\memory.db
%LOCALAPPDATA%\JARVIS\memory\memory.key.dpapi
```

Exact path names are implementation configuration, not hard-coded product semantics.

## 15.2 First initialization

1. create secure memory directory;
2. generate 32 random bytes from OS CSPRNG;
3. seal with DPAPI user scope and purpose `memory-sqlcipher-master-key-v1`;
4. persist only the sealed blob;
5. open SQLCipher with raw 256-bit key syntax;
6. run migrations;
7. verify expected SQLCipher/SQLite/FTS capabilities;
8. close raw-key references as soon as practical.

## 15.3 Connection hardening

At connection initialization, validate/apply the researched security posture:

- expected SQLCipher current engine/version policy;
- `cipher_memory_security=ON` where supported by the accepted 4.17 build;
- `temp_store=MEMORY`;
- `secure_delete=ON`;
- WAL;
- strong synchronous durability suitable for low-write personal memory;
- normal production WAL checkpointing (do not reuse the leak harness's intentionally disabled auto-checkpoint setting).

Do not execute full integrity scans on every conversational query. Use startup/maintenance/diagnostic health paths according to measured cost.

## 15.4 Backup

First production acceptance supports only the proven encrypted same-user/same-machine backup/restore model.

Portable recovery is explicitly deferred/unsupported unless separately designed and owner-approved.

---

# 16. Failure behavior

Memory must degrade safely without breaking basic JARVIS conversation unnecessarily.

## Store unavailable / key unwrap failure

- mark durable memory unavailable;
- do not silently create a new empty database over the old path;
- do not fall back to plaintext SQLite;
- basic conversation may continue without durable memory if policy permits;
- explicit remember/correct/forget reports inability to commit rather than claiming success.

## FTS/embedding derived index failure

- canonical database remains truth;
- deterministic structured lookup continues where possible;
- rebuild derived index/cache;
- do not delete canonical memory merely because a derived index is corrupt.

## Embedding/reranker unavailable

- fall back to deterministic + FTS5 retrieval;
- record degraded retrieval mode;
- do not substitute an unapproved remote embedding provider automatically.

## Extraction provider unavailable

- explicit operations may use deterministic handling where unambiguous or report inability to interpret safely;
- implicit extraction is skipped/deferred as a candidate process;
- no uncontrolled provider fallback that changes privacy policy.

## Self-knowledge source stale/unavailable

- current runtime/config must not be answered from stale durable memory as if current;
- report unknown/degraded where authority cannot be resolved.

---

# 17. Observability and audit

Step 4 should expose privacy-aware structured events, not memory plaintext dumps.

Useful event categories:

- memory operation type/result;
- candidate accepted/rejected reason;
- retrieval path used: exact/FTS/hybrid/degraded;
- number of eligible/released memories;
- context token/character budget used;
- stale/superseded filtering counts;
- semantic model latency/resource mode;
- store/index health state;
- self-knowledge source/fingerprint drift;
- forget verification result.

Logs should use IDs/reason codes by default rather than full sensitive values.

---

# 18. Configuration/features

Step-4 configuration should be explicit and fail safe.

Architecture-level controls include:

```text
memory enabled
database path / sealed-key path
extraction provider/model
implicit candidate extraction enabled
implicit auto-admission enabled            # initial default false
semantic retrieval enabled
semantic automatic context injection       # calibration-gated
embedding/reranker model asset locations
context memory count/token budget
self-knowledge enabled
```

Do not create dozens of unexplained tuning knobs before measurements require them.

Provider API keys remain in the existing secret/environment boundary, not the memory database or machine-profile normal state.

---

# 19. Acceptance test architecture

Step 4 is not accepted by CRUD unit tests alone.

## 19.1 Domain/lifecycle

Test:

- stable provenance IDs;
- new fact;
- legitimate historical change;
- correction of false belief;
- retraction;
- supersession;
- verification without value change;
- expiration/freshness;
- explicit forget physical removal;
- audit contains no forgotten plaintext.

## 19.2 Retrieval

Measure:

- exact current-fact correctness;
- historical query correctness;
- relevant-memory recall;
- irrelevant injection;
- stale/superseded recall rate;
- absent-answer abstention;
- English/Hindi/Hinglish paraphrases;
- poisoned/adversarial distractors;
- p50/p95 latency;
- GPU/RAM usage;
- realistic corpus-scale exact vector-cache behavior.

## 19.3 Admission/extraction

Measure:

- false durable-write rate;
- missed explicit operation rate;
- correction/forget/retraction classification;
- secret handling;
- external-content poisoning;
- English/Hindi/Hinglish.

Implicit durable auto-admission stays OFF until this gate has an owner-approved threshold based on measured baseline.

## 19.4 Privacy/security

Test:

- SQLCipher engine/version;
- correct/wrong key;
- stdlib SQLite blocked;
- no plaintext/key leaks in DB/WAL/SHM/sealed blob;
- DPAPI purpose binding;
- `LOCAL_ONLY` never leaves provider boundary;
- `SECRET_PROHIBITED` rejected;
- backup/restore;
- corruption detection;
- owner-PC exact custom 4.17 artifact;
- forget derived-index cleanup.

## 19.5 Live/provider integration

Test on pinned LiveKit/provider stack:

- context applies to intended current turn;
- retrieved memory is not permanently duplicated into provider history by default;
- static instructions remain intact;
- interruption/barge-in behavior does not corrupt accepted turn provenance;
- provider switch does not change canonical memory semantics.

## 19.6 Self-knowledge

Test:

- current config outranks historical memory;
- repo/ADR/capability declaration outranks learned inference;
- capability dependency graph validation;
- SBOM generation;
- fingerprint drift;
- incident memory cannot override current architecture truth;
- no registry arbitrary executable payloads.

---

# 20. Implementation sequence after approval

## Phase 4.0A — provenance + neutral security boundary

- add `session_id`, `turn_id`, `accepted_at`;
- preserve provider item ID only as optional external metadata;
- extract common DPAPI/key-protection primitive to `jarvis.security` without changing accepted identity behavior;
- tests first.

**Gate:** all existing Step-1/2/3 tests remain green.

## Phase 4.1 — canonical memory kernel

- domain enums/models;
- `MemoryStore` protocol;
- thin `sqlcipher3` DB worker;
- SQLCipher initialization/key lifecycle;
- migrations/schema/views;
- `MemoryService` lifecycle operations;
- deterministic current/history queries;
- FTS5 derived index;
- explicit forget verification;
- no LLM writes yet.

## Phase 4.2 — LiveContext + ContextAssembler foundation

- session-only LiveContext;
- context release policy/sensitivity;
- turn-scoped provider integration;
- deterministic memory retrieval only at first;
- token/count budgets.

## Phase 4.3 — explicit user memory operations

Ship first useful safe behavior:

- remember;
- correct/change;
- forget;
- inspect/recall.

Real-human acceptance occurs before implicit learning is promoted.

## Phase 4.4 — structured extraction/candidate quarantine

- Pydantic contracts;
- OpenAI/Gemini extractors;
- candidate table;
- source-trust policy;
- implicit extraction feature flag;
- auto-admission remains OFF until measured acceptance.

## Phase 4.5 — semantic retrieval

- pinned Qwen embedding model;
- 256d derived vectors;
- process-local NumPy exact index;
- FTS + semantic RRF;
- top-3 BF16 reranker;
- scale benchmark;
- abstention/irrelevant-injection calibration;
- only then enable broad automatic semantic context release.

## Phase 4.6 — episodic/reflection learning

- meaningful episodes;
- project/decision/incident summaries;
- reflection candidate generation;
- no raw conversation archiving;
- no self-authoritative reflection.

## Phase 4.7 — self-knowledge foundation

- production Capability Registry;
- CycloneDX generation/adapter;
- repo/ADR/policy/test references;
- runtime/config source adapters;
- fingerprint drift;
- incident linkage;
- no autonomous repair.

## Phase 4.8 — hardening + real acceptance

- exact 4.17 owner-PC package run;
- backup/restore;
- security/privacy tests;
- multilingual/adversarial memory corpus;
- restart/index rebuild;
- extended real use;
- corrections from real behavior;
- documentation reconciliation;
- ADR;
- protected-main merge only after owner acceptance.

---

# 21. Deferred/non-blocking decisions

These are intentionally deferred because current evidence says they do not block the first correct architecture.

1. **Portable disaster recovery** — same-machine encrypted recovery only is selected now.
2. **Extraction provider winner** — Terra/Gemini remain replaceable; current shared evidence is a provisional tie.
3. **Implicit-memory auto-admission threshold** — must be measured after implementation; default OFF.
4. **Semantic abstention threshold** — must be calibrated on larger corpus; no invented logit cutoff.
5. **Dedicated vector database/ANN index** — only if exact derived cache fails scale acceptance.
6. **Persisted LiveContext crash resume** — only if real usage demonstrates need.
7. **Graph memory** — only if later relationship-heavy use cases show measurable advantage.
8. **Autonomous diagnosis/repair/self-improvement** — later governed capability, not Step 4.

---

# 22. Human approval gate

Approval of this proposal means approval of the following architectural commitments:

1. `ConversationSession` stays conversation truth owner.
2. `MemoryService` becomes the one durable memory truth owner.
3. `ContextAssembler` becomes the one Step-4 model-context release owner.
4. SQLCipher 4.17 / SQLite + FTS5 is canonical storage.
5. Windows DPAPI protects a random database key.
6. Temporal/provenance lifecycle is JARVIS-owned and bitemporal-style.
7. Models only propose candidates.
8. Explicit remember/correct/forget is implemented before implicit durable learning.
9. Implicit durable auto-admission starts disabled.
10. Qwen 256d + FTS5 + RRF + top-3 BF16 reranking is the selected semantic retrieval path, with broad automatic injection calibration-gated.
11. No vector DB is introduced without scale evidence.
12. CycloneDX + JARVIS Capability Registry provides self-knowledge foundation.
13. Self-repair/code modification remains out of scope.

**If the owner approves this architecture, the next lifecycle step is Phase 4.0A implementation on a dedicated implementation branch, beginning with provenance IDs and the neutral security boundary—not with automatic LLM memory writing.**