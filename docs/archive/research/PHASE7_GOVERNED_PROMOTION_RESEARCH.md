# Phase 7 — Governed Promotion / Production Verification / Rollback Research

## Status

**OWNER-APPROVED RESEARCH BASIS — 2026-09-27**

Phase 7 begins only after Phase 6 has produced an independently verified, owner-reviewable source candidate. Its purpose is to connect that candidate to protected-main promotion, exact production activation, observation, and safe rollback without allowing model reasoning to become Authority.

## Repository findings

The accepted repository already provides the required foundations:

- `EngineeringChange` already owns `READY_FOR_PROMOTION`, `WAITING_PROMOTION_APPROVAL`, `PROMOTED`, `OBSERVING`, `CLOSED`, and `ROLLED_BACK`.
- `GateService` binds decisions to exact artifact identity/digest and explicitly does not create execution Authority.
- Phase 6 produces `SourceRepairCandidateEvidence` with exact candidate commit, diff digest, changed paths, sandbox evidence, and a CLEAR protected-surface verdict.
- the development supervisor already has readiness verification and startup rollback, but it mutates one working tree and therefore is not the final production-release design.
- runtime readiness/liveness, Windows Job Object ownership, the outer Windows guardian, DBOS durable work, WorkStore persistence, and versioned SQLite migrations already exist.
- production orchestration is Postgres-backed DBOS; the current package version is static `0.1.0`, so workflow compatibility must be treated explicitly during promotion.
- Phase 5 already provides governed dependency acquisition using trusted `uv`, PEP-751 pylock inspection, exact wheel hashes, and provenance; however the complete production runtime does not yet have one canonical fully reproducible release lock.

## External technology dispositions

### GitHub

Use GitHub as the protected source/promotion substrate rather than adding a separate deployment platform.

Keep:

- protected default branch + repository rulesets;
- pull requests;
- GitHub Actions / checks;
- exact-head merge protection;
- least-privilege GitHub App credentials for the future JARVIS runtime adapter.

Do not adopt merge queue for the current single-owner/low-concurrency repository.

GitHub Deployment records may mirror exact deployment SHA/status for audit, but are not Authority.

### Provenance

Adopt SLSA-style provenance concepts now: every promotion decision must bind exact candidate input, CI evidence, merge identity, deployment identity, and verification output.

Full artifact-attestation/signing can be added when JARVIS deploys packaged immutable artifacts. Current production is source based.

### Windows deployment

Do not make in-place `git pull/reset` the final autonomous promotion mechanism.

Use a **single-active release-slot** model:

1. stage the exact accepted merged SHA into a separate release root;
2. verify dependencies/config/schema compatibility;
3. record recovery intent and Last Known Good identity;
4. stop the one active runtime;
5. switch the active release pointer;
6. start and verify exact runtime identity;
7. observe;
8. restore LKG only when rollback is both attributable and data-compatible.

Do not run two simultaneous full JARVIS instances because voice/camera/hardware/DBOS resources are not generally safe for dual-active operation.

### Persistence / rollback

SQLite online backup is useful for consistent pre-change snapshots, but restoring an old snapshot after legitimate new-version durable writes can destroy valid state.

Therefore automatic rollback is allowed only when compatibility evidence proves it safe. Schema/durable-workflow changes are high-risk by default.

### DBOS

DBOS workflow upgrades require explicit compatibility discipline. Ordinary code changes may use the existing stable generic workflow contract. Changes to DBOS workflow structure/persistence behavior are protected/high-risk and require an explicit patch/version migration strategy.

Do **not** automatically map every Git SHA to a new DBOS application version: that could strand unfinished durable work.

### Dependencies

Ordinary source-only changes may use the normal promotion path.

Changes to `pyproject.toml`, runtime dependency policy, or production environment construction are protected/high-risk until a reproducible release-environment contract is independently evidenced.

## Permanent research conclusions

1. Extend existing EngineeringChange; do not create a competing engineering lifecycle.
2. Promotion evidence must be immutable and digest-bound.
3. A candidate built from a stale protected-main base is not silently rebased or merged. It must be reintegrated/reverified and receive new evidence.
4. Owner gate approval and execution Authority remain separate concepts.
5. Model output can prepare promotion but cannot authorize merge/deploy.
6. Protected-main promotion must re-read external GitHub state immediately before execution.
7. Production verification must prove the **running release identity**, not merely process liveness.
8. Automatic rollback must be attributable, bounded, and compatibility-safe.
9. External provider/hardware/network failures are not automatically code regressions.
10. Restart recovery must reconcile from durable local records plus current external truth and must not duplicate PRs, merges, deployments, or rollback.

## Technology decision

No large new orchestration/deployment platform is justified for Phase 7. Reuse JARVIS Work/EngineeringChange/Authority/Self-Repair foundations plus official GitHub primitives and a narrow Windows release controller.
