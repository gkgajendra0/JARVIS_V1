# Phase 9 — Owner-Requested Capability Acquisition Acceptance

## Status

**SOFTWARE / CI COMPLETE — REAL EXTERNAL OWNER-MACHINE ACCEPTANCE PENDING — 2026-09-27**

Phase 9 must **not** be marked DONE / OWNER-MACHINE ACCEPTED until one genuine owner-requested external capability completes the full lifecycle and produces canonical real-world evidence.

## Accepted software baseline

- final reviewed hardening head: `81d498a22bb2293d69c6b6a848b08740fae30f75`;
- protected-main squash merge from PR #178: `e73db07abad7ab0e73ee2f0030ff6e58e9f3ee76`;
- Phase-9 9A–9F implementation plus 9G deterministic evaluation/acceptance substrate are merged;
- live owner entrypoint, secure promotion composition and post-deploy lifecycle wiring are merged.

## Exact-head CI result

PR #178 Code Quality run #5086 passed on the exact reviewed head before merge.

Passed gates:

- Ruff formatting/lint;
- full Linux pytest suite;
- Windows Hello helper build/tests;
- Windows DPAPI and unified Windows regression lane;
- inherited Phase-6 replay regressions;
- Phase-7 release/promotion regressions and non-destructive acceptance harness;
- Phase-8 capability-registry regressions and non-destructive acceptance harness;
- Phase-9 capability-acquisition replay regressions;
- final promotion-policy gate.

The Windows Phase-8 acceptance harness remained green during this run, including its 45-case replay and protected-repository unchanged checks. Phase-9 replay contract tests remained green after the final restart-idempotency hardening.

## Software behavior now present

The protected-main Phase-9 path now provides:

1. canonical owner-goal admission grounded to the latest accepted owner turn;
2. exact trusted source-revision binding;
3. existing-capability/package reuse before new engineering;
4. strict owner-approved reusable source evidence for local, MCP, OpenAPI, AsyncAPI and SDK routes;
5. unverified research metadata that cannot self-assign trust;
6. deterministic source resolution with custom build as last resort;
7. durable RESEARCH -> exact architecture -> owner architecture gate;
8. isolated DEVELOPMENT with Phase-5 dependency, provenance, sandbox and secret controls;
9. exact capability candidate/package evidence;
10. secure short-lived GitHub App promotion sessions using SecretBroker + Windows Hello + one-shot Authority;
11. exact Phase-7 PR/CI/promotion/deployment reuse with no parallel Git/promotion truth;
12. automatic active-release Phase-8 package admission without auto-enable;
13. restart-idempotent package/lifecycle evidence;
14. durable post-deploy owner activation handoff;
15. explicit Phase-8 Authority-bound activate/disable;
16. immediate live capability-catalog refresh after activation/disable;
17. authenticated supervisor production observations;
18. exact active-release / tested-commit binding in final acceptance evidence;
19. canonical real-evidence collection from durable stores using the EngineeringChange ID;
20. rollback/disable evidence required for final acceptance.

## Security invariants preserved

- owner intent is not unrestricted Authority;
- no model-assigned source trust;
- no arbitrary shell/install surface;
- no plaintext credential in package or machine configuration;
- GitHub App private key remains DPAPI-sealed in SecretStore;
- live GitHub App token is scoped to one repository with only Actions read, Checks read, Contents write and Pull Requests write;
- protected-main source promotion remains Phase 7;
- capability lifecycle remains Phase 8;
- durable work remains WorkItem/DBOS;
- governed engineering truth remains EngineeringChange;
- registration/admission never auto-enables a new capability.

## Remaining real owner-machine acceptance gate

Use one genuine owner-requested capability with external state. The preferred reference case remains a TV/device integration when a reachable supported route is available.

The acceptance run must prove, from canonical evidence:

1. owner request admitted as one Phase-9 EngineeringChange;
2. existing capability/package check completed;
3. real source discovery/research occurred;
4. exact architecture proposal was owner-approved;
5. implementation completed without the owner manually researching, coding, managing Git or debugging the candidate;
6. dependency/secret/provenance controls passed;
7. automated verification passed;
8. exact Phase-7 promotion and production deployment completed;
9. exact Phase-8 package admission completed without auto-enable;
10. explicit owner activation made the package effectively enabled;
11. one genuine external operation produced an observed real-world effect;
12. production observation exists;
13. explicit disable/rollback restored the safe state;
14. active release SHA equals the tested acceptance checkout SHA;
15. the final Phase-9 acceptance harness passes its deterministic replay and evidence validation;
16. protected repository state remains unchanged by the acceptance harness.

## Operational prerequisite for autonomous Git/PR handling

The owner machine must have a repository-scoped GitHub App available to JARVIS. The accepted helper requests only:

- Actions: read;
- Checks: read;
- Contents: write;
- Pull requests: write.

The private key is enrolled through `jarvis.promotion.setup` into the DPAPI-backed SecretStore; only the non-secret App/client/installation/repository identifiers are persisted in machine configuration.

This is an operational credential prerequisite, not a new Authority path.

## Completion rule

After the real external capability run passes, append the exact:

- accepted protected-main SHA;
- EngineeringChange ID;
- acquisition/development WorkItem IDs;
- package identity/digest;
- promotion attempt;
- active release SHA;
- lifecycle evidence;
- external operation/target/effect;
- production observation reference;
- disable/rollback evidence reference;
- 24-case replay suite digest;
- final acceptance evidence digest.

Only then change the status to:

**DONE / OWNER-MACHINE ACCEPTED**
