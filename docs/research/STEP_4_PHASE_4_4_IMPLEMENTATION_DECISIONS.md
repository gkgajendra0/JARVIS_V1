# Step 4 — Phase 4.4 Structured Extraction / Candidate Quarantine Decisions

## Status

**RESEARCH REFRESH: COMPLETE.**

**IMPLEMENTATION: ACTIVE — CORE BOUNDARY + PRODUCTION-ALIGNED BAKE-OFF HARNESS BUILT.**

**IMPLICIT DURABLE ADMISSION: OFF.**

**ACTIVE CLOUD PROVIDER: GEMINI.**

**FINAL EXTRACTION MODEL: NOT YET SELECTED.**

Date refreshed: 2026-09-05

Phase 4.4 introduces typed memory-candidate extraction without granting a model durable-memory authority. The extractor may propose structured candidate evidence; JARVIS remains the only authority that may later decide whether a candidate may enter canonical memory.

---

## 1. Research-first technology decision

Current provider-native structured output support was re-checked before production integration.

### Provider-native structured output

Gemini supports schema-constrained JSON output through the current Google GenAI SDK and Interactions API. JARVIS therefore uses a thin provider adapter plus the production Pydantic schema instead of building a JSON-repair framework.

Primary references:

- https://ai.google.dev/gemini-api/docs/structured-output
- https://ai.google.dev/gemini-api/docs/interactions
- https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite

OpenAI structured-output support remains implemented behind the provider abstraction for future whole-provider switching, but it is not a Phase-4.4 production dependency while Gemini is the active JARVIS provider.

### Mature memory-framework review

LangMem, Trustcall, Mem0 and Letta remain useful prior art but are not adopted as JARVIS canonical memory owners:

- LangMem would pull lifecycle ownership toward LangChain/LangGraph;
- Trustcall is update/patch oriented while JARVIS extraction may not patch canonical truth;
- Mem0 duplicates the accepted SQLCipher/FTS5/lifecycle ownership, though its separation of extraction from update/delete is useful evidence;
- Letta would widen runtime/state ownership beyond this phase.

Disposition: **use provider-native structured output + JARVIS-owned Pydantic/policy/lifecycle boundaries.**

---

## 2. Single active cloud-provider rule

ADR-015 governs production cloud intelligence:

> JARVIS has one active cloud-AI provider/account at a time.

The canonical selector is `JARVIS_AI_PROVIDER` / `JarvisConfig.ai_provider`.

Phase 4.4 does not own an independent provider selector. When Gemini is active, memory extraction must use Gemini and the same Google API project/key used by JARVIS's other Gemini cloud workloads. If JARVIS is intentionally switched wholesale to OpenAI in the future, the extractor may use the existing OpenAI adapter under that same active-provider policy.

Different model IDs inside one provider are allowed when capabilities differ. For example, the realtime Live model and a structured-output extraction model need not be the same model ID.

Local ML and model-artifact downloads are outside this rule because they do not create a second metered cloud-intelligence provider.

---

## 3. Gemini extraction-model research refresh

### Primary candidate: `gemini-3.5-flash-lite`

Google documents Gemini 3.5 Flash-Lite as stable GA, low-latency and cost-effective, optimized for high-throughput work, subagent tasks, document parsing and simple data extraction. Structured outputs are supported.

That matches Phase 4.4's narrow classification/extraction job better than a long-horizon reasoning model.

Current pricing snapshot:

- Free Tier: free of charge within applicable quota;
- paid input: $0.30 / 1M tokens;
- paid output including thinking tokens: $2.50 / 1M tokens.

No shutdown date is currently announced.

Disposition: **TEST FIRST.**

References:

- https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite
- https://ai.google.dev/gemini-api/docs/pricing
- https://ai.google.dev/gemini-api/docs/deprecations

### Escalation candidate: `gemini-3.8-flash`

Google documents Gemini 3.8 Flash as its most intelligent stable Flash model, aimed at long-horizon software engineering, autonomous agents and complex enterprise workflows. Structured outputs are supported.

