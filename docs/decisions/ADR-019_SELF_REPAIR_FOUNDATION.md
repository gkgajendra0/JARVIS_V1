# ADR-019 — Self-Repair Foundation Control Loop and External Supervision

## Status

**OWNER-APPROVED ARCHITECTURE — REFINED 2026-09-23; IMPLEMENTATION MAY BEGIN**

Date: 2026-09-20
Refined: 2026-09-23

Related:
- issue #65
- `docs/research/SELF_REPAIR_SEQUENCE_DECISION_2026-09-20.md`
- `docs/research/SELF_REPAIR_FOUNDATION_RESEARCH_2026-09-20.md`

This ADR defines the first bounded Self-Repair Foundation interlude. It does not complete roadmap Step 19 / CAP-046.

## Context

JARVIS now has deterministic self-awareness, operational evidence, durable incidents, persistent work orchestration, isolated development worktrees, sandboxed tests, canonical Authority and an external development supervisor.

The existing supervisor deliberately stops when the child runtime exits unexpectedly. That was correct before a repair contract existed, but it leaves no bounded path for automatic recovery from a simple runtime crash or hang.

At the same time, recent provider-quota incidents prove why restart behavior cannot be tied to generic "something failed" signals. Gemini/Exa/TTS failure can leave the JARVIS process healthy and must not create a restart loop.

## Decision

### 1. Adopt one deterministic repair control loop

JARVIS will use a bounded Monitor -> Analyze -> Plan -> Execute -> Verify loop.

Canonical health/evidence remains JARVIS-owned. LLM output cannot directly set health, select unrestricted effectors, authorize repairs or declare recovery.

### 2. Keep runtime supervision process-external

The `jarvis-dev` parent remains the process-external boundary for child-runtime recovery.

The parent will be extended rather than introducing a second supervisor framework.

The parent owns:
- unexpected child-exit detection;
- startup readiness;
- runtime liveness/watchdog state;
- restart budgets/cooldowns;
- same-version restart;
- crash-loop exhaustion;
- supervisor-side incident signals.

The child owns ordinary subsystem health and evidence while it is alive.

### 3. Separate startup, liveness and dependency readiness

A child may be:
- started but not ready;
- ready and live;
- live but dependency-degraded;
- unresponsive/hung;
- exited.

Only startup/liveness failure is eligible for process restart.

External dependency failures such as provider quota, search credentials, TTS quota or optional sensor degradation do not by themselves authorize process restart.

### 4. Use a version-controlled RepairPolicy registry

Every automatic repair requires a registered policy with:
- trigger matcher;
- deterministic preconditions;
- typed action;
- risk class;
- attempt/restart budget;
- cooldown;
- verifier;
- escalation behavior.

Unknown incidents have no implicit repair.

### 5. Initial effectors are deliberately small

Initial typed actions:
- `RETRY_OPERATION`;
- `RECONNECT_SUBSYSTEM`;
- `RESTART_RUNTIME_CHILD`;
- `NO_ACTION_ESCALATE`.

No arbitrary shell or free-form model-generated command is an effector.

### 6. Initial automatic authority stops at bounded R1/R2

Risk classes:

- R0 observe only;
- R1 bounded reversible retry/reconnect;
- R2 bounded restart/recreate;
- R3 persistent runtime/config mutation;
- R4 source repair proposal;
- R5 protected/security/authority mutation.

Only explicitly registered R1/R2 policies are eligible for automatic execution in the initial foundation.

R3+ requires later architecture/authority decisions.

### 7. Verification is mandatory

An action completing without exception is not recovery.

Each policy defines a verifier of the original failed property. Failed or inconclusive verification keeps the incident unresolved and consumes/advances policy budget according to deterministic rules.

### 8. Crash/restart budget is owned by the supervisor

The supervisor is the only owner of runtime-child restart attempts.

Budget semantics must include:
- bounded attempts;
- rolling window;
- cooldown/backoff;
- deterministic fingerprint/correlation;
- stabilization criterion before budget reset;
- fail-closed exhaustion.

Nested components must not create a second runtime-restart loop.

### 9. Preserve the existing update rollback path

Owner-approved fast-forward update + readiness + last-known-good rollback remains unchanged.

Ordinary runtime crash recovery initially restarts the same local revision. It does not automatically reset source to an older commit.

### 10. Reuse the incident store

Repair attempts link to the existing engineering incident model and operational evidence.

Do not create a separate AI-memory database for repair truth.

### 11. LLM diagnostics are a later layer

For unknown/ambiguous incidents, a later phase may create a DIAGNOSTICS WorkItem with bounded/redacted evidence.

The model may propose:
- hypotheses;
- evidence to inspect;
- candidate repair policies;
- source patch candidates.

It does not grant authority or execute an unregistered repair.

### 12. Add staged RepairKnowledge inspired by mature agent skill systems

Successful verified repairs may generate reusable **RepairKnowledge** playbooks, but learned knowledge is never executable authority by itself.

RepairKnowledge lifecycle:

- `CANDIDATE` — extracted from an incident/repair or synthetic curriculum;
- `STAGED` — ready for replay/fault-injection validation;
- `ACCEPTED` — approved reusable diagnostic/playbook knowledge;
- `REJECTED` — failed validation/review;
- `RETIRED` — superseded or no longer safe.

