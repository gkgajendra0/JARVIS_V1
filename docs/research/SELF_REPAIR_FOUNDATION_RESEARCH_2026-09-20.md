# Self-Repair Foundation Research — 2026-09-20

## Status

**OWNER-APPROVED RESEARCH DIRECTION — REFINED WITH HERMES / ORNITH / NEMOTRON PATTERNS**

This document begins the bounded Self-Repair Foundation interlude approved in `SELF_REPAIR_SEQUENCE_DECISION_2026-09-20.md`.

It does not complete roadmap Step 19 / CAP-046 and does not authorize autonomous self-modification.

## Research question

What is the smallest JARVIS-owned repair architecture that can safely recover from known runtime failures without turning transient dependency failures, model guesses, or repeated crashes into destructive restart loops?

## Production baseline now available

The reliability prerequisites are present on protected `main`:

- Self Model + deterministic Health Registry;
- bounded operational evidence and redaction;
- durable engineering incidents;
- persistent WorkItems/DBOS;
- isolated DEVELOPMENT worktrees;
- locked-down Docker pytest for model-edited code;
- canonical Authority;
- `jarvis-dev` as an external parent process with authenticated child readiness;
- last-known-good rollback for owner-approved updates;
- protected-main PR + CI gates;
- Pocket OWNER continuity cleanup (#56);
- durable WorkDelivery provider-backoff cleanup (#57);
- lifecycle speech resilience (#50).

The main architectural gap is that `jarvis-dev` deliberately exits when the runtime child exits unexpectedly. It does not yet own a bounded crash/hang recovery policy.

## External architecture patterns

### MAPE-K control loop

IBM autonomic-computing work separates Monitor, Analyze, Plan and Execute around shared Knowledge. That separation is valuable for JARVIS because evidence collection must not itself authorize mutation.

JARVIS mapping:

- **Monitor:** Self Model, Health Registry, process state, operational evidence.
- **Analyze:** deterministic incident classifier first; AI diagnostics only later.
- **Plan:** typed repair policy selected from a registry.
- **Execute:** bounded repair effector.
- **Knowledge:** incident history, health model, repair-attempt history, accepted fixes.

Reference:
- https://dominoweb.draco.res.ibm.com/reports/h-0219.pdf

### Startup, readiness and liveness are different

Kubernetes distinguishes startup, readiness and liveness and warns that bad liveness checks can cause cascading failures.

JARVIS must therefore distinguish:

1. **startup readiness** — child has initialized enough to be considered a usable runtime;
2. **liveness** — the process is alive and making required control-loop progress;
3. **service readiness/degradation** — some dependencies may be unavailable while JARVIS itself remains alive.

A Gemini/Exa/TTS quota failure is dependency degradation. It is not proof that the JARVIS process should restart.

Reference:
- https://kubernetes.io/docs/concepts/workloads/pods/probes/

### Retry ownership and crash-loop protection

AWS reliability guidance recommends bounding retries, avoiding retry multiplication across layers, applying backoff, and making retryable actions idempotent.

JARVIS already applied this lesson to WorkDelivery in #57. The same rule should govern repair: one deterministic layer owns retry/restart policy.

References:
- https://docs.aws.amazon.com/wellarchitected/2023-04-10/framework/rel_mitigate_interaction_failure_limit_retries.html
- https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/

### External watchdog boundary

Mature service managers keep watchdog/restart logic outside the managed process. This matters because an in-process repair loop cannot recover if that process is dead or wedged.

JARVIS already has the correct process shape: `jarvis-dev` parent + production child. The Self-Repair Foundation should evolve that boundary instead of adding a second supervisor framework.

## Proposed canonical repair flow

```text
health/process/evidence signal
          |
          v
      DETECT incident
          |
          v
  deterministic CLASSIFY
          |
          +---- unknown / ambiguous ----> diagnostics WorkItem later
          |
          v
   lookup registered policy
          |
          v
  AUTHORITY + budget check
          |
          v
       EXECUTE
          |
          v
       VERIFY
       /    \
 recovered  failed
    |         |
 record       retry only if policy budget allows
 incident     otherwise escalate/cooldown
```

## Core data contracts

### RepairTrigger

A normalized immutable signal that enters the repair system.

Proposed fields:

- `trigger_id`
- `component_id`
- `reason_code`
- `source`
- `observed_at`
- `health_state`
- `process_exit_code` when applicable
- bounded evidence references
- correlation/session/work identifiers

A RepairTrigger never carries authority by itself.

### RepairPolicy

Static/version-controlled policy for one known repairable condition.

Proposed fields:

- `policy_id`
- matching component/reason codes;
- allowed action kind;
- risk class;
- preconditions;
- per-incident attempt limit;
- rolling-window budget;
- cooldown/backoff;
- verification contract;
- escalation behavior;
- idempotency/reversibility declaration.

No free-form shell is a repair action.

### RepairAction

Typed effectors only.

Initial action vocabulary should stay intentionally small:

- `RETRY_OPERATION`
- `RECONNECT_SUBSYSTEM`
- `RESTART_RUNTIME_CHILD`
- `NO_ACTION_ESCALATE`

Later, after acceptance, additional bounded actions may include subsystem recreation or configuration repair.

Source-code repair is not part of this initial executor.

### RepairAttempt

Durable record for each execution:

- action;
- policy;
- incident;
- started/finished timestamps;
- pre-state evidence;
- execution outcome;
- post-verification evidence;
- final verdict;
- cooldown/next eligibility.

### RepairVerdict

The executor cannot declare itself fixed merely because an action returned successfully.

The verifier returns one of:

- `RECOVERED`
- `NOT_RECOVERED`
- `INCONCLUSIVE`
- `ESCALATED`

Only `RECOVERED` closes the automated recovery loop.

## Proposed risk boundary

### R0 — observe only

Examples:
- health/evidence reads;
- incident creation;
- crash fingerprint creation.

May be automatic.

### R1 — bounded reversible operation

Examples:
- reconnect transport;
- retry one idempotent operation;
- rebuild one ephemeral session.

May be automatic only for explicitly registered policies with deterministic verification and budget.

### R2 — bounded process/subsystem restart

Examples:
- restart the JARVIS runtime child after an unexpected process exit;
- restart a specifically restart-safe subsystem.

May be automatic only under a strict restart budget and must be controlled by an independent parent/supervisor when the runtime child itself is affected.

### R3 — runtime/config mutation

Examples:
- changing persistent configuration;
- editing environment/settings.

Not automatically authorized in the initial foundation.

### R4 — source repair candidate

Create isolated DEVELOPMENT WorkItem/worktree, candidate patch, sandbox tests, diff and local commit/PR proposal.

No automatic protected-main merge or deployment.

### R5 — protected/security/authority mutation

Examples:
- Authority policy;
- CI/rulesets;
- sandbox policy;
- secrets/credentials;
- permission expansion.

Never automatically repaired by the initial Self-Repair system.

## Outer supervisor design

### Preserve current update semantics

The existing owner-approved update path already:

- requires explicit owner approval;
- applies fast-forward updates;
- starts the new child;
- waits for authenticated startup readiness;
- rolls back to the previous SHA if the updated child fails readiness.

Self-Repair must not weaken this.

### Add same-version runtime recovery

For an unexpected child exit:

1. create or correlate an incident;
2. compute a deterministic crash fingerprint;
3. check restart budget;
4. if allowed, wait the configured cooldown;
5. restart the same local revision;
6. require startup readiness;
7. observe liveness for a stabilization period;
8. record verification;
9. if the same failure repeats past budget, stop restarting and escalate.

The first implementation should not automatically `git reset` to an older source revision for ordinary runtime crashes. Source rollback remains tied to the existing owner-approved update path until a separate policy is explicitly accepted.

### Add liveness without confusing dependency health

The child-parent control channel can be extended with a cheap heartbeat or liveness signal.

A liveness signal should prove only that the runtime control loop is alive, not that Gemini, Exa, TTS, camera, or every optional subsystem is healthy.

Dependency failures continue through Health Registry / provider resilience and may create incidents without triggering a process restart.

### Crash fingerprint

A useful bounded fingerprint can be built from:

- child exit code / signal;
- startup vs running phase;
- final deterministic reason code if available;
- bounded recent redacted evidence IDs;
- affected component IDs;
- local commit SHA.

Avoid raw provider payloads, prompts, audio/video or secret-bearing data.

## Restart budget requirements

The budget must be configurable and deterministic.

Required properties:

- maximum attempts per incident/fingerprint;
- rolling time window;
- cooldown/backoff;
- reset only after an explicit stabilization criterion;
- no nested restart owner;
- budget state survives long enough to prevent immediate crash loops;
- exhaustion creates/escalates an incident and stops automatic restart.

Exact default timings should be selected during implementation/testing rather than hidden in model prompts.

## Deterministic repair registry

A registry entry should pair:

```text
(trigger matcher)
+ precondition evaluator
+ authority/risk classification
+ action factory
+ budget
+ verifier
+ escalation rule
```

Unknown reason codes do not fall through to an LLM-generated command. They create/augment an incident and later may launch a bounded DIAGNOSTICS WorkItem.

## Verification principles

Verification must test the original failed property.

Examples:

- process restart -> authenticated child readiness + liveness stabilization;
- reconnect -> fresh transport/evidence, not cached `connected=True`;
- provider recovery -> successful bounded provider probe or canonical provider-health transition;
- WorkDelivery repair -> durable state transition and no duplicate delivery;
- source repair later -> targeted regression + repository quality gates + final diff.

## Incident integration

The current incident model already supports:

- affected components;
- evidence references;
- root cause;
- accepted fix;
- regression tests;
- commit/PR;
- deployment and rollback fields;
- lessons.

The repair foundation should extend incident history by linking RepairAttempts rather than create a second incident database.

## Work orchestration integration

Use WorkItems only where durable background reasoning/work is actually useful.

Initial deterministic R1/R2 repairs should not require a WorkItem or provider brain.

Later:

- unknown incident -> DIAGNOSTICS WorkItem;
- source-code candidate -> DEVELOPMENT WorkItem;
- notification -> existing durable WorkDelivery.

This preserves foreground voice priority and restart recovery without making the model a dependency for basic recovery.

## Source-code repair boundary

Source repair comes only after deterministic runtime repair is accepted.

Required flow:

```text
incident
-> diagnostics evidence
-> DEVELOPMENT WorkItem
-> isolated worktree
-> model proposes bounded patch
-> Docker targeted pytest
-> repository ruff/pytest gates
-> inspect diff
-> local commit / PR
-> OWNER review/approval
-> protected-main merge
-> jarvis-dev update readiness
-> keep or existing rollback
```

Forbidden:

- direct edit of protected main;
- automatic merge;
- automatic permission expansion;
- automatic modification of repair evaluator/Authority/CI/sandbox;
- disabling failing tests to make a repair pass.

## Recommended implementation order

1. Repair models and registry with no effectors.
2. Incident-linked RepairAttempt persistence.
3. Supervisor crash fingerprint + restart budget state.
4. Bounded same-version child restart.
5. Startup/liveness verifier.
6. Fault-injection tests for one crash and repeated crash-loop exhaustion.
7. Deterministic subsystem repair registry.
8. Owner-machine acceptance.
9. Only then AI-assisted diagnostics.
10. Only then sandboxed source repair proposal.

## Acceptance scenarios

### A. One unexpected child exit

Expected:
- incident created;
- registered supervisor policy selected;
- one restart within budget;
- readiness/liveness pass;
- attempt marked recovered.

### B. Repeated identical child crash

Expected:
- same fingerprint correlated;
- bounded retries only;
- cooldown observed;
- budget exhausts;
- no further automatic restart;
- incident escalated for owner attention.

### C. Gemini/Exa/TTS quota failure

Expected:
- provider health may degrade;
- incident/evidence may be recorded;
- runtime child remains running;
- supervisor does not restart JARVIS solely because a cloud dependency is unavailable.

### D. Failed approved update startup

Expected:
- existing last-known-good rollback path remains authoritative;
- Self-Repair does not duplicate or bypass it.

### E. Unknown incident

Expected:
- no guessed repair action;
- incident remains open;
- diagnostics WorkItem may be created in the later AI-diagnostics phase.

## Technology reconnaissance — Hermes, Ornith and NVIDIA Nemotron

These technologies are not interchangeable. They contribute at different layers and should be adopted selectively rather than replacing JARVIS-owned truth, Authority, WorkItems or the external supervisor.

### Hermes Agent — adopt patterns, not the runtime

Hermes is a full agent runtime with useful production patterns for JARVIS:

- staged/approval-gated skill writes;
- capability-aware reusable skills;
- provider fallback chains that preserve the active session;
- independent fallback resolution for auxiliary tasks.

JARVIS should **not** embed Hermes as a second orchestration runtime because JARVIS already owns durable WorkItems/DBOS, memory, tools, incidents, Authority and provider resilience.

Adopt these Hermes-inspired patterns instead:

1. **Repair Knowledge / Playbooks** — a successful verified repair may produce a reusable candidate playbook.
2. **Staged writes** — learned playbooks never become executable policy immediately. They enter a staged state for deterministic validation and owner/governance approval.
3. **Capability requirements** — a playbook declares the exact tools/resources/configuration it requires and remains unavailable when those prerequisites are absent.
4. **Diagnostic-provider fallback** — AI diagnostics may use an ordered provider/model fallback chain without changing repair authority.

Official references:
- https://hermes-agent.nousresearch.com/docs/user-guide/features/skills
- https://hermes-agent.nousresearch.com/docs/user-guide/features/fallback-providers/
- https://hermes-agent.nousresearch.com/docs/user-guide/configuration

### Ornith 1.5 — adopt the self-generated repair curriculum later

Ornith 1.5 extends self-scaffolding into a self-improvement loop where the model proposes tasks, generates task-specific scaffolds and produces solution rollouts for reinforcement learning.

JARVIS should not depend on Ornith for runtime recovery. Its strongest contribution is the **learning loop** after deterministic repair is proven:

```text
verified real incident
-> generate bounded synthetic variants
-> run candidate diagnosis/repair in sandbox
-> verifier scores outcome
-> retain successful trajectories
-> propose improved diagnostic/playbook knowledge
```

This becomes a future **Repair Curriculum**. Generated scenarios cannot directly create production RepairPolicies.

A local Ornith model may later be benchmarked as one candidate DIAGNOSTICS/DEVELOPMENT worker. Model choice remains replaceable and is never hardwired into repair authority.

Official reference:
- https://ornith.ai/ornith_1_5.html

### NVIDIA Nemotron / NeMo — adopt model routing and verifiable training patterns

Nemotron contributes two especially relevant patterns:

1. **Model-neutral routing.** NeMo Switchyard separates routing policy from provider/model endpoints and supports stage/escalation routing. JARVIS should use the same architectural separation for diagnostics: route simple classification or summarization to a cheaper/local specialist and escalate difficult diagnosis/code repair to a stronger model only when required.
2. **Synthetic data + verifiable rewards.** NVIDIA demonstrates agent specialization using synthetic task generation and reinforcement learning with deterministic reward/verifier boundaries. This aligns with the future Repair Curriculum: a model may learn from generated fault scenarios only when an independent verifier can score the result.

JARVIS does not need to make NeMo Switchyard itself a hard dependency in the first implementation. The durable semantic requirement is a **provider-neutral DiagnosticModelRouter** whose policy can later use Switchyard or another router implementation.

Official references:
- https://developer.nvidia.com/topics/ai/nemotron
- https://developer.nvidia.com/blog/route-ai-agent-workloads-across-models-with-nvidia-nemo-switchyard
- https://developer.nvidia.com/blog/how-to-train-an-ai-agent-for-command-line-tasks-with-synthetic-data-and-reinforcement-learning/

## Refined architecture — two bounded loops

### Loop A — Production Repair Loop

This is the only loop allowed to mutate live runtime state automatically.

```text
DETECT
-> deterministic CLASSIFY
-> registered RepairPolicy
-> Authority + budget
-> typed EXECUTE
-> deterministic VERIFY
-> recovered or escalate
```

It must work without any LLM.

### Loop B — Repair Learning Loop

This loop improves future diagnosis and repair knowledge but cannot directly modify production repair policy.

```text
resolved incident / successful repair
-> extract candidate RepairKnowledge
-> STAGE
-> replay/fault-injection verification
-> review / policy validation
-> ACCEPT as playbook knowledge
-> optional later promotion into a version-controlled RepairPolicy
```

Unknown incidents may also generate synthetic variants for sandbox training/evaluation. The output remains candidate knowledge until independently verified.

## New canonical contracts

### RepairKnowledge

A reusable engineering playbook learned from real or synthetic evidence.

Required fields should include:

- `knowledge_id`
- `component_scope`
- `trigger_signature`
- evidence provenance;
- diagnosis summary;
- successful repair/action sequence;
- verification contract;
- required capabilities/resources;
- source incident IDs;
- confidence/evidence grade;
- lifecycle state: `CANDIDATE`, `STAGED`, `ACCEPTED`, `REJECTED`, `RETIRED`;
- version and supersession lineage.

RepairKnowledge is **not executable authority**. Only a version-controlled RepairPolicy can authorize an automatic repair.

### DiagnosticModelRouter

A model-neutral diagnostic routing boundary.

Inputs:

- task kind;
- risk class;
- required capabilities;
- privacy/locality constraints;
- latency/cost budget;
- model/provider health;
- prior attempt result/confidence.

Possible targets may include local models, Gemini, OpenAI, Nemotron/NIM, Ornith or future models.

Routing affects only reasoning quality/cost/availability. It never changes the RepairPolicy, Authority decision or verifier.

### RepairCurriculumCase

A sandbox-only fault scenario used to improve or evaluate diagnostic/repair workers.

It records:

- originating incident or synthetic parent;
- injected fault;
- expected evidence;
- allowed action space;
- success verifier;
- forbidden mutations;
- model trajectory;
- score/reward;
- reproducibility metadata.

No curriculum case may target protected-main mutation or weaken Authority/CI/sandbox policy.

## Updated implementation order

1. Repair models and deterministic registry with no free-form effectors.
2. Incident-linked RepairAttempt persistence.
3. Supervisor crash fingerprint + restart budget state.
4. Bounded same-version child restart.
5. Startup/liveness verifier.
6. Fault-injection tests for one crash and repeated crash-loop exhaustion.
7. Deterministic subsystem repair registry.
8. **RepairKnowledge store + CANDIDATE/STAGED/ACCEPTED lifecycle.**
9. **DiagnosticModelRouter interface with provider-neutral routing and explicit fallback/escalation.**
10. Owner-machine acceptance of deterministic R1/R2 recovery.
11. AI-assisted DIAGNOSTICS WorkItems using the router.
12. Sandboxed source-repair proposals.
13. **Repair Curriculum generation from accepted incidents with deterministic sandbox verifiers.**
14. Only after enough verified data exists, evaluate local/fine-tuned repair specialists such as Ornith or Nemotron-family models.

## Decision from research

The correct next implementation is **not** autonomous source editing.

The strongest Self-Repair architecture for JARVIS is:

1. one JARVIS-owned deterministic production repair contract;
2. one process-external restart owner;
3. strict retry/restart budgets;
4. verification before recovery is declared;
5. incident persistence;
6. no model in the authority path;
7. Hermes-inspired staged RepairKnowledge/playbooks;
8. provider-neutral diagnostic model routing with fallback/escalation;
9. Ornith/Nemotron-inspired synthetic fault curriculum with verifiable rewards;
10. replaceable models — no single model/framework becomes canonical repair truth.

That foundation can safely support later diagnostics and source-code repair without making JARVIS dependent on a model to recover from its first failure.
