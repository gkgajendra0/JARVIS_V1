# Step 4 — Phase 4.4 Structured Extraction / Candidate Quarantine Decisions

## Status

**RESEARCH: COMPLETE.**

**IMPLEMENTATION: COMPLETE.**

**OWNER-PC PRODUCTION ACCEPTANCE: PASS.**

**ACTIVE CLOUD PROVIDER: GEMINI.**

**SELECTED EXTRACTION MODEL: `gemini-3.5-flash-lite`.**

**IMPLICIT DURABLE ADMISSION: OFF.**

Date finalized: 2026-09-05

Phase 4.4 introduces typed memory-candidate extraction without granting a model durable-memory authority. The extractor proposes structured evidence only; JARVIS remains the sole authority over canonical memory.

---

## 1. Research-first technology decision

Provider-native structured output was selected over a custom JSON-repair framework. Gemini structured output through the Google GenAI SDK / Interactions API is wrapped by a narrow JARVIS adapter using the production Pydantic contract.

Mature memory frameworks including LangMem, Trustcall, Mem0 and Letta were reviewed as prior art but were not adopted as canonical memory owners because JARVIS already owns SQLCipher storage, provenance, temporal lifecycle, physical forget, context release and authority policy.

Disposition: **provider-native structured output + JARVIS-owned schema/policy/lifecycle boundaries.**

Primary references:

- https://ai.google.dev/gemini-api/docs/structured-output
- https://ai.google.dev/gemini-api/docs/interactions
- https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite

---

## 2. Single active cloud-provider rule

ADR-015 governs production cloud intelligence:

> JARVIS has one active cloud-AI provider/account at a time.

The canonical selector is `JARVIS_AI_PROVIDER` / `JarvisConfig.ai_provider`.

Phase 4.4 has no independent provider selector. With Gemini active, memory extraction uses Gemini under the same Google provider/account boundary. A future whole-provider switch to OpenAI may use the existing OpenAI adapter, but production must not mix cloud-AI providers for separate subsystems.

Different model IDs inside one provider remain allowed when capability surfaces differ.

---

## 3. Selected Gemini extraction model

### `gemini-3.5-flash-lite` — SELECTED

Measured owner-PC production-aligned corpus evidence:

- 14/14 provider-eligible cases schema-valid;
- 100% intent accuracy;
- 100% candidate-type accuracy;
- 100% durable-flag accuracy;
- 100% core exact accuracy;
- zero false durable proposals;
- zero missed durable candidates;
- English 10/10, Hindi 1/1, Hinglish 3/3 core exact;
- p50 latency 1,635.857 ms;
- p95/max latency 2,414.6174 ms;
- 6,748 input + 1,293 output tokens across 14 calls;
- human payload review found the extracted semantic content sufficient for non-authoritative quarantine evidence.

The first two-case smoke exposed ambiguous provider-facing intent semantics while preserving valid structure. The production prompt taxonomy was clarified without changing model, corpus or expected answers. The identical smoke rerun passed 2/2, followed by the clean 14/14 full run.

`gemini-3.8-flash` was retained as the staged quality-ceiling escalation but was not run because Flash-Lite satisfied the required stop condition.

Full evidence:

- `docs/research/STEP_4_PHASE_4_4_GEMINI_MODEL_SELECTION.md`

---

## 4. Accepted production boundary

```text
LiveKit committed USER item
        |
        v
JARVIS canonical ConversationSession acceptance
        |
        v
exact accepted ConversationTurn observer
        |
        +-> owning-session / USER verification
        +-> explicit Phase-4.3 memory-control exclusion
        +-> deterministic obvious-secret prefilter
        |
        v
MemoryCandidateExtractor
        |
        v
active-provider structured output
        |
        v
Pydantic MemoryExtractionProposal
        |
        +-> deterministic JARVIS proposal policy
        +-> secret defense in depth
        |
        v
session/process-local MemoryCandidateQuarantine
        |
        X  NO MemoryService call
        X  NO SQLCipher canonical assertion write
        X  NO FTS write
        X  NO embedding write
        X  NO automatic durable admission
```

Extraction remains background evidence collection and does not block the conversational response path.

---

## 5. Exact-turn and source authority

Production extraction receives the exact already-canonical `ConversationTurn`; it never performs an asynchronous lookup for a later "latest user turn".

The coordinator verifies that the turn:

- is a USER turn;
- belongs to the owning `ConversationSession`;
- belongs to the same session as the quarantine.

Non-USER sources such as assistant output, web content, email content and document content do not enter this personal-memory extraction path merely because they appear elsewhere in context.

Provider output never authors canonical provenance or authority. JARVIS attaches `session_id`, `turn_id`, `accepted_at`, source class, authority class and extractor identity from runtime truth.

---

## 6. Deterministic pre-provider gates

Ordering is:

1. canonical USER turn accepted;
2. explicit Phase-4.3 memory controls are excluded and remain owned by the governed explicit tool path;
3. locally recognizable credential/secret material is rejected;
4. only the remaining turn is sent for semantic extraction.

The provider does not decide source authority.

---

## 7. Production proposal contract

`jarvis.memory.candidates.MemoryExtractionProposal` remains the canonical provider schema with:

- intent;
- candidate type;
- durable-candidate proposal flag;
- subject;
- predicate;
- value;
- temporal hint;
- sensitivity;
- confidence.

No rationale or free-form chain-of-thought field exists.

The canonical extraction instruction is `jarvis.memory.extractors.MEMORY_EXTRACTION_SYSTEM_PROMPT`; production adapters and the research harness consume the same contract.

Model confidence is evidence only. Phase 4.4 selects no confidence threshold for durable truth.

