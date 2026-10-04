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

## LLMLingua implementation status — pending owner-machine acceptance

Implementation is complete on PR #252 for the bounded experiment and is intentionally
not production-enabled yet.

Implemented:

- optional `context-compression` dependency group pinned to Microsoft LLMLingua
  source revision `5a4c78ae18ab17a98cf997e8259354e546081d64`;
- local LLMLingua-2 BERT-base compressor using the reviewed
  `microsoft/llmlingua-2-bert-base-multilingual-cased-meetingbank` model;
- reviewed Hugging Face model revision pinned to `5f0c82792b7ea14c6484e015b6a072009496b7f2`;
- CPU is the default compression device so the experiment does not depend on the normal
  JARVIS local-brain/GPU runtime;
- JARVIS JSON structure is preserved exactly;
- Work identity/request, purpose, allowed action catalog/schema, IDs, versions, digests,
  source/code `text`, errors and other non-target leaves remain exact;
- only sufficiently long natural-language evidence fields such as `summary`, `content`,
  `body`, `rationale` and non-action `description` are candidates;
- a replacement is used only when it is non-empty and smaller than the original leaf;
- post-compression validation fails closed if object keys, list lengths, types or any
  protected value change;
- model-facing override is explicit and does not mutate canonical `BrainRequest`,
  WorkStore or execution state;
- owner harness supports a zero-ChatGPT local preflight and a bounded live A/B;
- the default LLMLingua proof targets only
  `research_requires_reresolution_after_new_evidence`, the case that failed the
  hand-selected C6 comparison;
- the live default uses at most two ChatGPT-plan calls and stops on mismatch;
- LLMLingua evidence can never automatically set global C6 APPLY.

The implementation deliberately does not use LLMLingua's `compress_json` path. Upstream
has an open LLMLingua-2 `compress_json` failure report; JARVIS instead owns JSON
traversal/validation and gives LLMLingua only selected string leaves.

### Owner-machine acceptance sequence

From an exact clean branch head:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[context-compression]"
```

Then run the zero-ChatGPT local preflight:

```powershell
.\.venv\Scripts\python.exe tools\research\c6_context_owner_acceptance.py `
    --llmlingua-fixture-preflight
```

The first run may download the pinned ~713 MB model into the normal Hugging Face cache.
It must report `c6_llmlingua_preflight_ready=true`, zero model calls and a real size
reduction before any ChatGPT-plan A/B is attempted.

Only after preflight passes, run the bounded research-pair comparison:

```powershell
.\.venv\Scripts\python.exe tools\research\c6_context_owner_acceptance.py `
    --llmlingua-fixture-benchmark `
    --model gpt-6-astra
```

Default live budget: exactly two model calls if both requests execute.

Acceptance requires:
- same action;
- exact same parameters;
- same `goal_complete`;
- same `needs_owner`;
- same owner question;
- lower actual provider input-token usage for the compressed request;
- no action execution, routing mutation, provider-circuit mutation or paid fallback.

A pass is evidence to design/promote the compressor path; it is not permission for this
benchmark command itself to flip production C6 APPLY.

### Production integration gate

The same compressor is now wired into the real `RoutedWorkReasoner`, not only the
benchmark harness. The production-facing setting is:

`JARVIS_WORK_PROMPT_COMPRESSION_MODE=off|shadow|apply`

Safety behavior:

- default is `off`, so current production behavior is unchanged;
- `shadow` locally compresses the complete available canonical RESEARCH history and
  records/logs the metrics while still sending the exact current provider payload;
- `apply` may send compressed full history only when JARVIS independently verifies that
  it is smaller than the current provider payload as well as smaller than the raw full
  history;
- compressor initialization/inference/validation/size-telemetry failure falls back to
  the exact current provider payload rather than blocking Work or sending partially
  compressed data;
- initial runtime eligibility is RESEARCH only; DEVELOPMENT remains on its already
  tested C6 path and source/diff text is never token-pruned by LLMLingua;
- compression runs through a serialized local `prompt_compression`/CPU resource lease
  so concurrent WorkItems cannot stampede one local transformer;
- routing/replay identity remains based on canonical BrainRequest/Work state;
- `JARVIS_WORK_CONTEXT_MODE=apply` and
  `JARVIS_WORK_PROMPT_COMPRESSION_MODE=apply` are rejected together until a combined
  compression acceptance exists.

