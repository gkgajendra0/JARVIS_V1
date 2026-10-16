# Step 4 Hindsight: free-tier constrained execution plan (2026-10-16)

**Research only. No durable production memory writes, passive context injection, D8 activation, paid fallback, or release authorization.**

## Actual owner-machine evidence

- `hindsight-client==0.10.3`, Docker 29.8.1, pinned image
  `ghcr.io/vectorize-io/hindsight:0.10.3-slim` on localhost:8888,
  with isolated volume, were initialized and health-checked.
- An actual disposable-bank, single-document `retain` / `recall` smoke
  succeeded and returned the expected synthetic source document; the bank
  was deleted successfully.
- The subsequent 24-document bulk `retain_batch` failed **before useful
  multi-memory recall**. The server returned HTTP 500 wrapping Gemini
  429 RESOURCE_EXHAUSTED: free-tier generate requests/minute/project/model
  limit 15 for gemini-3.5-flash-lite at that moment. This is neither a
  Hindsight retrieval quality failure nor evidence that any other model
  will fit the same free-tier capacity.
- The owner ran a read-only bank-list check and observed no matching
  `jarvis-dev-only-*` banks among the returned results.
- Owner then stopped `jarvis-hindsight-research`. The separate research
  volume was left intact; `jarvis-dbos-postgres` remains independent.
- Fixed JARVIS async model comparator later completed six consecutive
  real Gemini calls with zero provider failures; 18-case accuracy from
  the earlier recovered development trial remains 14/18, and LangMem 11/18.

## What this branch changes

`step4_hindsight_isolated_probe.py` **previously always retained all 24
synthetic context memories**, even with `--max-queries 3`. This was an
unbounded model-workload surprise. The new CLI uses these defaults:

| Control | Default | Meaning |
| --- | --- | --- |
| `--max-seed-items` | 3 | Retain only the first 3 pinned synthetic hints |
| `--max-queries` | 3 | Recall at most 3 seeded-query cases |
| `--retain-batch-size` | 1 | One document per retain_batch call |
| `--min-seconds-between-retain-batches` | 65 | Minimum *start-to-start* delay; does not observe actual internal LLM call count |
| `--allow-large-synthetic-run` | not set | Required to exceed 3 seeds or batch size 1 |
| `--allow-local-server-writes` | not set | Required to permit any real bank operations |

A retain operation may make several model and embedding calls internally.
**The 65-second interval is not an enforceable per-minute API quota and
does not reserve capacity against JARVIS, LangMem, other users or earlier
requests.** If Gemini quota is already exhausted, even one retain may
fail. Failures cause no automatic retry. CLI error reports suppress raw
provider response bodies; cleanup failure reports a synthetic bank ID
for manual inspection. Successful cleanup still needs the usual
read-only bank verification if the operation itself failed.

The function can still seed all 24 documents in a fake/local unit test.
**CLI limits and function-level limits are separate:** the CLI now passes
its explicit `max_seed_items`, while old local contract tests retain
their previous direct-call behavior.

## Why this is not yet JARVIS-vs-Hindsight acceptance

Retaining only three documents makes initial evaluation low-workload,
but reduces the distractor set. It cannot demonstrate relative retrieval
quality against the original JARVIS hybrid FTS/embedding/RRF/reranker
baseline. For valid A/B comparison later, require same seeded synthetic
source hints, per-language stratification, positive and hard-negative
queries, source-ID support, latency, **actual model call utilization**
and downstream no-memory versus memory-conditioned answer effects.
The current Hindsight probe counts source IDs and retrieval exposures,
not answer correctness, steering or full memory life cycle.

Do not automatically run all 24 on a free-tier key. No successful
server-side model operation is cached in this branch because banks are
deliberately deleted for safe isolation; preserving a live bank across
quota windows would require a distinct owner-approved, protected
resume/cleanup protocol. Aggregate reports can be saved manually.

## Next actions (separate opt-in)

1. Run local no-provider test: `setup_step4_memory_windows.ps1 -SkipInstall`
   with the isolated Windows research venv, and green exact-head CI.
2. Acknowledge that the stopped Docker Hindsight service must be
   deliberately restarted and verified. Limit server extraction
   concurrency on restart where documented; do not change JARVIS DBOS
   PostgreSQL or production provider config.
3. If the owner explicitly chooses to expend free Gemini quota, run only
   `--max-seed-items 3 --max-queries 3` with default per-document pacing.
   Before large trials, wait for a full quota reset and read current
   actual provider limits. Never assume this prevents 429.
4. Compare source-level retrieval against *existing* JARVIS retrieval
   with equivalent synthetic documents; run a fresh independent
   multilingual blind acceptance separately. Do not tune against
   exposed development labels.
5. Independently harden Phase 4.4 correction, semantic duplicate and
   temporal-reference reasoning in a *research-only* task. No implicit
   admission to canonical SQLCipher.
6. D8 was paused because **complex real-world TV capability acquisition**
   exceeded reliable full-workflow handling; this does **not** establish
   that all bounded self-evolution is impossible. D8 remains separate
   from Step 4 memory research.
