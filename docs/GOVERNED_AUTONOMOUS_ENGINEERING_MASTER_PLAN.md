# JARVIS Governed Autonomous Engineering Master Plan

## Status

**AUTHORITATIVE OWNER-APPROVED NORTH-STAR PROGRAM ARCHITECTURE — accepted on protected `main`; Phase 2 EngineeringKnowledge owner-machine accepted 2026-09-25; Phase 3 EngineeringChange is active**

Established: 2026-09-24

This document defines the long-term engineering architecture for the JARVIS V1 end state. It sits above the specialized Self-Repair/Self-Evolution program and the numbered product roadmap.

The central product promise is:

> **The owner expresses intent; JARVIS handles the engineering required to satisfy that intent; authority remains with the owner.**

The owner should not need to perform routine research, coding, Git operations, dependency setup, debugging, test execution, PR preparation, deployment mechanics or production diagnosis merely because JARVIS lacks a capability. The owner remains responsible for explicit architecture/promotion approvals, secrets or physical inputs that only the owner can provide, and real-world acceptance when software cannot independently prove physical behavior.

This plan does not authorize autonomous protected-main merge, governance mutation or privilege expansion.

---

## 1. End-state vision

JARVIS is intended to become one coherent personal intelligence runtime that can:

1. understand its own architecture, capabilities, dependencies, resources, health and accepted constraints;
2. accept high-level owner goals even when the required capability does not yet exist;
3. determine truthfully whether an existing capability can satisfy the goal;
4. identify a missing capability or engineering gap instead of hallucinating access;
5. research current technology, protocols, standards, libraries, vendor documentation and implementation approaches;
6. compare candidate approaches using explicit technical, security, privacy, performance, maintainability and operational criteria;
7. produce an architecture proposal and obtain the required owner approval before implementation;
8. create durable multi-step engineering work that survives conversation, provider and process restarts;
9. develop source changes only in isolated workspaces;
10. obtain dependencies and credentials only through governed brokers rather than unrestricted shell or prompt-visible secrets;
11. generate or extend tests, reproduce failures, execute bounded experiments and iterate on failed hypotheses;
12. use owner-assisted hardware-in-the-loop acceptance when only a person can confirm physical behavior;
13. produce evidence-backed candidate changes, PRs, CI results, documentation and rollback information;
14. promote only through explicit accepted governance, including explicit protected-main merge approval;
15. observe production results, retain verified engineering lessons and reuse them later;
16. detect recurring weaknesses and eventually propose improvements before a complete failure occurs;
17. benchmark improvement candidates against the accepted JARVIS baseline;
18. evolve progressively without silently weakening Authority, security, CI, sandbox, verification, credentials or repository governance.

The target relationship is therefore:

```text
OWNER
  |
  | intent / approvals / secrets / physical acceptance
  v
JARVIS GOVERNED ENGINEERING SYSTEM
  |
  +-> understand
  +-> research
  +-> design
  +-> build
  +-> test
  +-> diagnose
  +-> retry
  +-> verify
  +-> prepare promotion
  +-> learn
```

JARVIS may become the engineer. It does not become the owner.

---

## 2. Permanent governance invariants

### 2.1 Intelligence is not authority

Models may research, reason, classify, diagnose, write candidate code, generate tests, compare options and recommend promotion.

Models do not independently:

- lower deterministic risk floors;
- grant themselves capabilities;
- expand network, device, filesystem or credential scope;
- mint execution permits;
- declare verification truth merely from confidence;
- weaken tests, CI, sandbox or evaluator policy to make a candidate pass;
- modify protected Authority or governance without a separately authorized R5-class change;
- merge protected main;
- silently deploy a protected source change.

### 2.2 Owner approval remains explicit at material gates

Current engineering governance remains:

```text
research thoroughly
-> architecture
-> owner approval
-> isolated implementation / PR
-> CI
-> owner-machine acceptance where required
-> documentation
-> explicit owner merge approval
-> protected-main merge
```

Future convenience may reduce repetitive low-risk prompts only through a separately approved policy. It may not be inferred from this plan.

