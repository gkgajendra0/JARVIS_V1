# Phase 6 Unknown-Incident Investigation + Source Repair — Implementation Plan

Status: **PROPOSED / WAITING OWNER ARCHITECTURE APPROVAL**

Date: 2026-09-27

## 1. Permanent engineering rule

research thoroughly -> architecture -> owner approval -> isolated implementation / PR -> CI -> owner-machine acceptance where required -> documentation -> promotion approval -> protected-main merge

Phase-6 runtime implementation must not begin until the proposed architecture is explicitly approved.

## 2. Implementation sequence

Phase 6 is split into small additive slices so failures can be isolated without weakening accepted Phases 1–5.

### Phase 6A — contracts + process registration

Implement:
- jarvis.incident_repair domain contracts;
- IncidentRepairTrigger;
- DiagnosticHypothesis;
- IncidentDiagnosis;
- SourceRepairCandidateEvidence;
- canonical digests and validation;
- registered unknown_incident_repair.v1 process;
- generic ProcessStageContract support while preserving engineering.change.v1 behavior.

Tests:
- schema validation;
- digest determinism;
- process registration fail-closed behavior;
- duplicate incident+revision admission idempotency;
- existing Phase-3 EngineeringChange regression suite unchanged.

Exit gate: no runtime executor yet; contracts and process semantics only.

### Phase 6B — incident admission + bounded evidence

Implement:
- IncidentRepairCoordinator;
- source-revision capture;
- evidence allowlist/bounds/redaction;
- RepairAttempt/evidence linkage;
- accepted EngineeringKnowledge retrieval adapter;
- trigger/evidence artifacts in ChangeStore.

Tests:
- known deterministic repair does not enter Phase 6;
- unknown incident enters one canonical change;
- secret-like evidence is rejected/redacted;
- evidence package bound to exact revision;
- restart does not duplicate change/work.

Exit gate: one unknown incident can create a durable DIAGNOSTICS stage with bounded evidence.

### Phase 6C — read-only diagnostic workspace + source tools

Implement:
- DiagnosticWorkspaceManager;
- diag_prepare_workspace;
- diag_list_files;
- diag_search_source;
- diag_read_file;
- diagnostic sensitive-path restrictions;
- detached exact-revision workspace;
- no diagnostic write/commit actions.

Tests:
- exact revision checkout;
- protected main remains untouched;
- symlink/path traversal blocked;
- sensitive files blocked;
- restart reopens same workspace identity;
- DIAGNOSTICS registry exposes no write action.

Exit gate: model can inspect exact source revision through bounded read-only tools.

### Phase 6D — reproduction + hypothesis protocol + completion guard

Implement:
- diag_get_incident;
- diag_retrieve_knowledge;
- diag_run_reproduction using network-disabled sandbox;
- diag_record_hypothesis;
- diag_finalize;
- DIAGNOSTICS completion guard;
- WorkItem result derived from diag_finalize;
- routing signals for failed hypotheses/conflicting evidence/reproduction failure;
- optional research_web availability for DIAGNOSTICS.

Tests:
- successful reproduction;
- failed/non-reproducible result remains truthful;
- hypothesis supporting/refuting evidence validation;
- stale/unknown evidence IDs rejected;
- premature goal_complete blocked;
- provider failure -> WAITING_RESOURCE;
- no model confidence bypass.

Exit gate: diagnosis is a canonical structured result, not prose.

### Phase 6E — architecture derivation + owner gate + development handoff

Implement:
- deterministic repair architecture artifact derived from diagnosis;
- exact architecture digest gate through existing GateService;
- approved changed-path/component scope;
- development request builder with diagnosis provenance;
- development stage dependency on diagnostics;
- existing DEVELOPMENT actions reused unchanged where possible.

Tests:
- diagnosis completion alone cannot create write-capable work;
- rejected architecture creates no development stage;
- stale architecture approval rejected;
- approved architecture creates exactly one development WorkItem;
- development is bound to diagnosis + architecture revision;
- restart cannot skip owner gate.

Exit gate: owner approval is the only transition from diagnosis to source mutation.

### Phase 6F — protected-surface policy + candidate evidence

Implement:
- RepairProtectedSurfacePolicy v1;
- final changed-path classifier;
- approved-scope verifier;
- SourceRepairCandidateEvidence builder;
- candidate digest;
- Phase-6 VERIFYING -> owner-reviewable candidate transition.

