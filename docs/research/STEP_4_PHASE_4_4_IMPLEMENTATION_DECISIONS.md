# Step 4 — Phase 4.4 Structured Extraction / Candidate Quarantine Decisions

## Status

**RESEARCH REFRESH: COMPLETE.**

**IMPLEMENTATION BOUNDARY: APPROVED FOR BUILD.**

**IMPLICIT DURABLE ADMISSION: OFF.**

Date: 2026-09-05

Phase 4.4 introduces typed memory-candidate extraction without granting a model durable-memory authority. The extractor may propose structured candidate evidence; JARVIS remains the only authority that may later decide whether any candidate can enter canonical memory.

## 1. Research-first refresh

The pre-Step-4 bake-off already established a provider-swappable `MemoryCandidateExtractor` direction and a provisional OpenAI/Gemini tie on shared evidence. Before production implementation, current provider structured-output support and mature memory frameworks were re-checked.

### OpenAI structured outputs

Current OpenAI API documentation supports schema-constrained structured outputs and SDK-native typed/Pydantic workflows for extraction/classification use cases.

Source:

- https://developers.openai.com/api/docs/guides/structured-outputs

Disposition: **USE provider-native structured output through a thin adapter; do not build a JSON repair/parser framework.**

### Gemini structured outputs

Current Gemini API documentation supports JSON Schema structured output and Pydantic-generated schemas in the Python SDK. The current Interactions API examples use `response_format` with `application/json` plus `BaseModel.model_json_schema()`.

Sources:

- https://ai.google.dev/gemini-api/docs/structured-output
- https://ai.google.dev/gemini-api/docs/get-started

Disposition: **USE provider-native structured output through a thin adapter.**

### Pydantic

PyPI shows `pydantic==2.13.5` as the current stable release, published 2026-08-28. JARVIS already receives Pydantic transitively through LiveKit, but Phase 4.4 now relies on it directly as an architectural contract, so it must become an explicit pinned JARVIS dependency.

Source:

- https://pypi.org/project/pydantic/2.13.5/

Disposition: **PIN `pydantic==2.13.5`.**

## 2. Mature memory-framework review

### LangMem

LangMem provides memory managers and typed memory schemas and is useful prior art for background/hot-path extraction. Its latest PyPI release remains `0.0.30` from 2025-10-27 and adopting it would also pull JARVIS toward a LangChain/LangGraph-owned memory lifecycle.

Sources:

- https://pypi.org/project/langmem/0.0.30/
- https://langchain-ai.github.io/langmem/

Disposition: **REFERENCE, DO NOT ADOPT.** JARVIS already has an accepted canonical SQLCipher lifecycle, authority model, provenance contract, and provider boundary. Replacing those with a framework-owned memory manager would widen ownership rather than reduce custom work.

### Trustcall

Trustcall is designed for resilient structured extraction and JSON-patch-style updates of existing structured objects. That update-centric behavior is not the desired authority boundary: a JARVIS extractor may propose evidence but may not patch canonical personal truth.

Source:

- https://github.com/hinthornw/trustcall

Disposition: **DO NOT ADOPT.** Provider-native structured output + Pydantic is sufficient for the bounded extraction problem, while canonical update semantics remain JARVIS-owned.

### Mem0

Current Mem0 V3 documentation describes an additive extraction pipeline and a broader memory platform that owns extraction, storage and retrieval. The V3 add endpoint is single-pass ADD-only extraction; update/delete are separate memory operations.

Sources:

- https://docs.mem0.ai/api-reference/memory/add-memories
- https://docs.mem0.ai/core-concepts/memory-operations/update

Disposition: **REFERENCE, DO NOT ADOPT.** The ADD-only separation reinforces JARVIS's extraction-vs-lifecycle split, but adopting Mem0 would duplicate/compete with the accepted SQLCipher canonical store, FTS5, `MemoryService`, temporal lifecycle, and later JARVIS retrieval design.

### Letta

Letta provides persistent agent memory blocks and archival memory as part of a broader stateful agent runtime.

Sources:

- https://docs.letta.com/tutorials/attaching-detaching-blocks/
- https://docs.letta.com/api/python

Disposition: **DO NOT ADOPT.** Letta would own agent state/memory lifecycle far beyond Phase 4.4 and conflict with JARVIS's accepted conversation, memory, and authority ownership.

## 3. Selected Phase 4.4 production boundary

