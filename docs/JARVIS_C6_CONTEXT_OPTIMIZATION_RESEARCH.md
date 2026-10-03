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


## Owner-machine paired acceptance update — 2026-10-04

The current PR #252 acceptance sequence has now produced three fixed
legacy-vs-optimized pair results:

1. `development_repair_after_failure`
   - equivalent after the fixture pinned the exact required commit message;
   - action, parameters, completion and owner/safety fields matched;
   - optimized context materially reduced input usage.
2. `development_ready_for_local_commit`
   - equivalent;
   - 22.96% serialized-context reduction;
   - action/parameters/completion/owner fields all matched.
3. `research_requires_reresolution_after_new_evidence`
   - action remained `acq_record_candidate`;
   - `goal_complete`, `needs_owner` and owner-question fields matched;
   - parameters did **not** match;
   - 76.94% serialized-context reduction.

The research mismatch is material for C6 because the differing parameters contain
verification/acceptance semantics, not merely summary wording.

Therefore:

- production C6 remains **SHADOW**;
- `JARVIS_WORK_CONTEXT_MODE=APPLY` is not authorized;
- do not weaken the strict action-parameter equivalence gate to obtain a pass;
- next diagnosis should be zero-model first: identify which omitted/reshaped research
  evidence caused the parameter divergence and determine whether those parameters should
  be preserved in ContextPack or constructed canonically/deterministically downstream;
- only after that correction should the affected research pair be re-run.

The same acceptance also reinforces the model-routing direction in
`JARVIS_MODEL_ROUTER_AND_CODEX_DIRECTION_2026-10-04.md`: context reduction and model
tiering are complementary, and neither may trade away decision quality.


## Zero-model research-mismatch diagnosis — 2026-10-04

Repository inspection after the failed research pair shows:

- the fixed research fixture contains an original owner goal, nine earlier research
  observations, an unverified SDK candidate, a prior resolve, a prior finalize and then
  newer authoritative evidence;
- the C6 RESEARCH selector explicitly retains the latest step per kind, the latest
  research observations and critical `acq_inspect_goal`, `acq_resolve`,
  `acq_finalize` and `research_web` milestones;
- therefore the mismatch is not evidence that C6 simply dropped the candidate,
  re-resolution/finalization state or newest evidence;
- `acq_record_candidate` currently asks the model to generate free-form
  `verification_requirements` and optional free-form
  `external_acceptance_requirements`, and those strings participate in the canonical
  candidate digest.

The owner-machine mismatch is consistent with two context projections causing the model
to phrase/choose different safety requirements even though both selected the same source,
version, operations, evidence and action. The optimized output also surfaced owner-goal
constraints such as activation approval/no broad scanning that were not present in the
legacy parameter set.

Do **not** solve this by ignoring parameter differences. These fields affect candidate
identity and governance semantics.

Preferred architecture investigation:

1. move workflow invariants such as "re-resolve after verification" into deterministic
   control-plane/completion-guard logic rather than model prose;
2. derive mandatory owner-goal constraints (for example activation approval or discovery
   restrictions) from canonical goal/Authority state;
3. replace safety-critical free-form requirement strings with typed/versioned requirement
   IDs or another canonical representation where practical;
4. leave model-generated narrative advisory rather than authority-bearing;
5. then re-run only the affected research legacy-vs-optimized pair.

This is a stronger safety design than weakening C6 equivalence and should also make lower
model tiers more viable because less governance meaning depends on exact model wording.


## Market-solution direction — LLMLingua family (2026-10-04)

Do not build a bespoke Markdown/token-pruning compressor before benchmarking existing
prompt-compression technology.

Fresh research identifies Microsoft's open-source LLMLingua family as the strongest first
candidate for C6:

- LLMLingua is explicitly designed to compress prompts before sending them to a stronger
  black-box LLM;
- LongLLMLingua adds question-conditioned long-context selection/reordering and is aimed at
  long-context/RAG workloads;
- LLMLingua-2 replaces a generative compressor with a much smaller token-classification
  encoder, is task-agnostic, and the project reports materially faster compression than
  the original LLMLingua;
- the implementation supports structured JSON compression and force-preserved tokens /
  uncompressed regions, which is important for JARVIS canonical IDs, owner constraints,
  action names, digests and safety contracts;
- the official BERT-base multilingual LLMLingua-2 checkpoint is approximately 709 MB,
  making a fully local compressor practical on the owner machine without consuming
  ChatGPT-plan quota.

Primary references:
- https://github.com/microsoft/LLMLingua
- https://www.microsoft.com/en-us/research/project/llmlingua/llmlingua/
- https://huggingface.co/microsoft/llmlingua-2-bert-base-multilingual-cased-meetingbank
- https://aclanthology.org/2024.findings-acl.57/
- https://aclanthology.org/2024.acl-long.91/

### Revised C6 experiment

Before adding more custom ContextPack heuristics, compare three payloads on the same fixed
decision corpus:

A. legacy full canonical provider payload;
B. current hand-selected C6 ContextPack;
C. canonical payload passed through a local LLMLingua-2/LongLLMLingua adapter with
   mandatory JARVIS fields force-preserved.

Measure:
- exact semantic decision equivalence;
- safety/owner/parameter equivalence;
- input tokens;
- serialized size;
- compressor latency;
- compressor CPU/GPU memory;
- whether canonical IDs/digests/constraints survive byte-for-value;
- fallback behavior if the compressor is unavailable.

LLMLingua output is model input only. It never becomes canonical JARVIS state.

If C preserves more decision semantics than B at similar/lower token usage, prefer the
existing compressor technology over additional home-grown summarization rules.
