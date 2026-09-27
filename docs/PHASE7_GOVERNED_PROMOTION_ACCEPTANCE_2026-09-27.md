# Phase 7 Governed Promotion / Production Verification / Rollback — Owner-Machine Acceptance

## Status

**PASS — OWNER-MACHINE ACCEPTED 2026-09-27**

Acceptance-tested implementation head:

`19beb542295fa4e3ab23407564847a82d8621258`

PR:

`#150 — Phase 7: governed promotion, production verification and rollback`

Protected-main squash merge:

`d2c7dc360386dab22bff6406d405b298601bff81`

Owner-machine evidence file:

`C:\Users\gkgaj\AppData\Local\Temp\jarvis_phase7_owner_acceptance_19beb542\phase7-owner-acceptance.json`

Owner-machine evidence digest:

`9fb2bb940a855c1d0ab32e444e00d7e922bd66d5edd7915c31efe6dd5fa77a9b`

Deterministic replay digest:

`07f53707a42760f53b6dadb4fc8740ea4553437d33551038b2ba0f726c0356ae`

## Final disposition

Phase 7 is accepted for its defined scope.

The accepted implementation connects the Phase-6 verified source-repair candidate boundary to exact GitHub PR/CI evidence, digest-bound owner promotion review, one-shot Authority execution, protected-main exact-head squash merge, immutable Windows release staging, production identity verification, bounded observation and compatibility-safe rollback.

The final owner-machine run returned `status=PASS` for the exact implementation head above. The accepted candidate was subsequently merged to protected `main` as the squash commit above.

## Accepted Phase-7 behavior

The accepted Phase-7 path can:

- re-verify the canonical Phase-6 candidate and exact protected-main base;
- reject stale candidates rather than silently rebase/update them;
- publish only the exact verified local candidate commit through a typed Git boundary;
- reconcile exactly one candidate PR and exact PR/head/base identities;
- require actual successful Linux and Windows CI evidence;
- require the stable aggregate `promotion-policy` check;
- bind promotion evidence to the candidate, PR, tested merge result, CI/check identity, configuration, compatibility evidence and Last Known Good release;
- present one exact immutable owner-review artifact;
- keep owner gate approval separate from executable Authority;
- convert an exact approved promotion into one one-shot scoped Authority permit;
- merge only the expected PR head using squash merge;
- re-read and verify protected `main` after merge;
- stage the exact merged SHA into a separate immutable Windows release root;
- preserve single-active-runtime semantics for hardware/resource safety;
- verify runtime release identity rather than liveness alone;
- durably reconcile deployment after restart/crash;
- classify observation failures so provider/hardware/network failure does not automatically trigger code rollback;
- automatically roll back only attributable candidate-local failure when LKG and compatibility evidence allow it;
- bound automatic rollback to one attempt per deployment incident;
- preserve schema/DBOS/runtime dependency changes as high-risk paths requiring explicit compatibility planning;
- keep promotion/deployment, supervisors, durable persistence, migrations, Authority, secrets and acceptance controls protected from ordinary source repair.

## Deterministic replay result

The owner-machine run passed all 14 approved Phase-7 replay cases.

Final replay result:

- status: `PASS`;
- cases: `14/14`;
- suite digest: `07f53707a42760f53b6dadb4fc8740ea4553437d33551038b2ba0f726c0356ae`.

The replay covers exact candidate creation, stale-base failure, moved PR head, wrong CI App identity, skipped Windows validation, exact authorized merge, external-merge reconciliation, successful production close, external-failure non-rollback, candidate-local LKG rollback, high-risk compatibility blocking, protected control surfaces, unknown observation failure and deployment-resume idempotency.

## Owner-machine environment proof

The real Windows owner-machine run additionally proved:

- exact tested SHA: `19beb542295fa4e3ab23407564847a82d8621258`;
- staged release SHA: exact match;
- active release SHA: exact match;
- Last Known Good SHA: exact match;
- config digest: `8460f0900ed18bbb7603129a4a4690f9cdb691d33b145cd3b7b14ee96be5220a`;
- release staging: idempotent;
- staged release tracked state: clean;
- protected acceptance repository: unchanged;
- owner's normal JARVIS checkout: unchanged;
- protected-surface policy: `repair.protected_surfaces` version 2;
- protected-surface verdict for the acceptance probe: `protected_change_required`.

## Final CI result

Exact-head GitHub CI for the accepted implementation passed on workflow run:

`36304998175`

The accepted head passed:

- Ruff formatting/lint;
- full Linux pytest suite;
- Windows Hello helper build/contract;
- Windows Hands/sandbox/DPAPI/self-repair regressions;
- Phase-6 replay regressions;
- Phase-7 GitHub evidence/GitHub App transport tests;
- Phase-7 authority/merge tests;
- Phase-7 deployment/release-slot tests;
- Phase-7 deterministic replay;
- non-destructive Windows Phase-7 acceptance harness;
- aggregate `promotion-policy`.

## Authority and operational boundary

Phase-7 acceptance does **not** grant JARVIS ownership authority.

The accepted system still requires the owner-defined promotion boundary. In particular:

- model reasoning cannot self-approve protected-main promotion;
- gate approval alone is not an execution permit;
- protected-main merge remains bound to exact owner-reviewed evidence and one-shot Authority;
- the GitHub App private key is handled only through the governed SecretBroker child boundary;
- no GitHub credential is stored in source or exposed to model context;
- live GitHub App installation/configuration remains an operational secret/configuration prerequisite for runtime use of that transport;
- schema, DBOS workflow/persistence, runtime dependency and deployment/governance changes remain high-risk paths rather than ordinary autonomous promotion.

## Promotion decision

Phase 7 Governed Promotion / Production Verification / Rollback is:

**DONE / OWNER-MACHINE ACCEPTED 2026-09-27**

PR #150 was explicitly owner-approved and merged to protected `main` as:

`d2c7dc360386dab22bff6406d405b298601bff81`

The next cross-cutting phase is:

**Phase 8 — Capability Package + Registry Lifecycle**

Phase 8 must begin with its own repository inspection, technology research and architecture proposal. Phase-7 completion does not pre-authorize Phase-8 implementation.
