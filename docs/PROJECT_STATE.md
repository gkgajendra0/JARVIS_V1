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
`3c5a2f732db171a9ad61a4531fecd66aed0d27c4` on 2026-09-25.

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
| Deterministic Self-Repair | PARTIAL foundation for Step 19 | R1/R2 typed framework plus Phase-1H-hardened R2 production recovery: sustained rolling budgets, shared target/action circuit breaker, typed verification/preconditions/provenance, versioned persistence, Windows Job Object runtime ownership and bounded production guardian |
| EngineeringKnowledge | DONE foundation | Phase 2 owner-machine accepted 2026-09-25: immutable engineering knowledge, deterministic REPAIR projection, lifecycle/provenance/applicability, grounded local hybrid retrieval, integrity/security gates and open-ended facet extensibility |
| Self-Repair / Self-Evolution program | ACTIVE | Phases 1, 1H, 2 and 3 are accepted; Phase 4 Research + Diagnostic Model Router research/architecture is complete and implementation is next |
| Step 8 notes/tasks/reminders | PLANNED | still the next numbered product slice when numbered roadmap work resumes |

Phase 3 EngineeringChange is **DONE / OWNER-MACHINE ACCEPTED 2026-09-25**. The canonical record is `PHASE3_ENGINEERING_CHANGE_ACCEPTANCE_2026-09-25.md`. The owner-machine run proved durable same-identity recovery across a full Windows shutdown/reboot and live Exa research; persistent Gemini HTTP 429 pressure was accepted as an external limitation and did not weaken governance.

Phase 4 Research + Diagnostic Model Router has completed technology research and owner-approved architecture. Canonical documents: `PHASE4_MODEL_ROUTER_RESEARCH.md`, `PHASE4_MODEL_ROUTER_ARCHITECTURE.md`, and `PHASE4_MODEL_ROUTER_IMPLEMENTATION_PLAN.md`. Implementation is not yet accepted production state.

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
- **#90** Phase-1H foundation hardening: sustained restart budget semantics, shared restart circuit breaker, typed verification/preconditions/provenance, versioned engineering DB migrations, Windows Job Object ownership, local-only production supervisor and bounded Windows guardian; owner-machine accepted 2026-09-24.

Final deterministic Self-Repair acceptance:
- crash recovery passed;
- alive-but-unresponsive recovery passed;
- full Windows runtime process tree was frozen and recovered;
- durable RepairAttempt completed with
  `execution_result = unresponsive child restart stabilized`,
  `verifier_result = readiness_and_liveness_stable:6_probes`,
  `verdict = recovered`;
- issue **#65** is closed.
- Phase-1H owner-machine acceptance additionally passed launcher-only death, interpreter-only death, supervisor death + outer guardian recovery, no accepted duplicate/orphan runtime, mixed crash/liveness shared restart history, and the final shared circuit breaker test;
- final breaker proof: 3 verified recent repairs were present, the fourth crash produced 0 new RepairAttempts, 0 guardian/supervisor/runtime processes remained, and the test reported `PASS - FOURTH RESTART WAS BLOCKED`;
- automatic Windows logon startup was observed; an unavailable configured Pocket 3 microphone failed closed at preflight, while the same startup path succeeded once Windows enumerated the device.

### EngineeringKnowledge Phase 2

- **#91** governed autonomous-engineering north-star documentation alignment.
- **#92** owner-approved Phase-2 research/architecture/implementation-plan freeze.
- **#93** Phase 2A EngineeringKnowledge core contracts and schema.
- **#94** Phase 2B registered versioned facets and RFC-8785 canonicalization boundary.
- **#95** Phase 2C deterministic verified-repair projector.
- **#96** Phase 2D lifecycle and deterministic repair promotion.
- **#97** Phase 2E applicability evaluation.
- **#98** Phase 2F local-first hybrid retrieval.
- **#99** Phase 2G security/integrity/admission hardening.
- **#100** Phase 2H qrel evaluation harness.
- **#101** Phase 2I retrieval benchmarking/adoption policy.
- **#102** Phase 2J owner-machine acceptance harness and query-security hardening.
- **#103** owner-machine dependency-sync documentation correction.
- **#104** cold-start import-cycle correction and fresh-process regression coverage.
- **#105** grounded dense retrieval correction after real Qwen no-answer evidence.
- **#106** full bounded R2 recovery-observation correction.

