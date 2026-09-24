# JARVIS Self-Repair and Self-Evolution Master Plan

## Status

**AUTHORITATIVE PROGRAM PLAN — R2 Self-Repair foundation accepted; Phase 1H hardening precedes Repair Learning**

Date established: 2026-09-23

This document is the single planning source of truth for the long-term JARVIS
Self-Repair, Self-Learning and governed Self-Evolution program.

It consolidates the earlier Self-Repair sequence, research, ADR and acceptance work.
Those detailed historical documents are preserved by Git history; this master plan
owns the complete forward sequence in the current working tree.

The deterministic repair framework and bounded automatic R2 runtime crash/hang
recovery are accepted on the owner machine. R1 remains a typed risk/action class but
has no owner-accepted automatic production policy yet. Phase 1H hardening is required
before repair history is used as learned engineering knowledge. This does not complete
roadmap Steps 18, 19 or 20.

---

## 1. End-state vision

The intended end state is not merely a process watchdog.

JARVIS should be able to:

1. understand its own architecture, dependencies, capabilities and health;
2. detect failures and degradation from JARVIS-owned evidence;
3. recover automatically from known low-risk failures using bounded deterministic
   repair policies;
4. investigate unknown failures using governed AI diagnostics;
5. create source-code repair candidates inside isolated development environments;
6. independently test and verify candidate repairs before they can affect the live
   system;
7. deploy only through the accepted governance boundary, with health verification
   and rollback;
8. retain verified engineering lessons so the same problem does not need to be
   rediscovered;
9. create safe synthetic variants of real failures and practise diagnosis/repair in
   sandboxed environments;
10. identify repeated weaknesses, capability gaps, excessive cost/latency and
    reliability problems even before a complete failure occurs;
11. develop candidate improvements in shadow;
12. benchmark the candidate against the accepted JARVIS baseline;
13. promote only evidence-backed improvements through explicit governance;
14. improve its diagnostic and engineering ability over time without silently
    rewriting protected safety, Authority or evaluation boundaries.

The compact end-state loop is:

```text
UNDERSTAND
-> OBSERVE
-> DETECT
-> DIAGNOSE
-> REPAIR / DEVELOP CANDIDATE
-> VERIFY
-> GOVERNED PROMOTION
-> OBSERVE PRODUCTION RESULT
-> LEARN
-> PRACTISE
-> IDENTIFY NEXT GAP
-> IMPROVE
```

Self-improvement is therefore an engineering lifecycle, not permission for a model
to edit live code freely.

---

## 2. Non-negotiable ownership boundaries

### 2.1 Intelligence is not authority

Models may classify, reason, diagnose, research, write candidate code and propose
improvements.

Models do not independently:

- lower repair risk;
- grant themselves capabilities;
- mint execution permits;
- declare health truth;
- declare a repair successful without verifier evidence;
- modify protected Authority;
- modify CI/rulesets/sandbox controls to make a repair pass;
- merge into protected main;
- expand credentials or permissions;
- silently deploy a new JARVIS version.

Canonical Authority, policy, budgets, execution permits, verification and production
truth remain JARVIS-owned deterministic surfaces.

### 2.2 Production repair and learning are separate loops

The live system must remain able to recover from already-known faults even when all
cloud/model providers are unavailable.

No future learning component may become a hard dependency for the accepted bounded
production repair loop.

### 2.3 Evidence before action, verification before recovery

Every repair or improvement must preserve:

- source evidence;
- incident or improvement identity;
- selected policy/candidate;
- pre-state;
- action or patch;
- test/verification evidence;
- final outcome;
- rollback or supersession history.

An action returning successfully is not sufficient evidence that the original
problem is fixed.

### 2.4 Live production is not the experiment environment

Unknown diagnosis and source repair happen through WorkItems, isolated worktrees,
sandboxed tests and controlled verification.

Experimental curriculum cases and model training/evaluation never run by mutating
protected production state.

