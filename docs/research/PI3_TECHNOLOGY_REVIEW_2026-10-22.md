# PI-3A technology review — 22 October 2026

Status: bounded desk research and existing-repository evidence review completed for the PI-3A shortlist. Technology direction is RECOMMENDED, not approved architecture, implementation or a measured vendor winner. Exact selection contract/privacy budgets remain design decisions. No installs, new model downloads, provider inference requests, billing/account/model changes or owner activation occurred.

## Research question and exit boundary

For JARVIS's existing authorized personal facts, how should the normal realtime assistant identify the right entities/facts and use them together for an ordinary personal question? Preserve canonical SQLCipher, source/currentness/forget semantics and Authority, with low conversational latency/cost. This is the next PI-3A step; full episodic memory, temporal relationship graphs, autonomous learning from outcomes and proactive actions are later requirements. The whole memory/agent market is not being reevaluated from zero.

Exit criteria for desk research: trace the real path and gap, review prior repo experiments without replaying them, verify current primary capabilities of credible solution families, distinguish integration assumptions from measured evidence, and state what remains before implementation. A production-quality/model-performance claim is not an exit criterion that documentation alone can satisfy.

## Confirmed application gap

The [gap map](PI3_CONTEXTUAL_ASSISTANCE_GAP_MAP_2026-10-22.md) traces `category_<uuid>` nonscalar predicates, predicate-only context catalog and a separate selected-index read. Several owned items can therefore be semantically indistinguishable to the model until it reads their values; reading the first fourcannot ensure a relevant target among more items. This is confirmed information flow, not a reproduced normal-model error. The existing evaluator's forced first-up-to-four indices does not establish realtime selection quality. Fixing selection semantics is distinct from tuning the language model or replacing storage.

Current repo capabilities already include exact current-facet reads, canonical eligible/scoped learning records, FTS5/BM25 plus dense retrieval and reciprocal-rank fusion, transient LiveContext/ContextAssembler, realtime context tools, version/epoch checks and audio protection. Existing hybrid retrieval requires a compatible query vector; API existence does not prove fresh automatic facts have usable vectors or acceptable cold-start latency. Do not make a new embedding/reranking model an unmeasured prerequisite.

## Prior evidence reconciled

Read historical `STEP4_MEMORY_DECISION_MODERNIZATION_2026-10-16.md` at ref efff5b4f6c7a9309027bbd96f2dda4870f49dc32, current approved automatic-learning design's research section and the October19architecture record.

- Qwen/BGE/EmbeddingGemma/fusion/reranking experiments establish ranking components on their own fixed corpora, not universal relevance, answerability or personal-advice quality. Historical100% Recall@1 is a small fixed-corpus result.
- Prior utility/role/release classifiers had important failures. Do not reinstate them as mandatory gates just because they are available.
- LangMem 18-case pilot reported11/18 correct labels; native 14/18 was recovered across runs and also failed. This is not a clean generalized winner comparison or a PI-3selection test.
- Earlier small Hindsight results differed from later handover-reported240-fact decisions56/68 at K=8 and 63/68 at K=16. The older protocol still said not measured. Preserve the reporting/provenance discrepancy; do not call Hindsight universally unsuccessful or those later numbers a new verified run.
- None of those old scores proves the current live voice selector can choose a specific learned entity among opaque catalog IDs. No old/exposed case was rerun or rescored.

## Current primary-source comparison

| Approach | Current capability verified from primary sources | Fit for the bounded PI-3Ajob / decision |
| --- | --- | --- |
| Existing LiveKit/Gemini tool path plus canonical context projection | LiveKit documents external-data tools; Gemini Live documents function calls and client function responses. | Recommended foundation. Add application-specific authorized entity selection and evidence projection around existing state; preserve the current voice model and pinned adapters. Docs do not prove the exact pinned integration. |
| Existing native hybrid retrieval | Repo already has eligible-current FTS5/BM25+dense/RRF and metadata narrowing. | Reuse selectively if exact structured selection is insufficient. Verify vector/index availability, entity disambiguation and latency; ranking alone is not truth, answerability or authorization. |
| LangMem / LangGraph | LangMem offers functional primitives usable with any storage. LangGraph separates checkpointers/stores and supports namespaced semantic search with embeddings. | Credible replaceable helper, not necessarily a runtime takeover. A custom canonical adapter is possible. No concrete incremental value yet demonstrated for the current catalog/projection gap; do not add a workflow/state abstraction just for its name. |
| Hindsight | Current recall API describes semantic/spreading-activation recall, and a separate reflect endpoint generates answers from memory. | Credible later comparator for richer aliases/episodes/reflection. Adoption still needs a scoped read-only bridge, correction/forget freshness guarantees and a latency/call-budget comparison. Not selected as primary state or added to this first slice. |
| Mem0 | Current OSS migration documents ADD-only add() events, accumulated assertions/current retrieval, entity-matching collection and removal of graph memory from OSS in favor of Platform. | Useful memory/extraction/retrieval component family. ADD-only ingestion is not a replacement for JARVIS's exact canonical mutation/forget contract; this does NOT mean explicit delete APIs do not exist. A service/adapter or migration adds work not yet justified by this gap. |
| Graphiti / Zep | Graphiti supports temporal entities/relationships, hybrid search and graph drivers. Its reference servers expressly leave auth/authorization/injection controls to deployment. | Relevant to later temporal/relationship requirements. An application-owned library adapter could be safe, but a graph backend and ingest/resolve model calls are not established prerequisites for selecting already stored personal items. No claim of general unsafety or lack of capability. |
| Letta current MemFS / stateful agent harness | Current docs describe Git-backed memory projected as files, root-context memories, indexed deeper directories and optional semantic-search mod. Older memory-block links redirected to the current docs. | Keep the current capability picture updated. Full adoption changes memory/context ownership and introduces Git/file lifecycle considerations, including physical forget across retained history. Not justified as a whole-agent replacement for this first gap. Useful context-index ideas can inform a JARVIS-owned projection. |

