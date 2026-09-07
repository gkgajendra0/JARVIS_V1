# Step 4 Phase 4.5D — Gemini Free-Tier Quota Research and Acceptance Execution Contract

Date: 2026-09-07

Status: **RESEARCH COMPLETE — TRANSPORT-SAFETY AMENDMENT ONLY**

This document records the quota research performed after the first fresh final composite acceptance execution was interrupted by Google Gemini API quota exhaustion. It changes **only test execution safety**. The frozen 255-case corpus, corpus SHA, Gemini model, structured-query prompt/schema, local answer-type guard, deterministic memory policy, and acceptance gates remain unchanged.

## Observed owner-project evidence

The first owner run used `gemini-3.5-flash-lite` through the Gemini Interactions API and stopped after case 31 with HTTP `429`. The provider response identified:

- quota metric: `generativelanguage.googleapis.com/generate_content_free_tier_requests`;
- effective limit: `500`;
- model: `gemini-3.5-flash-lite`;
- free-tier request quota exhausted.

This is the strongest evidence for the **current owner project's actual effective request limit**. Google documents that active limits can vary by project/model/tier and should be read from AI Studio, so JARVIS must not hard-code `500` as a universal Gemini limit.

## Official Google findings

### 1. Standard Gemini 3.5 Flash-Lite is free on the Gemini API Free Tier

Google's pricing page lists Standard input and output for `gemini-3.5-flash-lite` as free of charge on the Free Tier.

The Google Cloud `$300` Free Trial is a different program and, since March 2026, does **not** apply to Gemini API usage. JARVIS is using the Gemini API's own Free Tier, not Google Cloud welcome credits.

### 2. Quotas are project-wide, not API-key-wide

Google documents normal inference rate limits across RPM, input TPM, and RPD. Exceeding any one dimension produces a rate-limit error. Limits are applied per **project**, not per API key. Creating or rotating another key in the same project therefore does not create a fresh quota budget.

RPD resets at midnight Pacific time.

### 3. Active limits can change

Google states that rate limits depend on factors including usage tier and account status and that the currently active rate limits should be viewed in Google AI Studio. The acceptance harness must therefore receive the owner's current `limit` and `used` values at execution time rather than assuming a web table or old log remains authoritative.

### 4. Daily-quota exhaustion is not fixed by lowering RPM

Google distinguishes short-window rate-limit errors from daily `quota_exceeded`. A daily quota error requires waiting for reset or obtaining more quota. The owner failure named the daily free-tier request metric, so lowering `--gemini-rpm` cannot repair an already exhausted RPD budget.

### 5. Google exposes monitoring metrics for limit, usage, and exceeded attempts

Cloud Monitoring publishes beta project metrics:

- `generativelanguage.googleapis.com/quota/generate_content_free_tier_requests/limit`;
- `generativelanguage.googleapis.com/quota/generate_content_free_tier_requests/usage`;
- `generativelanguage.googleapis.com/quota/generate_content_free_tier_requests/exceeded`.

Google documents 60-second sampling and up to roughly 150 seconds visibility delay. Reading project monitoring data requires Google Cloud authentication/IAM rather than merely the Gemini API key. We will not install or add a new Cloud SDK dependency solely for this acceptance; AI Studio is the immediate authoritative operator preflight. Cloud Monitoring can be integrated later if owner infrastructure already has ADC/gcloud.

### 6. The SDK itself retries transient errors

Google's troubleshooting documentation states that the Python SDK automatically retries transient failures such as `429` and `5xx`. The exact accepted owner dependency is `google-genai==2.22.0`.

Inspection of the pinned `v2.22.0` source confirms that the Interactions/NextGen client maps `HttpRetryOptions.attempts` into its retry configuration and otherwise installs retry behavior. The previous JARVIS acceptance harness then wrapped that SDK call in another five-attempt retry loop. This creates retry amplification near quota boundaries and is inappropriate for a finite acceptance budget.

For final acceptance, the SDK retry count must be explicitly set to zero and the JARVIS harness must not add a second retry loop. One logical planner request must correspond to at most one Gemini API attempt. Any provider transport/rate failure pauses execution instead of retrying blindly.