---

## 3. Two-loop architecture

### Loop A — Production Repair Loop

**Status: ACCEPTED R2 BASELINE / PHASE 1H HARDENING ACTIVE**

This is the only loop currently allowed to mutate live runtime state automatically.

```text
health/process/evidence signal
        |
        v
      DETECT
        |
        v
deterministic CLASSIFY
        |
        v
registered RepairPolicy
        |
        v
Authority + budget + preconditions
        |
        v
typed bounded EXECUTE
        |
        v
deterministic VERIFY
      /       \
RECOVERED   NOT RECOVERED
              |
              v
       retry within budget
       or fail closed/escalate
```

Current accepted properties include:

- durable incident-linked `RepairAttempt` records;
- independent process-external restart ownership through `jarvis-dev`;
- same-version child restart;
- startup-readiness verification;
- authenticated liveness stabilization;
- crash and hang handling;
- durable restart budgets/cooldowns;
- provider/dependency degradation separated from process liveness;
- Windows venv process-tree fault handling and force cleanup;
- fail-closed unknown/unregistered repair behavior.

Owner-machine acceptance and merge history are summarized in `PROJECT_STATE.md`; the detailed acceptance transcript remains available in Git history.

### Loop B — Repair Learning and Evolution Loop

**Status: PLANNED — next implementation starts with RepairKnowledge**

This loop improves future diagnosis and engineering ability but cannot directly
create production authority.

```text
real incident / observed weakness
        |
        v
RepairKnowledge + engineering evidence
        |
        v
diagnostic routing / AI investigation
        |
        +------ known safe repair ------> version-controlled RepairPolicy proposal
        |
        +------ source defect ----------> isolated source-repair candidate
        |
        +------ capability weakness ----> improvement candidate
        |
        v
sandbox tests / replay / benchmark / verifier
        |
        v
candidate accepted or rejected
        |
        v
governed promotion
        |
        v
production observation
        |
        v
learn verified outcome
        |
        v
curriculum / synthetic variants
        |
        v
better future diagnosis and repair
```

Loop B may propose changes to Loop A, but a proposal becomes executable production
policy only through the same version-controlled review/validation boundary used for
other protected JARVIS code.

---

## 4. Repair and evolution risk classes

The existing repair risk model remains canonical.

### R0 — observe / diagnose

Examples:

- read health/evidence;
- correlate incidents;
- create RepairKnowledge candidate;
- run a diagnostic WorkItem.

May be automatic when privacy and resource policy allow.

### R1 — bounded reversible operation

Examples:

- reconnect transport;
- retry one idempotent operation;
- rebuild one ephemeral session.

May execute automatically only through an explicitly registered policy and
deterministic verifier.

### R2 — bounded process/subsystem restart

Examples:

- restart the JARVIS runtime child;
- restart a separately restart-safe subsystem.

May execute automatically only under accepted budgets, cooldown and verification.

### R3 — persistent runtime/config mutation

Examples:

- changing durable configuration;
- modifying environment/settings.

Not automatically authorized by the current foundation. Future support requires a
separate policy and acceptance gate.

### R4 — source repair / improvement candidate

Examples:

- edit source inside an isolated DEVELOPMENT worktree;
- create tests;
- create a clean local candidate commit or PR.

Candidate creation may eventually be automated. Protected-main promotion is a
separate governed step.

### R5 — protected security / authority / governance mutation

Examples:

- Authority policy;
- permissions;
- credentials;
- CI/rulesets;
- sandbox policy;
- repair evaluator;
- verifier policy.

These remain protected. No repair-learning model may silently modify them.

---

## 5. Canonical program objects

### Existing accepted objects

- `RepairTrigger`
- `RepairPolicy`
- `RepairAction`
- `RepairAttempt`
- `RepairVerdict`
- engineering `Incident`
- `WorkItem`, `WorkStep`, `WorkDelivery`

### RepairKnowledge

