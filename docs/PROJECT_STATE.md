# JARVIS V1 Project State

## Purpose

This is the canonical repository-state ledger.

It answers four questions:

1. what is implemented and accepted on protected `main`;
2. what is only partial or bounded;
3. what is deferred/open;
4. what was superseded, rejected, or closed without merge.

Detailed experiment notes, old acceptance transcripts, superseded architecture proposals
and abandoned branches are historical evidence in Git history. They are not current
documentation authority.

Snapshot baseline verified from protected `main` at
`7cd4ab241d4706130a82636657da25eaf639d961` on 2026-09-24.

---

## Status vocabulary

- **DONE** — accepted production capability for its defined scope.
- **BOUNDED** — accepted useful subset with an explicit deferred remainder.
- **PARTIAL** — accepted foundation exists but the later formal product slice is not complete.
- **ACTIVE** — current cross-cutting work.
- **PLANNED** — intended but not accepted as production.
- **DEFERRED** — intentionally postponed because the acceptance boundary is not yet strong enough.
- **SUPERSEDED** — replaced by later accepted work.
- **REJECTED** — evaluated and intentionally excluded from production.
- **HISTORICAL** — useful evidence retained by Git history but not current architecture.

---

## Accepted production state

| Area | Status | Current accepted state |
| --- | --- | --- |
| Steps 0–3 | DONE | foundation, conversational core, wake/audio, vision foundation, identity/trust/Authority/observability accepted |
| Step 4 memory/context | BOUNDED | encrypted memory lifecycle, explicit recall and bounded semantic retrieval accepted |
| Step 5 provider resilience | BOUNDED | truthful provider-failure handling and local fallback status accepted |
| Step 6 knowledge/research | BOUNDED | provider-neutral current research, provenance and source sufficiency accepted |
| Step 7 capability runtime | DONE | governed capability runtime and safe local reads accepted |
| JARVIS Hands | PARTIAL foundation for Steps 9/10/12 | native Windows actions, Playwright, UI Automation, bounded file/device/Git work and governed visual fallback |
| Pocket 3 OWNER tracking | DONE for current defined scope | native targeting/tracking, reacquisition, recenter, transport recovery and continuity accepted |
| Self-Awareness | PARTIAL foundation for later diagnostics | Self Model, deterministic health/dependencies/blast radius, operational evidence and incident engineering memory |
| Persistent concurrent work | DONE foundation | durable WorkItems/steps/deliveries, restart recovery, background research/development, priority/resource control |
| Deterministic Self-Repair | PARTIAL foundation for Step 19 | R1/R2 typed framework; owner-accepted automatic production behavior is R2 runtime crash/hang recovery with durable RepairAttempts, budgets and readiness/liveness verification |
| Self-Repair / Self-Evolution program | ACTIVE | Phase 1 R2 foundation accepted; Phase 1H hardening is active before Phase 2 RepairKnowledge implementation |
| Step 8 notes/tasks/reminders | PLANNED | still the next numbered product slice when numbered roadmap work resumes |

---

## Accepted implementation history

The following merged PRs are represented by the current production state above.
Documentation-only reconciliation PRs are included because they changed repository
truth/status but not runtime behavior.

### Foundation, voice, vision and development supervision

- **#1** Step 2.5 vision sensor and active target tracking foundation.
- **#2** owner-approved development supervisor.
- **#3** pre-Step-3 documentation reconciliation.
- **#4** time-aware startup greetings.
- **#25** long-utterance inactivity fix.

### Identity, trust, Authority and Step 3

- **#6** Step-3 architecture approval.
- **#7** Step-3A Authority foundation.
- **#8** Step-3A status closure.
- **#9** .NET artifact hygiene.
- **#10, #12, #15** owner identity/face/liveness, sensor/AV and final Step-3 accepted foundation.
- **#16, #17** Step-4 activation and runtime log correction.
- **#49** power/session intent binding safety.

### Memory, provider resilience, research and capability runtime