Promotion from RepairKnowledge to an automatic RepairPolicy requires a version-controlled policy change and the normal repository/owner governance path.

This adopts the useful staged-write concept seen in Hermes Agent without importing Hermes as a second JARVIS runtime.

### 13. Add a provider-neutral DiagnosticModelRouter

AI diagnostics are replaceable consumers of bounded evidence.

The router may select/escalate among local models, Gemini, OpenAI, NVIDIA/NIM, Ornith or later models using:

- task/stage;
- required capability;
- privacy/locality;
- latency/cost;
- provider health;
- prior confidence/result.

Provider fallback affects reasoning availability only. It cannot widen repair authority or skip verification.

The first implementation should define the interface and policy boundary; it does not need NeMo Switchyard as a hard runtime dependency. NeMo Switchyard is a valid future router implementation because its model-routing design separates routing logic from model endpoints.

### 14. Add a sandbox-only Repair Curriculum after deterministic recovery is accepted

Borrow the self-generated-task principle demonstrated by Ornith and the synthetic-data/verifiable-reward pattern demonstrated by NVIDIA Nemotron/NeMo.

Accepted incidents may seed bounded synthetic fault variants. Candidate diagnostic/repair workers may attempt those scenarios only in an isolated environment with deterministic verifiers.

Successful trajectories can improve RepairKnowledge or future specialist models. They cannot directly create production RepairPolicies or modify protected safety surfaces.

### 15. Source repair remains isolated and review-gated

Later source repair reuses DEVELOPMENT WorkItems, isolated worktrees and locked-down Docker tests.

Initial flow ends at a candidate commit/PR for owner review.

Automatic protected-main merge/deploy, Authority changes, CI/ruleset changes, sandbox weakening and permission expansion remain forbidden.

## Consequences

### Benefits

- simple runtime crashes can recover without depending on the failed child;
- provider outages do not become restart storms;
- every automatic action is typed, budgeted and verifiable;
- incident history becomes useful engineering knowledge;
- later AI diagnosis can be added without putting the model in the authority path;
- current GitHub/update safety remains intact.

### Costs

- supervisor protocol/state becomes more complex;
- liveness must be carefully designed to avoid false positives;
- restart budgets and stabilization semantics need fault-injection testing;
- some failures will deliberately escalate instead of being auto-fixed;
- source-code self-repair remains a later phase.

## Technology disposition

- **Hermes Agent:** do not embed as JARVIS runtime; adopt staged learned-playbook, capability-requirement and diagnostic-provider-fallback patterns.
- **Ornith:** do not depend on it for production recovery; later benchmark as a DIAGNOSTICS/DEVELOPMENT worker and adopt its self-generated curriculum concept.
- **NVIDIA Nemotron / NeMo:** keep models optional/replaceable; adopt model-routing and synthetic-data/verifiable-reward patterns. NeMo Switchyard remains an optional future router implementation.
- **JARVIS deterministic core:** remains canonical for health, incidents, RepairPolicy, Authority, budgets, execution and verification.

## Initial acceptance gates

Implementation may be production-accepted only after proving:

1. one unexpected child exit causes at most the registered bounded restart;
2. successful restart requires readiness/liveness verification;
3. repeated identical crashes exhaust budget and stop;
4. provider quota failure does not restart the runtime;
5. existing approved-update rollback remains unchanged;
6. incidents contain bounded evidence + repair-attempt outcome;
7. unregistered reason codes cannot execute effectors;
8. repository Ruff/pytest + Windows gates pass;
9. owner-machine fault-injection acceptance passes;
10. learned RepairKnowledge cannot execute until separately promoted to a registered policy;
11. DiagnosticModelRouter failure cannot block deterministic R1/R2 repair;
12. synthetic curriculum execution remains sandbox-only and cannot mutate protected safety surfaces.

## Non-goals

- full Step 19 completion;
- autonomous source editing;
- autonomous protected-main merge/deployment;
- automatic Authority/permission expansion;
- universal repair of every subsystem;
- replacing DBOS/WorkItems;
- replacing the existing development supervisor.

## Reconsider when

Revisit this ADR after deterministic R1/R2 repairs are production-accepted, when introducing AI-assisted diagnostics/R4 source-repair proposals, or when a local specialist model/router has enough JARVIS-specific benchmark evidence to justify becoming a preferred diagnostic target.

## Reference technologies

- Hermes skills/write approval: https://hermes-agent.nousresearch.com/docs/user-guide/features/skills
- Hermes fallback providers: https://hermes-agent.nousresearch.com/docs/user-guide/features/fallback-providers/
- Ornith 1.5 self-improvement loop: https://ornith.ai/ornith_1_5.html
- NVIDIA Nemotron: https://developer.nvidia.com/topics/ai/nemotron
- NeMo Switchyard routing: https://developer.nvidia.com/blog/route-ai-agent-workloads-across-models-with-nvidia-nemo-switchyard
- NVIDIA synthetic data + RL with verifiable rewards: https://developer.nvidia.com/blog/how-to-train-an-ai-agent-for-command-line-tasks-with-synthetic-data-and-reinforcement-learning/
