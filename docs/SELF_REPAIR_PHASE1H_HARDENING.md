# Self-Repair Phase 1H — Foundation Hardening

## Status

**DONE / OWNER-MACHINE ACCEPTED 2026-09-24**

Phase 1H hardened the already accepted deterministic R2 runtime Self-Repair foundation before engineering repair history is allowed to feed Phase 2 EngineeringKnowledge.

This document is the canonical Phase-1H contract and acceptance record. The broader program sequence is owned by `SELF_REPAIR_AND_EVOLUTION_MASTER_PLAN.md` and `GOVERNED_AUTONOMOUS_ENGINEERING_MASTER_PLAN.md`.

---

## Implemented hardening

Phase 1H accepted the following foundation changes:

1. recovered attempts remain in the rolling restart history until they age out;
2. one target/action circuit breaker spans crash and liveness policies, incidents and crash fingerprints;
3. execution preconditions are evaluated from typed runtime state at execution time;
4. recovery requires typed verification bound to the registered policy verification contract;
5. RepairAttempt retains immutable trigger/policy snapshots plus a stable policy digest;
6. engineering-incident persistence uses versioned/checksummed SQLite migrations;
7. Windows runtime lifetime is owned by a Job Object with kill-on-close semantics and psutil fallback;
8. launcher-only failure cannot leave an orphan interpreter beside the recovered runtime;
9. production supervision is local-only and does not perform Git/network update polling;
10. a bounded Windows guardian owns the production runtime supervisor across current-user logon/session startup;
11. production fail-closed escalation exits cleanly so the outer guardian cannot bypass the inner Self-Repair budget;
12. operator logs report rolling restart-budget position rather than confusing it with durable per-policy attempt numbering.

---

## Owner-machine acceptance evidence

Accepted evidence on 2026-09-24 includes:

- full runtime crash recovery;
- alive-but-unresponsive runtime recovery after watchdog threshold + confirmation;
- launcher-only death recovery with old runtime-tree cleanup;
- interpreter-only death recovery;
- supervisor death followed by bounded outer-guardian recovery;
- exactly one recovered runtime chain with no accepted duplicate/orphan runtime;
- provider-quota degradation observed without incorrectly becoming runtime-liveness failure;
- mixed crash/liveness repair history sharing the same target/action restart budget;
- clean rolling-window circuit-breaker test establishing three verified recent repairs and then injecting a fourth crash;
- the fourth crash produced **zero** new RepairAttempts and left **zero** guardian/supervisor/runtime processes, proving the fail-closed shared circuit breaker blocked the fourth restart;
- automatic Windows logon startup was observed after a system restart;
- when the configured Pocket 3 microphone was not yet enumerated by Windows, startup correctly failed closed at preflight instead of silently selecting another input;
- after the Pocket 3 input became available, the same production startup path passed preflight, initialized audio/vision and reached native owner-tracking lock.

The final circuit-breaker acceptance output was:

```text
3/3 RECENT REPAIRS CONFIRMED
Injecting decisive FOURTH crash...
New repair attempts afterward: 0
Remaining guardian/runtime processes: 0
PASS - FOURTH RESTART WAS BLOCKED.
```

---

## Non-blocking follow-up

Windows may enumerate the configured Pocket 3 microphone after the logon-triggered guardian starts. The accepted behavior is fail-closed: JARVIS does not substitute an arbitrary microphone.

A future resilience improvement may add bounded startup retry/readiness handling for temporarily unavailable owner-configured hardware. That improvement is **not** evidence that the guardian/logon architecture failed and does not reopen Phase 1H acceptance.

---

## Exit decision

All Phase-1H blocking acceptance gates are satisfied.

Phase 2 may proceed as **EngineeringKnowledge Foundation**, with `REPAIR` as the first vertical. EngineeringKnowledge remains advisory evidence and never gains execution Authority merely because it was learned from an accepted repair.
