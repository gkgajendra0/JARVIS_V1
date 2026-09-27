# Phase 7 — Governed Promotion / Production Verification / Rollback Implementation Plan

## Status

**IMPLEMENTATION IN PROGRESS — OWNER ACCEPTANCE PENDING — 2026-09-27**

Implementation follows the owner-approved Phase-7 research and architecture. Slices 7A-7E are implemented on the isolated draft PR; 7F deterministic replay/Windows acceptance/documentation reconciliation is in validation. This status is not a production-activation claim.

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

Phase-7 implementation PRs may be built and tested in isolation, but autonomous protected-main promotion must remain disabled until complete Phase-7 acceptance.

No implementation slice may weaken existing Authority, protected-main, sandbox, secret, dependency, provenance, verification, or owner-gate controls.