It is retained as a quality ceiling only if Flash-Lite materially fails the fixed safety/correctness corpus.

Disposition: **ESCALATION ONLY.**

Reference:

- https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash

### Excluded new commitment: `gemini-3.1-flash-lite`

Google lists an earliest shutdown date of May 7, 2027 and recommends `gemini-3.5-flash-lite` as the replacement.

Disposition: **DO NOT START A NEW PHASE-4.4 PRODUCTION COMMITMENT ON 3.1 LITE.**

---

## 4. Implemented production boundary

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
active-provider native structured output
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

Extraction is background evidence collection and does not block the conversational response path.

---

## 5. Exact-turn race prevention

Production extraction receives the exact already-canonical `ConversationTurn`; it never performs an asynchronous later lookup of "latest user turn".

The coordinator verifies that the turn:

- is a USER turn;
- belongs to the owning `ConversationSession`;
- belongs to the same session as the quarantine.

The LiveKit bridge publishes the same accepted turn object only after canonical conversation acceptance. Observer failure cannot reject or rewrite canonical conversation truth.

---

## 6. Deterministic pre-provider gates

The provider does not decide source authority.

Ordering is:

1. canonical USER turn accepted;
2. explicit Phase-4.3 memory controls are excluded and remain owned by the explicit governed tool path;
3. locally recognizable credential/secret material is rejected;
4. only the remaining turn is sent for semantic extraction.

Assistant output, web content, email content, file/document content and other non-USER sources do not enter the provider extraction path merely because they are present somewhere in context.

A semantic statement such as `Correction: I live ...` remains eligible for Phase-4.4 classification; a deterministic tool command such as `Correct my ... memory to ...` remains Phase-4.3-owned.

---

## 7. Single production proposal contract

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

The canonical system instruction is:

- `jarvis.memory.extractors.MEMORY_EXTRACTION_SYSTEM_PROMPT`

Production adapters and the research harness consume the same schema and prompt.

The extractor never authors JARVIS provenance or authority. JARVIS attaches canonical `session_id`, `turn_id`, `accepted_at`, source/authority class and extractor model identity from runtime truth.

Model confidence is evidence only. No confidence threshold is selected in Phase 4.4.

---

## 8. Quarantine semantics

The accepted quarantine is session/process-local only.

Implemented properties:

- USER turns only;
- background extraction off the response path;
- task ownership by the session runtime;
- close cancels in-flight extraction;
- close clears/disposes quarantine;
- raw turn text is not duplicated into quarantine;
- logs contain bounded outcome/reason metadata rather than personal candidate values;
- records carry JARVIS-owned turn/session provenance;
- no candidate becomes canonical memory merely because a model labels it durable.

A durable candidate table remains deferred until a measured requirement, explicit retention policy and physical-forget integration are approved together.

---

## 9. Initial deterministic quarantine policy

A proposal may enter temporary quarantine only when all of the following hold:

- source is the exact canonical accepted USER turn;
- turn is not an explicit Phase-4.3 memory-control turn;
- local secret prefilter passes;
- structured output passes Pydantic validation;
- proposal is not secret;
- proposal declares `durable_candidate=true`;
- proposal intent/type is structurally eligible for durable/change/correction/retraction/meaningful-decision/incident evidence;
- subject, predicate and value are present.

Weak preferences, session instructions, transient interaction state, uncertain future statements, deletion requests, secret proposals and `none` are rejected from quarantine.

There is deliberately no confidence cutoff because quarantine grants no truth authority.

---

## 10. Rollout gate

Candidate extraction remains default OFF.

Enabling requires all of:

- `JARVIS_MEMORY_ENABLED=true`;
- `JARVIS_MEMORY_CANDIDATE_EXTRACTION_ENABLED=true`;
- canonical `JARVIS_AI_PROVIDER` configured through normal JARVIS provider policy;
- explicit `JARVIS_MEMORY_CANDIDATE_EXTRACTION_MODEL`.

