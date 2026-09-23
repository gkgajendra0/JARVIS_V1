# Research and Acceptance Records

This directory contains bounded research, implementation evidence, benchmark results, and owner-machine acceptance records for JARVIS product slices and approved interludes.

Research is evidence, not architecture and not implementation authority. `docs/CURRENT_ARCHITECTURE.md` describes what currently exists, `docs/CURRENT_PLAN.md` owns active work, and `docs/ROADMAP.md` owns sequence.

Each record should answer, where applicable:

- What JARVIS behavior is required?
- What current technologies are credible candidates?
- What old-JARVIS work is relevant as evidence or lessons?
- Which responsibilities are commodity vs JARVIS-owned authority?
- What are the architecture, security, privacy, licensing, cost, latency, reliability, and maintenance implications?
- What benchmark or acceptance evidence is required?
- What is the final decision: `KEEP_OURS`, `ADOPT`, `ADAPT`, `WRAP`, `REWRITE`, or `REJECT`?
- Was the work accepted, bounded/deferred, superseded, rejected, or left experimental, and why?

Historical proposal/experiment files may retain the state they had when written. They must not be treated as current architecture merely because they remain in Git. Later acceptance/reconciliation records take precedence for current status.

For the accepted work after formal Step 7, including JARVIS Hands, Pocket 3 native OWNER tracking, selective runtime-performance recovery, PR #38 stability fixes, PR #40 Pocket BLE startup hardening, and the explicit deferred/superseded/rejected ledger, see `POST_STEP_7_INTEGRATION_ACCEPTANCE.md`.

The focused owner-machine/CI acceptance record for PR #40 is `POCKET3_BLE_STARTUP_ACCEPTANCE_2026-09-14.md`.

The final owner-machine/CI acceptance record for persistent concurrent work orchestration PR #55 is `PERSISTENT_WORK_ACCEPTANCE_2026-09-20.md`.

The historical owner-approved sequencing decision for reliability cleanup followed by the bounded Self-Repair Foundation interlude is `SELF_REPAIR_SEQUENCE_DECISION_2026-09-20.md`. That sequence completed on 2026-09-23.

The deterministic foundation research is `SELF_REPAIR_FOUNDATION_RESEARCH_2026-09-20.md`, and final owner-machine acceptance is `SELF_REPAIR_PHASE5_ACCEPTANCE_2026-09-23.md`.

The authoritative forward Self-Repair -> Repair Learning -> Self-Evolution program plan is `../SELF_REPAIR_AND_EVOLUTION_MASTER_PLAN.md`. Historical research files remain evidence and must not override that master plan's current phase/status.

Do not research future subsystems merely because they are interesting. Research the active product slice or the explicitly active cross-cutting program phase unless a demonstrated blocker or owner-approved sequence change requires a detour.

- `POCKET3_OWNER_CONTINUITY_ACCEPTANCE_2026-09-20.md` — owner-machine acceptance evidence for issue #56 / PR #61: fresh OWNER acquisition, persisted exact visual-track authorization, biometric/head-gap continuity, and no false confirmed OWNER loss.
