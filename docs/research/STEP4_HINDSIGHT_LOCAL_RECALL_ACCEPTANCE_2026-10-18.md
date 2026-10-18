# Step 4 — Controlled real localhost Hindsight recall acceptance

**Date:** 2026-10-18. **Status:** opt-in capture code drafted; no live recall performed.
**Dependency:** draft PR #276 (nine fixed scenarios and offline scoring) and PR #275 (owner-proven import/readback/cleanup on Hindsight API 1.0.0).

## Objective

Measure whether Hindsight 1.0.0 retrieves the right **five fictional memory facts** for nine precommitted queries while the disposable bank is still present. The prior accepted archive import probe deletes the bank immediately after reading the facts, so it cannot measure retrieval. This stacked PR adds an explicit callback after import readback and before deletion, without changing the legacy import-only CLI.

The new CLI is `tools/research/step4_hindsight_local_recall_probe.py`. Running it **without** the approval flag executes no Docker, network, LLM, bank, or real-memory work.

## Safety protocol

1. Owner must approve **one** local synthetic-only write and nine local recall searches by deliberately specifying `--allow-one-local-recall-evaluation`.
2. Verify the existing Docker container identity, localhost-only port, no cloud credentials, `HINDSIGHT_API_LLM_PROVIDER=none`, no observations or auto-consolidation, embedded PostgreSQL and a single research named volume. No new Docker start, downloads, installs, resets, or external requests.
3. Create **one new disposable bank**, check effective per-bank safety configuration, upload the same SHA-256-pinned synthetic ZIP, poll one import and verify all five exact fact texts + source lineage.
4. While the bank exists, send precisely **nine** JSON `POST /v1/default/banks/{bank_id}/recall` retrieval requests (not LLM calls), from the frozen `CASES` in PR #276. Do not derive or customize queries based on the results.
5. Validate every returned fact against the pinned synthetic corpus and metadata. Measure whether each of the 7 evidence-bearing cases has all required assertions within its predeclared top-3/top-5 ranking.
6. Delete the bank inside the original import runner's `finally` and verify it is gone, even if recall or provenance fails. **Do not retry**, and do not run on production memory.
7. Report *only* sanitized metrics, case IDs, ranks, archive hash and cleanup flags. Never persist raw recall text, internal bank ID, API error body or personal facts.

## Predeclared metrics

- **Provenance gate:** 100% of returned facts must match exact synthetic identities; fail closed if any mismatch, unknown assertion or duplicate.
- **Retrieval gate:** 7/7 evidence-bearing cases meet rank limits to pass. The two unsupported queries have no retrieval target and do not count toward 7/7.
- **Decision gate:** **not evaluated**. No answer model is configured; the scorer cannot infer correction-vs-history truth by top-ranked similarity alone.
- **Abstention accuracy:** **not evaluated**. Hindsight may retrieve related facts for an unknown query; abstention requires a separate safe decision layer.

An observed retrieval score below 7/7 returns exit code `2` with sanitized metrics and confirmed cleanup: a meaningful measured failure, not a reason for an automatic retry. Hard errors (HTTP, wrong fact provenance, cleanup failure) fail closed with exit code `1`. An observed 7/7 score returns `0`, but **neither outcome authorizes production deployment**.

## Windows commands (read-only/offline preflight first)

```powershell
cd C:\Users\gkgaj\Desktop\jarvis_hindsight_loopback

if (git status --porcelain) { throw "Dirty research worktree" }
git fetch origin research/step4-hindsight-local-recall-acceptance-20261018
if ($LASTEXITCODE -ne 0) { throw "Fetch failed" }
git switch --detach FETCH_HEAD
if ($LASTEXITCODE -ne 0) { throw "Checkout failed" }
git rev-parse --short HEAD

$py = "C:\Users\gkgaj\Desktop\jarvis_v1\.venv\Scripts\python.exe"
& $py -m pytest -q tests\test_step4_hindsight_loopback_import_probe.py tests\test_step4_hindsight_semantic_eval.py
if ($LASTEXITCODE -ne 0) { throw "Tests failed" }

& $py -I tools\research\step4_hindsight_local_recall_probe.py
```

Expected default `status=dry_run_zero_network_calls`, `queries_planned=9`. **Do not run any live import until CI and local tests pass and the owner explicitly approves the single run.**

After the owner has reviewed acceptance limits and deliberately approves one research write:

```powershell
# This is a SEPARATE, explicitly opt-in local-only import+recall operation:
& $py -I tools\research\step4_hindsight_local_recall_probe.py --allow-one-local-recall-evaluation
$exitCode = $LASTEXITCODE
$banks = Invoke-RestMethod "http://127.0.0.1:18888/v1/default/banks?query=jarvis-dev-only-&limit=100" -ErrorAction Stop
Write-Host "Probe exit code: $exitCode; research banks remaining: $($banks.total)"
```

A successful readback is not evidence of correct answer synthesis or self-learning. PR stays draft, unmerged, and isolated.

See `docs/research/STEP4_HINDSIGHT_SEMANTIC_RETRIEVAL_GATE_2026-10-18.md` for the frozen nine queries and rank targets.