There is **no independent extraction-provider setting** and no guessed default extraction model.

Automatic durable admission remains a separate future policy decision and stays OFF even after an extraction model is selected.

---

## 11. Production-aligned bake-off

The fixed research corpus is retained, but the harness mirrors actual production gates and reuses the production schema/prompt.

`tools/research/step4_memory_extraction_bakeoff.py`:

- imports `MemoryExtractionProposal` and the production system prompt;
- validates corpus taxonomy against production enums;
- mirrors deterministic pre-provider gates;
- does not send non-user sources to the provider;
- does not send explicit Phase-4.3 command cases to the provider;
- does not send locally detected secret cases to the provider;
- sends only remaining eligible direct-user cases;
- uses `store=False`;
- records schema validity, core classification accuracy, false-durable proposals, misses, language breakdown, latency and token usage;
- never writes canonical memory.

`tests/test_memory_extraction_research_contract.py` protects this alignment in CI.

---

## 12. Staged active-provider validation

The old requirement for a comparable OpenAI-versus-Gemini production bake-off is superseded by ADR-015 and the user's one-provider requirement.

Current validation sequence:

1. test `gemini-3.5-flash-lite` on the production-aligned corpus;
2. require zero schema/provider failures and zero false durable proposals on expected non-durable provider-eligible cases;
3. human-review all core semantic mismatches, especially correction/retraction/uncertainty and Hindi/Hinglish cases;
4. measure latency and tokens without inventing an arbitrary latency threshold beforehand;
5. if Flash-Lite satisfies the safety/correctness bar, select it and stop;
6. only if Lite materially fails, run the identical corpus on `gemini-3.8-flash` and compare.

This selection is intentionally "smallest sufficient model inside the active provider," not "strongest model available anywhere."

---

## 13. Historical bake-off disposition

Older Terra-versus-Gemini extraction results remain historical technology evidence only. They predate both the final production-aligned schema/prompt and the single-active-provider rule.

They do not create an OpenAI dependency, do not require a second API account and do not select the Phase-4.4 production model.

---

## 14. Automated validation present

Coverage protects:

- exact canonical turn observation;
- observer failure isolation;
- background candidate processing;
- assistant-turn exclusion;
- session-close cancellation + quarantine disposal;
- default-OFF configuration;
- explicit extraction-model requirement;
- active-provider adapter boundary;
- production schema/prompt reuse by the research harness;
- non-user pre-provider gating;
- explicit-memory-command pre-provider gating;
- local non-explicit secret rejection;
- semantic correction remaining provider-eligible;
- single active cloud-provider/credential ownership through the repo-level architecture guard.

---

## 15. Remaining Phase-4.4 gates

Do not mark Phase 4.4 complete yet.

Remaining work:

1. keep the documented branch green in normal CI;
2. run a 2-case owner-PC `gemini-3.5-flash-lite` smoke under the existing Google API project;
3. if smoke succeeds, run the full production-aligned provider-eligible corpus on Flash-Lite;
4. select Flash-Lite if the safety/correctness bar passes, otherwise escalate to Gemini 3.8 Flash using the identical corpus;
5. run narrow owner-PC production-path acceptance with candidate extraction enabled only after the model choice is defensible;
6. verify candidate quarantine works, no candidate becomes canonical SQLCipher memory, and normal wake/Pocket3/provider behavior remains unchanged;
7. write Phase-4.4 implementation/acceptance closure;
8. only then begin Phase 4.5 semantic retrieval.

Phase 4.5 remains blocked until these gates are complete.

---

## 16. Non-goals

Phase 4.4 does not:

- auto-admit implicit candidates;
- write candidates into canonical SQLCipher storage;
- modify existing assertions;
- perform semantic retrieval;
- generate embeddings;
- mutate provider history;
- change VAD/turn detection;
- change Step-3 biometric/authority behavior;
- enable autonomous repair/self-modification.