Initial protected classes:
- Authority/approval code and policy;
- repository governance/ruleset/CI control surfaces;
- secret/credential policy;
- sandbox policy;
- acceptance/evaluator policy capable of self-approving the change.

Tests:
- ordinary source repair CLEAR;
- protected path -> PROTECTED_CHANGE_REQUIRED;
- unknown classification -> fail closed;
- out-of-approved-scope diff rejected;
- source edit without post-edit tests rejected;
- passing tests before latest edit do not count;
- final diff and clean commit required;
- candidate evidence binds exact commit/diff/diagnosis/architecture.

Exit gate: JARVIS can present a verified candidate without merge/deploy authority.

### Phase 6G — replay evaluation + owner-machine acceptance

Build deterministic replay/evaluation cases:

1. local deterministic source defect that reproduces and is repaired;
2. non-reproducible incident -> INCONCLUSIVE;
3. wrong first hypothesis then successful discriminator;
4. accepted EngineeringKnowledge retrieved but not executable;
5. provider pressure and fallback/wait behavior;
6. restart during diagnostics;
7. restart after owner approval before development;
8. restart during development;
9. failed candidate tests;
10. protected-surface attempted repair;
11. secret-bearing evidence negative control;
12. known deterministic repair negative control;
13. duplicate trigger/idempotency;
14. protected main unchanged;
15. candidate evidence exact-head/digest verification.

Owner-machine acceptance should use a harmless controlled fixture incident and must prove the real Windows worktree + Docker sandbox + restart path.

Exit gate:
- repository CI green;
- owner-machine acceptance PASS;
- exact accepted SHA and evidence digest recorded;
- docs reconciled;
- Phase 6 marked DONE only then.

## 3. Files likely to be added

- src/jarvis/incident_repair/__init__.py
- src/jarvis/incident_repair/models.py
- src/jarvis/incident_repair/evidence.py
- src/jarvis/incident_repair/workspace.py
- src/jarvis/incident_repair/actions.py
- src/jarvis/incident_repair/coordinator.py
- src/jarvis/incident_repair/verification.py
- tests/test_incident_repair_models.py
- tests/test_incident_repair_evidence.py
- tests/test_incident_repair_workspace.py
- tests/test_incident_repair_actions.py
- tests/test_incident_repair_coordinator.py
- tests/test_incident_repair_verification.py
- tests/test_phase6_acceptance.py

Existing files expected to receive bounded changes:
- src/jarvis/engineering_change/models.py
- src/jarvis/engineering_change/store.py
- src/jarvis/engineering_change/coordinator.py
- src/jarvis/work/runtime.py
- src/jarvis/work/engine.py
- src/jarvis/work/actions.py
- src/jarvis/model_routing/strategy.py

## 4. Dependencies

Initial implementation adds no new third-party runtime dependency.

Use existing:
- Git worktree operations;
- ripgrep fallback logic where available;
- pytest;
- Docker sandbox;
- EngineeringKnowledge retrieval;
- Model Router;
- Phase-5 DependencyBroker only when a real reproduction requires missing dependencies.

This avoids importing OpenHands, SWE-agent or another agent framework into the runtime.

## 5. Security/regression gates

Every slice must preserve:
- Authority tests;
- EngineeringChange gate tests;
- development isolation tests;
- Phase-5 sandbox/provenance tests;
- secret redaction tests;
- protected-main non-mutation;
- Windows-specific tests where file/worktree semantics differ;
- no unrestricted shell/network/package installation.

## 6. Owner-machine acceptance boundary

Owner input should be required only for:
- the Phase-6 architecture approval before implementation begins;
- any real physical/manual evidence not software-verifiable;
- final Phase-6 owner-machine acceptance if the automated evidence cannot prove the actual Windows integration;
- promotion/merge according to governance.

The controlled acceptance incident itself must be harmless and reversible.

## 7. Phase-6 completion definition

Phase 6 is complete only when JARVIS can truthfully do this without owner debugging/coding:

    detect/admit unknown incident
    -> investigate bounded evidence
    -> retrieve verified engineering knowledge
    -> reproduce/localize
    -> maintain explicit hypotheses
    -> finalize typed diagnosis
    -> wait for exact architecture approval
    -> build repair in isolation
    -> verify after edits
    -> block protected-surface drift
    -> produce clean source-repair candidate

and stop before protected-main merge/deployment.