Reusable engineering knowledge learned from verified real or synthetic evidence.

Required semantic fields:

- stable `knowledge_id`;
- component scope;
- trigger/failure signature;
- evidence provenance;
- diagnosis summary;
- successful repair or engineering sequence;
- verification contract;
- required capabilities/resources;
- originating incident/curriculum IDs;
- evidence grade/confidence;
- lifecycle state:
  `CANDIDATE`, `STAGED`, `ACCEPTED`, `REJECTED`, `RETIRED`;
- version, supersession and lineage.

RepairKnowledge is advisory knowledge, not executable authority.

### DiagnosticCase / DiagnosticResult

A durable AI-diagnostics record should capture:

- incident/component;
- bounded evidence package;
- diagnostic task type;
- selected model/provider and routing reason;
- hypotheses considered;
- evidence supporting/refuting hypotheses;
- proposed root cause;
- confidence/uncertainty;
- suggested next action;
- whether deterministic verification is available;
- cost/latency/outcome.

### SourceRepairCandidate

Represents one isolated source change proposal:

- incident/diagnostic provenance;
- worktree/branch identity;
- affected files/components;
- patch/diff;
- tests added or changed;
- targeted test results;
- repository quality-gate results;
- forbidden-surface checks;
- candidate commit/PR;
- reviewer/owner decision;
- deployment result and rollback identity when promoted.

### RepairCurriculumCase

Sandbox-only generated or replayed fault scenario:

- real or synthetic parent;
- injected fault;
- expected evidence;
- allowed action space;
- forbidden mutations;
- success verifier;
- diagnostic/repair trajectory;
- score/reward;
- model/provider/version;
- reproducibility metadata.

### ImprovementCandidate

Used when the system is not simply broken but could be improved:

- source observation/gap;
- objective metric;
- current baseline;
- proposed change;
- expected benefit;
- risk/authority class;
- benchmark plan;
- shadow result;
- regression result;
- final promotion/rejection decision.

---

## 6. Program phases and exact sequence

### Phase 0 — prerequisites

**STATUS: DONE**

Established before Self-Repair:

- Self-Awareness / Self Model;
- Health Registry;
- operational evidence;
- durable engineering incidents;
- Authority;
- persistent WorkItems/DBOS;
- isolated development worktrees;
- sandboxed tests;
- protected-main CI/governance;
- `jarvis-dev` update/readiness/rollback boundary.

Exit condition: repair work has trustworthy evidence, durable work and a safe
development/deployment substrate.

### Phase 1 — deterministic repair framework + R2 runtime Self-Repair foundation

**STATUS: DONE / OWNER-MACHINE ACCEPTED 2026-09-23**

Includes:

- repair domain/contracts and fail-closed registry;
- durable RepairAttempt persistence;
- process-external crash supervision;
- crash-loop budgets/cooldowns;
- startup readiness;
- liveness watchdog;
- alive-but-unresponsive recovery;
- same-version restart;
- verification before RECOVERED;
- provider degradation excluded from liveness truth;
- owner-machine crash/hang fault injection;
- Windows process-tree corrections.

Exit condition: the registered owner-accepted R2 runtime crash/hang faults recover
under budget and deterministic verification, while unknown/dependency failures cannot
trigger guessed live repair.

### Phase 1H — Self-Repair foundation hardening

**STATUS: ACTIVE — REQUIRED BEFORE PHASE 2 IMPLEMENTATION**

A post-acceptance audit found that the original R2 foundation worked on real crash/hang
faults but needed stronger system-level invariants before its history could safely feed
RepairKnowledge.

Hardening includes:

- restart history is not forgiven by a short RECOVERED stabilization window;
- one target/action circuit breaker spans crash/liveness policies and fingerprints;
- RECOVERED derives from typed verifier proof tied to the policy contract;
- execution preconditions are computed from typed deterministic state;
- RepairAttempts retain immutable trigger/policy snapshots and policy digests;
- engineering persistence uses versioned/checksummed migrations;
- Windows Job Objects own runtime process lifetime with psutil fallback;
- a local-only production supervisor mode removes Git/network polling from Loop A;
- a bounded current-user Task Scheduler guardian can restart supervisor failures
  without overriding an intentional repair-budget escalation;