### 2.3 Production is not the experiment environment

Unknown diagnosis, generated code, dependency experiments, model-generated tests and synthetic training/evaluation run outside protected production state.

The accepted production runtime remains the baseline until a candidate is explicitly promoted.

### 2.4 Verification is independent of model confidence

A model that generated a candidate does not get to declare the candidate correct merely by evaluating its own output.

Verification should combine, as applicable:

- deterministic postconditions;
- predefined verification contracts;
- reproduction/regression tests;
- repository quality gates;
- independent CI;
- hardware/device state evidence;
- owner acceptance;
- production health observation.

### 2.5 No unrestricted general-purpose execution surface

Do not solve autonomy by exposing arbitrary shell/PowerShell, unrestricted package installation, unrestricted LAN scanning or unrestricted credentials to the model.

Autonomy is created by adding typed governed capabilities around the engineering lifecycle.

---

## 3. One shared platform, three autonomous loops

JARVIS should not grow separate competing repair, coding, skill and device brains. The system uses one durable governed engineering substrate with three trigger loops.

### Loop A — deterministic production repair

Trigger: an accepted known runtime failure signature.

```text
signal
-> deterministic classify
-> registered RepairPolicy
-> Authority / budget / preconditions
-> bounded action
-> deterministic verifier
-> recovered OR fail-closed escalation
```

This loop must continue to work without AI providers for owner-accepted low-risk repairs.

### Loop B — unknown-problem investigation and repair engineering

Trigger: an incident or malfunction that has no accepted deterministic repair.

```text
incident
-> bounded evidence package
-> engineering knowledge retrieval
-> research / diagnosis
-> hypotheses and experiments
-> architecture decision
-> owner approval when implementation is required
-> isolated source repair
-> tests / verification
-> owner acceptance where required
-> governed promotion
-> production observation
-> engineering knowledge
```

### Loop C — capability evolution

Trigger: either a direct owner goal or, later, an autonomously detected capability gap.

```text
owner goal OR observed gap
-> capability check
-> missing capability
-> research
-> candidate approaches
-> architecture proposal
-> owner approval
-> isolated implementation
-> dependency / secret broker as required
-> automated tests / simulation / replay
-> hardware-in-the-loop acceptance where required
-> PR / CI / docs
-> explicit promotion approval
-> production observation
-> engineering knowledge
```

Direct owner-requested capability acquisition must exist before autonomous gap detection. JARVIS must not require repeated failure or repeated owner requests before acting on an explicit request to acquire a capability.

### 3.4 Engineering processes are open-ended consumers, not a closed enumeration

The three loops above are the first known consumers of the governed engineering substrate, not the permanent list of everything JARVIS may ever engineer.

Future process families such as security remediation, model training, infrastructure evolution, hardware adaptation, data migration or categories not yet anticipated must be addable without creating parallel systems for Authority, EngineeringKnowledge, WorkItems, verification, promotion or provenance.

The extension model is therefore:

```text
stable governed engineering core
        |
        +-- repair process
        +-- unknown-investigation process
        +-- capability-acquisition process
        +-- future process type
        +-- future unknown process type
```

New process semantics must enter through registered, versioned contracts and fail closed when the running JARVIS does not understand them. Extensibility must not become arbitrary unvalidated JSON or unrestricted execution.

---

## 4. Canonical engineering objects

### 4.1 WorkItem remains the execution unit

Existing `WorkItem`, `WorkStep` and `WorkDelivery` remain the durable execution truth for bounded work. They should not be overloaded into representing the complete lifecycle of a multi-stage engineering change.

### 4.2 EngineeringChange becomes the program-level aggregate

One durable `EngineeringChange` should represent the complete lifecycle of a source repair, integration, new capability or improvement.

Recommended trigger kinds:

- `INCIDENT`
- `OWNER_GOAL`
- `OBSERVED_GAP`
- `PERFORMANCE_WEAKNESS`
- `SECURITY_FINDING`
- `MAINTENANCE_REQUIREMENT`

Recommended lifecycle:

