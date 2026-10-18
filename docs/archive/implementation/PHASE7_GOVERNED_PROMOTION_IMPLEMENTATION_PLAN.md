# Phase 7 — Governed Promotion / Production Verification / Rollback Implementation Plan

## Status

**COMPLETE — OWNER-MACHINE ACCEPTED 2026-09-27**

Implementation followed the owner-approved Phase-7 research and architecture. Slices 7A-7F are complete. Exact-head CI, Windows regression coverage, the deterministic 14-case replay and the real owner-machine acceptance all passed for implementation head `19beb542295fa4e3ab23407564847a82d8621258`. PR #150 was explicitly owner-approved and squash-merged to protected `main` as `d2c7dc360386dab22bff6406d405b298601bff81`. Canonical final evidence is recorded in `PHASE7_GOVERNED_PROMOTION_ACCEPTANCE_2026-09-27.md`.

## Slices

### 7A — Promotion domain and safety

- durable PromotionAttempt contract/store;
- candidate normalization/verifier;
- immutable PromotionEvidenceV1 contract;
- stale-base/restart semantics;
- Phase-7 protected-surface hardening;
- deterministic unit tests.

### 7B — GitHub promotion integration

- typed GitHub adapter contracts;
- exact candidate ref/PR reconciliation;
- CI/check evidence verification;
- aggregate `promotion-policy` CI gate;
- exact tested head/base/merge identity.

### 7C — Owner promotion + protected merge

- promotion evidence artifact/gate;
- exact digest owner review;
- one-shot Authority bridge;
- expected-head squash merge;
- post-merge protected-main verification;
- restart/idempotency tests.

### 7D — Windows release deployment

- release-slot layout;
- immutable exact-SHA staging;
- active/LKG/recovery metadata;
- supervisor integration;
- runtime hello/readiness release identity;
- crash-safe activation/recovery;
- Windows CI.

### 7E — Production observation + rollback

- observation contract/budget;
- failure attribution;
- LKG validation;
- schema/DBOS/dependency/config compatibility;
- deterministic safe rollback;
- external-failure non-rollback controls.

### 7F — End-to-end acceptance

- full deterministic replay/fault injection;
- GitHub/CI identity negative controls;
- Windows release/recovery acceptance;
- exact accepted SHA;
- one consolidated owner-machine acceptance block;
- documentation reconciliation.

## Merge/activation rule

Phase-7 implementation is accepted for its defined scope. Protected-main promotion still requires the exact owner/Authority boundary defined by the architecture; acceptance does not grant JARVIS ownership authority or permission to weaken repository governance.

No implementation slice may weaken existing Authority, protected-main, sandbox, secret, dependency, provenance, verification, or owner-gate controls.