- canonical docs distinguish the R1/R2 framework from accepted R2 behavior.

Exit condition: repository gates and the expanded owner-machine fault matrix pass,
including supervisor death and repeated cross-signature restart-storm cases.

### Phase 2 — RepairKnowledge foundation

**STATUS: BLOCKED UNTIL PHASE 1H ACCEPTANCE**

Build the durable repair-engineering memory layer.

Scope:

1. canonical RepairKnowledge schema/store;
2. provenance links to incidents, RepairAttempts, commits/PRs and tests;
3. CANDIDATE/STAGED/ACCEPTED/REJECTED/RETIRED lifecycle;
4. deterministic duplicate/supersession semantics;
5. query by component, signature and similarity;
6. conversion of verified resolved incidents into candidate knowledge;
7. explicit separation from executable RepairPolicy;
8. owner/governance promotion path for accepted playbooks.

Entry condition: Phase 1 accepted.

Exit condition:

- a successful real repair can produce a durable candidate playbook;
- candidate cannot execute as repair authority;
- provenance and supersession are testable;
- rejected/retired knowledge cannot silently reappear;
- accepted knowledge can be retrieved for diagnosis.

### Phase 3 — DiagnosticModelRouter

**STATUS: PLANNED AFTER PHASE 2**

Create one provider/model-neutral routing boundary for repair diagnostics.

Routing inputs:

- task kind;
- component/risk class;
- privacy/locality;
- evidence size/type;
- required capabilities;
- latency target;
- cost budget;
- provider/model health;
- previous attempt result;
- confidence/escalation requirement.

Possible targets may include:

- local models;
- OpenAI;
- Gemini;
- Nemotron/NIM;
- future Ornith or other specialist models.

Routing never changes Authority or repair policy.

Exit condition:

- deterministic routing/fallback/escalation contract;
- unavailable provider cannot block Loop A;
- cost/latency and outcome are recorded;
- model replacement does not change canonical diagnostic/result schema.

### Phase 4 — AI-assisted diagnostics

**STATUS: PLANNED**

Unknown/ambiguous incidents become durable DIAGNOSTICS WorkItems.

Flow:

```text
unknown incident
-> gather bounded/redacted evidence
-> retrieve relevant RepairKnowledge
-> DiagnosticModelRouter
-> diagnostic worker
-> structured hypotheses/root cause
-> evidence check
-> proposed action
-> deterministic policy/authority boundary
```

The diagnostic worker may inspect approved source/docs/logs and perform bounded
research where needed.

It cannot directly execute arbitrary live repair.

Exit condition:

- injected unknown incidents create restart-safe diagnostic work;
- diagnosis cites actual evidence;
- uncertainty is explicit;
- no model output becomes executable merely by being confident;
- useful diagnosis is persisted and inspectable.

### Phase 5 — sandboxed source repair

**STATUS: PLANNED**

When diagnosis indicates a source defect:

```text
Incident
-> DIAGNOSTICS result
-> DEVELOPMENT WorkItem
-> isolated Git worktree
-> inspect affected code/tests
-> generate bounded patch
-> targeted regression
-> locked-down sandbox tests
-> Ruff/full relevant gates
-> inspect final diff
-> clean candidate commit / PR
```

Forbidden during this phase:

- editing protected main directly;
- automatic merge/deploy;
- weakening tests to make a candidate pass;
- modifying Authority/CI/sandbox/evaluator without a separately authorized task;
- arbitrary host shell authority.

Exit condition: JARVIS can truthfully present a tested source repair candidate for
owner/reviewer decision.

### Phase 6 — governed deployment, production verification and rollback