```text
PROPOSED
-> RESEARCHING
-> ARCHITECTURE_READY
-> WAITING_OWNER_APPROVAL
-> APPROVED_FOR_BUILD
-> DEVELOPING
-> VERIFYING
-> WAITING_OWNER_ACCEPTANCE
-> READY_FOR_PROMOTION
-> WAITING_PROMOTION_APPROVAL
-> PROMOTED
-> OBSERVING
-> CLOSED
```

Terminal/alternate states include `REJECTED`, `FAILED`, `SUPERSEDED`, `ROLLED_BACK` and `BLOCKED_EXTERNAL`.

One `EngineeringChange` may own several dependent WorkItems: research, diagnostics, development, benchmarking, device acceptance, documentation and promotion preparation.

### 4.3 EngineeringKnowledge replaces a repair-only knowledge silo

The durable engineering memory foundation should be generic from Phase 2 onward.

Recommended knowledge kinds:

- `REPAIR`
- `DIAGNOSTIC`
- `CAPABILITY`
- `INTEGRATION`
- `ARCHITECTURE`
- `EVALUATION`
- `OPERATIONS`

`RepairKnowledge` may remain a repair-specific semantic subtype/view, but the underlying provenance, lifecycle, supersession, confidence and retrieval model should be shared.

Required common fields include:

- stable knowledge ID;
- type/kind;
- component/capability/device scope;
- evidence provenance;
- source freshness/version compatibility;
- verified finding or engineering sequence;
- verification contract;
- required resources/capabilities;
- originating incident/change/work IDs;
- lifecycle state `CANDIDATE`, `STAGED`, `ACCEPTED`, `REJECTED`, `RETIRED`;
- version/supersession/lineage;
- confidence/evidence grade;
- expiry or revalidation rules where facts can become stale.

EngineeringKnowledge is advisory truth. It is not executable Authority.

### 4.4 CapabilityManifest

Every dynamically acquired capability should have a normalized manifest declaring at least:

- capability ID and version;
- purpose and supported operations;
- adapter/provider/device compatibility;
- required permissions;
- network requirements;
- secrets/credentials required;
- dependencies and exact versions;
- CPU/RAM/GPU/resource expectations;
- health probes;
- verification contracts;
- enable/disable/rollback procedure;
- source/build provenance;
- owner acceptance evidence;
- current lifecycle status.

A capability manifest does not self-authorize runtime operations. Normal Authority still applies per action.

---

## 5. Governed engineering substrate

### 5.1 Isolated development workspace

Keep the accepted properties:

- one deterministic worktree/branch per development WorkItem;
- no production-tree writes;
- no arbitrary host shell as the generic model interface;
- no automatic push/merge/deploy;
- sensitive-file restrictions;
- locked-down test execution;
- final diff inspection;
- clean candidate commit proof.

Do not weaken these controls to make capability acquisition easier.

### 5.2 DependencyBroker

Future capability acquisition requires a governed way to add libraries, SDKs or tools without giving a model unrestricted package-install authority.

Recommended flow:

```text
dependency proposal
-> authoritative package/source identity
-> exact version
-> license/policy/security checks
-> hash/provenance capture
-> owner/policy gate when required
-> trusted acquisition
-> local artifact cache
-> isolated environment consumes staged dependency
```

The dependency source, digest, resolved version and acquisition evidence should be durable and reproducible.

### 5.3 SecretBroker

Secrets must not become ordinary model prompt/log/source material.

Recommended flow:

```text
JARVIS identifies credential requirement
-> owner enters secret through local trusted UI
-> OS-bound encrypted storage
-> opaque secret reference
-> scope-bound runtime access
-> audit usage without plaintext
-> revoke / rotate
```

The model should normally see that a secret handle exists and what scope it authorizes, not the plaintext secret.

### 5.4 Device/Service Discovery Broker

Discovery must be bounded to owner-authorized networks/devices/services.

It may support typed mechanisms such as mDNS, SSDP, ONVIF discovery, vendor discovery or approved inventory queries, but must not become unrestricted network reconnaissance.