The runtime integration is code-complete but remains `off` by default. The owner-machine
preflight and A/B decision test above are the admission gate before any setting change.


## LLMLingua implementation candidate — 2026-10-04

PR #252 now contains the compression-first implementation candidate. This is code/CI
status only; owner-machine acceptance remains required before any production promotion.

Implemented:

- optional/lazy `LLMLingua2WorkPayloadCompressor` behind a JARVIS-owned protocol;
- exact Microsoft LLMLingua source revision and exact reviewed model revision recorded in
  dependency provenance;
- local CPU-first compression with `trust_remote_code=False`;
- first admission restricted to RESEARCH Work;
- only long natural-language `summary/content/body/rationale/description` leaves are
  compressible;
- owner request, purpose, action catalog/schema, source/code `text`, paths, IDs,
  digests, evidence refs, source identity/version and JSON/list structure remain exact;
- malformed/empty/larger compressor output is rejected or discarded;
- compressor failure falls back to the exact legacy provider payload;
- independent `off/shadow/apply` prompt-compression mode, default `off`;
- C6 hand-selected context and LLMLingua compression cannot both be APPLY until a
  combined-path acceptance exists;
- SHADOW computes compression but sends the exact legacy payload;
- provider retries reuse one already-prepared payload rather than recompressing;
- local compression has its own bounded resource lease;
- benchmark seam compares the complete canonical full-history payload against its locally
  compressed full-history copy while decision validation still uses the canonical
  BrainRequest;
- the benchmark separately proves compressed full history is smaller than today's
  current provider payload, so preserving more history cannot increase routine token use;
- strict action/parameter/completion/owner equivalence remains unchanged;
- benchmark records actual provider input-token reduction as well as chars/estimated
  tokens/compressor latency;
- one-command Windows owner acceptance:
  `tools/research/c6_llmlingua_owner_acceptance.ps1`.

The first owner-machine live gate intentionally targets only
`research_requires_reresolution_after_new_evidence`, the case that failed the hand-built
ContextPack comparison. It performs a zero-ChatGPT local preflight first and, only when
that succeeds, at most two ChatGPT-plan calls: one exact full-history request and one
LLMLingua-compressed full-history request.

Passing that single pair is evidence to continue the compressor evaluation; it does not
automatically enable `JARVIS_WORK_PROMPT_COMPRESSION_MODE=apply` and does not promote
the older `JARVIS_WORK_CONTEXT_MODE=apply` switch.


### Full-history correction — 2026-10-04

Repository review found that the pre-C6 provider payload called "legacy" above was not
the complete Work history; it carried only the latest 12 WorkSteps. In the research
fixture, the original `acq_inspect_goal` step containing owner constraints was older
than that window. The hand-selected ContextPack restored that goal, which explains why
the earlier optimized decision surfaced constraints absent from the legacy parameters.

The LLMLingua proof is therefore intentionally stronger than the old C6 A/B:

```text
canonical full Work history
        |
        +--> exact full-history provider payload --------> strong model (baseline)
        |
        +--> local LLMLingua-2 compression
                    |
                    +--> compressed full-history payload -> strong model
```

Production SHADOW still sends today's exact current payload. A future compressor APPLY is
eligible only when compressed full history is smaller than today's current payload and
passes strict decision equivalence. This preserves more decision-relevant history without
paying a token penalty. Production remains OFF/SHADOW until owner-machine evidence is
accepted.


## First LLMLingua owner result — 2026-10-04

Owner-machine acceptance at exact head
`30d08bae656e14a70a56b1e884c6f09c6f1c2135` proved the local compressor/runtime
integration works, but the default 0.50 retained-rate was too aggressive for strict
decision equivalence.

Measured on `research_requires_reresolution_after_new_evidence`:

- canonical full history: 14 steps / 102,333 serialized chars;
- today's current provider window: 12 steps / 92,506 chars;
- LLMLingua-2 at rate 0.50: 65,031 chars;
- reduction vs full history: 36.45%;
- reduction vs today's current payload: 29.70%;
- actual provider input-token reduction vs full-history baseline: 34.96%;
- local CPU compression latency: about 12.3 seconds;
- action/completion/owner fields matched;
- exact action parameters did not match.

