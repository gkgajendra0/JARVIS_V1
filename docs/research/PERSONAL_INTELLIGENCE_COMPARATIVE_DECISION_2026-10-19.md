# Personal intelligence: comparative research and bounded recommendation

**Observed:** 18–19 October 2026. **Status:** source-backed recommendation;
empirical technology selection pending. No production acceptance or activation.
**Repository baseline:** main `a7ef430d614cf60bd11298ab352a342216594736`.
This supports [Product](../PRODUCT.md), Section 17 of the existing North Star,
and [Current Plan](../CURRENT_PLAN.md); it creates no competing product vision.

## Recommendation

Keep JARVIS as the assistant. Reuse its memory, conversation, identity, Authority,
Hands and durable Work owners. Add one read-only personal-context selection
boundary, initially shadow, to connect those foundations to relevant everyday
questions. Compare optional memory services behind that boundary before selecting
one. Do not replace JARVIS with a second assistant runtime.

The first useful outcome is ordinary assistance: after several sessions and a
restart, a breakfast suggestion respects current preferences, a purchase discussion
remembers what is already owned, and a changed preference overrides its predecessor.
The assistant must also recognize missing information, protected facts and stale
observations. Retrieval accuracy alone cannot establish that outcome.

This is an architectural recommendation based on inspected interfaces and primary
sources, not a measured claim that a particular service is best. The smallest
JARVIS-only baseline can win; an external service must earn its operating cost and
integration burden.

## Reuse, modify, add

| Decision | Existing owner / proposed responsibility |
| --- | --- |
| Reuse | SQLCipher/DPAPI canonical memory and explicit remember/correct/forget/inspect; never make vendor profiles the source of truth. |
| Reuse | LiveContext and budgeted ContextPacket assembly; WorkStore/DBOS for actual work status; Authority for execution decisions. |
| Reuse | LiveKit voice and existing provider adapters, Hands, research and permitted observations. |
| Modify after approval | Broaden eligible read-only context selection beyond a single explicit fact lookup; independently validate the voice handoff. |
| Add after approval | One PersonalContextSelector returning source-linked, current, budgeted evidence or an explicit abstention; shadow mode cannot send it to the conversation provider. |
| Optional after evidence | Replaceable derived retrieval/profile adapters. Correction, deletion and provenance must remain enforceable through JARVIS. |
| Later slices | Governed natural memory admission, useful proactivity and additional life integrations. Neither a memory service nor this proposal completes those slices. |

The repository already implements a substantial self-management substrate.
More repair orchestration does not close the primary personal-intelligence gap.

## Finalists and alternatives

These are comparison candidates, not a performance ranking. Hosted and open-source
editions must be named separately in every result.

| Option | Relevant capability from primary sources | Question that must be tested |
| --- | --- | --- |
| Existing JARVIS | Encrypted assertions, source/release gates, live context and optional semantic retrieval already exist. | Does a small relevant packet materially improve normal answers without another service? |
| Compact profile + permitted history search | An inspectable alternative assembled from the same authorized fictional sources. | Is simple context curation sufficient? Profile construction cost and update failures count. |
| Hindsight | Retain/recall/reflect and source documents with replacement/deletion APIs. | Does episodic/temporal retrieval improve whole answers, with reliable correction/deletion and acceptable extraction/reflect cost? |
| Honcho | User modeling and recall rather than only nearest-neighbor storage; published evaluations describe their own grading choices. | Does the derived user model improve assistance without unsupported inference, subject confusion or deletion residue? |
| Supermemory | Static and dynamic profiles plus query search. | Does ready-to-use personal context justify service dependency, and can all released profile claims be traced and invalidated? |
| Mem0 | Memory extraction/retrieval; current OSS migration documents describe ADD-only extraction. | Useful alternate baseline if finalists fail; explicitly test old/new coexistence and do not equate hosted benchmark results with OSS. |
| Graphiti | Temporal entity/relationship graph. | Add only if relationship/history tasks justify another graph store and extraction lifecycle. |

