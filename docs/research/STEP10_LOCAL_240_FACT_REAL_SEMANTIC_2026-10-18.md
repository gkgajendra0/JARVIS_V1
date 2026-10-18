# Step 10 — 240-fact owner-local real retrieval comparison (research only)

**2026-10-18; unmerged draft.** Step 9 showed an actual lexical failure
on an offline synthetic dataset. This PR implements **but does not run**
one larger opt-in comparison of local Hindsight v1.0 against BM25 and
rank-fused hybrid. Prior experimental permissions do not carry over.

## Verified owner-machine Step 9 result

- 17/17 relevant tests passed, commit `45340511`.
- All 240 assertions fictional; on-disk production owner memory untouched.
- Source ZIP SHA-256 (cross-platform pinned):
  `d5ee8f2d9587691012d276748e3c553a6c057f33ad83e357d48f258163df0246`.
- At **K=8**, BM25 found complete evidence in **17/64** supported cases
  and got **21/68** rule-based decisions right.
- BM25 scored **16/16** on identical-word descriptor controls, but
  **1/48** on synonym/semantic-alias cases.
- At K=16 BM25 evidence **18/64**, decisions **22/68**.
- Unsupported/ambiguous cases are pre-labeled; passing them does not
  demonstrate automatic referent resolution.
- **Hindsight and hybrid results for this corpus have NOT been measured.**

## Step 10 protocol

**Same frozen data, same exact questions.** 240 source facts:
16 fictional concepts × 2 original/corrected states, plus 208 decoys.
68 fixed questions: 48 semantic aliases, 16 lexical control descriptions,
2 unsupported, 2 unresolved-reference gates.

Both engines see precisely the same natural-language question. Compare
real local Hindsight ranked IDs, pure text-only BM25 rankings, and RRF
combination at **K=4/8/16**, with the same complete-revision-lineage
decision rubric. Report per-category scores, retrieval recall, and
structured (non-LLM) decision accuracy. If semantic retrieval beats BM25,
that is real evidence of added capability **on this synthetic fixture**,
not proof of general conversational accuracy.

### Safety gates (opt-in only)

1. Strict `verify_local_container()`: only
   `jarvis-hindsight-lab` at `127.0.0.1:18888`, isolated volume,
   local no-LLM provider, cloud secrets absent, auto observations/
   consolidation disabled, no unreviewed mounting or restart mode.
2. Block if any previous `jarvis-dev-only-` test bank exists.
3. Check exact reviewed archive SHA and source ID set before network.
4. Create a *fresh UUID-only* disposable bank and verify its effective
   observations and consolidation config before any import.
5. Send exactly one fixed fictional ZIP and poll operation completion
   (bounded, no retries, no arbitrary owner file selection).
6. Read all 240 list entries with **three distinct pages**
   `?limit=80&offset=0/80/160`; reject missing/duplicate/extra IDs.
   Official Hindsight document-list docs confirm `limit` and `offset`.
7. Independently read back each of 240 original document texts and the
   single world memory attached to each; verify exact source,
   revision, and full synthetic metadata.
8. Run precisely 68 local recall requests, verify returned memory
   provenance and text byte-for-byte, score all engines identically.
9. Always attempt to delete the created bank in `finally`, then demand
   HTTP 404 for its config. Report sanitized errors only. The owner
   should separately check research-bank total is zero after a run.

The preexisting Hindsight HTTP transport caps each response at
131,072 bytes, refuses redirects and proxies, and uses fixed loopback
only. Pagination avoids an unsafe oversized listing. **No real owner
data, no SQLCipher reads/writes, no paid cloud LLM, no persistent memory
index, no Graphiti/Mem0 installation, no production promotion.**

The official documentation on document listing:
https://github.com/vectorize-io/hindsight/blob/main/hindsight-docs/docs/developer/api/documents.mdx

## Validation before any live approval

Default invocation constructs only reviewed fictional data in memory
and emits the actually computed offline BM25 baseline. It never
inspects Docker or contacts localhost.

```powershell
cd C:\Users\gkgaj\Desktop\jarvis_hindsight_loopback
if (git status --porcelain) { throw "Research worktree has local changes" }
git fetch origin research/step10-240fact-local-semantic-comparison-20261018
if ($LASTEXITCODE -ne 0) { throw "Fetch failed" }
git switch --detach FETCH_HEAD
if ($LASTEXITCODE -ne 0) { throw "Checkout failed" }
git rev-parse --short HEAD

$py = "C:\Users\gkgaj\Desktop\jarvis_v1\.venv\Scripts\python.exe"
& $py -m pytest -q tests\test_step10_local_240fact_semantic_trial.py tests\test_step9_semantic_pressure.py
if ($LASTEXITCODE -ne 0) { throw "Offline test failure" }
& $py -I tools\research\step10_local_240fact_semantic_trial.py
if ($LASTEXITCODE -ne 0) { throw "Dry run failure" }
```

The `--allow-one-local-240-fact-semantic-trial` flag is designed for
a **separate explicit owner-approved** experiment, only after all
Linux/Windows CI and owner-machine offline tests pass. Never call it
just because a Step 7/8 experiment was previously approved.

## What this trial still does NOT prove

- No real natural-language ambiguity detection: gold subject/predicate
  and intent are fixed by the synthetic test designer.
- No real LLM factual-answer or memory extraction quality measurement.
- The alias/descriptors are deliberately written by researchers, and
  they only cover 16 familiar concepts.
- Hindsight vs in-process BM25 timing surfaces are unequal; report
  timings, never imply an apples-to-apples speed ratio.
- No long-running production workload, 3,600 live facts, owner data,
  or automatically accepted vendor architecture decision.

Only after evidence, a read-only canonical shadow adapter can be
reviewed, still with zero production memory writes.
