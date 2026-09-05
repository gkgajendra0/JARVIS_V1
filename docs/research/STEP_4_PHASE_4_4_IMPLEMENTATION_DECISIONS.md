# Step 4 — Phase 4.4 Structured Extraction / Candidate Quarantine Decisions

## Status

**RESEARCH REFRESH: COMPLETE.**

**IMPLEMENTATION: ACTIVE — CORE BOUNDARY + PRODUCTION-ALIGNED BAKE-OFF HARNESS BUILT.**

**IMPLICIT DURABLE ADMISSION: OFF.**

**FINAL EXTRACTION PROVIDER/MODEL: NOT YET SELECTED.**

Date: 2026-09-05

Phase 4.4 introduces typed memory-candidate extraction without granting a model durable-memory authority. The extractor may propose structured candidate evidence; JARVIS remains the only authority that may later decide whether any candidate can enter canonical memory.

---

## 1. Research-first refresh

The pre-Step-4 bake-off established a provider-swappable `MemoryCandidateExtractor` direction and a provisional OpenAI/Gemini tie on shared evidence. Before and during production implementation, current structured-output support and mature memory patterns were re-checked.

### OpenAI structured outputs

Current OpenAI Responses documentation supports schema-constrained Structured Outputs and recommends JSON Schema structured output over older JSON mode. Current model documentation lists `gpt-5.6-terra` as the balanced intelligence/cost member of the GPT-5.6 family.

Sources:

- https://platform.openai.com/docs/api-reference/responses-streaming/response/content_part
- https://platform.openai.com/docs/models/gpt-4-turbo-and-gpt-4

Disposition: **USE provider-native structured output through a thin adapter; do not build a JSON repair/parser framework.**

### Gemini structured outputs

Current Gemini documentation supports JSON Schema structured output and Pydantic-generated schemas in the Python SDK. Current Interactions examples use `response_format` with `application/json` plus `BaseModel.model_json_schema()`.

Sources:

- https://ai.google.dev/gemini-api/docs/structured-output
- https://ai.google.dev/gemini-api/docs/get-started

Disposition: **USE provider-native structured output through a thin adapter.**

### LiveKit committed-item boundary

Current LiveKit AgentSession documentation exposes `conversation_item_added` when an item is added/committed to conversation history. JARVIS therefore attaches extraction downstream of canonical accepted conversation truth rather than raw/final transcription callbacks.

Sources:

- https://docs.livekit.io/agents/logic/sessions/
- https://docs.livekit.io/reference/agents/events/

Disposition: **EXTRACT FROM THE EXACT ALREADY-ACCEPTED CANONICAL USER TURN, NEVER FROM RAW TRANSCRIPTION OR A LATER `latest_user_turn` LOOKUP.**

### Pydantic

JARVIS now depends directly on `pydantic==2.13.5` as the extraction contract boundary rather than relying on a transitive install.

Disposition: **PIN `pydantic==2.13.5`.**

---

## 2. Mature memory-framework review

### LangMem

LangMem provides memory managers and typed memory schemas and is useful prior art for background/hot-path extraction. Adopting it would pull JARVIS toward a LangChain/LangGraph-owned lifecycle that competes with the already accepted SQLCipher, provenance and authority model.

Sources:

- https://pypi.org/project/langmem/0.0.30/
- https://langchain-ai.github.io/langmem/

Disposition: **REFERENCE, DO NOT ADOPT.**

### Trustcall

Trustcall focuses on resilient extraction and JSON-patch-style updates of existing structured objects. That update-centric model is not the required authority boundary because a JARVIS extractor may propose evidence but may not patch canonical personal truth.

Source:

- https://github.com/hinthornw/trustcall

Disposition: **DO NOT ADOPT.** Provider-native structured output + Pydantic is sufficient for bounded extraction.

### Mem0

Current Mem0 V3 documentation describes a single-pass ADD-only extraction pipeline while update/delete remain separate operations. JARVIS does not adopt Mem0 as canonical storage or authority, but this is useful independent evidence for separating extraction from destructive lifecycle mutation.

Sources:

- https://docs.mem0.ai/platform/features/graph-memory
- https://docs.mem0.ai/api-reference/memory/add-memories
- https://docs.mem0.ai/core-concepts/memory-operations/update

Disposition: **REFERENCE, DO NOT ADOPT.** It would duplicate the accepted SQLCipher store, FTS5, `MemoryService`, temporal lifecycle and later JARVIS retrieval design.

### Letta

Letta provides persistent agent memory/state as part of a broader agent runtime.

Sources:

- https://docs.letta.com/tutorials/attaching-detaching-blocks/
- https://docs.letta.com/api/python

Disposition: **DO NOT ADOPT.** It would widen ownership beyond the Phase-4.4 problem and conflict with JARVIS-owned conversation/memory authority.

---

## 3. Implemented production boundary

```text
LiveKit committed conversation item
        |
        v
JARVIS canonical ConversationSession acceptance
        |
        v
exact accepted ConversationTurn observer
        |
        +-> USER role / owning-session verification
        +-> explicit Phase-4.3 memory-control exclusion
        +-> deterministic obvious-secret prefilter BEFORE provider
        |
        v
MemoryCandidateExtractor protocol
        |
        v
provider-native structured output
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

The response path does not wait on candidate extraction. Extraction is background evidence collection, not a prerequisite for conversation.

---

## 4. Exact-turn race prevention

Background extraction must never re-read "the latest user turn" after another user turn may already have arrived.

The coordinator therefore accepts the exact already-canonical `ConversationTurn` object and verifies that:

- it is a USER turn;
- it belongs to the owning `ConversationSession`;
- the quarantine belongs to the same session.

The canonical LiveKit bridge publishes that same accepted turn object to observers only after conversation acceptance. Observer failure cannot reject or rewrite the conversation.

A compatibility `consider_latest_user_turn()` wrapper remains available internally, but production runtime integration uses the exact-turn API.

---

## 5. Deterministic pre-provider gates

The provider does **not** decide source authority.

Production ordering is:

1. canonical USER turn accepted;
2. detect Phase-4.3 explicit memory control and leave it to the explicit governed tool path;
3. reject locally recognizable credential/secret material;
4. invoke semantic extraction only for the remaining turn.

Assistant output, web content, email content, file/document content and other non-USER sources do not enter this Phase-4.4 provider path merely because they are available somewhere in context.

A semantic utterance such as `Correction: I live ...` is intentionally distinct from a deterministic Phase-4.3 command such as `Correct my ... memory to ...`. The former remains eligible for Phase-4.4 semantic classification; the latter remains Phase-4.3-owned.

---

## 6. Single production proposal contract

`jarvis.memory.candidates.MemoryExtractionProposal` is the canonical provider schema.

It contains:

- intent;
- candidate type;
- durable-candidate proposal flag;
- subject;
- predicate;
- value;
- temporal hint;
- sensitivity;
- confidence.

The contract deliberately contains no provider rationale/free-form chain-of-thought field.

The canonical extraction system instruction is exported as:

`jarvis.memory.extractors.MEMORY_EXTRACTION_SYSTEM_PROMPT`

Both production adapters and the research bake-off consume this same schema and prompt. This removes the earlier research/production contract drift.

---

## 7. JARVIS-owned metadata and authority

The extractor never authors provenance/authority identifiers. JARVIS attaches these from canonical runtime truth:

- `session_id`;
- source `turn_id`;
- source `accepted_at`;
- source class `OWNER_DIRECT`;
- authority class `OWNER_DIRECT`;
- extractor provider/model identity;
- JARVIS candidate ID and quarantine timestamp.

The model proposes semantic fields only. Model confidence is evidence only. **No numeric confidence threshold is selected in Phase 4.4.**

---

## 8. Quarantine semantics

The initial accepted quarantine is session/process-local only.

Properties now implemented:

- extraction is scheduled off the response path;
- USER turns only;
- pending extraction tasks are owned by the session runtime;
- close cancels in-flight extraction;
- close clears and disposes the candidate quarantine;
- raw turn text is not duplicated into quarantine;
- logs contain outcome/reason metadata, not candidate personal values;
- candidate records carry JARVIS-owned turn/session provenance;
- no candidate is canonical memory simply because a provider labeled it durable.

A durable candidate table remains deferred until a measured requirement, explicit retention policy and physical-forget integration are jointly approved.

---

## 9. Initial deterministic quarantine policy

A proposal may enter temporary quarantine only when all of the following hold:

- source is the exact canonical accepted USER turn;
- the turn is not an explicit Phase-4.3 memory-control turn;
- local secret prefilter passes;
- structured output passes Pydantic validation;
- proposal is not secret;
- proposal declares `durable_candidate=true`;
- proposal intent is structurally eligible for candidate/change/correction/retraction evidence;
- proposal type is structurally durable fact/preference/rule/change/correction/retraction/meaningful-decision/incident evidence;
- subject, predicate and value are present.

Weak preferences, session instructions, transient interaction state, uncertain future statements, deletion requests, secret proposals and `none` are rejected from quarantine.

There is deliberately **no confidence cutoff** because quarantine grants no truth authority. Any later admission threshold must be measured separately.

---

## 10. Rollout gate

Candidate extraction is **default OFF**.

Enabling requires all of:

- `JARVIS_MEMORY_ENABLED=true`;
- `JARVIS_MEMORY_CANDIDATE_EXTRACTION_ENABLED=true`;
- an explicit supported provider;
- an explicit model.

There is no guessed default extraction model.

Even after a provider/model is selected, automatic durable admission remains a separate policy decision and stays OFF unless explicitly accepted later.

---

## 11. Production-aligned bake-off

The existing 24-case research corpus is retained, but the harness has been realigned to the actual production boundary rather than carrying a second schema/prompt.

`tools/research/step4_memory_extraction_bakeoff.py` now:

- imports production `MemoryExtractionProposal`;
- imports `MEMORY_EXTRACTION_SYSTEM_PROMPT`;
- validates corpus taxonomy against production enums;
- mirrors deterministic pre-provider gates;
- never sends non-user source cases to a provider;
- never sends explicit Phase-4.3 command cases to a provider;
- never sends locally detected secret cases to a provider;
- sends only remaining eligible direct-user cases;
- uses `store=False`;
- records schema validity, core classification accuracy, false-durable proposals, misses, language breakdown, latency and token usage when available;
- never writes canonical memory.

`tests/test_memory_extraction_research_contract.py` protects this alignment in normal CI.

---

## 12. Historical bake-off disposition

`STEP_4_MEMORY_EXTRACTION_PROVISIONAL_TIE.md` remains historical evidence from the earlier research harness.

Its Terra-versus-Gemini numbers must **not** be treated as directly comparable with future production-aligned Phase-4.4 runs because the old harness:

- carried a separate extraction schema;
- included an extra rationale field;
- used a separate prompt;
- asked the provider to classify source trust for cases production now deterministically gates before the provider.

The old result remains useful as provisional technology evidence only. It does not select the Phase-4.4 production provider.

---

## 13. Automated validation now present

Coverage protects:

- exact canonical turn observation;
- observer failure isolation;
- background candidate processing;
- assistant-turn exclusion;
- session-close cancellation + quarantine disposal;
- default-OFF configuration;
- explicit provider/model configuration requirement;
- OpenAI/Gemini adapter structured-output boundaries;
- production schema/prompt reuse by the research harness;
- non-user pre-provider gating;
- explicit-memory-command pre-provider gating;
- local non-explicit secret rejection;
- semantic correction remaining provider eligible.

---

## 14. Non-goals

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

---

## 15. Remaining Phase-4.4 gates

Do **not** mark Phase 4.4 complete yet.

Remaining work:

1. keep the fully integrated documented branch green in normal CI;
2. run a fair production-aligned provider bake-off when both provider credentials/quota permit comparable evidence;
3. select provider/model only from measured quality/safety/latency/cost evidence, or retain an explicit tie if evidence remains insufficient;
4. run a narrow owner-PC production-path acceptance with candidate extraction enabled only after the provider/model choice is defensible;
5. verify no candidate becomes durable memory and normal wake/Pocket3/provider behavior remains unchanged;
6. write Phase-4.4 implementation/acceptance closure before Phase 4.5 begins.

Phase 4.5 remains blocked until these gates are complete.
