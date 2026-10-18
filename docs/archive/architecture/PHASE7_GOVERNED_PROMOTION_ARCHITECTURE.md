# Phase 7 — Governed Promotion / Production Verification / Rollback Architecture

## Status

**OWNER-APPROVED ARCHITECTURE — 2026-09-27**

This document is the stable Phase-7 implementation contract.

## 1. Boundary

Input:

- one canonical EngineeringChange at `READY_FOR_PROMOTION`;
- one exact verified candidate and its acceptance/provenance evidence.

Output:

- `CLOSED` after exact merge, exact production activation, and observation; or
- deterministic fail-closed / rollback state with complete evidence.

Phase 7 never grants JARVIS permission to redefine Authority, repository governance, verification requirements, or protected surfaces.

## 2. Components

### PromotionCandidateVerifier

Re-derives promotion input from canonical ChangeArtifacts and rejects:

- missing or superseded candidate evidence;
- candidate/acceptance mismatch;
- non-CLEAR protected-surface evidence;
- malformed candidate/base/head identity;
- stale protected-main base.

### PromotionAttempt

Durable operational record for one exact candidate promotion attempt. It binds:

- EngineeringChange;
- candidate artifact + candidate digest;
- candidate base/head SHA;
- PR and CI identity;
- exact promotion-evidence artifact/digest;
- merge SHA;
- deployment identity;
- Last Known Good identity;
- observation/rollback outcome.

This is not a second engineering lifecycle. EngineeringChange remains canonical lifecycle truth.

### GitHubPromotionAdapter

Typed least-privilege operations only:

- ensure/read candidate remote ref;
- ensure/read one PR;
- read PR/check/workflow state;
- verify exact tested head/base/merge result;
- merge only with expected head SHA;
- optionally mirror deployment status.

No generic shell and no repository Administration/Workflow mutation capability.

### PromotionEvidenceV1

Immutable evidence digest binds at least:

- change/candidate identity;
- candidate base/head/diff;
- protected-surface policy/verdict;
- PR base/head;
- tested merge SHA;
- required CI/check identities and conclusions;
- Windows verification result;
- schema/DBOS/dependency/config compatibility evidence;
- merge method;
- deployment environment;
- current Last Known Good identity.

Owner promotion approval reviews this exact digest.

### PromotionAuthorityBridge

Consumes:

1. exact approved PROMOTION gate decision;
2. same immutable PromotionEvidence digest;
3. canonical one-shot Authority permit scoped to exact merge/deploy operation.

Gate decision alone is never executable Authority.

### DeploymentCoordinator

Stages exact merged SHA into an immutable release root and performs one-active-runtime switch with durable recovery marker.

### ProductionVerifier

Requires authenticated runtime readiness plus runtime-reported:

- exact release SHA;
- release root;
- promotion-attempt ID;
- config digest.

### ObservationController

Classifies failures as:

- `CANDIDATE_LOCAL`;
- `EXTERNAL_PROVIDER`;
- `EXTERNAL_HARDWARE`;
- `UNKNOWN`.

Only deterministic candidate-local regression is eligible for automatic code rollback.

### RollbackCoordinator

Automatic rollback requires:

- exact verified LKG;
- compatibility-safe schema/DBOS state;
- no protected/manual intervention requirement;
- deterministic candidate-local failure;
- unused rollback budget.

Maximum one automatic rollback attempt for one deployment incident; otherwise fail closed and escalate.

## 3. Lifecycle

```text
READY_FOR_PROMOTION
  -> candidate verification
  -> exact PR/ref reconciliation
  -> CI evidence
  -> compatibility evidence
  -> PromotionEvidenceV1
  -> PROMOTION owner gate
  -> one-shot Authority permit
  -> exact-head protected merge
  -> verify main/merge identity
  -> PROMOTED
  -> stage exact merged release
  -> activate
  -> verify exact running identity
  -> OBSERVING
  -> bounded observation
  -> CLOSED
       or
     safe rollback -> ROLLED_BACK
```

## 4. Stale candidate rule

If protected `main` no longer equals the candidate's verified base revision:

- mark the PromotionAttempt stale;
- do not rebase, update branch, or merge automatically;
- create/reuse governed integration/reverification work;
- produce a new candidate/evidence lineage;
- old promotion approval is unusable.

## 5. CI policy

Phase 7 should expose one stable aggregate required check, `promotion-policy`, that explicitly requires all mandatory Linux and Windows validations to have actually succeeded.

Skipped/neutral jobs are not accepted by the internal PromotionCandidateVerifier merely because GitHub branch rules might consider a status satisfactory.

The existing `ruff` and `pytest` rules remain.

## 6. Merge policy

Standard Phase-7 merge method: **squash**.

Immediately before merge:

- re-read PR;
- confirm exact approved head SHA;
- confirm base SHA and required checks;
- confirm PromotionEvidence digest is still current;
- consume the one-shot Authority permit;
- merge with expected-head protection;
- verify protected `main` now resolves to the returned merge SHA.

No silent rebase/update branch.

## 7. Release identity / Last Known Good

LKG identity includes:

- release SHA;
- release root;
- config digest;
- relevant schema versions;
- promotion-evidence digest;
- accepted timestamp.

Runtime readiness must identify the actual loaded release, not infer identity from a mutable working directory.

## 8. Compatibility gates

The ordinary autonomous path requires all compatibility checks SAFE.

High-risk/manual-plan surfaces include:

- DBOS durable workflow/persistence contract changes;
- schema/migration changes that are not backward/rollback compatible;
- runtime dependency/environment changes;
- deployment controller/supervisor/guardian changes;
- Authority/governance/CI/protected-surface policy changes.

## 9. Protected surfaces added by Phase 7

At minimum ordinary source repair may not directly modify:

- `src/jarvis/promotion/`;
- `src/jarvis/dev_supervisor.py`;
- `src/jarvis/runtime_supervisor.py`;
- `src/jarvis/self_repair/windows_guardian.py`;
- `src/jarvis/work/dbos_backend.py`;
- WorkStore schema/migration control;
- `src/jarvis/incidents/migrations/`;
- `src/jarvis/memory/migrations/`;
- production release/deployment configuration;
- their boundary/acceptance tests.

## 10. Crash/restart reconciliation

Every side-effecting step is idempotent by durable identity.

On restart:

- before PR: recreate only if exact candidate has no matching PR;
- during CI: re-read workflow/check state;
- after approval: verify approval still binds current evidence;
- after merge: detect exact protected-main SHA rather than merge twice;
- during deployment: reconcile recovery marker + active release + process identity;
- during observation: resume remaining observation budget;
- during rollback: verify active/LKG identities before acting.

## 11. Acceptance

Phase 7 completion requires deterministic tests for:

- stale candidate;
- superseded evidence;
- moved PR head;
- missing/wrong CI App/check;
- skipped Windows requirement;
- duplicate resume;
- crash before/after merge;
- crash during release switch;
- wrong runtime SHA;
- external provider/hardware failure not causing rollback;
- safe candidate-local rollback;
- rollback budget exhaustion;
- schema/DBOS/dependency incompatibility;
- protected-surface mutations.

Windows-specific release/recovery behavior must run in Windows CI wherever practical. Final owner-machine acceptance must be one consolidated, non-destructive PowerShell block bound to the exact accepted SHA.
