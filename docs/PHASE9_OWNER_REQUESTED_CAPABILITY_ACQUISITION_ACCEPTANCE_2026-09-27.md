# Phase 9 — Owner-Requested Capability Acquisition Acceptance

## Status

**DONE (BOUNDED) / OWNER ACCEPTED — 2026-09-28**

The owner explicitly accepted Phase 9 for roadmap progression after the software, governance, routing and durable-work behavior were validated on the owner machine.

The complete real external lifecycle was **not** executed end to end. That validation is deliberately deferred to the final whole-system acceptance run because the live Phase-9 acquisition was blocked by provider resource availability: Gemini repeatedly returned rate-limit pressure and the configured OpenAI fallback returned quota exhaustion.

This acceptance must therefore never be represented as proof that the full external capability lifecycle already completed. The deferred final-system run remains responsible for proving the external device effect, downstream engineering/promotion/package lifecycle, observation and disable/rollback path.

### 2026-09-30 follow-up

The provider-capacity blocker that stopped the original live external run is no longer
the primary constraint. PR #234 introduced owner-accepted ChatGPT-plan reasoning and the
owner-machine acceptance proved live `gpt-6-astra` plan-backed inference with
`work.chatgpt_plan.default` as the durable Work primary. The deferred external lifecycle
therefore moves from "blocked by provider resources" to **active validation target**.

The next live mission should exercise a generic Hisense-TV capability through a natural
owner goal (for example: "I want to watch Transporter") and must still collect every
deferred lifecycle item below. Nothing in the 2026-09-30 provider acceptance itself
constitutes proof of TV control, app launch, media search, playback, observation, or
rollback.


## Accepted software baseline

- Phase-9 9A–9F implementation plus 9G deterministic evaluation/acceptance substrate were merged through PR #178;
- PR #178 protected-main squash merge: `e73db07abad7ab0e73ee2f0030ff6e58e9f3ee76`;
- target-aware acquisition-routing hardening was completed in PR #180 after the first live TV request exposed cross-target existing-capability reuse;
- PR #180 exact reviewed head: `0b2a7b6058485e158964194cc6b59134acfdef65`;
- PR #180 protected-main squash merge / accepted Phase-9 software baseline: `15974c4089aeea014dc68f4a6fb385072278b379`;
- the final PR #180 CI run passed Ruff, Linux pytest, Windows Hello, Windows DPAPI/unified Windows regression, Phase-7/8/9 regression/acceptance coverage and the promotion-policy gate.

## Owner-machine evidence obtained

The owner-machine run established the following bounded acceptance evidence:

1. the fixed protected-main release `15974c4089aeea014dc68f4a6fb385072278b379` started successfully in production;
2. the previous accepted release remained preserved as rollback / Last Known Good during the routing-fix validation;
3. the natural-language request to acquire Hisense-TV mute/unmute control no longer collapsed into a superficially similar existing local operation;
4. JARVIS admitted the request into the canonical Phase-9 process as EngineeringChange `change_ac029f8cad1945f9` with process `owner_capability_acquisition`;
5. durable acquisition WorkItem `work_acc8c88809ee4837` was created for the exact request: “Required capability to mute and unmute my Hisense TV over the local network.”;
6. the work survived provider pressure rather than disappearing or falsely completing;
7. the work transitioned through `waiting_resource` and later returned to `running / reasoning`;
8. the model router preserved deterministic two-target routing and attempted the approved fallback path;
9. Gemini attempts were recorded as `rate_limited`;
10. OpenAI fallback attempts were recorded as `quota_exhausted`;
11. routing-target health/cooldown and durable retry behavior continued without weakening Authority, sandbox, source-trust, promotion or package-lifecycle controls;
12. a separate stale research WorkItem that requested owner input was correctly identified as unrelated to the TV acquisition and did not alter the Phase-9 work item.

## Why the end-to-end external run stopped

Both approved cloud reasoning targets had credentials available, but neither had usable execution capacity during the acceptance window:

- Gemini was available through the owner's free tier but repeatedly returned rate-limit pressure;
- OpenAI was configured as the bounded fallback, but the API account had no usable quota/balance and returned `quota_exhausted`.

The router therefore behaved as designed: it attempted the primary, attempted the approved fallback when eligible, placed target-local health into cooldown when appropriate, persisted the work and retried rather than inventing an unapproved provider or bypassing governance.

The owner explicitly chose **not** to purchase additional provider quota solely to force this acceptance run to completion.

## Deferred final-system end-to-end validation

The following Phase-9 lifecycle evidence remains **unproven by the 2026-09-28 live run** and is deferred to final whole-system acceptance:

1. real source discovery/research completes for the external target;
2. exact acquisition architecture is produced and owner-approved;
3. isolated implementation completes without manual owner coding/debugging;
4. dependency, secret, provenance and sandbox controls pass on the real candidate;
5. automated verification passes;
6. exact Phase-7 governed promotion and production deployment complete;
7. exact Phase-8 package admission completes without auto-enable;
8. explicit owner activation makes the new package effectively enabled;
9. a genuine Hisense-TV mute/unmute operation produces an observed physical external effect;
10. production observation is recorded;
11. explicit disable/rollback restores the safe state;
12. active release SHA equals the tested acceptance checkout SHA for the final run;
13. the final Phase-9 replay/evidence harness passes against the completed lifecycle;
14. protected repository state remains unchanged by the acceptance harness;
15. the final package identity/digest, promotion attempt, lifecycle evidence, observation reference, rollback reference and acceptance-evidence digest are captured.

These are not waived. They are moved to the final integrated-system validation so the complete JARVIS stack can be exercised once with usable provider resources.

## Accepted behavior

The protected-main Phase-9 path now provides:

1. canonical owner-goal admission grounded to the latest accepted owner turn;
2. target-aware existing-capability/package reuse rather than operation-name-only reuse;
3. exact trusted source-revision binding;
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
20. rollback/disable evidence required for a completed external lifecycle.

## Security invariants preserved

- owner intent is not unrestricted Authority;
- no model-assigned source trust;
- no arbitrary shell/install surface;
- no plaintext credential in package or machine configuration;
- GitHub App private key remains DPAPI-sealed in SecretStore;
- live GitHub App token remains repository-scoped and short-lived;
- protected-main source promotion remains Phase 7;
- capability lifecycle remains Phase 8;
- durable work remains WorkItem/DBOS;
- governed engineering truth remains EngineeringChange;
- registration/admission never auto-enables a new capability;
- provider exhaustion does not authorize an unapproved provider or a governance bypass.

## Acceptance decision

The owner's 2026-09-28 sequencing decision is:

- accept Phase 9 as **DONE (BOUNDED) / OWNER ACCEPTED**;
- do not spend money merely to complete this intermediate acceptance run;
- preserve the incomplete external lifecycle as an explicit deferred validation item;
- perform the complete Phase-9 end-to-end external validation during final whole-system acceptance after the end-to-end JARVIS system is created;
- allow the autonomous-engineering program to proceed to Phase 10 without claiming that the deferred physical/external lifecycle has already been proven.

This record is the canonical source for that bounded acceptance decision.
