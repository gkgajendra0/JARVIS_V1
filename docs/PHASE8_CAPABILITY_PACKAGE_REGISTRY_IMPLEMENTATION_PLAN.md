# Phase 8 — Capability Package + Registry Lifecycle Implementation Plan

## Status

**PROPOSED — IMPLEMENTATION REQUIRES OWNER ARCHITECTURE APPROVAL — 2026-09-27**

## 8A — package contracts and schema

Deliver:

- `CapabilityPackageV1`;
- package artifact descriptor;
- strict SemVer;
- package kind/runtime API contracts;
- canonical digest;
- JSON Schema Draft 2020-12;
- forbidden executable/secret fields tests.

## 8B — durable registry

Deliver:

- dedicated capability registry state directory/database;
- checksummed/versioned migrations;
- immutable package admission rows;
- per-capability selected version + desired state + generation;
- append-only lifecycle events;
- optimistic CAS/restart tests.

## 8C — admission and compatibility

Deliver:

- `ReleaseCapabilityPackageSource`;
- exact active-release SHA binding;
- Phase-5 manifest validator reuse;
- trusted provider registry;
- ArtifactStore/provenance verification;
- runtime API/platform/provider compatibility;
- version-reuse conflict handling;
- quarantine;
- compatibility evidence digest.

## 8D — runtime projection + health

Deliver:

- registry inventory view;
- CORE_PINNED vs PACKAGE_MANAGED truth;
- `CapabilityRegistryProjection`;
- effective-enable policy;
- existing CapabilityRuntime integration;
- trusted health probe bridge to Self Model;
- disable/enable routing refresh;
- no dynamic Python reload.

## 8E — lifecycle Authority + version rollback

Deliver:

- Authority-bound enable/disable/select-version operations;
- exact package/generation/compatibility proposal binding;
- one selected version invariant;
- old-version rollback when current release explicitly supports it;
- retire/quarantine behavior;
- artifact retention references;
- restart/idempotency tests.

## 8F — evaluation and acceptance

Deliver:

- deterministic lifecycle replay matrix;
- Linux CI;
- Windows registry/restart CI;
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
- existing core capabilities must continue working throughout migration.

## Stop condition

After research/architecture docs are complete, stop before Phase-8 runtime implementation and request explicit owner architecture approval.