## Sources and limits

1. [LiveKit external data/tools](https://docs.livekit.io/agents/logic/external-data/): tool-based external context; turn-completion RAG hook guidance is specifically for STT-LLM-TTS, not a blanket realtime hook guarantee.
2. [Gemini Live tools](https://ai.google.dev/gemini-api/docs/live-api/tools): client-managed function responses. Actual pinned LiveKit 1.8.3 / google-genai 2.22.0 capabilities must still be respected.
3. [LangMem official repository](https://github.com/langchain-ai/langmem): functional primitives and storage integration.
4. [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence) and [stores](https://docs.langchain.com/oss/python/langgraph/stores): thread state versus cross-thread records, semantic search configuration.
5. [Hindsight recall](https://docs.hindsight.vectorize.io/api-reference/recall-memories/) and [reflect](https://docs.hindsight.vectorize.io/api-reference/reflect/): distinct retrieval and answer-generation APIs. No performance estimate follows.
6. [Mem0 OSS migration](https://github.com/mem0ai/mem0/blob/main/docs/migration/oss-v2-to-v3.mdx): algorithm/entity matching/graph availability changes. Managed and OSS capabilities are not interchangeable.
7. [Graphiti official repository](https://github.com/getzep/graphiti): temporal graph/search/deployment responsibilities.
8. [Letta MemFS](https://docs.letta.com/concepts/memfs) and [memory/dreaming](https://docs.letta.com/configuration/memory): current memory model. These replace an assumption that old memory-block documentation is the complete current product.

Source review establishes advertised/API/source capabilities, not independent multilingual benchmarks, measured latency on this PC or a universal best product. The fit judgments in the table are JARVIS-specific inferences based on the constrained job and existing ownership.

## Recommended direction and narrower design alternatives

Recommend native entity-aware context tools, current canonical facts and the existing realtime model. Reuse proven retrieval components if needed; keep external adapters replaceable for future measured gaps. This is a technology direction, not an assertion that JARVIS must invent extraction, vector search, graph algorithms or a new reasoning model.

Two native designs remain to select in the written architecture:

A. **Authorized semantic catalog descriptors.** Keep opaque IDs as identity, expose enough code-derived category/kind/entity information to select correctly. Entity labels/status are owner data, not free metadata: define release authority, source/version binding and total catalog/value budgets, and invalidate them on mutation/forget.

B. **Structured query-driven context projection.** Let the existing voice model request approved kinds/targets for the current canonical question; resolve under canonical scope with exact filters and existing retrieval where justified. Return bounded grounded facts/ambiguity. Prevent arbitrary SQL, inferred owner identity, unrelated broad searches and unreliable fuzzy target selection.

Do not choose A or B by counting files. Freeze an information-flow/authorization contract covering more than four mixed items, specific target, multi-fact advice, irrelevant query, unknown reason, correction/forget and budget overflow. Perform an offline contract comparison after its design/probe authorization; then implement the selected contract with observed failing-then-passing tests. No provider experiment has been authorized or run by this review.

## What is complete, what is not

**Complete for this bounded decision:** repository/prior-evidence review, current primary-source landscape comparison, separation of retrieval/selection/reasoning/authority responsibilities and recommendation to extend the native path first. No need to repeat the earlier full vendor benchmark to write the design.

**Not complete:** exact descriptor-versus-query/release-budget decision, written approved architecture/implementation plan, offline reproducer/comparison, live actual-model selection evidence, normal-app quality/owner acceptance. These are visible next stages; they must not be described as completed technology tests. If the offline check reveals a larger retrieval/temporal gap, reopen only the corresponding alternatives with a bounded fresh evaluation proposal.

Next action: present this research result, settle the scoped contract in the written design, then obtain the normal design/plan decisions before product code. Existing PI-2deferred qualification, default OFF and protected merge boundaries remain unchanged. No paid validation, provider budget expansion or account/model switch is requested.
