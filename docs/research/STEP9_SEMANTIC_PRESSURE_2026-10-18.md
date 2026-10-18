# Step 9 — 240-fact semantic-pressure memory research (OFFLINE ONLY)

**Date:** 2026-10-18. **Status:** research branch/draft PR; no production
integration, no Hindsight live import authorized.

## Why this exists: measured Step 7 and Step 8 results

With 60 fictional and explicitly labeled fact statements:

| Owner-machine pilot | Hindsight-only retrieval | Local BM25 | RRF hybrid |
|---|---:|---:|---:|
| Step 7 top-8 supported evidence | 8/16 | 16/16 | 16/16 |
| Step 7 correct structured decisions | 3/18 | 18/18 | 18/18 |
| Step 8 paraphrased top-8 supported evidence | 15/20 | 20/20 | 20/20 |
| Step 8 correct structured decisions | 19/24 | 24/24 | 24/24 |

Both previous experiments imported data into **disposable synthetic-only**
Hindsight banks and verified cleanup with 0 remaining banks. Those tests
did **not** demonstrate that semantic retrieval adds value beyond BM25;
their documents and queries shared easily matched unique project numbers.

## Honest pressure test

This new **offline-only** fixture produces precisely 240 independent,
source-linked fictional memory facts:

- 16 catalog concepts, each with a 2-version source correction history
  (32 facts);
- 208 *distinct* unrelated catalog-inventory decoy facts;
- 16 curated natural-language aliases absent from each concept's stored
  descriptions (for example, “telescope” vs “optical device for observing
  distant celestial objects”);
- 68 immutable evaluated questions: 16 × semantic current, semantic
  original, semantic correction history, exact-descriptor control;
  plus two unsupported details and two unresolved references.

A pure BM25 baseline ranks **only document texts**. No concept alias
table, source provenance, question subject, or gold answer is searchable
in the baseline. The curated description/alias pairs are human-labeled
semantic relationships, **not** independently measured language-model
understanding. There is no Graphiti or Mem0 in this test.

### Evaluation

- Compare at k=4, 8 and 16: evidence-lineage recall and independently
  checked rule-based answer codes; each real answer requires its **entire
  original/correction chain**, not just the newest value.
- Unknown facts must abstain. Unresolved reference cases come with
  **oracle pre-labeled unresolved scope**, so passing those cases **does
  not demonstrate independent pronoun or referent detection**.
- Ranked evidence is checked against the reviewed IDs and source metadata.
  Unknown or modified facts cause a hard failure, not a false accuracy pass.
- The deterministic, cross-platform Hindsight-shaped ZIP is constructed
  **in memory only**, with output reporting its SHA-256. A ZIP file is
  **not uploaded** by this PR and no endpoint for the larger corpus has
  been approved. Its shape is not yet proven compatible at 240-document
  scale or with server-side pagination/readback.
- The baseline's measured result is the actual offline Python BM25 output.
  Results for a real Hindsight or RRF combination are **intentionally
  absent** until a separately designed, approved and audited live trial.
  Do not interpret a BM25 miss as a semantic-engine success.

## Offline acceptance

```powershell
cd C:\Users\gkgaj\Desktop\jarvis_hindsight_loopback
if (git status --porcelain) { throw "Worktree has local changes" }
git fetch origin research/step9-semantic-pressure-offline-20261018
if ($LASTEXITCODE -ne 0) { throw "Fetch failed" }
git switch --detach FETCH_HEAD
if ($LASTEXITCODE -ne 0) { throw "Checkout failed" }
git rev-parse --short HEAD

$py = "C:\Users\gkgaj\Desktop\jarvis_v1\.venv\Scripts\python.exe"
& $py -m pytest -q tests\test_step9_semantic_pressure.py
if ($LASTEXITCODE -ne 0) { throw "Offline tests failed" }
& $py -I tools\research\step9_offline_semantic_pressure.py
if ($LASTEXITCODE -ne 0) { throw "Offline evaluation failed" }
```

The dry-run creates the 240-document synthetic archive **in memory** and
reports real lexical accuracy in the 3 rank budgets. No need to run Docker
and no approval to import is carried forward from Steps 7 or 8.

## Next steps, not in this PR

1. Inspect offline category-by-category BM25 performance for genuine
   lexical weaknesses; revise independently authored question sets if
   accidental token leakage is discovered, without fitting to Hindsight.
2. Review a separate *staged* 240-fact importer, Docker safety, paginated
   240-document readback, imported provenance, resource budgets and cleanup.
   Begin with a smaller gate if compatibility is unknown. Require fresh
   owner consent before any live upload.
3. Compare real Hindsight against BM25 and RRF under identical rankings,
   exact questions and fresh top-k cutoffs, reporting non-improvement
   honestly if it occurs.
4. Benchmark natural-language entity scope resolution, privacy, edits,
   deletions, provenance and abstention independently before any
   production SQLCipher shadow adapter or memory promotions.

**Production stays on encrypted SQLCipher; this work cannot change it.**
