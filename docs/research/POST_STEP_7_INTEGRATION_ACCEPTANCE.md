# Post-Step-7 Integration Acceptance

Status: **ACCEPTED PRODUCTION BASELINE**

Date: 2026-09-14

Protected-main baseline: `fcb87500b0cf7e431f9f76077aa1fad8234db53f`

## Accepted integration work

- **PR #30 — JARVIS Hands:** governed desktop/browser/file/device/Git foundations, verification, audit and bounded fallback behavior.
- **PRs #33–#35 — Pocket 3 native tracking:** native DJI transport, OWNER target/tracking evidence, adaptive perception, leave/re-enter reacquisition and clear/recenter behavior.
- **PR #36 — selective runtime performance:** bounded MiniFAS threading, low-CPU wake cascade, opt-in preview and runtime profiler.
- **PR #38 — runtime stability:** canonical USER-generation cleanup, silent-audio recovery, immediate standby, Hands fixes and Pocket tracking/recovery hardening.
- **PR #40 — Pocket BLE startup reliability:** protocol-readiness gating before pairing, bounded startup retries, correct reconnect cooldown timing and clean shutdown-aware BLE waits.

Detailed PR #40 acceptance evidence is recorded in `docs/research/POCKET3_BLE_STARTUP_ACCEPTANCE_2026-09-14.md`.

## Deferred / unfinished

| Item | State | Reason |
| --- | --- | --- |
| Turn-specific spoken actor binding | **DEFERRED** | OWNER presence does not prove who spoke a specific turn; speaker/active-speaker evidence remains shadow-only pending stronger validation. |
| PR #18 Step-3 branch | **UNMERGED HISTORICAL** | Useful evidence remains, but current main has moved beyond the branch. |
| Strict independent 4.5D semantic-memory verifier | **DEFERRED / UNRESOLVED** | Independent semantic release quality was not proven strongly enough. |
| Phase 4.5E automatic memory influence | **DEFERRED / DISABLED** | Automatic memory influence remains off until the semantic release boundary is stronger. |
| Full local/offline conversation | **DEFERRED** | The accepted provider-failure survival slice solved the immediate need without another conversation stack. |
| Long-running/background research and proactive monitoring | **DEFERRED** | Belongs to later governed background/proactivity work. |
| Full Steps 9/10/12 | **PLANNED WITH PARTIAL FOUNDATIONS** | Hands provides useful foundations but not the complete future product slices. |

## Superseded / rejected history

- PR #13 was superseded by the accepted Step-3 closure.
- PR #27 was superseded by the accepted Step-7 implementation.
- PR #31 was superseded by selective profiler/performance recovery in PR #36.
- PR #32 was superseded/partially recovered; only proven pieces were carried forward.
- PR #37's canonical generation correction is represented in PR #38.
- Automatic workstation locking from OWNER absence was rejected; OWNER loss affects tracking/reacquisition/recenter only.

## Next formal roadmap work

Step 8 — Notes, Tasks, Reminders, and Scheduling — remains the next formal roadmap slice. It must begin research-first from the accepted main baseline and reuse existing capability, authority, memory, audit and lifecycle boundaries.
