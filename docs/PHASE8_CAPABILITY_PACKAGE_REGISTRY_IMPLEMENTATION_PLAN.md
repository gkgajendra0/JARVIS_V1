# Phase 8 — Capability Package + Registry Lifecycle Implementation Plan

## Status

**OWNER-APPROVED — IMPLEMENTATION IN PROGRESS — 8A–8E DONE / 8F ACTIVE — 2026-09-27**

## 8A — package contracts and schema — DONE

Deliver:

- `CapabilityPackageV1`;
- package artifact descriptor;
- strict SemVer;
- package kind/runtime API contracts;
- canonical digest;
- JSON Schema Draft 2020-12;
- closed/allowlisted package object schema so unknown execution/secret fields fail closed;
- forbidden executable/secret fields tests;
- explicit separation of package-schema version, manifest-contract version and package SemVer.

## 8B — durable registry — DONE

Deliver:

- dedicated capability registry state directory/database;
- checksummed/versioned migrations;
- immutable package admission rows;
- per-capability selected version + desired state + generation;
- append-only lifecycle events;
- SQLite WAL + explicit transactional lifecycle mutation;
- `BEGIN IMMEDIATE` mutation boundary;
- atomic registry-CAS + lifecycle-event commit;
- optimistic CAS/concurrent-writer/restart tests.

## 8C — admission and compatibility — DONE

Deliver:

- `ReleaseCapabilityPackageSource`;
- exact active-release SHA binding;
- Phase-5 manifest validator reuse;
- trusted provider registry with execution-model-neutral source-owned registrations;
- exact reuse of Phase-7 active release identity verification;
- ArtifactStore/provenance verification;
- runtime API/platform/provider compatibility;
- version-reuse conflict handling;
- quarantine;
- compatibility evidence digest.

## 8D — runtime projection + health — DONE

Deliver:

- registry inventory view;
- CORE_PINNED vs PACKAGE_MANAGED truth;
- `CapabilityLifecycleReconciler`;
- `CapabilityRegistryProjection`;
- immutable generation-bearing effective-state snapshot;
- per-capability transition fence;
- stale-generation fail-closed routing;
- effective-enable policy;
- existing CapabilityRuntime integration;
- trusted health probe bridge to Self Model;
- startup/release/health/lifecycle reconciliation triggers;
- bounded periodic safety reconciliation;
- no SQLite read on every normal capability invocation solely for generation checking;
- no dynamic Python reload.

## 8E — lifecycle Authority + version rollback — DONE

Deliver:

- `CapabilityLifecycleService` for Authority-bound enable/disable/select-version operations;
- exact package/generation/compatibility proposal binding;
- transition-fence-before-mutation semantics;
- Authority before durable permissive transition;
- one selected version invariant;
- old-version rollback when current release explicitly supports it;
- retire/quarantine behavior;
- safety quarantine that immediately removes routing without rewriting desired state;
- artifact retention references;
- crash-after-commit/before-projection recovery tests;
- restart/idempotency tests;
- DBOS explicitly outside canonical registry truth; use only if a future lifecycle operation genuinely needs durable multi-step orchestration.

## 8F — evaluation and acceptance — IN IMPLEMENTATION

Deliver:

- deterministic lifecycle replay matrix covering the complete architecture acceptance matrix, including reconciliation, transition fencing, atomic event/CAS commit, stale projection generation and concurrent mutation cases;
- Linux CI;
- Windows registry/restart/file-handle CI;
- non-destructive owner-machine acceptance;
- exact accepted implementation SHA/evidence digest;
- final docs reconciliation;
- protected-main promotion only after explicit owner approval.

## Permanent implementation rules

- extend Phase-5 manifest/security, do not duplicate it;
- metadata never imports code;
- registry never installs dependencies;
- installed entry points never auto-enable execution;
- no arbitrary shell;
- no plaintext secret fields;
- no model-written health;
- no second approval system;
- code changes still use EngineeringChange + Phase 7;
- existing core capabilities must continue working throughout migration;
- PACKAGE_MANAGED routing must fail closed during transition or stale projection generation;
- the reconciler never grants Authority and never silently rewrites desired state;
- canonical lifecycle truth remains available even if DBOS is unavailable;
- persistent package metadata cannot choose an arbitrary execution model;
- WASI/Extism/AppContainer/Dapr/Nix/OCI-registry/TUF infrastructure remains deferred from Phase-8 v1.

## Stop condition

After research/architecture docs are complete, stop before Phase-8 runtime implementation and request explicit owner architecture approval.
