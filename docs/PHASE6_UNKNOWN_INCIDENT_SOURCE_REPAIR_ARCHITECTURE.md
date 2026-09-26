# Phase 6 Unknown-Incident Investigation + Source Repair — Architecture

Status: **PROPOSED / OWNER APPROVAL REQUIRED**

Date: 2026-09-27

## 1. Purpose

Phase 6 adds the governed path from an unknown incident to an owner-reviewable source-repair candidate. It does not add promotion/deployment; that belongs to Phase 7.

Accepted boundaries from Phases 1–5 remain authoritative.

## 2. Architectural invariants

1. Unknown investigation is evidence-driven and durable.
2. Known accepted deterministic RepairPolicy handling keeps priority over Phase 6.
3. Model reasoning never becomes execution Authority.
4. Diagnostic source access is read-only.
5. Diagnostic code execution is sandboxed and network-disabled by default.
6. Source mutation begins only after the existing owner architecture gate.
7. DEVELOPMENT reuses the accepted isolated worktree/edit/test/diff/commit substrate.
8. A normal repair candidate cannot modify registered protected governance/security surfaces.
9. Production/protected main is never the experiment environment.
10. Phase 6 ends with a candidate; it does not merge or deploy it.

## 3. New process contract

Add a registered process family: unknown_incident_repair.v1.

Trigger identity is the canonical incident ID, exact source revision, initiating evidence IDs and process version. Admission is idempotent for the same incident + revision while an active change exists.

Lifecycle:

    Incident OPEN / INVESTIGATING
      -> EngineeringChange PROPOSED
      -> DIAGNOSTICS WorkItem
      -> typed diagnosis + repair architecture artifact
      -> ARCHITECTURE_READY
      -> WAITING_OWNER_APPROVAL
      -> APPROVED_FOR_BUILD
      -> existing DEVELOPMENT WorkItem
      -> VERIFYING
      -> source-repair candidate evidence
      -> WAITING_OWNER_ACCEPTANCE / READY_FOR_PROMOTION boundary

Phase 7 later owns promotion.

## 4. New Phase-6 domain

Create jarvis.incident_repair.

### 4.1 IncidentRepairTrigger

Fields: incident_id, source_revision, component_ids, evidence_ids, reason_code, created_at_epoch and canonical digest. This trigger is evidence identity, not an executable permit.

### 4.2 DiagnosticHypothesis

Fields: stable hypothesis ID, statement, affected components/paths, supporting evidence IDs, refuting evidence IDs, proposed discriminator/reproduction target, and status PROPOSED / SUPPORTED / REFUTED / INCONCLUSIVE.

No numeric confidence value can create truth or unlock development.

### 4.3 IncidentDiagnosis

Fields: diagnosis ID, incident/change/work IDs, source revision, evidence IDs, EngineeringKnowledge revision IDs, reproduction state, hypotheses, selected root-cause hypothesis ID or null, affected paths/components, proposed repair scope, verification targets, reason codes and canonical digest.

Reproduction state is REPRODUCED / NOT_REPRODUCED / INCONCLUSIVE.

### 4.4 SourceRepairCandidateEvidence

Derived from canonical DEVELOPMENT evidence: incident ID, diagnosis ID/digest, architecture artifact ID/digest, development WorkItem ID, branch, commit, changed paths, diff digest, passing verification targets, sandbox profile/version, protected-surface verdict and candidate digest.

This artifact is review evidence only.

## 5. Incident admission

Add IncidentRepairCoordinator.

Admission rules:

1. incident exists and is not CLOSED/RESOLVED;
2. no accepted deterministic automatic RepairPolicy is currently applicable to the initiating trigger;
3. incident has bounded evidence;
4. exact source revision is available;
5. no active Phase-6 EngineeringChange already owns the same incident + revision;
6. source revision is immutable in the Phase-6 trigger.

On admission the incident becomes/retains INVESTIGATING, an EngineeringChange using unknown_incident_repair.v1 is linked, a trigger artifact is persisted and a DIAGNOSTICS stage is created.

Unknown policy failures remain fail-closed: Phase 6 investigates; it does not guess a live repair action.

## 6. Diagnostic evidence package

Add IncidentEvidencePackager.

Inputs may include IncidentRecord fields, incident EvidenceReferences, immutable RepairAttempt snapshots/verifier outcomes, exact Git revision, component identifiers, bounded health/self-model references and accepted EngineeringKnowledge retrieval results.

Security requirements: size limits, allowlisted evidence kinds, secret-pattern rejection/redaction, no raw environment dumps, no credentials, no unrestricted filesystem traversal, and persisted references rather than unbounded blob copies where practical.

The package has a canonical digest and is bound to the diagnostic WorkItem.

## 7. Diagnostic workspace

Add DiagnosticWorkspaceManager.

Properties:

- one deterministic workspace per DIAGNOSTICS WorkItem;
- exact source revision pinned at creation;
- detached diagnostic Git worktree;
- no source-write/edit/commit action registered to DIAGNOSTICS;
- source reads/searches only through typed executors;
- project code executes only through an approved sandbox profile;
- workspace mounted read-only into the test/reproduction sandbox;
- hooks disabled;
- sensitive paths blocked;
- never use protected main itself as the experiment workspace.

## 8. Diagnostic actions

Register only for WorkType.DIAGNOSTICS:

- diag_prepare_workspace — prepare/reopen pinned diagnostic workspace.
- diag_get_incident — return bounded canonical evidence package.
- diag_retrieve_knowledge — retrieve bounded EngineeringKnowledge revisions as advisory evidence.
- diag_list_files — bounded non-sensitive repository listing.
- diag_search_source — bounded text search.
- diag_read_file — bounded non-sensitive UTF-8 read.
- diag_run_reproduction — explicit pytest targets in a network-disabled read-only sandbox.
- diag_record_hypothesis — persist a typed hypothesis WorkStep with evidence references.
- diag_finalize — validate and persist the final structured diagnosis observation.

research_web may also be available to DIAGNOSTICS when an external library/API/protocol question actually requires fresh research. It is not a completion requirement for local bugs.

## 9. Diagnostic completion guard

WorkType.DIAGNOSTICS may complete only when:

1. canonical incident evidence was inspected;
2. source-revision workspace was prepared;
3. at least one hypothesis was recorded;
4. at least one reproduction/controlled observation attempt exists unless a typed reason says reproduction is impossible;
5. diag_finalize exists after the latest relevant evidence;
6. the final diagnosis references only known evidence/knowledge IDs;
7. the result is either a supported repair diagnosis with verification targets or a truthful INCONCLUSIVE result.

The Work engine derives the WorkItem result from diag_finalize rather than free-form completion text.

## 10. EngineeringChange integration

Extend the process registry without breaking engineering.change.v1.

Introduce a registered ProcessStageContract instead of permanently hard-coding only research and development stages.

For unknown_incident_repair.v1 the sequence is diagnostics -> architecture gate -> development -> acceptance boundary.

For existing engineering.change.v1 the sequence remains research -> architecture gate -> development -> acceptance boundary.

Existing Phase-3 behavior and tests must remain unchanged from the caller perspective.

## 11. Repair architecture artifact

After DIAGNOSTICS completes, derive the architecture artifact from diagnosis ID/digest, source revision, proposed repair scope, approved changed-path/component scope, verification targets, dependency proposal IDs if any, protected-surface classification and rollback/disable notes.

The owner reviews this exact digest through the existing architecture gate. No source-write executor becomes admitted before approval.

## 12. Development handoff

After approval, reuse the existing DEVELOPMENT WorkItem. Its context includes incident ID, diagnosis artifact ID/digest, approved architecture artifact, source revision, bounded affected paths and required verification targets.

Existing development controls remain: isolated worktree, bounded read/search/write, no unrestricted shell, sandboxed pytest, tests after latest edit, final diff after tests, clean local commit and no push/merge.

## 13. Protected-surface policy

Add versioned RepairProtectedSurfacePolicy.

Initial protected classes include Authority/approval policy, protected-main governance/ruleset configuration, credential/secret policy, sandbox policy, and acceptance/evaluator policy that could self-mark the repair successful.

Verdicts: CLEAR, PROTECTED_CHANGE_REQUIRED, UNKNOWN. Only CLEAR can proceed through ordinary Phase 6. The other outcomes fail closed and require a separately authorized protected change.

## 14. Candidate verifier

Before Phase-6 completion:

1. development WorkItem is COMPLETED;
2. commit/branch exist and worktree is clean;
3. tests passed after latest edit;
4. final diff was inspected;
5. required diagnosis verification targets passed;
6. changed paths match approved scope;
7. protected-surface verdict is CLEAR;
8. source revision/architecture/diagnosis provenance matches;
9. no production/main mutation occurred.

Persist SourceRepairCandidateEvidence. Phase 6 stops at owner review / Phase-7 promotion boundary.

## 15. Router behavior

No new model router is required. Reuse engineering_stage.v1. Unknown diagnostics already select capable reasoning unless the work has settled. Phase 6 can add routing features for failed hypotheses, conflicting evidence, reproduction failures and evidence size. Provider failure remains bounded fallback or WAITING_RESOURCE and never changes Authority.

## 16. Dependency handling

Normal diagnosis does not install packages. If reproduction needs a missing dependency, a typed dependency requirement goes through the Phase-5 DependencyBroker and admitted artifacts are consumed by an approved sandbox. No unrestricted model-authored package install.

Initial Phase 6 may support the already configured JARVIS test image first and add dynamic diagnostic dependencies later only if real acceptance evidence requires it.

## 17. Restart semantics

Incident ID, EngineeringChange ID, diagnostic WorkItem ID, source revision, workspace identity, hypotheses/evidence WorkSteps, architecture artifact/gate, development WorkItem/branch and candidate evidence all survive restart.

Interrupted executor outcomes remain unknown and use existing fail-closed WorkEngine semantics.

## 18. Non-goals

Phase 6 does not auto-merge, deploy, rollback production, create a general shell, add unrestricted network access, automatically promote RepairKnowledge into RepairPolicy, train a repair model, implement autonomous capability-gap detection, or bypass architecture/acceptance/promotion gates.

## 19. Acceptance criteria

A controlled unknown incident must prove this complete lineage:

    unknown incident
      -> same durable incident
      -> same durable EngineeringChange
      -> bounded/redacted evidence
      -> accepted knowledge retrieval
      -> sandboxed reproduction
      -> typed supported/inconclusive diagnosis
      -> exact owner-approved architecture
      -> isolated source edit
      -> post-edit verification
      -> protected-surface CLEAR
      -> final diff
      -> clean commit
      -> owner-reviewable source-repair candidate

Restart, provider failure and failed hypotheses must not create duplicate work or weaken controls.
