# Personal learning: bounded retries for temporary provider failures

**Owner decision, 2026-11-21.** This replaces the earlier "no retries" rule for
automatic personal learning (2026-10-22 architecture decision). The rest of
that decision is unchanged.

## Rule

- One initial attempt plus **at most two retries** per learning stage
  (extraction, resolution). The stages are retried separately: a failed
  resolution never repeats a completed extraction.
- **Only temporary provider failures qualify:** HTTP 503/502 (service
  unavailable), 500 (server error) or a lost connection.
- **Never retried:** 429 rate limits and quota exhaustion (the existing
  cooldown applies); authentication, permission and invalid-request failures;
  timeouts and stalls; invalid or unparseable output; a completed but wrong
  proposal.
- **Waits:** about 2 s, then about 5 s, each with ±25 % randomness.
- **Deadline:** every attempt and wait stays inside the source's existing
  28-second processing budget. Each attempt's timeout is the smaller of 25 s
  and the time remaining. A retry is made only if the wait plus at least 6 s
  for a useful attempt still fits. Nothing extends the budget, the 30-second
  source lease or the learning grant.
- **Permissions:** source validity, the source registration and the learning
  grant are rechecked before every retry. A revocation, privacy control,
  forget or session close during a wait stops the stage without another
  request.
- **No repeated effects:** only the model request is repeated. Storage,
  approvals and tools run once, after the stage has succeeded.

## One retry owner

| Path | Retry owner | Others |
|---|---|---|
| Direct provider call (Free key, routing disabled) | `PersonalLearningRuntime._infer` | SDK retries disabled (`retry_config=None`); the adapter makes one request per call |
| Model router enabled | The router's existing policy (unchanged) | The learning runtime does not retry router failures (`retry_owned_by_router`) |

The policy constants live in `jarvis.provider_retry`. Every failed attempt is
reported, content-free, to the runtime's `retry_observer` and to learning
diagnostics: stage, attempt number, failure kind, HTTP status, decision, wait
and remaining budget.

## What it does not fix

A stall (no response before the timeout) uses the whole window, so it is never
retried. It stays an explicit unresolved provider failure.
