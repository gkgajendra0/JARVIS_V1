# Step 5: Synthetic memory decisions, conflict safety and read-only shadow contract

**Date:** 2026-10-18  
**State:** offline-only research implementation. No JARVIS production memory connection, no cloud model calls, no Hindsight service calls and no canonical-memory writes.

## What we have already proven

- Step 4 owner-machine import into isolated Hindsight 1.0.0 succeeded with five fictional facts, exact source/provenance readback and disposable bank cleanup.
- Nine real local recall requests completed; evidence requirements for seven cases passed **7/7**, and two unknown cases were queried but not evaluated for abstention.
- GitHub CI for #277 (commit `e5b8aefd6beafa9647d534bfa8b18a5080d24b10`) passed all six jobs.
- Retrieval proves the facts can be found, **not** that an assistant resolves corrections, history or contradictions.

## This PR

1. `src/jarvis/memory/research_decision_gate.py` is a pure deterministic interpreter of structured fictional facts. It accepts an explicit `MemoryQuestion(subject, predicate, intent)` and complete versioned evidence. It validates synthetic identity and provenance, predecessor links, chronological versions and branch uniqueness.
2. The decision gate distinguishes: **current** answer, **original** statement, **history** (a correction lineage versus a real historical change), independent facts, and **abstention** when evidence is missing, ambiguous, contradictory, incomplete or mixes revision semantics. It will not choose the latest-looking fact when multiple branches or roots exist.
3. `tools/research/step5_memory_decision_acceptance.py` projects only the existing five **exactly pinned fictional texts** into typed assertions and scores all nine pinned questions. It does not parse owner language, call an LLM or access user memories. This is a fixture-specific correctness test, **not general NLP reasoning**.
4. The large synthetic workload generates **3,600** strictly fictional assertions (600 subjects × 2 predicates × 3 versions), scores **4,200** decisions including 600 unsupported questions, and verifies correction/historical-change semantics and explicit abstention.
5. `compare_shadow(canonical, candidate)` is a read-only synthetic comparison contract: reports disagreement without changing either decision. It neither reads SQLCipher nor promotes the Hindsight candidate.

## Zero-network commands

```powershell
cd C:\Users\gkgaj\Desktop\jarvis_hindsight_loopback
$py = "C:\Users\gkgaj\Desktop\jarvis_v1\.venv\Scripts\python.exe"

& $py -m pytest -q tests\test_step5_memory_decision_gate.py
if ($LASTEXITCODE -ne 0) { throw "Decision gate offline tests failed" }

& $py -I tools\research\step5_memory_decision_acceptance.py
if ($LASTEXITCODE -ne 0) { throw "Nine-case decision acceptance failed" }

& $py -I tools\research\step5_memory_decision_acceptance.py --large-synthetic
if ($LASTEXITCODE -ne 0) { throw "Large fictional benchmark failed" }
```

No Docker operations or files are written by these commands. They produce sanitized, synthetic-only pass/fail summaries.

## Strict interpretation of results

Passing 9/9 is proof that **this deterministic structured-data rule engine** handles the nine reviewed fictional cases. Passing 4,200/4,200 would show it handles the larger **constructed, deterministic** sample. It does not prove future user-language understanding, reliable open-world inference, actual large-scale Hindsight retrieval, multilingual performance, tail latency, LLM-mediated reasoning or correctness on real owner memories.

### Remains before production integration

- Independently test a **bounded, privacy-reviewed adapter** that transforms real memory evidence into typed assertions without trusting LLM-produced source metadata or letting an assistant invent provenance. Current pinned-text adapter is intentionally not generalized.
- Separately evaluate ambiguity, effective-time versus mention-time, transitive and mixed corrections, contradictory independent witnesses, deletions/retractions, identity disambiguation, and uncertainty. A mixed revision chain currently **abstains**.
- Benchmark a truly large isolated Hindsight bank, including recall precision/recall, latency, CPU/GPU footprint and reranker behavior. The 3,600-fact corpus in this PR is an **offline decision** benchmark, not a large Hindsight server test.
- Implement **feature-flagged, read-only** observability against JARVIS canonical memory with explicit owner approval, strict access controls and redacted metrics. The `compare_shadow` primitive alone is not a live adapter.
- Add independent regression/security reviews, restore/rollback protocol, gated policy review, CI and owner-machine acceptance before any staged promotion. SQLCipher remains canonical; no automatic mirroring, writing, merging or deployments.

**Do not merge or enable this work in production merely because unit tests pass.** Keep the branch draft and layered on earlier research until reviewed.
