# Step 8 — Harder-language, correction-aware memory retrieval challenge

**2026-10-18.** Research draft only. Based on Step 7's measured owner-local
60-fact benchmark, not a production memory change.

## Why this stage exists

On 2026-10-18 the user approved and ran Step 7 on the independent local
Hindsight 1.0.0 research container, with **60 imported and source-verified
fictional documents, 18 questions, top K=8, and complete cleanup**:

| Engine | Evidence cases | Structured decisions | Unsupported abstentions |
|---|---:|---:|---:|
| Hindsight retrieval only | 8/16 | 3/18 | 2/2 |
| Pure local lexical BM25 | 16/16 | 18/18 | 2/2 |
| Reciprocal rank fusion hybrid | 16/16 | 18/18 | 2/2 |

Hindsight HTTP round-trip total: 6,615.58 ms across 18 queries;
in-process BM25 total: 49.82 ms (different measurement surfaces;
**not** directly comparable latency). The experimental bank was deleted
and independent owner-side enumeration showed zero remaining banks.
The success flags mean the experiment completed; they do not prove a
hybrid wins against BM25 or works for arbitrary user conversations.

### New, harder suite

This PR reuses **the identical 60 fictional facts and their deterministic
ZIP** to isolate *query wording* effects from database size effects.
`CHALLENGE_CASES` defines 24 new, immutable questions:

- 4 × paraphrase current weekday
- 4 × ask about previous/original weekday
- 4 × ask for before-and-after correction history
- 4 × indirectly ask about place, not time
- 4 × mention a wrong nearby project number then explicitly exclude it
- 2 × ask for unsupported budget/start-time details
- 2 × omit a unique referent or ask an ambiguous cross-project question

**20 answerable retrieval questions; 4 abstention cases.**
The first 20 have reviewed source assertion IDs and full correction lineage.
For ambiguous questions, the synthetic harness pre-labels
`subject=None` so the decision gate abstains; this is **not** proof that
a deployed LLM recognizes the ambiguity. Similarly, the query-to-subject,
predicate, and intent mappings are gold fixtures, **not** automatic
conversation understanding.

The engine comparison is fair on facts, question strings, effective
timestamp, Hindsight route, top K, provenance checks, and structured
decision rules. A decision is correct only if **every assertion in the
source lineage is present among the top K** and the decision code matches
the independent gold. No engine can borrow missing history from the full
fixture during inference.

## What changes technically

- `src/jarvis/memory/research_challenge_suite.py` provides a completely
  separate challenge case registry and strict per-category structured
  evaluator. The prior Step 7 baseline benchmark and its golden results
  are unchanged.
- `tools/research/step7_local_engine_comparison.py` has a tiny
  backward-compatible optional `capture` hook, preserving all existing
  source readback, Docker isolation, import, failure and cleanup checks.
- `tools/research/step8_local_hard_language_probe.py` previews offline
  by default and prints the **actual local BM25** result without invoking
  Hindsight, Docker or a model. An explicit new flag would permit one
  disposable local 60-fact import, 24 real Hindsight recall requests,
  comparison against BM25 and RRF, and verified deletion.
- `tests/test_step8_hard_language_probe.py` includes fake-transport
  evidence tampering, missing predecessor, complete lineage, mandatory
  24-query count, cleanup failure, and `python -I` preview tests.

No Graphiti/Mem0 installation, no production runtime hook, no SQLCipher
reads, no owner information, no external LLM, and no persistent index.

## Owner-machine procedure — offline only until fresh approval

Run after reviewing the draft PR and all six GitHub CI jobs pass:

```powershell
cd C:\Users\gkgaj\Desktop\jarvis_hindsight_loopback

if (git status --porcelain) { throw "Worktree has local changes" }
git fetch origin research/step8-linguistic-recall-challenge-20261018
if ($LASTEXITCODE -ne 0) { throw "Fetch failed" }
git switch --detach FETCH_HEAD
if ($LASTEXITCODE -ne 0) { throw "Checkout failed" }

git rev-parse --short HEAD

$py = "C:\Users\gkgaj\Desktop\jarvis_v1\.venv\Scripts\python.exe"
& $py -m pytest -q tests\test_step8_hard_language_probe.py tests\test_step7_engine_comparison.py
if ($LASTEXITCODE -ne 0) { throw "Offline tests failed" }
& $py -I tools\research\step8_local_hard_language_probe.py
if ($LASTEXITCODE -ne 0) { throw "Offline preview failed" }
```

**Do not run** `--allow-one-local-60-fact-hard-challenge` until the owner
separately approves exactly one new fictional import and 24 local requests,
after CI and offline gates have passed. Approval of the previous Step 7
experiment is NOT approval to import again.

## Interpretation and remaining challenges

The linguistic-challenge score can establish whether actual Hindsight
retrieval, BM25, or their union copes better with altered query wording
*on these 60 exact fictional records*. It cannot show whether an LLM can
extract memories, resolve pronouns, disambiguate identities, preserve
negation, understand user corrections, or reliably handle years of
retrieved context. A future benchmark must independently assess those
components, with natural language user turns and multiple valid referents.

Neither Hindsight nor other memory engines gain permission to overwrite
JARVIS's canonical SQLCipher store. Production promotion remains blocked.
