# Provider availability and current model research — 22 October 2026

Decision: retain the configured account/models and production behavior. No model inference comparison or switch is authorized by the exhausted recovery protocol. This read-only investigation neither qualifies the product nor spends inference budget.

## Observed evidence

Three successful single-question probes did not predict a stable cohort. Recovery continuation stopped on answering503, an outer extraction timeout and answering429. Only exception class/status are retained for the429; subtype, affected quota and reset time are unknown. A different model cannot be claimed to solve this. The current conservative budget is upper304/532,228remain, but the three-opportunity execution protocol is exhausted.

Google's [Interactions error reference](https://ai.google.dev/gemini-api/docs/api-errors) distinguishes429 rate/quota errors,503 temporary unavailability and402 payment-required errors. Our429 is not evidence of402 or proof that purchasing credits is necessary. A timeout without retained HTTP detail also has no demonstrated provider cause.

Google's [rate-limit guide](https://ai.google.dev/gemini-api/docs/rate-limits) says limits can concern requests/minute, tokens/minute or requests/day, vary by model/project tier and apply per project rather than per key. It directs users to AI Studio for their actual limits; daily quotas reset at midnight Pacific time. That reset rule applies only if a daily quota is the observed cause, which is not established here.

## Available technology, without changing it

The official [deprecation table](https://ai.google.dev/gemini-api/docs/deprecations) says the requested answering alias gemini-3.5-flash automatically routes to gemini-3.6-flash and its endpoint is not shutting down. Therefore our requested-model labels do not prove the effective historical server version. The learning model gemini-3.5-flash-lite remains listed without a shutdown date.

The current [Gemini3.8Flash model card](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash) lists stable structured outputs and low/medium/high thinking; minimal is unsupported. This makes it a possible future bounded comparison candidate, not a proved fix, superior model for JARVIS or a configuration change we made. If separately approved, serving-schema/deadline/single-send compatibility must be verified before any fresh evaluation. It must not turn exposed failed IDs into fresh successes or erase their failures.

Read-only same-account model metadata returned for3.5Flash,3.5Flash-Lite and3.8Flash. [Retained metadata](../../benchmarks/results/personal-auto-learning-2026-10-22-v4-recovery/model_metadata_read_only.json) contains no key or project identifier and used0inference requests. Metadata availability does not prove inference availability, effective alias destination, quota headroom or actual billing tier. No comparison inference was sent.

## Concrete next input and sequence

The owner can read the same project's current Gemini limits in [AI Studio](https://aistudio.google.com/rate-limit?timeRange=last-28-days). Needed text: affected model/limit, current usage versus limit, and any retry/reset information or detailed429 error. Do not share an API key. This is diagnosis, not a request to purchase quota or change account.

Once the actual limit is understood, prepare a finite continuation decision using the228remaining sends and only74never-attempted frozen IDs. The exact cadence must match the observed constraint; preserve all16attempted cases, four failed pairs and the incomplete gate. Any new recovery/model experiment needs a separate concrete owner-approved protocol because the latest authorization explicitly capped recovery at3and prohibited model/account changes. No automatic schedule, fourth probe or owner activation is created here.