The full-history decision preserved owner constraints such as no broad network scanning
and owner approval before activation. The compressed decision omitted those optional
action fields and rephrased verification requirements. Therefore promotion correctly
failed.

Repository inspection confirms the compressor did **not** delete the owner constraint
list: it only compresses sufficiently long prose keys such as
`summary/content/body/rationale/description`; canonical constraint lists, IDs,
versions, digests, schemas, requests and action parameters remain exact. The mismatch is
therefore evidence that 0.50 token-level compression changed model decision behavior,
not that JARVIS corrupted canonical state.

### Revised admission strategy

Do not optimize for maximum compression. Full history only needs enough reduction to
beat today's current model payload.

The owner acceptance now performs a zero-cloud conservative sweep:

`0.95 -> 0.90 -> 0.85 -> 0.80 -> 0.75 -> 0.70 -> 0.60 -> 0.50`

It selects the **least aggressive** rate that:

1. reduces the complete full-history payload;
2. remains smaller than today's current payload;
3. beats today's payload by at least 5% serialized size.

Only the selected rate is then sent to the strong model, using at most two ChatGPT-plan
calls for the strict full-history-vs-compressed pair.

This preserves the compression benefit while minimizing semantic disturbance. Runtime
rate is now a first-class setting:
`JARVIS_WORK_PROMPT_COMPRESSION_RATE`, defaulting conservatively to `0.8`.
Production compression mode remains OFF and no rate is admitted until strict owner
acceptance passes.

### 512-token warning interpretation

The owner run emitted a Transformers warning because one source string tokenized above
the encoder's declared 512-token sequence length. The reviewed LLMLingua-2 implementation
internally chunks each context before token-classification inference using its
`max_seq_len=512` path; upstream v0.2.2 also contains the chunk-max-sequence fix.
The warning is retained as observable diagnostic output, but the completed compression
run is not evidence of a 1,575-token tensor being passed directly into the encoder.


## Second LLMLingua owner result — 2026-10-04

The conservative auto-selection run chose rate `0.75`, the first coarse rate that
made compressed full history at least 5% smaller than today's current provider payload.

Observed:

- full canonical history: 14 steps / 102,333 chars;
- current provider window: 12 steps / 92,506 chars;
- rate 0.75 compressed full history: 87,860 chars;
- reduction vs full history: 14.14%;
- reduction vs current payload: 5.02%;
- actual provider input-token reduction vs full-history baseline: 16.05%;
- strict action equality: PASS;
- strict goal/owner-state equality: PASS;
- strict parameter equality: FAIL.

The mismatch is narrower than the 0.50 run. Both outputs retain the same evidence refs,
source identity/kind/version, supported operations and the same underlying verification
intent. However, the full-history decision emitted an explicit
`external_acceptance_requirements` field while the compressed decision incorporated
owner approval into a verification requirement instead. Because C6 admission requires
exact parameter equality, this remains a valid failure and APPLY stays blocked.

### Fine-grained crossover strategy

The zero-cloud sweep showed rate `0.80` was only about 0.03% larger than today's current
payload. Therefore the next acceptance does not jump directly to 0.75. It searches the
local crossover in fine steps:

`0.800, 0.795, 0.790, 0.785, 0.780, 0.775, 0.770, 0.765, 0.760, 0.755, 0.750`

The first rate that is at least 0.25% smaller than today's payload is selected. This
preserves the maximum possible context while still proving a real net token win. The
strict decision comparator is unchanged.


## Baseline-stability correction — 2026-10-04

Comparison of the two owner-machine LLMLingua runs exposed an additional validity
requirement before attributing parameter differences to compression.

The full-history baseline itself changed across separate runs even though the canonical
fixture payload and reasoning contract did not change. The first owner run's full-context
decision included `discovery_scopes` plus two external-acceptance requirements. The
second run's full-context decision omitted `discovery_scopes` and emitted only one
external-acceptance requirement.

Therefore a full-vs-compressed mismatch is not attributable to LLMLingua unless the
strong model first proves exact same-input stability for that exact full-history
research request.

The live LLMLingua gate now runs:

```text
full canonical history -> strong model #1
full canonical history -> strong model #2
        |
        +-- mismatch: STOP after 2 calls; compression is not evaluated
        |
        +-- exact match:
              compressed full history -> strong model #3
              compare strictly against the stable full-history decision
```