**STATUS: PLANNED**

Connect accepted source repair candidates to the existing deployment boundary.

Initial flow:

```text
verified candidate
-> review / approval
-> protected-main merge through repository governance
-> jarvis-dev sees accepted update
-> startup readiness
-> production health/liveness observation
-> KEEP or ROLLBACK
-> record deployment result
```

Later autonomy may reduce human friction only after a separate acceptance decision;
the master safety invariants remain.

Exit condition:

- deployment state is durable;
- failed production verification restores last-known-good;
- production outcome is linked back to the source candidate and incident;
- no candidate can bypass protected-main rules.

### Phase 7 — closed-loop repair learning

**STATUS: PLANNED**

Turn verified production outcomes into better future engineering knowledge.

Flow:

```text
repair candidate
-> production verification
-> successful / failed outcome
-> update incident
-> create/supersede RepairKnowledge
-> record lessons/regression
-> improve future retrieval/diagnosis
```

A successful source fix may later lead to a proposed deterministic RepairPolicy only
when the action is safe, repeatable and independently verifiable.

Exit condition: repeated problems demonstrably reuse verified knowledge instead of
starting from zero, while bad/stale knowledge can be retired.

### Phase 8 — Repair Curriculum

**STATUS: PLANNED**

Adopt the useful Ornith/Nemotron-style learning pattern without giving training
systems production authority.

Flow:

```text
verified real incident
-> create bounded synthetic/replay variants
-> sandbox diagnosis/repair attempts
-> deterministic verifier/reward
-> retain successful trajectories
-> reject unsafe/incorrect trajectories
-> propose better RepairKnowledge / specialist data
```

Curriculum runs only against safe test/sandbox environments.

Exit condition:

- generated cases are reproducible;
- verifier cannot be model self-scoring alone;
- protected surfaces are inaccessible;
- synthetic success does not directly create a production RepairPolicy.

### Phase 9 — specialist diagnostic/repair model evaluation

**STATUS: PLANNED WHEN DATA EXISTS**

Only after enough JARVIS-specific verified cases exist:

- benchmark local and hosted models;
- measure diagnosis accuracy;
- measure patch success rate;
- measure unsafe/unsupported action rate;
- measure latency, cost, GPU/RAM use;
- compare general model vs repair specialist;
- evaluate Ornith/Nemotron-family or future models on the same corpus.

No specialist becomes canonical merely because it was trained for coding/repair.

Exit condition: a preferred model/routing policy is justified by reproducible
JARVIS-specific evidence and remains replaceable.

### Phase 10 — capability-gap and weakness detection

**STATUS: PLANNED / maps strongly to roadmap Step 18**

Move beyond incident-only repair.

JARVIS should identify patterns such as:

- repeated failures in one component;
- repeated manual intervention;
- recurring expensive model calls;
- excessive latency;
- repeated owner requests for a missing capability;
- frequent fallback use;
- fragile dependency;
- high resource consumption;
- poor success/verification rate.

These observations create ImprovementCandidates, not automatic live changes.

Exit condition: meaningful gaps are surfaced from measurable evidence rather than
model imagination.

### Phase 11 — shadow self-improvement

**STATUS: PLANNED / bridge from Steps 18–20**

For an approved improvement objective:

```text
observed gap
-> research options
-> improvement candidate
-> isolated implementation
-> tests
-> benchmark against current JARVIS
-> shadow execution where applicable
-> regression/safety comparison
-> ACCEPT / REJECT
```

The current production JARVIS remains the baseline until the candidate proves a
measurable improvement without unacceptable regressions.

Required comparison dimensions may include:

- task success;
- reliability;
- latency;
- cost/tokens;
- CPU/RAM/GPU;
- safety/authority violations;
- false actions;
- user-visible quality;
- compatibility with accepted architecture.

Exit condition: JARVIS can produce an evidence-backed improvement proposal and
explain why it is better than the current baseline.

