# Phase 4 Research + Diagnostic Model Router — Owner-Machine Acceptance

## Status

**PASS — OWNER-MACHINE ACCEPTED 2026-09-26**

Acceptance-tested implementation head:

`b6d88199eedaca568efa82bf62a26ec2ef396903`

PR:

`#118 — Phase 4I: add owner-machine routing acceptance boundary`

Canonical live WorkItem:

`work_b58f84dc9f344630`

Accepted live fallback decision:

`decision_09e098b8df291566d2262535`

Owner-machine evidence file:

`C:\Users\gkgaj\AppData\Local\JARVIS\operations\acceptance\phase4-model-routing-work_b58f84dc9f344630.json`

## Final disposition

Phase 4 is accepted for its defined scope.

The owner-machine run proved real provider-neutral background reasoning, deterministic eligibility and stage routing, durable decision/attempt provenance, JARVIS-owned bounded retry/fallback, target-local health/cooldown, restart-safe routing lineage and unchanged Authority/security controls.

The live provider environment also supplied the preferred natural pressure case. No credential corruption, policy rejection, Authority weakening or artificial provider fault was used to manufacture fallback.

## Exact-head and CI evidence

The owner-machine run used the isolated acceptance worktree with the protected-main virtual environment reused read-only through process-local `PYTHONPATH`.

Before the final live sequence:

- exact implementation head: `b6d88199eedaca568efa82bf62a26ec2ef396903`;
- Code Quality run #4502: PASS;
- Ruff: PASS;
- full pytest: PASS;
- Windows Hello helper: PASS;
- Windows multilingual Hands: PASS;
- Windows DPAPI: PASS;
- Self-Repair Windows Job Object regression: PASS;
- focused Phase-4 routing surface: PASS.

The final documentation reconciliation occurs after this accepted implementation head. No accepted runtime code is changed by the documentation-only closure commit.

## Live routing and fallback evidence

The final bounded research WorkItem was created only after both approved cloud routing targets were effective healthy:

- `work.gemini.default`;
- `work.openai.default`.

The canonical WorkItem remained:

`work_b58f84dc9f344630`

For the accepted decision:

`decision_09e098b8df291566d2262535`

the persisted route was:

`work.gemini.default -> work.openai.default`

with:

- strategy: `engineering_stage.v1`;
- selected role: `efficient`;
- fallback budget: `1`;
- both targets eligible;
- no exclusions.

The live attempts were:

1. Gemini primary -> `rate_limited`;
2. OpenAI fallback -> `quota_exhausted`.

This proves that provider SDK retry behavior no longer owns the routed-work retry boundary. JARVIS received provider pressure, classified it, persisted the primary attempt, updated target health and invoked the already-approved OpenAI target within the configured fallback budget.

OpenAI's quota exhaustion is an external provider limitation. It was represented as target-local health/cooldown and did not cause policy relaxation, secret mutation or uncontrolled provider hopping.

## Durable provenance and bounded lineage

The acceptance inspector showed:

- `routing_decision_present` — PASS;
- `routing_links_canonical_work` — PASS;
- `engineering_stage_v1` — PASS;
- `strategy_registry_policy_provenance` — PASS;
- `routing_attempt_present` — PASS;
- `attempt_lineage_preserved` — PASS;
- `bounded_attempt_lineage` — PASS;
- `status_fallback_path_matches_attempts` — PASS.

The evidence output contained bounded routing facts only. Prompt text, API keys, credential material and correlation keys were not exposed.

The inspector intentionally reports machine-verifiable routing evidence as `PENDING` while manual external gates remain outside the JSON. Final accepted evidence was therefore generated with the explicit accepted decision ID rather than relying on the latest in-progress reasoning cycle.

## Restart continuity

The acceptance supervisor was stopped while the canonical WorkItem was active/waiting on routed provider capacity and then started again against the same exact implementation head.

Post-restart verification proved:

- same WorkItem ID: `work_b58f84dc9f344630`;
- exactly one fresh research WorkItem for the acceptance window;
- duplicate routing-request IDs: `0`;
- accepted fallback decision retained exactly two attempts;
- attempt #1 remained Gemini / `rate_limited`;
- attempt #2 remained OpenAI / `quota_exhausted`;
- restart same-lineage verification: PASS.