### 5.5 Hardware-in-the-loop acceptance

A real physical device often cannot be fully verified by CI.

JARVIS must be able to pause with a concrete acceptance action such as:

- "I sent the TV power command. Did the TV turn on?"
- "Please stand at the gate; I will verify the alert path."
- "The device is showing a pairing PIN; please provide/confirm it through the secure prompt."

The owner's observation becomes typed acceptance evidence, not free-form proof that bypasses automated verification.

---

## 6. Research and architecture discipline

Before implementation of a material new capability or repair candidate, JARVIS should:

1. restate the owner goal and measurable acceptance criteria;
2. inspect accepted architecture and existing capabilities first;
3. prefer official standards/vendor documentation and mature supported interfaces;
4. compare multiple viable approaches where meaningful;
5. evaluate local vs cloud privacy and latency;
6. evaluate dependency and supply-chain risk;
7. evaluate compatibility with existing capability/runtime interfaces;
8. define security/permission/secret/network requirements;
9. define failure modes and rollback;
10. define automated verification and real-world acceptance before code is written;
11. present the architecture decision for owner approval.

Research output is evidence, not execution authority.

---

## 7. Verification and evidence hierarchy

### Runtime repair

Verify the failed property directly: readiness, authenticated liveness, durable state and absence of duplicate side effects.

### Unknown diagnosis

Verify hypotheses against reproduced symptoms, correlated evidence, controlled experiments and known injected root causes when available.

### Source change

Require reproduction/regression evidence where feasible, targeted tests, repository gates, final diff inspection, forbidden-surface checks and clean candidate state.

### New capability

Require protocol/API mocks where practical, failure-path tests, compatibility checks, actual device/service acceptance when needed and a support matrix stating what is and is not proven.

### Improvement

Require benchmark comparison against the accepted production baseline. "Tests pass" is not sufficient evidence that an optimization is an improvement.

---

## 8. Program phases

The accepted Phase 0, Phase 1 and Phase 1H foundations are preserved. No Phase 1/R2 rewrite is required by this architecture.

### Phase 0 — prerequisites

**STATUS: DONE**

Self-Awareness/Self Model, Health Registry, operational evidence, engineering incidents, Authority, durable WorkItems, isolated development, sandboxed tests, CI/governance and deployment/readiness boundaries.

### Phase 1 — deterministic repair framework + R2 runtime self-repair

**STATUS: DONE / OWNER-MACHINE ACCEPTED 2026-09-23**

Preserve the accepted deterministic repair foundation and bounded automatic R2 crash/hang recovery.

### Phase 1H — foundation hardening

**STATUS: DONE / OWNER-MACHINE ACCEPTED 2026-09-24**

Preserve the current hardening contract. This architecture review does not reopen the accepted runtime design.

### Phase 2 — EngineeringKnowledge foundation

**STATUS: DONE / OWNER-MACHINE ACCEPTED 2026-09-25**

Generalize the already researched RepairKnowledge work into the shared durable engineering knowledge model, with `REPAIR` as the first implemented vertical.

Exit criteria:

- verified repair outcomes produce provenance-linked candidate knowledge;
- lifecycle/supersession/rejection are deterministic;
- accepted knowledge is retrievable;
- no knowledge record gains execution authority;
- schema can represent later integration/capability knowledge without migration to a parallel silo.

### Phase 3 — EngineeringChange lifecycle and mission orchestration

**STATUS: ACTIVE / NEXT ARCHITECTURE SLICE**

Add the durable program-level aggregate above WorkItems.

Exit criteria:

- one owner goal/incident can own multiple dependent restart-safe WorkItems;
- architecture approval, owner-input waits, acceptance and promotion gates are explicit durable states;
- restarts cannot skip a gate or lose change provenance.

### Phase 4 — Research/Diagnostic Model Router

Create one provider/model-neutral routing boundary for research, diagnostics and engineering reasoning.

Routing considers task kind, privacy/locality, evidence size, model capabilities, latency, cost, provider health and previous outcomes. Provider choice never changes Authority.

### Phase 5 — Secure autonomous engineering substrate

