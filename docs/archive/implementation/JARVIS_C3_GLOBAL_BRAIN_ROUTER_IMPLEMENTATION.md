# JARVIS C3 Global Brain Router v1 — Implementation

Status: **IMPLEMENTED / CI ACCEPTED**

Date: 2026-09-29

Research source: `JARVIS_C3_GLOBAL_BRAIN_ROUTER_RESEARCH.md`

## Purpose

C3 reduces unnecessary model spend by deciding whether a bounded JARVIS reasoning
cycle can be solved exactly from trusted state before invoking a model.

It does not execute tools and does not grant Authority. All actions still flow through
the existing governed Work/Hands/capability execution boundaries.

## Architecture

C3 is a thin intelligence-path policy around the existing Phase-4 ModelRouter.

```
canonical Work state
        |
        v
GlobalBrainRouteFacts
        |
        v
versioned deterministic resolver registry
        |
        +--> exact approved BrainDecision -> existing WorkEngine executor
        |
        +--> abstain/ambiguous
                 |
                 v
       existing RoutedWorkReasoner
                 |
                 v
       existing Phase-4 ModelRouter
       eligibility / strategy / health /
       bounded fallback / model invocation
```

The Phase-4 ModelRouter remains the only model-target selector.

## New runtime components

### `src/jarvis/brain_routing/models.py`

Provides:

- `GlobalBrainRouteFacts`;
- `BrainRouteKind`;
- `BrainRoutingMode`;
- `BrainRouteRecord`;
- projection from global facts into the existing Phase-4 `RoutingRequest`.

The global facts contract is subsystem-neutral. C3 production adoption begins with Work,
but a non-engineering acceptance fixture proves the same facts can enter the existing
ModelRouter.

### `src/jarvis/brain_routing/deterministic.py`

Provides the fail-closed, versioned deterministic resolver registry.

Initial accepted resolvers:

1. `work.development.initial_workspace.v1`
   - when development has not attempted workspace preparation;
   - selects only the already-allowed `dev_prepare_workspace` action.

2. `work.diagnostics.initial_incident.v1`
   - when diagnostics has not attempted canonical incident inspection;
   - selects only the already-allowed `diag_get_incident` action.

3. `work.development.post_test_diff.v1`
   - only after a completed source write;
   - the latest test is verified passing;
   - no later write invalidates that test;
   - no post-test diff has already been attempted;
   - selects only the already-allowed `dev_diff` action.

If more than one resolver matches, the registry abstains rather than choosing between
them.

### `src/jarvis/brain_routing/store.py`

Adds durable bounded route provenance to the canonical protected WorkStore.

Stored metadata includes:

- route request ID;
- Work scope;
- subsystem/task kind;
- deterministic/model route kind;
- rollout mode;
- policy version/digest;
- resolver ID/version;
- reason codes;
- selected action name;
- shadow proposal/match result;
- linked Phase-4 model decision/target IDs;
- timestamp/outcome code.

It does not store prompts, hidden reasoning, credentials or action parameters.

`summary_for_work()` exposes:

- route count;
- deterministic route count;
- model route count;
- model calls avoided;
- shadow matches;
- shadow mismatches.

This will be joined with C1 cost telemetry during the final TV capability experiment.

### `src/jarvis/brain_routing/work.py`

`GlobalBrainRouterReasoner` wraps the existing `RoutedWorkReasoner`.

It reads the full canonical WorkStep history for deterministic rules while preserving
the bounded recent-step context used by the model.

Replay behavior is fail-closed:

- an existing deterministic C3 route is replayed only when the resolver still proves
  the same action;
- a previously persisted Phase-4 model route pins the same reasoning cycle to the
  model path, even if C3 provenance had not yet been written before a process crash;
- conflicting durable deterministic/model provenance raises rather than silently
  changing route.

## Rollout modes

Machine setting:

`JARVIS_GLOBAL_BRAIN_ROUTER_MODE`

Allowed values:

- `off`
  - true rollback;
  - deterministic resolvers are not executed;
  - existing model reasoner handles the cycle.

- `shadow` **(production default)**
  - deterministic proposal is computed;
  - the current model path still decides;
  - match/mismatch is recorded;
  - no behavior change.

- `apply`
  - one unambiguous accepted deterministic match bypasses model invocation;
  - abstain/ambiguity uses the existing model route.

The mode is non-secret and can be persisted in the machine profile.

## Authority and governance invariants

C3 does not:

- execute a capability directly;
- add actions to `allowed_actions`;
- relax risk/Authority policy;
- bypass Work action admission;
- bypass EngineeringChange governance;
- bypass sandboxing;
- bypass completion verification;
- bypass promotion;
- alter realtime voice.

The deterministic decision is validated once inside C3 and again by the existing
`BrainCoordinator` allowance check.

## Acceptance evidence

The C3 test suite proves:

- apply mode can execute a real `WorkEngine.advance()` cycle with zero model-reasoner
  calls;
- the normal governed WorkStep is still created and executed;
- route provenance records one avoided model call;
- shadow mode preserves model behavior;
- shadow match and mismatch are recorded;
- ambiguous deterministic matches abstain to the model;
- an unapproved deterministic action is rejected;
- off mode does not execute deterministic resolvers;
- deterministic route replay remains stable;
- a pre-existing Phase-4 model decision pins retries to the model path;
- initial diagnostics and post-test diff rules behave deterministically only under
  their exact state conditions;
- a synthetic non-engineering memory route uses `GlobalBrainRouteFacts` and the same
  Phase-4 ModelRouter to select an accepted local target.

Repository acceptance on 2026-09-29:

- Ruff: PASS;
- full pytest: PASS;
- Windows Hello helper: PASS;
- Windows multilingual Hands regressions: PASS;
- Windows Phase-6 replay: PASS;
- Windows Phase-7 release/promotion + acceptance: PASS;
- Windows Phase-8 capability-registry + acceptance: PASS;
- Windows Phase-9 capability-acquisition replay: PASS;
- promotion policy: PASS.

## Production posture after C3

Default remains `shadow`.

This is intentional: the cost-optimization program will collect shadow evidence before
broad production apply-mode adoption. The deterministic apply path is already accepted
and can be enabled explicitly for controlled acceptance/experiments.

C3 does not yet introduce:

- Jev or another bounded decision model (C4);
- a production local LLM target (C5);
- retrieval/context compression (C6);
- real cheap/standard/strong cloud economics (C7);
- broad memory/Hands/voice routing adoption (C8).

## TV capability experiment linkage

For the eventual blind TV-control capability mission, C3 makes it possible to report:

- how many reasoning cycles were deterministic;
- how many model decision calls were avoided;
- how many cycles remained model-routed;
- shadow match/mismatch evidence where applicable.

Together with C1, the final mission report can distinguish:

- model-token cost;
- Exa/non-token provider cost;
- deterministic calls avoided;
- later local-model share;
- later cheap/strong-cloud share;
- retries/fallbacks;
- stage-level cost.

This allows the highest-cost stage to be identified from evidence rather than guessed.