DBOS therefore resumed the same durable mission rather than creating replacement WorkItems or duplicate routing decisions for the same reasoning-cycle key.

## Authority and security regression

After restart, the owner-machine Authority/security regression suite passed 100%.

The exercised surface included:

- Authority foundation;
- Authority security edges;
- Authority tooling;
- strong approval;
- Hands Authority;
- Windows Authority adapters;
- Windows Hello UTF-8 behavior;
- EngineeringChange gates;
- EngineeringChange admission;
- development Git verification;
- EngineeringKnowledge security.

No Phase-4 behavior bypassed or weakened:

- owner approval;
- Windows Hello;
- OPA/risk controls;
- sandboxing;
- EngineeringChange lifecycle gates;
- credential controls;
- protected-main governance;
- verification boundaries.

No privileged action was created merely to force acceptance.

## Integration defects discovered and corrected during acceptance

Owner-machine acceptance exposed real integration defects. They were fixed before final acceptance.

### 1. Strict OpenAI structured-output schema

The provider-facing WorkDecision schema previously exposed arbitrary-object parameters, which OpenAI strict structured output rejected with HTTP 400.

The provider contract was changed to transport dynamic action arguments as JSON text and decode them back into the canonical `BrainDecision` dictionary only after parsing. Strict-schema regressions verify required properties and `additionalProperties: false`.

### 2. Import-cycle hardening

Fresh-process imports exposed eager package initialization cycles between model-routing and Work modules.

Both package façades were made lazy while preserving their public APIs, with subprocess import regressions covering model-routing and Work imports.

### 3. Provider retry ownership

Pinned provider SDKs performed their own retry behavior. In particular, Gemini Interactions could consume 429 retry/backoff internally before JARVIS saw the first provider failure.

Routed background reasoning now disables provider-SDK retries for both Gemini and OpenAI while preserving existing interactive/Hands defaults. JARVIS routing/health code is the sole owner of bounded retry/fallback for routed WorkReasoner calls.

### 4. Repeated resource-blocker speech

DBOS recovery could expose multiple durable resource-blocker deliveries for the same persistent blocker, and a transient speech failure could make the repeated message especially visible.

Repeated blocker evidence remains durable, but owner-facing blocker delivery is coalesced by blocker reason per WorkItem. Regression coverage verifies distinct routing decisions can record repeated blocker steps while only one pending owner notification is created for the same blocker.

## External provider condition

During final acceptance both approved providers experienced real quota/rate pressure:

- Gemini: `rate_limited`;
- OpenAI: `quota_exhausted`.

This prevented the bounded research WorkItem from completing its underlying research objective during the acceptance window, but it does not invalidate Phase-4 routing acceptance. The router correctly preserved truth, moved the affected targets into bounded cooldown and placed the WorkItem into `WAITING_RESOURCE` rather than fabricating success.

## Accepted Phase-4 scope

Phase 4 now provides:

- provider/model-neutral routing models and registries;
- deterministic eligibility with privacy/locality/capability/credential/health filtering;
- durable routing decision, attempt, outcome and target-health persistence;
- `engineering_stage.v1` deterministic WorkStep-aware strategy;
- Gemini and OpenAI structured-output adapters;
- routed background WorkReasoner integration;
- JARVIS-owned bounded retry/fallback;
- target-local cooldown and health;
- truthful `WAITING_RESOURCE` behavior when approved targets are exhausted;
- owner-visible bounded routing status;
- offline replay/evaluation infrastructure;
- owner-machine acceptance evidence tooling;
- restart-safe route lineage;
- unchanged Authority/security/governance boundaries.

Realtime voice routing, local-model installation, learned production routing, Jev and autonomous routing-policy mutation remain deferred.

## Promotion decision

Phase 4 Research + Diagnostic Model Router is **DONE / OWNER-MACHINE ACCEPTED 2026-09-26**.

PR #118 is authorized for protected-main merge once the final documentation-only head is CI-green and comparison confirms the acceptance-tested implementation code is unchanged.

After merge, the next cross-cutting phase is:

**Phase 5 — Secure Autonomous Engineering Substrate.**