Primary references:
[Hindsight source](https://github.com/vectorize-io/hindsight),
[documents and lifecycle](https://hindsight.vectorize.io/developer/api/documents),
[Honcho source](https://github.com/plastic-labs/honcho),
[Honcho evaluation methodology](https://honcho.dev/evals/),
[Supermemory profiles](https://supermemory.ai/docs/recall/user-profiles),
[Supermemory lifecycle](https://supermemory.ai/blog/memory-lifecycle-retention-corrections-deletion/),
[Mem0 OSS migration](https://docs.mem0.ai/migration/oss-v2-to-v3),
[Graphiti source](https://github.com/getzep/graphiti).

Version identity observed during research, not approved dependency pins:

| Repository | Source commit |
| --- | --- |
| vectorize-io/hindsight | `5331da2f4db369528bb122075341a7de9c3df6df` |
| plastic-labs/honcho | `ed9fe6c122446a30a74bbba1364003349bf0acb5` |
| supermemoryai/supermemory | `f81fad00e4bfc42610159cf6bd7bdb5fc4ca7cbe` |
| mem0ai/mem0 | `0724291bd864cf807e88ee8981c8226644e8fb42` |

A trial must pin its actual installed artifact, API/SDK version, edition and model
configuration; these source observations do not identify a hosted deployment.

Letta, OpenClaw and Hermes provide useful patterns for context maintenance,
tool use and initiative. Replacing JARVIS with their full runtimes would introduce
migration and overlapping state ownership; no inspected evidence justifies that
cost now. Screened MemOS, Cognee, LangMem and AgentCore are alternatives if a
specific unmet requirement emerges, not dependencies to install speculatively.
Sources: [Letta memory](https://docs.letta.com/agent-sdk/memory),
[OpenClaw memory](https://docs.openclaw.ai/concepts/memory),
[active memory](https://docs.openclaw.ai/concepts/active-memory/how-it-works),
[heartbeat](https://docs.openclaw.ai/gateway/heartbeat),
[Hermes memory](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory),
[MemOS](https://github.com/MemTensor/MemOS), [Cognee](https://www.cognee.ai/how-cognee-builds-ai-memory),
[LangMem](https://langchain-ai.github.io/langmem/),
[AgentCore strategies](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/long-term-configuring-built-in-strategies.html).

## Caveats that affect selection

- Hindsight's automatic retention integrations are not suitable for silently
  changing JARVIS's accepted retention policy. Use bounded direct APIs in a
  disposable fictional lab. Issue 3803's author corrected the original orphaned
  observation premise after testing 0.9.1; it is not evidence that deletion is
  broken. Still verify the exact deployed version and derived caches.
  [Issue 3803](https://github.com/vectorize-io/hindsight/issues/3803).
- Honcho's issue discussion identifies the complexity of deleting an individual
  message after recursive derivation; current behavior needs a version-specific
  lifecycle test. Do not assume message deletion equals erasure of every derived
  conclusion. Self-hosting also introduces its server/database/model stack and
  AGPL licensing review. [Issue 616](https://github.com/plastic-labs/honcho/issues/616),
  [source and deployment instructions](https://github.com/plastic-labs/honcho).
- Supermemory's forget/retention semantics require an explicit lifecycle review.
  Its self-hosting instructions do not establish native Windows parity or equality
  with hosted model quality. Aggregated profile entries also require special
  source-lineage handling.
  [Self-hosting](https://github.com/supermemoryai/supermemory/blob/main/apps/docs/self-hosting/quickstart.mdx),
  [profiles](https://supermemory.ai/docs/recall/user-profiles),
  [lifecycle](https://supermemory.ai/blog/memory-lifecycle-retention-corrections-deletion/).
- Vendor benchmark numbers are not a controlled comparison: different answerers,
  extraction models, prompts, judges, editions and budgets can change the result.
  Published capability is evidence to test, not acceptance.

## What the existing experiments actually establish

The earlier Step 7/8 records reported small lexical-fixture evidence scores of
8/16 and 15/20 for Hindsight versus 16/16 and 20/20 for BM25. Their structured
decision counts were 3/18 and 19/24 versus 18/18 and 24/24. These fixtures supplied
scope/intent and used deterministic scoring, not natural personalized answers.
They imported prepared facts into a restricted local no-LLM configuration with
observations/consolidation disabled; they did not measure Hindsight's normal
model-backed extraction and reflection pipeline.

The Step 9 synonym-pressure fixture reported BM25 top-8 evidence 17/64 and
structured decisions 21/68. Step 10's larger semantic comparison was documented
as implemented but **not run**. None of these numbers proves that Hindsight,
BM25 or the proposed architecture is best for everyday assistance.

Historical records are on the experimental branch associated with
[PR #284](https://github.com/gkgajendra0/JARVIS_V1/pull/284), head
`efff5b4f6c7a9309027bbd96f2dda4870f49dc32`; its stacked history is not a
production integration plan. This proposal starts directly from current main.

## Concrete integration seam and voice constraint

Inspected paths:
- `src/jarvis/memory/service.py`, `query.py`, `runtime.py`: canonical explicit operations and reads.
- `live_context.py`, `context.py`: transient state and budgeted packets.
- `candidate_runtime.py`: session quarantine, not automatic durable admission.
- `src/jarvis/voice/memory_tools.py`: bounded current-fact recall.
- `context_adapter.py`, `context_sync.py`: provider conversion/sync policy.
- `production_runtime.py`, `config.py`: memory/extraction defaults and runtime construction.
- `src/jarvis/work/context.py`, `context_knowledge.py`: Work context projections, currently shadow.

The major unknown is timely, correctly bound realtime context delivery.
LiveKit documents that `on_user_turn_completed` with realtime models requires
agent-side turn detection. JARVIS's existing provider-native turn completion must
not be changed merely to fit a RAG example. A separate bridge probe must establish
turn identity, response timing, interruption and reconnect behavior before apply.
A declared mid-session policy is not end-to-end proof.
[LiveKit hook documentation](https://docs.livekit.io/agents/logic/nodes/).

## Evidence package and next decision

The [design](../superpowers/specs/2026-10-19-personal-intelligence-comparison-design.md)
defines one bounded architecture and its gates.
The [implementation plan](../superpowers/plans/2026-10-19-personal-intelligence-comparison.md)
defines exact contracts and staged verification.
The [public fictional corpus](../../benchmarks/personal_intelligence_v1.json)
contains 20 scenarios / 34 events in English, Hindi and Hinglish.
Its [protocol](../../benchmarks/personal_intelligence_v1.md) separates inputs,
answer rubrics, lifecycle checks and future measured runs.

The public corpus is an authored regression set, not a hidden holdout, external
benchmark or completed model trial. It tests using already authorized sources;
it cannot establish that natural memory capture/admission is solved. Larger
independent evaluation remains necessary. Relevant research includes
[PrefEval](https://github.com/amazon-science/PrefEval),
[AgentMemBench](https://github.com/mazaiying/AgentMemBench),
[PersonaMemv3](https://arxiv.org/abs/2608.21381) and
[DyadMem](https://arxiv.org/abs/2610.03020). Recent preprints are research evidence,
not product certification.

**Execution status:** local execution fails before a command starts while the
launcher enumerates BitLocker-locked volumes, even with workspace and executables
on C:. The contents of D:/I: are not required. Root cause is unproven. No new
JARVIS/model/engine benchmark was executed in this session. Source inspection and
structural fixture checks must not be reported as empirical performance results.

**Next decision:** approve the bounded read-only comparison/shadow architecture,
restore a working execution service, then measure existing JARVIS and the simple
profile/history baseline before adding finalist adapters. Choose an external
service only after comparable answer-quality, lifecycle, resource and latency
evidence. Keep CAP-053 planned until the documented owner-machine gate is met.
