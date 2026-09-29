# JARVIS C6 Retrieval / Context Optimization Research

Status: **RESEARCH COMPLETE / ARCHITECTURE APPROVED BY CONTINUATION SCOPE / SHADOW IMPLEMENTATION ACTIVE**

Date: 2026-09-29

## Objective

Reduce model context cost and context pollution without weakening JARVIS authority,
completion guards, replay semantics, or the durable Work record.

C6 starts with the existing Work Orchestrator because current production code sends
the last 12 complete `WorkStep` objects to every reasoning cycle.  The provider payload
includes each step's input, observation and error in full, plus all supplied evidence.

The durable WorkStore remains canonical truth.  C6 changes only the bounded view shown
to the model.

## Repository findings

Current path:

```text
SQLiteWorkStore.list_steps(work_id)
  -> WorkEngine
  -> steps[-12:]
  -> BrainRequest.recent_steps
  -> work.reasoner._work_input_payload()
  -> complete input/observation/error serialization
  -> provider
```

Important existing substrate that must be reused:

- WorkStore already preserves complete durable step history.
- Work completion guards independently inspect canonical history and do not depend on
  the model-facing context projection.
- Model routing already derives replay identity and progress/failure signals from the
  canonical recent WorkSteps.
- EngineeringKnowledge already provides exact identifier/evidence retrieval,
  FTS5/BM25, Qwen3 embeddings, exact NumPy similarity, reciprocal-rank fusion,
  applicability, freshness, sensitivity and integrity gates.
- Dense-only candidate expansion is intentionally disabled by prior owner-machine
  evidence; C6 must not undo that guard.
- No new vector database or retrieval framework is justified by the current problem.

## External research

Current agent-context research supports the same direction.

Anthropic's context-engineering guidance treats context as a finite attention budget and
recommends the smallest high-signal set of tokens, just-in-time retrieval, progressive
disclosure, compaction and durable memory outside the active model window:

- https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- https://www.anthropic.com/engineering/managed-agents

The second source is particularly aligned with JARVIS: durable session history remains
outside the model context and the harness selects/reshapes only the subset needed for
the next inference.  That is preferable to destructively summarizing canonical Work
history.

## Decision

Do **not** introduce LangGraph, a new vector database, another memory layer, or another
retrieval authority for C6.

Implement a JARVIS-native bounded projection over existing WorkStore and
EngineeringKnowledge contracts.

## Target architecture

```text
owner request + canonical WorkItem
              |
              v
       durable WorkStore
              |
              +--------------------------+
              |                          |
              | full history             | deterministic C6 projection
              |                          v
              |                    ContextPack c6.v1
              |                    - selected high-signal steps
              |                    - bounded large payloads
              |                    - omitted-step manifest
              |                    - advisory evidence
              |                    - provenance/digests
              |                          |
              |                          v
              |                    WorkReasoner payload
              |                          |
              +--> completion guards     +--> model
                   and replay truth
```

C6 never deletes canonical history.

## Deterministic step selection

The first selector is task-aware and intentionally conservative.

Always retain:

- the last three WorkSteps;
- recent failed/interrupted evidence;
- owner-input/completion-guard/provider-pressure milestones;
- the latest occurrence of each relevant action kind.

Development additionally prioritizes:

- workspace preparation;
- latest write;
- recent tests;
- final diff;
- commit/status;
- capability dependency/manifest/substrate verification when present.

Diagnostics additionally prioritizes:

- incident inspection;
- admitted EngineeringKnowledge;
- workspace preparation;
- reproduction/static evidence;
- hypotheses;
- final diagnosis.

Research/capability acquisition additionally prioritizes:

- exact goal inspection;
- current research evidence;
- candidate records;
- deterministic resolution;
- final acquisition plan.

Generic work remains recent-history biased.

The selector is bounded.  Omitted steps are represented by a lightweight manifest
containing step ID, kind, summary, state and error presence so omission is visible rather
than silently treated as non-existence.

## Safe payload compaction

Selected steps may still contain large source reads, diffs, test output or research
results.  C6 bounds large strings deterministically while preserving:

- head and tail;
- original character count;
- SHA-256 digest;
- the durable source step ID.

Large lists are bounded with an explicit omitted-item count.

This is a model-context optimization only.  The unmodified full payload remains in the
WorkStore and can be re-observed through normal governed actions.

## EngineeringKnowledge integration

C6 provides an optional adapter over the existing
`EngineeringKnowledgeRetrievalIndex`.

Rules:

- only accepted/current/applicable/integrity-valid knowledge may be returned;
- external-context sensitivity policy is the default because Work may route to cloud;
- knowledge is marked `advisory_only`;
- no retrieval result may mint or lower Authority;
- no EngineeringKnowledge provider is wired when a trustworthy applicability context
  cannot be derived.

This avoids broad, context-free knowledge injection.

## Rollout

Modes:

- `off`: legacy behavior only;
- `shadow`: build/measure ContextPack but send the exact legacy provider payload;
- `apply`: send ContextPack.

The production default for C6 is **shadow**.

C6 apply is forbidden until benchmark evidence proves useful context reduction without
decision degradation.

Routing/replay identity remains based on canonical Work progress so shadow/apply cannot
silently fork durable reasoning-cycle identity.

## Measurements

For each shadowable request measure:

- legacy serialized characters;
- optimized serialized characters;
- approximate token count using the existing provider-neutral 4-char estimate;
- reduction percentage;
- selected step count;
- omitted step count.

Quality equivalence fields:

- selected action;
- `goal_complete`;
- `needs_owner`;
- owner question;
- action parameters.

Decision-summary wording is deliberately not part of strict equivalence because wording
changes can be harmless while action/authority changes are not.

## Acceptance sequence

1. CI/unit acceptance:
   - shadow payload equals legacy payload byte-for-structure;
   - stage-critical milestones survive selection;
   - large payloads are bounded with digest provenance;
   - optimized routing token estimate is used only in apply mode;
   - decision-equivalence scorer rejects action/owner/parameter changes.
2. Owner-machine zero-cloud history probe:
   - run `tools/research/c6_context_owner_acceptance.py`;
   - read real Work history only;
   - make zero model/API calls;
   - prove latest-step retention and measure real reduction.
3. Shadow observation on ordinary Work traffic.
4. Only then design an apply acceptance using paired legacy/optimized decisions.
5. Do not spend the ₹400–₹500 paid-brain experiment budget for C6.

## Current implementation scope

Branch: `feat/c6-context-optimization-shadow`

Implemented in this slice:

- `src/jarvis/work/context.py`;
- `src/jarvis/work/context_knowledge.py`;
- `src/jarvis/work/context_evaluation.py`;
- WorkEngine shadow assembly;
- WorkReasoner shadow/apply projection;
- apply-aware routing context estimates without replay-ID changes;
- deterministic tests;
- zero-cloud owner-machine history acceptance harness.

Production model input remains legacy while C6 is in shadow.
