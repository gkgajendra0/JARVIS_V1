# Step 5 — actual localhost recall to deterministic memory decision acceptance

**Date:** 2026-10-18. **Status:** opt-in local-only test code, not executed against owner's Hindsight yet. Draft/unmerged research; **never** production promotion.

## Why add this

Step 4's owner-machine test imported five fictional facts, ran nine real
`POST /memories/recall` queries and obtained **7/7 required evidence rankings**,
with provenance and cleanup passing. That did not measure whether a decision
layer can answer correctly or abstain.

This follow-up executes the *same pinned nine queries* while the disposable
bank exists, passes only the **facts actually retrieved for each question**
into the Step 5 structured, source-checked decision engine, and then scores:
- 7 required structured answers;
- 2 explicit abstentions on questions with no evidence;
- source IDs and correction-vs-historical-change semantics;
- missing predecessor fails closed instead of silently filling from fixture.

The engine is deterministic over a five-fact fictional fixture; **no natural
language model generates answers**, so this does not prove real JARVIS language
understanding, real-owner memory handling, multilingual reasoning or overall
reliability.

## Safe operating contract

The CLI `tools/research/step5_hindsight_local_decision_probe.py` does nothing
but print a dry-run report without its opt-in flag. Under one explicit owner
approval it calls the existing verified Docker safety guard, imports **one
synthetic ZIP** into one fresh disposable localhost bank, checks all five
documents/facts and their source metadata, executes exactly nine frozen local
recall requests and scores decisions *before* deletion. The prior import
harness `finally` verifies deletion even when a recall fails.

Output contains only scores, case IDs, cleanup and archive SHA256: no
retrieved text, temporary bank ID, private memory or source data. Hindsight
cloud LLM and consolidation stay disabled. No automatic retry, model request,
owner data ingestion or SQLCipher access occurs.

- Exit 0: 7/7 evidence retrieval plus 9/9 deterministic structured decisions
  including 2/2 abstentions, provenance and bank cleanup all successful.
- Exit 2: measured failure of retrieval and/or structured decision thresholds,
  with sanitized results and verified cleanup. Do not automatically retry.
- Exit 1: fail-closed transport, provenance, import or cleanup error. Stop and
  inspect without repeating the local import.

## Owner Windows offline first

```powershell
cd C:\Users\gkgaj\Desktop\jarvis_hindsight_loopback
if (git status --porcelain) { throw "Research worktree has local changes" }
git fetch origin research/step5-hindsight-local-decision-acceptance-20261018
if ($LASTEXITCODE -ne 0) { throw "Fetch failed" }
git switch --detach FETCH_HEAD
if ($LASTEXITCODE -ne 0) { throw "Checkout failed" }
git rev-parse --short HEAD

$py = "C:\Users\gkgaj\Desktop\jarvis_v1\.venv\Scripts\python.exe"
& $py -m pytest -q tests\test_step4_hindsight_loopback_import_probe.py tests\test_step5_memory_decision_gate.py
if ($LASTEXITCODE -ne 0) { throw "Offline tests failed" }
& $py -I tools\research\step5_hindsight_local_decision_probe.py
if ($LASTEXITCODE -ne 0) { throw "Dry-run failed" }
```

Only after full GitHub CI, offline tests and owner confirmation of the
existing isolated Hindsight container and zero temporary banks, the **owner**
may explicitly approve a single synthetic run using
`--allow-one-local-structured-decision-evaluation`. This is a separate live
write, **not** implied by earlier research approvals.

Regardless of success, the following remain unmet: a large-scale actual
Hindsight recall benchmark, verified language-to-assertion extraction,
permission-safe live shadow integration with JARVIS canonical SQLCipher,
production performance budgets, real-world conflict policies and end-to-end
acceptance. Do not merge or promote based on this small fictional test.
