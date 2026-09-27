# Phase 8 — Capability Package + Registry Lifecycle Implementation Plan

## Status

**PROPOSED — AWAITING OWNER ARCHITECTURE APPROVAL**

No implementation is authorized by this document until the Phase-8 architecture is explicitly owner-approved.

## Planned slices

1. **8A — Durable package/registry domain**
   - immutable CapabilityPackageRecord;
   - lifecycle state machine;
   - SQLite registry/migrations;
   - lifecycle event evidence;
   - PEP-440 capability-version validation.

2. **8B — Trusted implementation/content binding**
   - version-controlled implementation catalog;
   - exact source-content digest;
   - trusted executor/adapter registration digests;
   - compatibility evidence;
   - Phase-5 manifest/references reuse.

3. **8C — Runtime projection + health**
   - registry-backed runtime projection;
   - deterministic health probes;
   - Self Model health publication;
   - disabled/degraded behavior.

4. **8D — Activation lifecycle**
   - governed enable/disable;
   - atomic version switch;
   - activation-attempt recovery;
   - bounded rollback;
   - management Authority bridge.

5. **8E — Existing built-in bootstrap**
   - checked-in manifests/package definitions for current default executors;
   - deterministic migration into registry;
   - catalog/operation equivalence validation.

6. **8F — Acceptance**
   - negative-control replay;
   - Linux + Windows CI;
   - non-destructive owner-machine acceptance;
   - docs reconciliation.

## Permanent implementation rules

- Phase-5 CapabilityManifest remains canonical.
- Phase-8 registry never becomes per-action Authority.
- no arbitrary entry-point/plugin auto-loading;
- no generic package-manager shell;
- no remote registry/marketplace in v1;
- no enable before ACCEPTED + COMPATIBLE;
- one ordinary ENABLED version per capability ID;
- source-integrated capability code must already have passed governed source promotion;
- disable/rollback never delete provenance/evidence;
- live health comes from deterministic probes and the existing Self Model;
- implementation stops for any new architecture/Authority decision not covered by the approved Phase-8 design.