- **#20, #21, #22** bounded Step-4 memory/context and semantic recall closure.
- **#23** minimal Step-5 provider resilience.
- **#24** provider-neutral Step-6 current research.
- **#26, #28, #29** governed computer-use/core capability runtime and Step-7 closure.
- **#30** governed Windows Hands.

### Pocket 3, performance and runtime stability

- **#33, #34, #35** native OWNER tracking, locked-FPS optimization and recovery integration.
- **#36** accepted OPT-1 runtime optimizations.
- **#37, #38** generation drift/runtime stability corrections; #37's useful behavior is consolidated by later runtime work.
- **#39** production-state documentation reconciliation.
- **#40, #42** BLE startup/pairing reliability.
- **#43** realtime conversation grounding + semantic standby.
- **#48** native tracking liveness recovery.
- **#61** Pocket OWNER continuity across transient biometric gaps.
- **#68, #71** removal of obsolete manual follow/lock semantics.

### Self-Awareness

- **#41** Self-Awareness foundation.
- **#51, #52, #54** production baseline and post-merge documentation reconciliation.

### Persistent work orchestration and reliability prerequisites

- **#55** Persistent Concurrent Work Orchestration foundation.
- **#58, #59** post-orchestration documentation reconciliation.
- **#60** documented reliability-cleanup/Self-Repair sequence.
- **#62** durable WorkDelivery TTS retry backoff.
- **#64** lifecycle speech independence from cloud TTS quota.

### Self-Repair and Self-Evolution foundation

- **#72** refined Self-Repair research with RepairKnowledge/model-routing/curriculum patterns.
- **#73** deterministic repair domain + registry.
- **#74** durable incident-linked RepairAttempt persistence.
- **#75** bounded supervisor crash recovery.
- **#76** liveness stabilization before recovery.
- **#77** bounded runtime liveness watchdog.
- **#78** fault-injection acceptance harness.
- **#79, #80** CI corrections required during acceptance.
- **#81** real-hardware startup-readiness handshake.
- **#82** suspended-runtime socket/Git blocking corrections.
- **#83** watchdog isolation from Git update polling.
- **#84** Windows virtual-environment process-tree fault injection.
- **#85** full runtime-tree force cleanup during recovery.
- **#86** final owner-machine Self-Repair acceptance record.
- **#87** complete Self-Repair/Self-Evolution master-plan reconciliation.

Final deterministic Self-Repair acceptance:
- crash recovery passed;
- alive-but-unresponsive recovery passed;
- full Windows runtime process tree was frozen and recovered;
- durable RepairAttempt completed with
  `execution_result = unresponsive child restart stabilized`,
  `verifier_result = readiness_and_liveness_stable:6_probes`,
  `verdict = recovered`;
- issue **#65** is closed.

---

## Open / deferred work

These are intentionally not represented as completed.

| Issue / item | Status | Meaning |
| --- | --- | --- |
| #19 production conversation voice isolation / turn ownership | DEFERRED RESEARCH | speaker/ASD evidence remains shadow; no turn-specific speaker authority |
| #44 relative/provider volume fast-path semantics | DEFERRED BUG | relative-volume/current-volume normalization remains unfinished |
| #45 false-interruption resume | DEFERRED BUG | configured resume semantics exceed current production audio pause capability |
| #46 intermittent LiveKit AudioMixer timeout | DEFERRED INVESTIGATION | warning not yet proven to cause a user-visible failure |
| #63 blocked background-work status truth | DEFERRED FOLLOW-UP | blocked work must surface blockers instead of stale normal ETA/progress |
| #69 multi-device JARVIS distributed Core + remote client | PLANNED / OPEN | separate future architecture stream; not current implementation |
| strict Step-4 independent semantic verifier | DEFERRED | required independent quality boundary was not proven |
| automatic Phase-4.5E memory injection | DEFERRED / DISABLED | conversational influence remains disabled |
| full local/offline conversation | DEFERRED | current provider resilience is truthful survival, not a second full local conversation stack |
| proactive/event-driven monitoring | PLANNED | later Step 15 |
| full Steps 9/10/12 | PLANNED with partial foundations | Hands supplies foundations only |
| RepairKnowledge and later repair-learning/evolution phases | ACTIVE / PLANNED | exact sequence lives in `SELF_REPAIR_AND_EVOLUTION_MASTER_PLAN.md` |