This keeps the strict comparator unchanged and prevents provider/model variance from
being misclassified as information loss. The bounded live gate now uses at most three
ChatGPT-plan calls for one fixture and still executes no Work action, changes no
production routing, enables no paid fallback and cannot promote APPLY automatically.


## Deterministic acquisition-governance correction — 2026-10-04

The stability-first owner run proved the exact same full-history research request was not
strictly stable: Astra produced different free-form `verification_requirements` on two
identical calls. Compression was correctly not evaluated.

Root-cause review found `acq_record_candidate` allowed the model to author
`verification_requirements`, `secret_scopes`, `network_scopes`,
`device_scopes`, `discovery_scopes`, and
`external_acceptance_requirements`. Those values flowed into
`AcquisitionCandidateV1` and later into canonical acquisition-plan contracts/digests.

That conflicts with the existing Phase-9 invariant that selectable/blocking conditions
are deterministic and free-form model text cannot complete acquisition.

The unverified-candidate action is now narrowed:

- model-owned: source kind, source identity, optional exact version/digest/license,
  supported semantic operations, evidence refs;
- JARVIS-owned: verification contract;
- model may no longer invent trust/governance scope or owner-acceptance policy in
  `acq_record_candidate`.

JARVIS reuses the source-type verification contracts already used by standard trusted
source evidence:

- MCP -> `mcp-tools-list-contract`;
- OpenAPI -> `openapi-contract-test`;
- AsyncAPI -> `asyncapi-contract-test`;
- SDK library -> `sdk-adapter-contract-test`.

This is not a relaxed C6 comparator. It removes nondeterministic prose from the canonical
decision contract itself. The same strict action/parameter comparison remains in place.

The next owner acceptance must use the new reasoning-contract digest/action schema; older
full-history stability evidence is not promotable across this contract change.


### Local action-schema enforcement

The candidate-governance correction also exposed a general Work boundary gap:
`parameters_json` was decoded and the selected action name was checked, but action
parameters were not locally validated against the selected `BrainAction.parameter_schema`.

JARVIS now validates provider-returned parameters with JSON Schema Draft 2020-12 before
creating an executable Work decision. This means the narrowed
`acq_record_candidate` schema is an actual runtime boundary, not merely prompt guidance.

C6 equivalence therefore compares decisions that are valid under the same canonical
action contract. Out-of-schema provider output fails rather than being silently accepted.


## Research-fixture routing correction — 2026-10-04

The owner-machine stability run at
`e5d66c7a8675d60b4971a1c0d0ba857ab986e5ce` proved that the prior
`research_requires_reresolution_after_new_evidence` fixture was not a valid
LLMLingua model-equivalence target.

The full-history A/A pair disagreed before compression was evaluated: one call selected a
zero-parameter protocol action while the other selected `acq_record_candidate`. More
importantly, repository review showed the production `WorkEngine` asks
`Phase9ResearchControlPlaneDecider` before invoking the model. For this fixture's
"new evidence after prior resolve/finalize" state, production should perform deterministic
protocol bookkeeping instead of consuming model reasoning.

A second protocol inconsistency was found during that review: the production runtime
registers `acq_verify_pypi_sdk`, and `acq_resolve` explicitly instructs exact-version
SDK candidates to be verified first, but the deterministic research controller
previously jumped directly from new candidate evidence to `acq_resolve`.

The controller no longer auto-resolves immediately after `acq_record_candidate`.
A recorded candidate is a model-owned staging point so the model can select the
appropriate registered verifier when the evidence supports it. Jarvis does not infer
that generic `sdk_library` means PyPI/Python. Once `acq_verify_pypi_sdk` produces
canonical verification evidence, the existing deterministic re-resolve rule runs.

The old re-resolve fixture is therefore retired from model-equivalence promotion
evidence. Its prior runs remain useful diagnostics, but they do not prove or disprove
LLMLingua quality.

The replacement C6 research fixture is
`research_ready_for_digest_bound_finalize`: canonical research and deterministic
resolution are already current, there is no newer source evidence, and the next
`acq_finalize` step is genuinely model-owned. The owner request pins the exact bounded
plan parameters so strict A/A and full-history-vs-compressed equality remain meaningful.
