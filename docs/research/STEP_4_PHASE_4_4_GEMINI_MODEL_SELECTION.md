# Step 4 — Phase 4.4 Gemini Extraction Model Selection

## Status

**MODEL SELECTION: COMPLETE.**

**SELECTED MODEL: `gemini-3.5-flash-lite`.**

**ESCALATION MODEL `gemini-3.8-flash`: NOT RUN — staged stop condition was satisfied.**

**IMPLICIT DURABLE ADMISSION: OFF.**

Date: 2026-09-05

This record captures the production-aligned owner-PC evidence used to choose the structured memory-candidate extraction model while Gemini is the active JARVIS cloud-AI provider.

---

## 1. Selection rule

ADR-015 requires one active cloud-AI provider/account at a time. Therefore Phase 4.4 does not compare independent paid providers.

The staged rule was:

1. test the smallest suitable stable Gemini model first;
2. require zero schema failures, zero false durable proposals on expected non-durable provider-eligible cases, and no missed durable candidates;
3. inspect English/Hindi/Hinglish behavior plus per-case semantic payloads;
4. measure latency and token usage;
5. stop if Flash-Lite is sufficient;
6. run `gemini-3.8-flash` only if Flash-Lite materially fails.

Google currently positions `gemini-3.5-flash-lite` as its most cost-efficient GA model for high-volume/simple data-processing work and supports structured outputs.

References:

- https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite
- https://ai.google.dev/gemini-api/docs/structured-output
- https://ai.google.dev/gemini-api/docs/pricing

---

## 2. Initial smoke and research-first prompt correction

The first two-case owner-PC smoke proved the Gemini API/SDK/schema path but returned:

- schema valid: 2/2;
- candidate type accuracy: 100%;
- durable flag accuracy: 100%;
- intent accuracy: 0%.

The failure was investigated before changing the model. The production prompt did not define the provider-facing intent taxonomy clearly enough even though explicit Phase-4.3 memory controls are removed before the extractor.

Google structured-output guidance recommends clear schema/prompt descriptions and application-level semantic validation because schema-conformant JSON does not guarantee semantically correct values.

The production prompt was therefore clarified without changing the corpus, expected labels, provider or model.

The identical two-case rerun then returned:

- schema valid: 2/2;
- intent accuracy: 100%;
- candidate type accuracy: 100%;
- durable flag accuracy: 100%;
- core exact accuracy: 100%;
- false durable proposals: 0;
- missed durable candidates: 0;
- p50 latency: 1,980.4231 ms;
- p95/max latency: 2,229.8508 ms.

Disposition: the first failure was a production-contract ambiguity, not evidence that Flash-Lite lacked the required capability.

---

## 3. Full production-aligned owner-PC run

Owner-PC source branch head for the full run:

`00f00a762b85acfbc95331716c9a1f0eb9b65afd`

Corpus size: 24 cases.

Deterministic pre-provider gates removed cases that production would not send to the semantic extractor:

- non-user source cases: 4;
- explicit Phase-4.3 memory-control cases: 6;
- provider was called for no gated case.

Provider-eligible Flash-Lite cases executed: **14**.

Measured result:

- schema valid: **14/14**;
- schema failures: **0**;
- intent accuracy: **100%**;
- candidate-type accuracy: **100%**;
- durable-flag accuracy: **100%**;
- core exact accuracy: **100%**;
- false durable proposals: **0**;
- false durable rate among expected non-durable provider cases: **0%**;
- missed durable candidates: **0**.

Language breakdown:

- English: **10/10 core exact**;
- Hindi: **1/1 core exact**;
- Hinglish: **3/3 core exact**.

Latency:

- p50: **1,635.857 ms**;
- p95: **2,414.6174 ms**;
- max: **2,414.6174 ms**.

Token usage for all 14 calls:

- input: **6,748 tokens**;
- output: **1,293 tokens**;
- usage record complete: **yes**.

At the 2026-09-05 paid-tier price snapshot of $0.30 / 1M input tokens and $2.50 / 1M output tokens, this run is approximately **$0.00526 total**, or **$0.000376 per provider-eligible turn** before any free-tier allowance.

The free tier is currently free of charge within its applicable quota.