### Phase 12 — governed self-evolution

**STATUS: LONG-TERM / roadmap Step 20**

This is the mature integrated loop:

```text
observe self
-> identify gap
-> research
-> design candidate
-> build in isolation
-> verify
-> benchmark
-> governance decision
-> deploy
-> observe
-> rollback if required
-> learn
```

The objective is progressively more autonomous engineering, not unbounded
self-modification.

Any future proposal to automate protected-main promotion, Authority changes or
governance mutation is a separate architectural decision and cannot be inferred from
this master plan.

---

## 7. Technology strategy

### Hermes

**Decision: adopt patterns, not a second runtime.**

Useful patterns:

- reusable engineering playbooks;
- staged/approval-gated learned skills;
- explicit capability requirements;
- provider fallback for auxiliary reasoning.

JARVIS already owns orchestration, memory, Authority, incidents and provider
boundaries, so embedding Hermes as another orchestration owner would duplicate truth.

### NVIDIA Nemotron / NeMo

**Decision: adopt routing and verifiable-training patterns; keep implementation
replaceable.**

Useful patterns:

- model-neutral routing/escalation;
- specialist models;
- synthetic data generation;
- independently verifiable reward.

NeMo Switchyard may later be evaluated as one implementation behind
DiagnosticModelRouter. It is not required by the semantic architecture.

### Ornith

**Decision: use its self-generated curriculum concept later, not for live repair
authority.**

The most relevant pattern is:

```text
generate task/fault
-> generate scaffold/attempt
-> execute in sandbox
-> verify
-> learn from successful trajectory
```

Ornith or an Ornith-style local model may later be benchmarked as a
DIAGNOSTICS/DEVELOPMENT worker when enough JARVIS-specific evaluation data exists.

### Model policy

There is no permanent repair brain.

The architecture must allow future models to replace current models without replacing
JARVIS-owned:

- repair truth;
- Authority;
- incident truth;
- verification;
- risk policy;
- deployment governance.

---

## 8. Verification hierarchy

Different phases require different proof.

### Runtime repair

Verify the failed runtime property:

- readiness;
- authenticated liveness;
- fresh transport/state;
- correct durable state;
- absence of duplicate side effects.

### Diagnostic quality

Verify against:

- evidence consistency;
- known injected root cause;
- reproduced failure;
- rejected alternative hypotheses where measurable.

### Source repair

Require:

- reproduction/regression test where feasible;
- targeted tests;
- repository gates;
- final diff inspection;
- clean worktree/commit;
- forbidden-surface checks.

### Improvement/evolution

Require comparison against the accepted baseline, not merely "tests pass".

A candidate that is functionally correct but substantially worse in reliability,
latency, cost, resources or safety may be rejected.

---

## 9. RepairKnowledge promotion rules

RepairKnowledge lifecycle is deliberately separate from RepairPolicy.

```text
CANDIDATE
   |
   v
STAGED
   |
   +--> REJECTED
   |
   v
ACCEPTED
   |
   +--> RETIRED
   |
   +--> SUPERSEDED by newer accepted knowledge
```

Promotion to `ACCEPTED` requires provenance and verification evidence.

Promotion from knowledge into an executable RepairPolicy is a separate
version-controlled engineering change with tests and authority review.

No model can perform that promotion merely by assigning itself high confidence.

---

## 10. Failure handling inside the learning loop

The learning/evolution machinery must itself fail safely.

Examples:

- DiagnosticModelRouter unavailable -> incident remains open; Loop A still works.
- Diagnostic model quota exhausted -> retry/backoff or alternate target; no runtime
  restart solely because diagnostics failed.
- source candidate tests fail -> candidate rejected/not ready; production untouched.
- curriculum worker crashes -> WorkItem recovery semantics apply; production
  untouched.
- verifier unavailable -> outcome is INCONCLUSIVE, never RECOVERED/IMPROVED.
- deployment fails readiness -> existing rollback path remains authoritative.
- new version degrades after deployment -> rollback/escalation according to accepted
  production policy.