Build the governed primitives needed before JARVIS can acquire arbitrary new capabilities safely:

- DependencyBroker;
- SecretBroker;
- capability manifest schema;
- bounded device/service discovery interface;
- sandbox profiles that remain least-privilege;
- artifact/source/dependency provenance;
- hardware-in-the-loop acceptance contracts.

### Phase 6 — unknown-incident investigation and source repair

Use EngineeringKnowledge + router + EngineeringChange + existing isolated development to investigate unknown incidents, generate repairs, test them and present owner-reviewable candidates.

### Phase 7 — governed promotion, production verification and rollback

Connect accepted candidates to PR/CI/protected-main governance and existing deployment/readiness/rollback boundaries.

No automatic protected-main merge is implied.

### Phase 8 — capability package and registry lifecycle

Create normalized capability packages/manifests, compatibility and health truth, enable/disable semantics and versioned registry lifecycle.

### Phase 9 — owner-requested capability acquisition

This is the first complete "capability to build capabilities" milestone.

Example owner request:

> "JARVIS, I want to control this TV through you. Get that capability."

Required lifecycle:

```text
owner goal
-> capability check
-> discovery/research
-> architecture proposal
-> owner approval
-> isolated implementation
-> governed dependency/secret handling
-> automated verification
-> owner-assisted real-world acceptance
-> PR/CI/docs
-> explicit merge approval
-> production observation
-> EngineeringKnowledge
```

Exit criteria: the owner can acquire one real new capability without manually researching, coding, managing Git or debugging the candidate.

### Phase 10 — closed-loop engineering learning

Production outcomes update/supersede EngineeringKnowledge, regressions and compatibility knowledge. Failed candidates remain useful negative evidence.

### Phase 11 — autonomous capability-gap and weakness detection

Only after direct owner-requested acquisition works reliably should JARVIS create ImprovementCandidates from repeated manual intervention, fallback use, latency/cost/resource problems, reliability weakness or clearly measurable missing capability patterns.

A detected gap creates a proposal, not automatic live mutation.

### Phase 12 — shadow improvement and baseline benchmarking

Research and develop approved improvement candidates in isolation, compare them with production JARVIS, reject regressions and retain the accepted baseline until evidence supports promotion.

### Phase 13 — engineering curriculum and specialist model evaluation

Generate/replay bounded synthetic engineering cases in sandboxes, evaluate diagnostic/coding models on JARVIS-specific evidence and retain only independently verified trajectories.

### Phase 14 — governed self-evolution

Mature integrated lifecycle:

```text
understand
-> observe / receive owner goal
-> identify problem or gap
-> research
-> architect
-> owner gate when required
-> build in isolation
-> verify
-> benchmark / accept
-> promotion gate
-> deploy
-> observe
-> rollback if required
-> learn
```

The objective is increasingly autonomous engineering with stable governance, not autonomous governance mutation.

---

## 9. Relationship to numbered product roadmap

This program is cross-cutting and does not renumber product Steps 8–20.

The numbered roadmap still builds user-facing capabilities such as device control, browser interaction, files/coding, proactive monitoring and extensible skills.

This master plan provides the engineering system by which JARVIS can eventually acquire, repair and improve those capabilities itself.

Important relationships:

- Step 9 Device Control provides stable user-facing device capability semantics.
- Step 12 Coding/Project Engineering matures the engineering action surface.
- Step 16 Extensible Skills provides lifecycle/registration substrate.
- Step 18 Learning/Gap Detection/Governed Skill Creation consumes the autonomous engineering platform.
- Step 19 Self-Diagnostics/Repair uses Loops A and B.
- Step 20 Governed Self-Improvement integrates all three loops.

Do not create duplicate task, permission, research, development, secret or capability registries for these steps when the shared canonical primitive exists.

---

## 10. Reference scenarios

### Smart TV

Owner: "JARVIS, I want to control this TV through you. Get that capability."