---

## Completed issues that must not reappear as open limitations

- **#47** power/session semantic grounding — completed by PR #49.
- **#50** lifecycle speech/cloud-TTS dependency — completed by PR #64.
- **#53** persistent concurrent work orchestration — completed by PR #55.
- **#56** Pocket OWNER continuity — completed by PR #61.
- **#57** durable WorkDelivery TTS backoff — completed by PR #62.
- **#65** deterministic Self-Repair foundation — completed by PRs #73–#86.
- **#67** obsolete manual follow mode — completed by PR #68.
- **#70** obsolete manual lock semantics — completed by PR #71.

Issue **#14** was closed as not planned after its useful Step-3 work was superseded by
the accepted modern identity/security baseline.

---

## Superseded / rejected / historical work

Closed without merge or intentionally excluded work remains useful only as history.

| PR / branch | Disposition | Current truth |
| --- | --- | --- |
| PR #5 | SUPERSEDED | replaced by merged Step-3 architecture approval #6 |
| PR #11 | SUPERSEDED | replaced by merged current Step-3 sensor foundation #12 |
| PR #13 | HISTORICAL / UNMERGED | LR-ASD bake-off work remains evidence only |
| PR #18 | HISTORICAL / UNMERGED | old final identity/security branch; do not merge wholesale |
| PR #27 | SUPERSEDED | replaced by accepted Step-7 PR #28 |
| PR #31 | SUPERSEDED | profiler work recovered through #36 |
| PR #32 | SUPERSEDED / PARTIALLY RECOVERED | accepted optimization pieces recovered; rejected/stale pieces excluded |
| PR #66 | SUPERSEDED RESEARCH | replaced by refined Self-Repair research #72 |
| `feature/owner-presence-workstation-lock` | REJECTED | OWNER absence must not automatically lock Windows |
| `implementation/step-4-phase45e-context-injection` | FUNCTIONAL PASS / NOT ACCEPTED | automatic memory influence remains disabled |
| `implementation/step-4-phase45e2-utility-gate` | REJECTED | utility/safety gate did not justify production influence |

Git history is the authoritative archive for detailed experiments, benchmarks,
old acceptance transcripts and superseded proposals.

---

## Current branch / PR truth

At reconciliation start:

- protected `main`: `4036b2e58eb93136905a5c8c41654c10fb14a8d7`;
- open pull requests: **none**;
- Self-Repair issue #65: **closed / completed**;
- Self-Repair PRs #73–#87: **all merged**.

Several old feature/research branches still exist remotely. Their presence does not
mean their code is pending. Branch cleanup is repository hygiene and should be done
separately after state/document reconciliation.

---

## Current active work

The active development slice is:

**Self-Repair / Self-Evolution Phase 1H — Self-Repair Foundation Hardening**

Phase-2 RepairKnowledge research/design is preserved, but its implementation is
blocked until Phase 1H is independently accepted.

Phase 1H scope is intentionally limited to hardening repair truth and supervision:

1. restart-budget and target-level circuit-breaker correctness;
2. typed verifier proof and deterministic execution preconditions;
3. immutable trigger/policy provenance and versioned engineering DB migrations;
4. authoritative Windows runtime-tree ownership;
5. local-only production supervision and bounded outer-supervisor recovery;
6. truthful R1/R2 status and expanded acceptance.

After Phase 1H is accepted, Phase-2 RepairKnowledge may begin under the separately
preserved research/design contract. DiagnosticModelRouter and source repair remain
later phases.

Step 8 remains the next numbered product slice when numbered roadmap work resumes.
