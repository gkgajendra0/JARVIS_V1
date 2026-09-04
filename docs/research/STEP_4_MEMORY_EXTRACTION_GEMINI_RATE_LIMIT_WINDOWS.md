# Step 4 — Gemini extraction rate-limit observation (Windows)

## Status

**OPERATIONAL BENCHMARK NOTE — NOT A GEMINI QUALITY RESULT.**

On the real JARVIS Windows machine on 2026-09-04, the full `gemini-3.8-flash` Step-4 memory-candidate extraction bake-off was first attempted with the harness default `--delay-ms 100`.

The run produced only 5 schema-valid model responses out of 24 cases. All 5 successful responses were core-exact against the fixed benchmark contract (English 2/2, Hindi 2/2, Hinglish 1/1). The remaining 19 cases failed before semantic evaluation with Gemini API `429` rate-limit errors.

Observed API error detail included:

- quota metric: `generativelanguage.googleapis.com/generate_content_free_tier_requests`;
- active limit reported by the API: `20`;
- model: `gemini-3.8-flash`;
- retry windows around 60 seconds, counting downward and then resetting around the next minute window.

Google's Gemini API rate-limit documentation distinguishes requests-per-minute (RPM), tokens-per-minute (TPM), and requests-per-day (RPD), and explicitly notes that exceeding an RPM limit such as 20 causes subsequent requests within that minute to fail. Active limits are project/model-specific and are visible in Google AI Studio.

Source:

- https://ai.google.dev/gemini-api/docs/rate-limits

## Interpretation

The measured behavior is consistent with the project hitting a **20 RPM** free-tier request limit. Therefore the first full Gemini run is not a quality comparison against OpenAI Terra.

Do **not** interpret the harness's `core_exact_accuracy=0.2083` from that partial run as Gemini semantic accuracy: it is simply 5 successful/core-exact responses divided by the 24 requested cases while 19 cases were unevaluable due to provider quota errors.

The 5 actually evaluable Gemini responses were 5/5 core-exact.

## Correct rerun protocol

Keep the exact same:

- 24-case corpus;
- `gemini-3.8-flash` model;
- Pydantic extraction contract;
- JARVIS system policy;
- scoring logic.

Change only request pacing. Rerun Gemini with `--delay-ms 3500`. Since calls are sequential and model latency is additional to this delay, this keeps request starts comfortably below the observed 20-RPM ceiling without changing semantic test conditions.

Use the Windows-safe UTF-8 runner:

```powershell
.\.step4-extraction-venv\Scripts\python.exe tools\research\step4_extraction_utf8_runner.py --output .step4-gemini-full-paced.json --providers gemini --delay-ms 3500
```

Only a complete 24/24 schema-valid/provider-success run is eligible for the OpenAI-vs-Gemini quality comparison. Provider quota errors must be treated as operational failures, not semantic misses.