---

## 4. Per-case semantic payload review

The full JSON output was manually reviewed beyond the aggregate core labels.

Observed useful payloads included:

- direct ownership event -> `Jimny` with `today` temporal context;
- Hindi current residence -> `सागर` with current temporal context;
- Hinglish current bike -> `BMW G 310 GS`;
- weak off-roading interest -> correctly non-durable;
- one-answer brevity instruction -> correctly transient/session-only;
- temporary irritated mood + short-answer request -> correctly transient;
- real-world ownership change -> current `Jimny` state, historical-change classification;
- correction -> `lives_in = Sagar`;
- retraction -> `Defender` ownership claim marked as retraction evidence;
- quoted hypothetical text -> `none`, non-durable;
- uncertain future job change -> `uncertain_future`, non-durable;
- Step-3 echo test decision -> durable episode-decision evidence;
- repeated wake-detector failure after Windows device-index change -> durable incident-observation evidence.

No reviewed payload justified escalating to the more expensive Gemini 3.8 Flash model.

### Non-blocking normalization observations

Provider semantic evidence is not canonical memory. The reviewed outputs showed lexical variation such as `subject = I`, `subject = user`, `subject = we`, and occasionally verbose predicates/values.

This does not block Phase 4.4 because:

- quarantine grants zero durable truth authority;
- JARVIS attaches canonical session/turn/source/authority metadata itself;
- no candidate reaches `MemoryService` automatically;
- any future implicit durable-admission design must separately define deterministic canonical subject/predicate normalization before storage.

Do not solve this by letting the provider silently establish canonical identity/keys.

---

## 5. Safety interpretation

`secret_policy_accuracy` was not applicable in this live corpus because production-aligned deterministic gates prevented the relevant explicit secret request from reaching Gemini. This is expected behavior, not a missing safety pass.

Automated Phase-4.4 tests separately cover local non-explicit secret rejection and post-provider secret defense in depth.

The Hinglish deletion-request case that remained provider-eligible was classified as `forget / deletion_request / durable=false`, so it cannot enter quarantine or canonical memory through Phase 4.4. This result does not widen the deterministic destructive-memory authorization grammar.

---

## 6. Decision

**Select `gemini-3.5-flash-lite` as the Phase-4.4 structured memory-candidate extraction model while Gemini is the active JARVIS provider.**

Reasons:

1. production-native structured output works with the pinned Google GenAI SDK;
2. full provider-eligible corpus produced zero schema failures;
3. all 14 provider cases were core-exact;
4. zero false durable proposals and zero missed durable candidates;
5. English/Hindi/Hinglish evidence passed;
6. reviewed semantic payloads are sufficient for non-authoritative quarantine evidence;
7. measured latency is acceptable for the background/non-response-blocking extraction path;
8. measured token cost is extremely low;
9. it stays inside the already-selected Google/Gemini provider/account;
10. the staged escalation condition for Gemini 3.8 Flash was not met.

`gemini-3.8-flash` remains an escalation option only if later real-world acceptance reveals a material extraction-quality defect.

---

## 7. What this decision does not authorize

This model selection does **not** authorize:

- implicit durable-memory writes;
- automatic candidate admission;
- provider-authored canonical subject/predicate keys;
- SQLCipher writes from the extractor;
- FTS/embedding writes from quarantine;
- widening explicit remember/correct/forget authority;
- changing Step-3 audio/vision/identity authority;
- using another paid cloud provider for memory while Gemini remains active.

---

## 8. Next gate

Run a narrow owner-PC production-path acceptance with:

- active provider = Gemini;
- extraction model = `gemini-3.5-flash-lite`;
- candidate extraction enabled;
- implicit durable admission still OFF.

Acceptance must prove:

1. normal wake/Pocket3/Gemini conversation remains stable;
2. accepted USER turns can produce background candidate-quarantine results;
3. transient/non-durable turns are dropped;
4. explicit Phase-4.3 memory controls remain on their governed path;
5. no implicit candidate becomes canonical SQLCipher memory;
6. session close disposes the quarantine;
7. normal return-to-wake behavior remains intact.

Only after that owner-PC production acceptance may Phase 4.4 be closed and Phase 4.5 begin.