```text
canonical accepted USER turn
        |
        +-> deterministic source eligibility
        +-> explicit-memory-control exclusion
        +-> deterministic obvious-secret prefilter BEFORE provider
        |
        v
MemoryCandidateExtractor protocol
        |
        v
provider-native strict structured output
        |
        v
Pydantic MemoryExtractionProposal
        |
        +-> deterministic JARVIS proposal policy
        +-> deterministic secret defense in depth
        |
        v
session/process-local MemoryCandidateQuarantine
        |
        X  NO MemoryService call
        X  NO canonical SQLCipher assertion write
        X  NO FTS/embedding write
        X  NO automatic admission
```

The user-facing response path must not wait on candidate extraction once runtime integration begins. Extraction is shadow/background evidence collection, not a prerequisite for conversation.

## 4. Why the first quarantine is process/session-local

The approved architecture requires candidate quarantine but does not require candidate persistence before automatic admission exists. Persisting candidates now would create new privacy/lifecycle obligations without a measured requirement:

- a durable candidate could retain content after an owner later invokes physical forget unless forget semantics were widened;
- durable candidate retention would require an arbitrary retention duration, which would violate the measured-threshold rule;
- rejected/stale candidates would create a second durable personal-content store before a use case needs it;
- Phase 4.4 explicitly keeps automatic durable admission OFF.

Therefore the initial accepted quarantine is **session/process-local only**. It is disposed with the owning conversation/session and cannot survive a JARVIS process restart. A durable `memory_candidate` table is deferred until a measured requirement, retention policy, and physical-forget integration are jointly approved.

This is deliberately stricter than the long-term data-model sketch and avoids silently turning candidate evidence into another memory store.

## 5. JARVIS-owned metadata

The extractor is never allowed to author provenance/authority identifiers. JARVIS attaches these from canonical runtime truth:

- `session_id`;
- source `turn_id`;
- source `accepted_at`;
- source class `OWNER_DIRECT`;
- authority class `OWNER_DIRECT`;
- extractor provider/model identity;
- JARVIS candidate ID and quarantine timestamp.

The model may propose only semantic fields such as intent/type/subject/predicate/value/temporal hint/sensitivity hint/confidence.

Model confidence is evidence only. **No numeric confidence threshold is selected in Phase 4.4.**

## 6. Data minimization and secret handling

Production extraction receives only the one canonical accepted USER turn being evaluated, not the full transcript or provider history.

Before any cloud extractor call, the existing deterministic JARVIS credential/secret guard is applied to the raw turn. Obvious credentials are rejected locally and are not sent to the extraction provider.

After extraction, the same deterministic guard is applied to proposed predicate/value fields as defense in depth. `secret` proposal sensitivity and secret candidate type are never quarantined.

Raw turn text is not copied into quarantine. Quarantine keeps only the validated structured proposal plus JARVIS-owned provenance metadata.

## 7. Explicit-memory operations remain Phase 4.3 owned

Turns that already authorize/ask for explicit `remember`, `correct`, `forget`, or `inspect` are excluded from the implicit candidate extractor. This prevents a second path from competing with the accepted Phase 4.3 tool lifecycle.

## 8. Initial deterministic quarantine policy

A proposal may enter the temporary quarantine only when all of the following hold:

- source is the canonical accepted USER turn;
- the turn is not an explicit Phase 4.3 memory-control turn;
- the local secret prefilter passes;
- structured output passes Pydantic validation;
- proposal is not secret;
- proposal declares `durable_candidate=true`;
- proposal intent is one of the durable-candidate/historical-change/correction/retraction classes;
- proposal type is one of the structurally durable fact/preference/rule/change/correction/retraction/meaningful-decision/incident classes;
- subject, predicate and value are present.

Weak preferences, session instructions, transient interaction state, uncertain future statements, deletion requests, secret proposals and `none` are rejected from quarantine.

There is deliberately **no confidence cutoff**. A structurally eligible proposal with low model confidence may be quarantined as evidence because quarantine grants no truth authority. Confidence thresholds/admission rules must come from measured evaluation later.

## 9. Non-goals

Phase 4.4 does not yet:

- auto-admit any implicit candidate;
- write candidates into canonical SQLCipher storage;
- modify existing assertions;
- perform semantic retrieval;
- generate embeddings;
- mutate provider history;
- change VAD/turn detection;
- change Step-3 biometric/authority behavior;
- enable autonomous repair/self-modification.

## 10. Implementation order

1. Pin Pydantic explicitly.
2. Add typed proposal/protocol/policy/quarantine primitives and unit tests.
3. Add thin OpenAI/Gemini structured-output adapters behind the protocol.
4. Add a default-OFF extraction rollout flag and background integration after accepted USER turns.
5. Run synthetic/provider bake-offs and repository CI.
6. Require measured owner acceptance before enabling any production extraction by default.
7. Keep implicit durable admission OFF until a separate measured admission decision exists.