Final Phase-2 owner-machine acceptance on protected-main baseline
`3c5a2f732db171a9ad61a4531fecd66aed0d27c4` passed every integrated gate:

- R2 recovered before EngineeringKnowledge existed for the new repair;
- the verified RepairAttempt projected, promoted and retained exact provenance;
- exact/lexical retrieval and wrong-component exclusion passed;
- paraphrased Qwen-256 retrieval passed;
- poisoning and secret-like admission gates passed;
- unknown facets failed closed while a reviewed future facet used the same registry;
- lexical qrel safety passed;
- hybrid Qwen-256 qrel safety passed.

Canonical acceptance record:
`PHASE2_ENGINEERING_KNOWLEDGE_ACCEPTANCE_2026-09-25.md`.

### EngineeringChange Phase 3

- **#108** governed EngineeringChange lifecycle / mission orchestration: canonical change/work identity, immutable artifact-bound owner gates, revision-safe development attempts, acceptance/promotion intent boundaries, PostgreSQL DBOS recovery and bounded owner-machine evidence.

Final Phase-3 owner-machine acceptance on 2026-09-25 proved same-turn idempotency, owner-input resume, successful Exa-backed research actions, same-identity PostgreSQL DBOS recovery and full Windows cold-boot survival. Persistent Gemini HTTP 429 provider pressure prevented the live run from naturally traversing the downstream architecture/Windows-Hello/development gates; the owner explicitly accepted this external limitation, with those contracts retained in the exact green automated suite and no governance bypass.

Canonical acceptance record:
`PHASE3_ENGINEERING_CHANGE_ACCEPTANCE_2026-09-25.md`.

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
| Later autonomous-engineering phases | ACTIVE / PLANNED | Phases 2 EngineeringKnowledge and 3 EngineeringChange are accepted; Phase 4 research/architecture is complete and implementation is next; later phases remain planned in `GOVERNED_AUTONOMOUS_ENGINEERING_MASTER_PLAN.md` |

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

At Phase-2 closure reconciliation start:

- protected `main`: `3c5a2f732db171a9ad61a4531fecd66aed0d27c4`;
- Phase-2 implementation/acceptance PRs #92–#106: **merged**;
- Phase-2 owner-machine acceptance: **PASS 2026-09-25**;
- Self-Repair issue #65: **closed / completed**.

Several old feature/research branches still exist remotely. Their presence does not
mean their code is pending. Branch cleanup is repository hygiene and should be done
separately after state/document reconciliation.

---

## Current active work

Phase 1H is **DONE / OWNER-MACHINE ACCEPTED 2026-09-24** and is promoted through PR #90.

Phase 2 EngineeringKnowledge is **DONE / OWNER-MACHINE ACCEPTED 2026-09-25**. The accepted implementation and final real-machine evidence are recorded in `PHASE2_ENGINEERING_KNOWLEDGE_ACCEPTANCE_2026-09-25.md`.

Phase 3 EngineeringChange Lifecycle / Mission Orchestration is **DONE / OWNER-MACHINE ACCEPTED 2026-09-25**. PR #108 carries the accepted implementation and `PHASE3_ENGINEERING_CHANGE_ACCEPTANCE_2026-09-25.md` carries the final owner-machine evidence.

The active cross-cutting slice is:

**Phase 4 — Research + Diagnostic Model Router**

Research and architecture are complete and owner-approved. Implementation must follow the frozen Phase-4 documents and reuse existing WorkItems/WorkSteps/WorkDeliveries, EngineeringChange, EngineeringKnowledge and Authority boundaries rather than create a parallel task, routing, verification or provenance system. Jev is explicitly deferred to a later optimization experiment.

Source repair remains a later phase. Step 8 remains the next numbered product slice when numbered roadmap work resumes.