JARVIS should discover/identify the device through authorized mechanisms, research official/local control options, compare vendor API/WebSocket/ADB/CEC/IR or other applicable routes, present architecture, request pairing/PIN only when necessary, build a normalized adapter, test state-changing operations with safe bounds, ask the owner to verify physical state where needed, prepare evidence and seek explicit promotion approval.

JARVIS must truthfully report unsupported operations or vendor restrictions rather than inventing control.

### Gate camera

Owner: "Integrate the gate camera and tell me when a person is there."

JARVIS should identify the camera/protocol, prefer standard local interfaces such as ONVIF/RTSP when applicable, obtain credentials through SecretBroker, implement an adapter behind the canonical camera source interface, reuse person detection, add zone/temporal/cooldown logic, test disconnect/reconnect and false alerts, conduct owner-assisted physical acceptance, then use normal promotion governance.

### Unknown production defect

Incident: audio/vision/runtime behavior is wrong and no deterministic policy matches.

JARVIS should preserve production state, create diagnostic work, gather bounded evidence, retrieve relevant engineering knowledge, reproduce in isolation where feasible, test hypotheses, generate a source candidate only after architecture/authority requirements are satisfied, and never convert model confidence directly into a live repair.

---

## 11. Security and supply-chain research principles

The engineering architecture follows the direction of established secure-development and supply-chain practices:

- integrate secure-development controls into the software lifecycle rather than bolt them on after implementation;
- address root causes so vulnerabilities/failures do not repeatedly recur;
- preserve provenance describing where, when and how software artifacts/dependencies were produced;
- require branch/PR/status-check governance before protected-main promotion;
- keep least privilege and separation between development/test and production.

References used for this architecture review:

- NIST SP 800-218 Secure Software Development Framework (SSDF) v1.1;
- SLSA v1.2 Provenance specification;
- GitHub protected-branch documentation for required reviews/status checks.

These are architectural guidance, not a claim that JARVIS currently implements every control described by those standards.

---

## 12. Documentation authority and drift prevention

Canonical ownership after this plan is accepted:

- `PRODUCT.md` — durable product intent/capability catalogue;
- `ROADMAP.md` — numbered product sequence/high-level status;
- `CURRENT_ARCHITECTURE.md` — accepted running architecture only;
- `CURRENT_PLAN.md` — current active work only;
- `PROJECT_STATE.md` — accepted/deferred/superseded/rejected ledger;
- `QUALITY_GATES.md` — universal completion and promotion rules;
- `GOVERNED_AUTONOMOUS_ENGINEERING_MASTER_PLAN.md` — authoritative north-star architecture for owner-directed autonomous engineering;
- `SELF_REPAIR_AND_EVOLUTION_MASTER_PLAN.md` — specialized repair/evolution program aligned under this master plan;
- phase-specific design/research documents — implementation detail for the active phase.

Rules:

1. future architecture must not be represented as current production architecture;
2. `CURRENT_PLAN.md` is authoritative for the currently active phase;
3. roadmap summaries must not contradict `CURRENT_PLAN.md`;
4. a phase cannot be declared complete merely because code exists;
5. accepted architecture decisions that future agents could misunderstand should receive an ADR or explicit master-plan ruling;
6. Git history is the archive; do not create competing FINAL/V2 planning documents.

---

## 13. Immediate sequence from 2026-09-25

1. Phase 1/R2 and Phase 1H remain accepted foundations.
2. Phase 2 EngineeringKnowledge is complete and owner-machine accepted.
3. Begin Phase 3 by researching and freezing the durable `EngineeringChange` lifecycle / mission-orchestration architecture above existing WorkItems.
4. Do **not** reopen or rewrite accepted Phase 1/R2, Phase 1H or Phase 2 without new concrete evidence.
5. Define `EngineeringChange` before multi-stage autonomous source/capability engineering is implemented.
6. Preserve current sandbox and Authority restrictions; add brokers rather than broad permissions.
7. Continue through the phases in Section 8 unless new evidence justifies an owner-approved sequencing change.

The program is considered aligned only while each active slice can answer:

> **How does this move JARVIS toward accepting owner intent and autonomously performing the necessary governed engineering, without taking ownership authority away from the owner?**
