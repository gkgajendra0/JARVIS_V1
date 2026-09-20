# Self-Repair Foundation Sequence Decision — 2026-09-20

## Status

**OWNER-APPROVED SEQUENCE CHANGE — DOCUMENTATION / PLANNING ONLY**

This record captures the decision to perform a bounded reliability cleanup and then pull a **Self-Repair Foundation interlude** forward before formal Step 8 implementation.

This does **not** mark Step 19 (CAP-046) complete, does not authorize autonomous self-modification, and does not change the numbered roadmap. Step 8 remains the next numbered product slice after the interlude.

## Why this sequence changes now

Protected `main` already contains the prerequisites that make a repair foundation useful rather than speculative:

- bounded whole-JARVIS Self-Awareness with deterministic health, dependencies, blast-radius reasoning, operational evidence, and engineering incident memory;
- persistent concurrent WorkItems/steps/deliveries with DBOS recovery and restart-safe state;
- isolated repository-development WorkItems using per-work Git worktrees;
- locked-down Docker pytest execution for model-edited code;
- canonical Authority and governed capability execution;
- a development supervisor with startup-readiness verification and last-known-good rollback for approved updates;
- protected-main repository rules requiring pull requests plus `ruff` and `pytest`.

As more product capabilities are added, the number of possible runtime failure modes and interactions increases. A bounded repair foundation now can become shared infrastructure for later roadmap work rather than being retrofitted after Steps 8–18.

## Required cleanup before Self-Repair implementation

Three current reliability issues directly affect the evidence, recovery, or delivery semantics that Self-Repair would depend on.

### 1. Issue #56 — Pocket 3 OWNER continuity

Correct the state semantics so transient face/head/liveness refresh gaps do not become false confirmed OWNER absence while an already-authorized visual/native continuity signal remains credible.

Why it blocks repair work:

- Self-Repair must consume trustworthy health/failure evidence.
- A false OWNER-loss signal must not cause repair or restart activity.
- Identity authorization and continuity evidence must remain separate.

### 2. Issue #57 — durable work notification TTS backoff

Respect provider retry delay or bounded exponential backoff when scripted TTS is rate-limited, while preserving pending WorkDelivery truth.

Why it blocks repair work:

- repair completion/failure notifications will reuse durable delivery;
- provider pressure must not create busy retry loops;
- successful later delivery must remain exactly-once at the canonical WorkDelivery layer.

### 3. Issue #50 — lifecycle/system speech resilience

Remove cloud TTS as a liveness dependency for fixed lifecycle/system speech. Evaluate reuse of the accepted local status-speech path before adding another speech subsystem.

Why it blocks repair work:

- runtime health/readiness must not be confused with TTS quota failure;
- the future outer supervisor must not enter restart loops because a greeting/acknowledgement could not synthesize;
- lifecycle transitions must remain independent from speech delivery success.

## Non-blocking residuals

The following remain valid but do not block the Self-Repair Foundation interlude:

- issue #44 — volume fast-path provider alias/relative semantics;
- issue #45 — false-interruption resume configuration vs output capability;
- issue #46 — intermittent LiveKit AudioMixer timeout investigation;
- issue #19 — production-grade conversation voice isolation / turn ownership;
- strict independent semantic-memory release and automatic conversational memory injection;
- full local/offline conversation and automatic provider failover.

They should remain separate tracks unless new evidence shows they undermine repair truth or runtime safety.

## Self-Repair Foundation interlude scope

After the cleanup issues close, the interlude begins research-first from the reconciled production baseline.

### Phase SR-1 — research, technology decision, and ADR

Define the repair contract before implementation:

- incident and diagnosis inputs;
- repair candidate and repair plan models;
- typed repair actions/effectors;
- repair risk/authority classes;
- retry budgets, cooldowns and escalation;
- verification and rollback semantics;
- crash/hang/readiness evidence;
- Docker sandbox threat model;
- immutable boundaries that repair cannot silently change.

### Phase SR-2 — outer runtime supervision

Evolve the existing development supervisor pattern into a process-external runtime supervision boundary with bounded:

- unexpected-exit detection;
- readiness/hang detection;
- restart budget and cooldown;
- crash fingerprinting;
- last-known-good handling;
- incident creation;
- rollback/escalation.

The supervisor must survive failure of the JARVIS runtime it supervises.

### Phase SR-3 — deterministic repair engine

Build a JARVIS-owned repair registry/policy/executor/verifier layer.

Known failures should map to deterministic, typed, reversible repair actions where possible. LLM reasoning must not be required for routine recovery.

### Phase SR-4 — accepted known repairs

Start with a deliberately small real set of failure modes already observed in JARVIS. Acceptance must inject or reproduce each failure, execute the bounded repair, verify recovery, and record the incident/outcome.

### Phase SR-5 — AI-assisted diagnostics

For unknown or ambiguous incidents:

- gather bounded/redacted evidence;
- create a DIAGNOSTICS WorkItem;
- allow the selected model to propose root-cause hypotheses and candidate repairs;
- keep policy/authority/verification deterministic and JARVIS-owned.

The model may diagnose; it does not authorize itself.

### Phase SR-6 — sandboxed source-code repair

Only after deterministic repair and verification are proven:

- create an isolated DEVELOPMENT WorkItem;
- use a per-incident Git worktree;
- generate a candidate patch;
- run targeted regression plus repository quality gates in the Docker sandbox;
- inspect final diff and produce a clean isolated commit;
- open a PR.

Initial Self-Repair must **not** automatically merge, push to protected main, deploy, weaken Authority, alter repository safety rules, or modify the repair evaluator itself.

## Explicitly out of scope

This interlude does not include:

- autonomous self-evolution;
- unrestricted code rewriting;
- automatic protected-main merge/deployment;
- self-expansion of permissions or Authority;
- autonomous modification of CI/rulesets/sandbox policy/evaluator policy;
- solving every deferred runtime issue;
- replacing DBOS, the existing WorkItem model, or the existing development worker with another agent framework.

## Step 8 relationship

Step 8 (CAP-027/CAP-028 Notes, Tasks, Reminders, Scheduling) remains the next numbered roadmap slice.

The intended sequence is:

```text
Persistent Concurrent Work Orchestration — accepted
-> reliability cleanup (#56 -> #57 -> #50)
-> Self-Repair Foundation interlude
-> Step 8 requirements/research
-> numbered roadmap continues
```

This follows the same foundation-first pattern already used for Self-Awareness and Persistent Concurrent Work Orchestration without renumbering the roadmap.

## Immediate action

Begin cleanup issue **#56** in its own branch/PR. Do not mix #57 or #50 into the same change unless evidence proves they share one inseparable root cause.
