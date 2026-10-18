# Step 7 — first real-engine Hindsight vs local lexical vs hybrid comparison

**Date:** 2026-10-18. **State:** research-only opt-in implementation; **no owner-machine 60-document live run has occurred**. Keep draft/unmerged.

## Why this experiment

The earlier Step 6 hybrid test used 3,600 structured fictional assertions
and simulated retrieval results. Passing the Step 6 merger contract does not
prove that multiple real retrieval strategies improve memory accuracy.

This new *smaller and independent* experimental fixture provides an actual
Hindsight ↔ local BM25 ↔ RRF comparison with the **same data, same 18 queries,
same top-eight cutoff, same gold evidence/structured decision tests**.
Start at 60 fictional records to test a new import path safely. This is a
compatibility/pilot experiment, **not** a full 3,600-fact server benchmark.

## Frozen corpus and benchmark

- 20 fictional Meridian projects, three facts each:
  original weekly-review weekday, corrected weekday, and venue.
  Total: **60** documents and **60** world-type memory facts with individual
  synthetic source IDs, exact provenance, timestamps, and explicit revisions.
- Fixed 18 questions: four projects × (current day, original day, correction
  history, venue), plus two unsupported questions. Sixteen scored retrieval
  cases and two scored structured abstentions.
- Exact deterministic ZIP with a SHA-256 printed by dry-run. Same external
  Hindsight transfer shape successfully used in the five-fact Step 4 study,
  but the new archive and new importer are **separate and independently
  bounded** (196,608 bytes max), leaving original successful fixture intact.
- Real Hindsight result text, type, document ID and full metadata must match
  the reviewed fictional corpus exactly. Any unknown result, duplicate,
  changed text or provenance fails closed.
- Keyword baseline is deterministic, in-process BM25 over the **same memory
  texts** (no metadata, gold labels or hidden access at ranking time).
- Hybrid ranker uses two lists, Hindsight and BM25, with RRF K=60.
  Every engine uses top K=8 before evidence and decision scoring.
- An answer counts as correct only if all source-backed facts for that
  subject/predicate, including older revisions, are present within the top
  eight. This deliberately penalizes stale partial histories even if the
  latest-looking statement alone seems plausible.
- Timing is tracked separately for Hindsight HTTP round-trips versus lexical
  in-process work; **these figures are not apples-to-apples latency
  measurements**, as network, import and model setup differ.

## Safety

By default `tools/research/step7_local_engine_comparison.py` builds and
inspects only the fictional archive in memory, then prints a protocol
preview. Zero network, no Docker, no database or JARVIS runtime access.

Explicit local opt-in `--allow-one-local-60-fact-comparison` authorizes
exactly one disposable synthetic Hindsight bank:

1. Inspect the exact `jarvis-hindsight-lab` container; require loopback
   only, the expected isolated volume and no cloud model keys/providers.
2. Refuse to start if any `jarvis-dev-only-` bank already exists.
3. Create a fresh UUID bank and independently verify effective
   observations and auto-consolidation are disabled before importing.
4. Import the 60-fact ZIP once (no retry); poll bounded operation completion.
5. Read back all 60 document texts, 60 world facts and source/provenance data.
6. Run 18 identical queries, record Hindsight's *actual* ranked assertion
   IDs (never display raw recalled texts), BM25 ranks and hybrid ranks.
7. Delete only the fresh bank in a `finally` block, then demand a 404
   on the bank's configuration URL. Failure aborts; report cleanup errors
   separately. Independently enumerate research banks after any owner run.

Output is sanitized summary metrics only. The `status="measured"` field means
protocol completed, **not** that any engine achieved perfect accuracy.
Exit code 2 means hybrid underperformed Hindsight under the prescribed two
accuracy measures; report is still real evidence and must not trigger a
replay. There is no automatic promotion or merge.

No real owner information, SQLCipher reads, new production dependencies,
external model calls, paid APIs, Graphiti, Mem0 or persistent indexes.

## Owner offline acceptance first

```powershell
cd C:\Users\gkgaj\Desktop\jarvis_hindsight_loopback
if (git status --porcelain) { throw "Worktree has local changes" }
git fetch origin research/step7-local-retrieval-comparison-20261018
if ($LASTEXITCODE -ne 0) { throw "Fetch failed" }
git switch --detach FETCH_HEAD
if ($LASTEXITCODE -ne 0) { throw "Checkout failed" }
git rev-parse --short HEAD

$py = "C:\Users\gkgaj\Desktop\jarvis_v1\.venv\Scripts\python.exe"
& $py -m pytest -q tests\test_step7_engine_comparison.py
if ($LASTEXITCODE -ne 0) { throw "Offline unit tests failed" }
& $py -I tools\research\step7_local_engine_comparison.py
if ($LASTEXITCODE -ne 0) { throw "Offline preview failed" }
```

**Do not run the opt-in command before** all CI jobs pass, offline owner tests
pass and owner explicitly approves a fresh 60-document synthetic import.
A live Hindsight result for this larger fixture is not yet known; inspect
the installed `/openapi.json` if an endpoint changes.

## Further gates — not accomplished by this PR

- Grow real-server fictional corpora in stages (e.g. 60, 300, 1,000,
  3,600) under separately approved bounded trials with measured accuracy,
  latency, failure rate, resource use and privacy.
- Prevent untrusted language-to-fact extraction, handle deletions/retractions,
  mixed correction-history semantics, fuzzy entity identity and source
  verification in real conversations.
- Replace the fictional-only canonical adapter with a reviewed read-only
  JARVIS adapter in shadow mode; redacted metrics, isolation, rollback, and
  no automatic memory writes.
- Only add Graphiti or Mem0 if a comparable isolated test demonstrates
  significant benefit over the established Hindsight/BM25 baseline.

The user-facing phrase "Unified Memory" is an architecture *goal*, not
a claim that production long-term memory is completed.