---

## 11. Relationship to roadmap Steps 18–20

This program deliberately started early as a bounded reliability foundation.

Mapping:

- **Step 18 — Learning, Gap Detection, Governed Skill Creation**
  - Phase 7 closed-loop learning;
  - Phase 8 Repair Curriculum;
  - Phase 10 capability-gap detection;
  - portions of Phase 11 candidate creation.

- **Step 19 — Governed Self-Diagnostics and Repair**
  - Phase 1 deterministic production repair;
  - Phase 2 RepairKnowledge;
  - Phase 3 DiagnosticModelRouter;
  - Phase 4 AI diagnostics;
  - Phase 5 sandboxed source repair;
  - Phase 6 governed deployment/rollback.

- **Step 20 — Governed Self-Improvement and Advanced Autonomy**
  - Phase 9 specialist evolution where justified;
  - Phase 10 weakness detection;
  - Phase 11 shadow self-improvement;
  - Phase 12 governed self-evolution.

The early accepted deterministic foundation means Step 19 now has an accepted
partial foundation. It does not mean Step 19 is complete.

---

## 12. Current program state

As of 2026-09-23:

| Program phase | Status |
| --- | --- |
| Phase 0 prerequisites | DONE |
| Phase 1 deterministic framework + R2 runtime Self-Repair | DONE / OWNER ACCEPTED |
| Phase 1H Self-Repair foundation hardening | **ACTIVE** |
| Phase 2 RepairKnowledge | BLOCKED UNTIL PHASE 1H ACCEPTANCE |
| Phase 3 DiagnosticModelRouter | PLANNED |
| Phase 4 AI-assisted diagnostics | PLANNED |
| Phase 5 sandboxed source repair | PLANNED |
| Phase 6 governed deployment + rollback | PLANNED |
| Phase 7 closed-loop repair learning | PLANNED |
| Phase 8 Repair Curriculum | PLANNED |
| Phase 9 specialist model evaluation | PLANNED WHEN DATA EXISTS |
| Phase 10 gap/weakness detection | PLANNED |
| Phase 11 shadow self-improvement | PLANNED |
| Phase 12 governed self-evolution | LONG-TERM |

---

## 13. Immediate next development slice

**Do not start implementation from this documentation PR.**

The active development slice is:

### Phase 1H — Self-Repair Foundation Hardening

Complete automated gates and the owner-machine fault matrix defined in
`SELF_REPAIR_PHASE1H_HARDENING.md`.

After Phase 1H is independently accepted, the next slice is:

### Phase 2 — RepairKnowledge Foundation

Recommended implementation order:

1. define the canonical RepairKnowledge domain contract;
2. add durable persistence and migrations;
3. link knowledge to incidents/RepairAttempts and repository evidence;
4. implement lifecycle transitions;
5. implement deterministic provenance/evidence validation;
6. implement component/signature retrieval;
7. create candidate knowledge from verified existing repair incidents;
8. prove knowledge cannot execute or mutate RepairPolicy;
9. add repository acceptance tests;
10. perform owner-machine inspection/acceptance;
11. reconcile docs and merge;
12. only then begin DiagnosticModelRouter.

---

## 14. Program completion definition

The Self-Repair/Self-Evolution program is not complete when JARVIS can restart
itself.

It is complete only when the integrated system can safely demonstrate:

```text
understand itself
+ recover known failures
+ diagnose unknown failures
+ develop fixes in isolation
+ verify fixes independently
+ deploy through governance
+ rollback bad changes
+ learn verified lessons
+ practise on safe synthetic variants
+ detect weaknesses/gaps
+ develop measurable improvements
+ compare against the current baseline
+ promote only proven improvements
```

while preserving JARVIS-owned Authority, truth, verification and protected safety
boundaries.

That is the intended self-repairing and self-evolving JARVIS.
