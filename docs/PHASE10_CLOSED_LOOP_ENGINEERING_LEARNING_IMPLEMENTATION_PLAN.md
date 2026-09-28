# Phase 10 — Closed-Loop Engineering Learning Implementation Plan

## Status

**IMPLEMENTATION COMPLETE — AUTOMATED VALIDATION GREEN — OWNER-MACHINE ACCEPTANCE PENDING — 2026-09-28**

Permanent engineering sequence remains:

```text
research thoroughly -> architecture -> owner approval -> isolated branch/PR
-> CI -> owner-machine acceptance when required -> docs -> merge
```

Implementation must preserve all accepted Phase 2/6/7/8/9 contracts and the deferred
Phase-9 full external lifecycle validation.

## 1. Slice sequence

Phase-10 implementation uses numeric sub-slices because `Phase 10A` is already
reserved for the future Autonomous Operations Control Plane.

### Phase 10.1 — Learning contracts and registered facets

Deliver:

- `jarvis.engineering_learning` package;
- typed `EngineeringOutcomeV1` and enums;
- deterministic outcome identity/digest semantics;
- learning facet schemas/handlers:
  - `jarvis.engineering.outcome` v1;
  - `jarvis.engineering.regression` v1;
  - `jarvis.engineering.compatibility` v1;
- register these handlers in the default EngineeringKnowledge facet registry;
- strict validation and unknown-field rejection;
- tests for canonicalization, identity, schema validation, duplicate keys,
  searchable text, applicability and revalidation rules.

Gate:

- no persistence/lifecycle behavior yet;
- no Authority or production changes;
- existing EngineeringKnowledge tests remain green.

### Phase 10.2 — Canonical outcome adapters

Deliver read-only adapters for:

- Phase-7 promotion/production observation;
- Phase-8 capability compatibility;
- verified Phase-1/Phase-2 repair outcome lineage where appropriate;
- Phase-9 acquisition terminal evidence where actually proven.

Adapters must preserve exact IDs/digests and fail closed on missing/stale evidence.

Gate:

- adapters cannot write canonical source stores;
- external/provider/hardware/unknown attribution stays distinct;
- deferred Phase-9 physical lifecycle is never fabricated.

### Phase 10.3 — Deterministic learning eligibility

Deliver:

- `EngineeringLearningEligibilityPolicy`;
- POSITIVE / NEGATIVE / COMPATIBILITY / INCONCLUSIVE / IGNORE dispositions;
- evidence requirements per outcome source/result/attribution;
- deterministic reason codes;
- policy-version identity.

Gate:

- no model call;
- unknown attribution cannot become verified causal learning;
- external failure cannot poison candidate knowledge.

### Phase 10.4 — Knowledge projection

Deliver:

- deterministic stable knowledge identity;
- immutable revision construction;
- facets/evidence/applicability/attestation projection;
- atomic `EngineeringKnowledgeCandidateBundle` persistence;
- idempotent replay for the same source outcome.

Gate:

- source evidence and subject digests must be exact;
- tampered/missing evidence fails closed;
- no duplicate knowledge on replay/restart.

### Phase 10.5 — Learning lifecycle and supersession

Deliver:

- engineering-learning promotion policy;
- CANDIDATE -> STAGED -> ACCEPTED using existing lifecycle primitives;
- contradiction/supersession evaluation;
- immutable successor revision creation;
- old ACCEPTED revision -> SUPERSEDED only after successor acceptance.

Gate:

- no row mutation;
- no unsupported cross-applicability supersession;
- superseded/rejected/retired revisions remain non-current.

### Phase 10.6 — Closed-loop reconciler and retrieval integration

Deliver:

- bounded restart-safe `EngineeringLearningReconciler`;
- cursor/idempotency semantics using canonical outcome identities;
- recovery of missed terminal outcomes after restart;
- derived EngineeringKnowledge retrieval indexing of newly accepted learning;
- Phase-6/engineering retrieval compatibility.

Gate:

- learning failure cannot block promotion rollback or production safety;
- reconciler cannot create general autonomous projects or Authority;
- no new retrieval truth store.

### Phase 10.7 — Deterministic evaluation and owner-machine acceptance

Deliver:

- replay corpus covering success/failure/external/unknown/compatibility/
  contradiction/restart/tamper cases;
- acceptance harness;
- Windows owner-machine path where required;
- final evidence record;
- final documentation/status reconciliation.

Minimum acceptance scenarios:

1. verified successful deployment -> accepted retrievable positive learning;
2. candidate-local production failure + rollback -> accepted negative/regression lesson;
3. external provider failure -> no candidate-blaming accepted lesson;
4. external hardware failure -> no candidate-blaming accepted lesson;
5. unknown attribution -> inconclusive/fail closed;
6. compatibility READY -> exact positive compatibility lesson;
7. compatibility BLOCKED -> exact negative compatibility lesson;
8. contradictory newer verified result -> immutable successor + prior SUPERSEDED;
9. restart/replay -> no duplicates;
10. evidence tamper/missing digest -> fail closed;
11. rejected/retired/superseded knowledge excluded from current retrieval;
12. existing Phase 2/6/7/8/9 acceptance/regression lanes remain green.

## 2. CI strategy

Each slice should run at minimum:

- Ruff formatting/lint;
- targeted new Phase-10 tests;
- full Linux pytest;
- relevant existing EngineeringKnowledge / promotion / capability-registry regressions.

Later integration slices must also preserve the Windows/security/promotion regression
lanes required by repository policy.

## 3. Branch/PR strategy

Implementation starts from protected-main baseline:

`a35164f35f426166c5986525df4f1dade5b5e594`

Active branch:

`feat/phase10-closed-loop-engineering-learning`

The branch must remain isolated. Protected `main` is updated only through the normal
PR/CI/governance path.

## 4. Explicit non-goals

Phase 10 does not:

- implement Phase 10A objectives/desired-state reconciliation;
- autonomously create improvement projects;
- implement Phase 11 capability-gap detection;
- add a universal cross-domain Knowledge Fabric;
- replace EngineeringKnowledge persistence/retrieval;
- replace Phase-7 promotion/rollback;
- add a second package registry or work system;
- grant JARVIS new execution Authority;
- depend on an LLM for truth classification.

## 5. Completion rule

Slices 10.1–10.7 are implemented. The final Phase-10.7 replay matrix is automated and
the owner-machine harness is implemented.

Do not mark Phase 10 DONE until the exact Phase-10.7 implementation/acceptance head has CI green, required owner-machine acceptance has passed against that tested commit, and a later documentation-only acceptance record has captured the evidence before merge.

The Phase-9 deferred full external capability lifecycle remains a separate mandatory
final whole-system validation item.
