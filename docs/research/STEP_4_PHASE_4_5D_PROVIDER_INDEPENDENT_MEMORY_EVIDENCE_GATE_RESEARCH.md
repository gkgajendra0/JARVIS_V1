# Step 4 Phase 4.5D — Provider-Independent Memory Evidence Gate Research

## Status

Research-first architecture direction after fresh V3 `FAIL_CALIBRATION` and the quota-only Gemini 3.8 diagnostic interruption.

This document is architecture research, not acceptance evidence and not Phase 4.5E authorization.

## Problem restatement

The durable-memory system already stores structured semantic truth, but current retrieval primarily ranks whole assertion text after deterministic current/authority/sensitivity eligibility. Fresh V3 exposed two distinct failure modes:

1. candidate starvation / relation confusion in multilingual factual lookup;
2. semantic release mistakes on near-miss, ambiguity, unsupported-source, and historical-scope queries.

The final memory trust contract must not depend on whichever conversational brain/provider happens to be active.

## Existing JARVIS assets that should be preserved

The canonical semantic assertion already carries:

- `subject_scope`;
- `subject`;
- `predicate`;
- typed value;
- `valid_from` / `valid_to`;
- current/system lifecycle state;
- source provenance / authority;
- sensitivity;
- verification and freshness metadata.

The initial schema already has an index over:

`(subject_scope, subject, predicate, state, system_to, valid_to)`.

Therefore no new vector database, graph database, or framework is required merely to perform structured filtering.

The accepted Qwen embedding + hybrid FTS/dense retrieval + Qwen reranker remain useful after deterministic narrowing.

`ContextAssembler` remains the sole release boundary for model context.

## External research findings

### Metadata filtering before semantic retrieval is a mature pattern

Haystack documents query-time metadata filtering as a way to narrow a retriever to the relevant subset before similarity ranking. LangChain's self-query retriever uses an LLM to construct metadata filters and then executes filtered retrieval. The architectural idea is mature even though JARVIS does not need either framework as a dependency.

References:

- https://docs.haystack.deepset.ai/docs/metadata-filtering
- https://docs.langchain.com/oss/python/integrations/document_loaders/docugami

### 2026 structure-guided RAG research supports this direction

Recent ACL work on exact/structure-guided retrieval identifies the same failure mode seen in JARVIS V3: vector similarity alone introduces semantic noise and does not ensure that all conditions of factual queries are satisfied. Structured constraints are used before/with retrieval to improve exact factual matching.

Reference:

- https://aclanthology.org/2026.acl-long.1873/

### Local information-extraction options exist, but should not be selected prematurely

GLiNER/GLiNER2 provide local schema-driven entity and relation extraction, including relation extraction and structured extraction. They are viable future local adapters, but introducing another model is not justified until the lightweight JARVIS-native structured-query contract is proven insufficient.

References:

- https://github.com/fastino-ai/GLiNER2
- https://github.com/urchade/GLiNER

### Temporal parsing can use mature local tooling

`dateparser` supports absolute and relative dates across more than 200 locales and includes Hindi. It is a better candidate for explicit date/as-of expressions than custom date parsing, subject to a small JARVIS-specific Hinglish bake-off before adoption.

Reference:

- https://dateparser.readthedocs.io/en/latest/

## Selected architectural direction

### Core principle

The conversational brain may interpret the user's language, but it does not own memory truth, lifecycle, eligibility, or release authority.

The brain/provider is replaceable. The memory evidence contract is stable.

### Proposed flow

```text
natural user query
    ↓
MemoryQueryInterpreter / tool-call adapter
    ↓ proposal only
MemoryQueryPlan
    ↓
JARVIS MemoryQueryPolicy + canonical facet validation
    ↓
Deterministic authority / sensitivity / lifecycle / temporal / metadata constraints
    ↓
Constrained FTS5 + Qwen dense retrieval
    ↓
Qwen reranker inside the constrained candidate set
    ↓
MemoryEvidenceGate
    ↓
TrustedMemoryEvidence OR ABSTAIN
    ↓
ContextAssembler
    ↓
active BrainProvider (Gemini / OpenAI / future/local)
```

## New contracts

### `MemoryQueryPlan`

A typed query proposal, never authority. Initial fields:

- `mode`: exact factual lookup vs unsupported/ambiguous vs explicitly historical/as-of;
- `subject_scope`;
- `subject`;
- `predicate`;
- `temporal_scope`: current / historical / as_of / unspecified;
- optional `as_of` timestamp;
- optional requested relation phrase / qualifier for audit/debugging;
- interpreter provenance (provider/model/local adapter) for diagnostics only.

The model must not be allowed to choose authority classes, sensitivity classes, source trust, or secret policy.

### `MemoryFacetCatalog`

JARVIS-owned view of the currently eligible canonical metadata values that may be selected by a query interpreter:

- allowed subject scopes;
- allowed subjects;
- allowed predicates.

A provider may select from this catalog but cannot invent a new canonical filter value at query time.

### `MemoryQueryPolicy`

Deterministic validation of a proposed plan:

