# Phase 2J — EngineeringKnowledge Owner-Machine Acceptance

## Status

**READY FOR OWNER-MACHINE ACCEPTANCE — NOT YET ACCEPTED**

Phases 2A through 2I are implemented and merged on protected main. Phase 2 is not DONE until this owner-machine matrix passes and the final documentation reconciliation is accepted.

## Why this run is required

CI proves deterministic contracts, migrations, security gates, retrieval behavior under controlled fixtures, and Windows regressions.

CI cannot prove all of the following on the owner's production machine:

- a fresh real R2 recovery on the production supervisor;
- EngineeringKnowledge independence from that recovery;
- the production engineering SQLite history;
- the owner's local Qwen model/GPU behavior;
- real RAM/VRAM/index cost;
- real repair projection and retrieval from production evidence.

## One-command acceptance runner

After pulling the accepted main revision and while the normal supervised JARVIS runtime is healthy, run:

    jarvis-engineering-knowledge-acceptance --live-crash --device cuda

Equivalent module form:

    python -m jarvis.engineering_knowledge.acceptance --live-crash --device cuda

The live-crash flag is deliberately explicit. Without it, the runner will perform non-destructive checks but will leave the R2 independence gate PENDING.

The runner refuses live fault injection when recent runtime-restart history is still inside the 300-second circuit-breaker window. It also refuses if it cannot identify exactly one production runtime owned by a recognized JARVIS supervisor.

## Acceptance sequence

The runner intentionally orders the critical proof as follows:

1. locate the canonical production engineering database;
2. verify the restart circuit-breaker precondition;
3. inject one explicit crash into the uniquely supervised production runtime;
4. wait for a new typed PASS / RECOVERED R2 RepairAttempt;
5. prove no EngineeringKnowledge revision exists yet for that new repair;
6. only then project the RepairAttempt into an EngineeringKnowledge CANDIDATE;
7. promote it through STAGED to ACCEPTED;
8. verify canonical integrity and exact incident/attempt/trigger/policy/verifier provenance;
9. verify exact and lexical retrieval with embeddings disabled;
10. verify wrong-component applicability exclusion;
11. verify paraphrased retrieval with the pinned local Qwen-256 baseline;
12. verify poisoning and secret-like evidence gates;
13. verify unknown facets fail closed;
14. verify a reviewed new future facet plugs into the same registry;
15. run the Phase-2H qrel corpus through exact/lexical retrieval;
16. run the same corpus with real Qwen-256 where available;
17. record latency, CPU, RSS, optional CUDA VRAM, database/index size, and rebuild cost.

This ordering is important: the R2 recovery happens before any knowledge projection for the new repair, providing direct negative-control evidence that advisory EngineeringKnowledge did not cause or authorize the recovery.

## Evidence output

The runner writes one JSON evidence file under the default operational acceptance directory:

    %LOCALAPPDATA%\JARVIS\operations\acceptance\

unless an explicit output path is supplied.

The console reports every gate as PASS, FAIL, or PENDING.

A FAIL means implementation evidence is not acceptable and must be corrected before Phase 2 closure.

A PENDING result means the required proof could not be completed, for example:

- the restart circuit-breaker window has not aged out;
- no uniquely supervised runtime is running;
- the local retrieval dependency/model is unavailable;
- a required owner-machine resource cannot be measured.

## Retrieval benchmark interpretation

Phase 2I deliberately retains the current baseline until owner-machine evidence exists:

    exact identifiers/evidence references
      + SQLite FTS5 unicode61/BM25
      + Qwen3-Embedding-0.6B at 256 dimensions
      + exact NumPy cosine
      + RRF
      + deterministic lifecycle/applicability/integrity/sensitivity gates

The qrel safety gate is zero tolerance for:

- applicability violations;
- stale/superseded results explicitly prohibited by the corpus;
- sensitivity/leakage violations;
- false positives on no-answer/security cases.

The owner-machine run measures the real Qwen baseline. It does not silently adopt the optional Phase-2I candidates.

If the real baseline exposes a relevance or abstention weakness, the result is evidence for a correction or benchmarked improvement, not a reason to weaken the safety gate.

## Closure rule

Do not mark Phase 2 DONE from a green acceptance-harness PR alone.

After the owner-machine run:

- inspect the generated evidence;
- correct and rerun any FAIL;
- resolve any required PENDING gate;
- reconcile CURRENT_ARCHITECTURE, CURRENT_PLAN, PROJECT_STATE, and any materially affected PRODUCT/ROADMAP statements;
- create the canonical Phase-2 acceptance record;
- obtain the owner's final acceptance of Phase 2.
