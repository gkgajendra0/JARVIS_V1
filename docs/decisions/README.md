# Architecture Decision Records

This directory contains durable Architecture Decision Records (ADRs) for accepted technology/architecture choices whose reasoning future work must preserve.

ADRs support—but do not replace—the current authorities:

- `docs/PRODUCT.md` owns durable product intent/status;
- `docs/ROADMAP.md` owns sequence;
- `docs/CURRENT_PLAN.md` owns active work/disposition;
- `docs/CURRENT_ARCHITECTURE.md` owns what actually runs.

An older ADR may describe the accepted state at the time it was written. When later accepted work changes that boundary, a newer ADR should explicitly reconcile/supersede the old assumption rather than silently rewriting history.

Current important reconciliation decisions include:

- `ADR-016_SPOKEN_ACTOR_BINDING_AND_BOUNDED_POST_T3_T2.md` — turn-specific spoken actor binding/general biometric T2 remain deferred, while Hands may use only a bounded same-session T2 convenience derived from successful direct-user Windows Hello/T3;
- `ADR-017_POST_STEP_7_GOVERNED_HANDS_AND_NATIVE_POCKET_INTERLUDE.md` — accepted Hands/Pocket/performance/stability foundations are current production architecture without prematurely marking later roadmap Steps 9/10/12 complete.

Create an ADR when future work needs to understand the context, decision, alternatives, tradeoffs, replacement boundary, and reconsideration triggers. Do not create ADRs for routine implementation details, temporary bugs or disposable experiments. Git history remains the chronological archive.
