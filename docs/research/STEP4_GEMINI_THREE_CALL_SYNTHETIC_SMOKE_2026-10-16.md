# Step 4.4 — Owner-approved three-call Gemini Free-tier smoke (2026-10-16)

**Approval scope:** at most **three Gemini Free-tier requests**, exactly
three *new fictional* conversation examples, incumbent
`gemini-3.5-flash-lite` only, no paid fallback, no retries, no real
owner memory, no production changes. Three diagnostics are **not** a
multilingual accuracy or safety acceptance result.

## Engineering and privacy constraints

- The tool `tools/research/step4_contextual_gemini_three_call_smoke.py`
  is **dry-run by default**, showing only case IDs and languages.
- No arbitrary corpus/file/URL input, no model choice: the fixture has
  exactly **three hardcoded synthetic cases** that do not reuse the
  published 18-case development fixture. The three language examples
  cover an English inaccurate prior statement, a Hindi true historical
  change, and a Hinglish *ambiguous* revision with two plausible targets.
- Model invocation goes through the existing
  `ContextualGeminiMemoryExtractor` and native
  `MemoryExtractionProposal` JSON schema. No database/MemoryService,
  LangMem, Hindsight, Qwen, Jev, ContextAssembler, or owner context.
- One managed async event loop, sequential calls, **65 seconds apart**
  as a courtesy to Gemini Free-tier RPM. This does not guarantee quota
  for other apps/keys, and RPD exhaustion still can cause 429.
- The Google Gen AI Python SDK defaults to retry behavior in some
  versions. This runner sets `HttpRetryOptions(attempts=1)` so a 429,
  timeout or any provider/validation failure **stops the run** instead of
  retrying and spending more calls. No paid model fallback.
- Returned console JSON contains only case IDs, predicted intent/type,
  booleans for exact target/value grounding, attempted-call count,
  and sanitized error *class*. Never prints extracted memory values,
  full prompts, provider exception text or API keys.
- No output file, database write or model response persistence.

## Free-tier billing gate: owner must verify before running

Google allows Free and Paid API projects, and the same model identifier
can have a paid price when the API key belongs to a paid project.
**An API-call cap alone is not a zero-cost guarantee.**

1. Open https://aistudio.google.com/ and inspect the **Projects** page:
   the project associated with `GOOGLE_API_KEY` must show `Free`
   under **Billing Tier**. If the project is Paid, stop; do not use it.
2. Check the model's remaining rate limits/quota in AI Studio.
   No free quota or uncertain project tier = do not run.
3. Keep the key private, already in your local shell's
   `GOOGLE_API_KEY` environment variable. Do NOT paste it into
   ChatGPT, GitHub issues, PRs or logs.
4. In a **separate research checkout**, use the installed JARVIS
   Python 3.11 environment. Do not install model weights or connect
   a real memory database.

Dry-run to inspect the fixed test IDs (zero calls):

```powershell
.\.venv\Scripts\python.exe tools\research\step4_contextual_gemini_three_call_smoke.py
```

**Only once the project's Free tier has been verified**, invoke:

```powershell
.\.venv\Scripts\python.exe tools\research\step4_contextual_gemini_three_call_smoke.py --allow-three-calls --confirmed-free-tier
```

The command accepts no `--cases`, `--model`, `--retry`, or
`--max-calls` override. Its maximum attempts is three; if an error
occurs it ends the experiment rather than automatically continuing.
Check your AI Studio usage dashboard after running. Do not repeat
any failed requests without **new explicit approval**, because failed
requests can still consume quota.

## Evidence, decisions and next gate

- This is a **diagnostic**, not a blinded or statistically meaningful
  evaluation. The three fixtures are written by the implementer.
- Expected categories are used **only after** inference for local
  scoring; they are not included in provider input.
- Prediction labels are compared as delivered by the model; a bad
  predicate, invented corrected value, or unsafe resolution fails
  the corresponding diagnostic.
- If provider calls fail, preserve the failure report and stop.
- If all three pass, do **not** enable automatic memory writing,
  passive context injection, D8, production routing, or model changes.
- For future model/owner-machine work beyond the three calls, obtain
  separate explicit approval and a proper independent held-out test
  with a documented free-tier budget.

Sources checked: Google Gemini API billing/rate-limit docs,
https://ai.google.dev/gemini-api/docs/billing and
https://ai.google.dev/gemini-api/docs/rate-limits and
Google Python SDK HttpRetryOptions documentation.