Payload review observed harmless lexical variation such as `I` / `user` / `we` and occasionally verbose predicates. Provider wording must never silently become canonical keys. Deterministic canonical subject/predicate normalization remains deferred until a future implicit durable-admission design actually needs it.

---

## 8. Quarantine semantics

The accepted quarantine is session/process-local only.

Properties:

- USER turns only;
- background extraction;
- task ownership by the session runtime;
- session close cancels in-flight extraction;
- session close physically disposes all candidate records;
- raw turn text is not duplicated into quarantine;
- logs expose bounded outcome/reason/count metadata rather than personal candidate values;
- no candidate becomes canonical memory merely because a model labels it durable.

A durable candidate table remains deferred until a measured requirement, explicit retention policy and physical-forget integration are approved together.

---

## 9. Deterministic quarantine policy

A proposal may enter temporary quarantine only when all required structural and policy conditions hold, including:

- exact canonical accepted USER source;
- not an explicit Phase-4.3 memory-control turn;
- local secret prefilter passes;
- Pydantic validation succeeds;
- proposal is not secret;
- proposal marks `durable_candidate=true`;
- intent/type is eligible for durable/change/correction/retraction/meaningful-decision/incident evidence;
- subject, predicate and value are present.

Weak preferences, session instructions, transient interaction state, uncertain future statements, deletion requests, secrets and `none` are rejected from quarantine.

There is deliberately no confidence cutoff because quarantine grants no truth authority.

---

## 10. Rollout/configuration boundary

Extraction remains opt-in configuration rather than a guessed model default.

Enabling requires:

- `JARVIS_MEMORY_ENABLED=true`;
- `JARVIS_MEMORY_CANDIDATE_EXTRACTION_ENABLED=true`;
- canonical `JARVIS_AI_PROVIDER`;
- explicit `JARVIS_MEMORY_CANDIDATE_EXTRACTION_MODEL`.

Accepted Gemini model value: `gemini-3.5-flash-lite`.

Automatic durable admission remains OFF even when extraction is enabled.

---

## 11. Production-aligned bake-off

`tools/research/step4_memory_extraction_bakeoff.py` reuses the production schema/prompt and mirrors deterministic pre-provider gates. It records schema validity, core classification accuracy, false-durable proposals, misses, language breakdown, latency and token usage and never writes canonical memory.

`tests/test_memory_extraction_research_contract.py` protects this alignment.

The staged active-provider validation is complete and follows the "smallest sufficient model inside the active provider" rule.

---

## 12. Owner-PC production acceptance — PASS

The accepted final run proved:

- Pocket3 stable WASAPI microphone preflight and NVIDIA TV output remained intact;
- wake detection -> Gemini realtime -> return-to-wake remained functional;
- ordinary declarative personal fact did not use `remember_memory` after model-facing routing hardening;
- ordinary declarative fact did not trigger a memory-confirmation question after final conversational hardening;
- Flash-Lite extraction returned successfully;
- the ordinary fact produced `outcome=quarantined` with `durable_admission=False`;
- session close logged `disposed_candidates=1`, `cancelled_tasks=0`, `quarantine_disposed=True`;
- a fresh-session explicit memory query was skipped by Phase 4.4 and routed to the governed Phase-4.3 exact lookup;
- canonical lookup returned no current memory for the synthetic predicate;
- JARVIS did not recall the synthetic value across sessions;
- CAM++ and LR-ASD stayed diagnostic/shadow only;
- prototype admission and authority behavior remained unchanged.

During acceptance an early realtime model attempt to call `remember_memory` for an implicit fact was blocked by the deterministic Phase-4.3 authorization guard. Research-first prompt/tool-description hardening removed that unnecessary call. A second refinement removed the conversational "should I remember that?" question for ordinary declarative facts. Neither change weakened deterministic memory authority.

The fresh-session explicit memory query later offered to remember the missing fact only after exact memory inspection had returned no record. No mutation occurred. This is an explicit-memory-query UX follow-up, not implicit candidate leakage, and is non-blocking for Phase 4.4.

Owner acceptance record:

- `docs/research/STEP_4_PHASE_4_4_OWNER_PC_ACCEPTANCE.md`

---

## 13. Automated validation

Coverage protects:

- exact canonical turn observation;
- observer failure isolation;
- background candidate processing;
- assistant-turn exclusion;
- session-close cancellation + quarantine disposal;
- default-OFF configuration;
- explicit extraction-model requirement;
- active-provider adapter boundary;
- production schema/prompt reuse;
- non-user pre-provider gating;
- explicit-memory-command pre-provider gating;
- local secret rejection;
- semantic correction provider eligibility;
- single active cloud-provider architecture;
- invisible ordinary-fact routing for explicit memory tools.

Final closure CI is recorded separately after the closure/documentation commits.

---

## 14. Phase 4.4 conclusion

**COMPLETE.**

Phase 4.4 successfully establishes a typed semantic-candidate shadow that can observe ordinary accepted USER turns without turning model output into personal truth.

Permanent Phase-4.4 invariants:

- models propose; JARVIS owns authority;
- implicit durable admission remains OFF;
- candidate quarantine is non-durable and physically disposed;
- `MemoryService` remains the sole durable mutation facade;
- provider history is not canonical memory;
- secrets and source authority remain deterministic local policy concerns;
- Step-3 audio/vision/authority architecture is unchanged.

Phase 4.5 semantic retrieval is now unblocked.

---

## 15. Non-goals / deferred work

Phase 4.4 does not:

- auto-admit implicit candidates;
- write candidate proposals into canonical SQLCipher storage;
- modify current assertions;
- perform semantic retrieval;
- generate embeddings;
- select semantic abstention thresholds;
- mutate provider history;
- change VAD/turn detection;
- change Step-3 biometric/authority behavior;
- enable autonomous repair/self-modification.
