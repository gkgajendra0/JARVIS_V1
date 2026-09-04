# Step 4 — Gemini extraction free-tier quota observation (Windows)

## Status

**OPERATIONAL BENCHMARK NOTE — NOT A GEMINI QUALITY RESULT.**

On the real JARVIS Windows machine on 2026-09-04, the full `gemini-3.8-flash` Step-4 memory-candidate extraction bake-off was first attempted with the harness default `--delay-ms 100`.

The run produced only 5 schema-valid model responses out of 24 cases. All 5 successful responses were core-exact against the fixed benchmark contract (English 2/2, Hindi 2/2, Hinglish 1/1). The remaining 19 cases failed before semantic evaluation with Gemini API `429` quota errors.

Observed API error detail included:

- quota metric: `generativelanguage.googleapis.com/generate_content_free_tier_requests`;
- active limit reported by the API: `20`;
- model: `gemini-3.8-flash`;
- provider error: `429 RESOURCE_EXHAUSTED` / too many requests.

An initial interpretation treated the reported limit as a 20-RPM ceiling because some errors included retry windows around one minute. That interpretation was then tested rather than assumed.

A second run used the identical model, corpus, prompt, schema, and scoring contract but increased pacing to `--delay-ms 3500`, comfortably below 20 request starts per minute when combined with model latency. That paced run produced **0 schema-valid responses out of 24**. Therefore request pacing did not resolve the quota condition and the earlier 20-RPM interpretation was rejected.

Current external evidence on 2026-09-04:

- Google's Gemini API rate-limit documentation states that quotas may include RPM, TPM, and RPD; usage is evaluated against each dimension; limits are project/model-specific; and RPD quotas reset at midnight Pacific time: https://ai.google.dev/gemini-api/docs/rate-limits
- A Google AI Developers Forum report published 2026-09-03 specifically reports the Gemini 3.8 Flash free tier as **20 RPD** and contrasts it with higher RPD allowances on Flash-Lite: https://discuss.ai.google.dev/t/gemini-3-8-flash-free-tier-20-rpd-is-too-limited-for-practical-evaluation/180609

## Correct interpretation

The evidence is consistent with the JARVIS Gemini project having exhausted the **20 requests-per-day (RPD)** free-tier allowance for `gemini-3.8-flash`, not merely an RPM limit.

The first partial run is therefore **not** a quality comparison against OpenAI Terra. Do **not** interpret `core_exact_accuracy=0.2083` as Gemini semantic accuracy: it is simply 5 successful/core-exact responses divided by the 24 requested cases while 19 cases were unevaluable due to provider quota errors.

The five actually evaluable Gemini responses were 5/5 core-exact.

The second paced run (`--delay-ms 3500`) is also not a quality result: 24/24 calls were rejected before semantic evaluation because the daily quota was already exhausted.

## Correct continuation protocol

Do not rerun all 24 Gemini cases after the daily quota reset. Preserve the five successful case results from the first partial run and create a corpus containing only the 19 previously unevaluable cases. This fits within a fresh 20-RPD allowance and avoids wasting free-tier requests.

Keep the exact same:

- 24-case benchmark contract;
- `gemini-3.8-flash` model;
- Pydantic extraction schema;
- JARVIS system policy;
- expected labels;
- scoring semantics.

After Google's daily reset at midnight Pacific time, run only the 19 missing cases. Then combine those results with the five already valid cases before performing the OpenAI-vs-Gemini quality comparison.

Provider quota failures must always be reported separately from semantic/model failures.