### 7. Batch API is not the final-acceptance substitute

Google documents Batch API quotas as separate from normal interactive inference, and Gemini 3.5 Flash-Lite Batch can be free on the Free Tier. However, the frozen 4.5D acceptance intentionally tests the production-shaped Interactions path with one user query per provider request. Switching the final acceptance to Batch would change the transport/execution contract and is therefore rejected for this acceptance. Batch remains available for unrelated offline development workloads.

## Quota-safe final acceptance contract

The semantic/statistical acceptance contract is unchanged. The execution layer is amended as follows.

### A. Mandatory local quota-planning pass before any Gemini request

The frozen local answer-type guard is evaluated over the not-yet-completed acceptance queries **without consulting expected labels**. This yields the exact number of queries that are eligible to reach the cloud planner for that invocation.

The planning pass may report only aggregate request-budget information. It must not print per-case guard classifications for use in tuning.

### B. Mandatory active-quota input from AI Studio

Before the harness is allowed to make a Gemini request, the owner supplies:

- current active RPD limit for `gemini-3.5-flash-lite`;
- current RPD usage for that same model/project.

The harness computes:

`remaining = active_limit - active_usage`

and a safety reserve:

`reserve = max(25, ceil(active_limit * 0.10))`

For the owner's previously observed `500` RPD project limit, the default reserve is `50` requests.

The harness fails **before the first provider call** unless:

`remaining >= required_provider_calls + reserve`

This protects against dashboard/monitoring lag, incidental project usage, and small accounting differences.

### C. No nested retries

Acceptance-specific Gemini transport uses the same `GeminiMemoryQueryInterpreter` and same Interactions request, but configures the pinned Google SDK with `HttpRetryOptions(attempts=0)` so the SDK does not retry. The JARVIS pacing wrapper performs one attempt only.

Acceptance evidence must assert:

`provider_api_attempts == provider_logical_calls`

### D. Checkpoint/resume is transport-only

The harness writes an atomic checkpoint after every completed case. The checkpoint contains only the already-public acceptance result fields and immutable contract metadata; it persists no query text or canonical memory value.

On a later invocation the checkpoint may be resumed only when all immutable metadata matches, including:

- frozen corpus SHA;
- Gemini model ID;
- local answer-type model ID/revision;
- acceptance schema;
- exact repository commit SHA that created the checkpoint.

A provider transport/quota interruption is `EXECUTION_PAUSED_PROVIDER`, not `FAIL_ACCEPTANCE`. Completed rows are not rerun. No prompt/model/corpus/gate tuning is permitted between resume invocations.

On successful completion, the final acceptance artifact is written and the checkpoint is removed.

### E. Hard quota budget during execution

The interpreter tracks its logical calls and refuses to start a call that would exceed the certified provider-call budget for that invocation. Therefore a stale or unexpectedly consumed project quota cannot cause the harness itself to exceed the amount approved at preflight.

## Operator procedure

1. Pull the exact green owner-run SHA.
2. Confirm the final acceptance artifact is absent.
3. Open Google AI Studio's active rate-limit/usage view for the same API project and `gemini-3.5-flash-lite`.
4. Record the current RPD `limit` and `used` values.
5. Run the harness in quota-plan/preflight mode. It performs local inference only and prints the exact required provider-call count plus the minimum remaining quota required with reserve.
6. Only if the quota gate passes, run/resume the unchanged acceptance using those same quota values.
7. Do not run other Gemini development workloads from the same project during the acceptance window.

## Why this preserves fresh acceptance validity

The first owner execution produced no complete artifact and was already classified by the frozen method as transport/quota failure rather than model evidence. This amendment is frozen **before a complete acceptance result exists** and changes no semantic decision rule, model, prompt, corpus, label, or acceptance threshold. It only prevents transport retry amplification, certifies sufficient request budget before inference, and preserves completed rows if the provider becomes unavailable.

Phase 4.5E remains blocked until the complete fresh artifact passes every frozen acceptance gate and closure evidence is recorded on a green exact SHA.