- rejects unknown subject/predicate values;
- rejects conflicting or incomplete exact-fact plans;
- current auto-context path permits current assertions only;
- explicit historical/as-of requests use a separate controlled path and must never silently fall through to current evidence;
- secret/local-only/untrusted rules remain policy-owned and cannot be relaxed by the interpreter;
- invalid/ambiguous plans fail closed.

### `RetrievalConstraints`

Extend `SemanticRetrievalService` with optional exact metadata constraints independent of `RetrievalEligibility`:

- `subject_scope`;
- `subject`;
- `predicate`;
- later, explicit time/as-of constraints when the historical path is implemented.

The SQL constraints are applied before lexical/dense ranking. Existing authority/sensitivity/current-state filtering remains mandatory.

### `MemoryEvidenceGate`

Provider-independent release service. It owns orchestration, not canonical mutation.

Inputs:

- natural query;
- validated `MemoryQueryPlan`;
- fixed retrieval eligibility appropriate to the destination (cloud/local).

Outputs:

- typed trusted evidence with assertion ID, subject, predicate, value, provenance references and release reason; or
- typed abstention with deterministic reason code.

The initial architecture should not require a cloud semantic verifier in order to release an exact structured match. An optional `SemanticJudge` protocol may remain as an additional guard for future broad/semantic memory modes, but it is not canonical authority and is not coupled to `BrainProvider`.

## Provider independence

The query interpreter should use a fixed JARVIS protocol. Adapters may include:

- active-brain structured tool/JSON adapter;
- Gemini adapter;
- OpenAI adapter;
- future local GLiNER/other adapter;
- deterministic/local resolver for simple exact cases.

Changing the brain must not modify:

- SQL schema/lifecycle;
- retrieval eligibility;
- metadata constraints;
- `MemoryEvidenceGate` policy;
- `ContextAssembler` release rules.

A provider failure or quota exhaustion must fail closed rather than weaken the memory policy.

## Why this is preferable to importing LangChain/Haystack

Their metadata-filter/self-query pattern is appropriate, but JARVIS already has:

- an encrypted SQLite canonical store;
- the required structured fields;
- exact current/lifecycle semantics;
- hybrid retrieval;
- reranking;
- provider abstractions.

Adding a large RAG framework would duplicate established components and expand dependency/runtime surface. We should adopt the mature pattern, not the framework.

## Expected code changes

### New modules

Likely:

- `src/jarvis/memory/query_plan.py`
  - `MemoryQueryPlan`
  - `MemoryQueryMode`
  - `MemoryTemporalScope`
  - `MemoryFacetCatalog`
  - `MemoryQueryInterpreter` protocol
  - deterministic validation/policy

- `src/jarvis/memory/evidence_gate.py`
  - `MemoryEvidenceGate`
  - `TrustedMemoryEvidence`
  - `MemoryEvidenceAbstention`
  - deterministic reason codes

Provider-specific query-interpreter adapters should be isolated from these core modules.

### Modify

- `src/jarvis/memory/retrieval.py`
  - add typed metadata constraints;
  - apply exact subject/scope/predicate filters before FTS/dense ranking;
  - preserve current authority/sensitivity logic and RRF behavior.

- `src/jarvis/memory/context.py`
  - no wiring yet in 4.5D;
  - 4.5E will later accept only `TrustedMemoryEvidence` from the gate.

- provider adapter area
  - reuse the same provider-swappable structured-output design already used by Phase 4.4 memory candidate extraction rather than binding query planning to Gemini.

### Database migration

No schema migration is currently required for the first structured-gate implementation because the needed fields and composite lookup index already exist.

A predicate/alias registry should be considered only if development evidence shows uncontrolled predicate synonym drift in real admitted memory. Do not add it preemptively.

## Development sequence before any fresh acceptance

1. Freeze typed query-plan / evidence contracts and fail-closed policy.
2. Add metadata constraints to retrieval with unit tests proving filters are applied before ranking.
3. Build a provider-independent query-interpreter adapter contract.
4. Use only exposed/retired development data to test the new architecture.
5. Specifically test the V3 failure families:
   - Hindi `archive_destination`;
   - Hindi `signin_method`;
   - near-miss relation qualifiers;
   - ambiguous relation;
   - unsupported source;
   - explicit historical request against current-only release.
6. If the structured architecture resolves the failure families without weakening security, freeze it.
7. Generate a completely fresh acceptance corpus/version only after architecture freeze.
8. 4.5E remains blocked until that fresh acceptance passes.

## Non-goals

Do not:

- bind memory truth to Gemini, OpenAI, or any conversational brain;
- add another cloud semantic judge merely to improve the old architecture;
- add a graph/vector database;
- add LangChain/Haystack as a dependency solely for metadata filtering;
- change accepted Qwen model revisions or Torch/Torchvision;
- weaken canonical current/forget/secret/local-only/untrusted rules;
- expose retired V3 validation;
- start 4.5E before the new 4.5D architecture is freshly accepted.

## Decision

Proceed with a provider-independent `MemoryQueryPlan` + deterministic metadata-constrained `MemoryEvidenceGate` architecture. Treat model/tool query interpretation as a replaceable proposal adapter, not as authority. Preserve Qwen hybrid retrieval/reranking inside the deterministically narrowed candidate set.
