# Research Round 1 — Building a Movie-Inspired Personal JARVIS (2026-10-18)

**Status:** INITIAL EXTERNAL TECHNOLOGY LANDSCAPE / NOT FINAL TECHNOLOGY
SELECTION / NO IMPLEMENTATION AUTHORIZED.

**Authority:** \`docs/PRODUCT.md\` and Section 17 of
\`docs/AUTONOMOUS_SELF_MANAGEMENT_MASTER_PLAN.md\` define the owner experience.
\`docs/research/PERSONAL_INTELLIGENCE_REPOSITORY_AUDIT_2026-10-18.md\` documents
existing JARVIS wiring and deferred boundaries. External products are pattern
sources, not permission to replace canonical components.

## 1. Reframe the engineering question

Not "what is the best vector database?" or "what framework copies Iron Man?"
Ask **which assembly of memory, personal modeling, contextual reasoning,
awareness, tools, governance and feedback will make JARVIS helpful across an
owner's real life, without repeated refreshers?**

Movie-inspired behaviors can be approached:
- a consistent personal assistant, voice and interaction style;
- relevant durable memory and evolving preferences;
- connected, authorized real-time observations;
- thoughtful proactive signals and grounded device/tool execution;
- multi-session coherence and learning from verified outcomes.

Movie-level omniscience, sentience, perfect understanding and access to every
device cannot be promised by 2026 systems. A product must be judged by working
capabilities, not fiction-inspired UI or branding.

## 2. Established approaches and verified technical patterns

| Approach | Public evidence and capability | Transfer to JARVIS | Caveat |
| --- | --- | --- | --- |
| OpenAI ChatGPT "Dreaming" (2026) | Background synthesis from past conversations to produce fresher, more relevant personal context; official evaluation considers carrying context, preferences and changing facts. | Study the *lifecycle* of memory synthesis and freshness and the metric "used in answer," not just search ranking. | Proprietary implementation details and training infrastructure not disclosed. |
| Anthropic context engineering | Context curation and utility per model token; selective retrieval, long-horizon compaction and concise state. | Token-budgeted assembly on every relevant turn, source-scoped context and minimal distractions. | General design principle, not a complete memory product. |
| OpenAI Agents SDK | Separates conversation sessions, compaction and reusable workflow memory. | Reinforces separate transient/long-lived stores and bounded projection. | New SDK adoption is not justified where JARVIS already owns Work and conversation state. |
| Mem0 v3 | Extracts reusable facts from conversation; retrieval by semantic, keywords, entities, temporal signals and scoped metadata; documents current ADD-only default extraction. | Study extraction/metadata and relevance pipeline; compare as memory-engine *candidate*, not canonical replacement. | Mutations and deletion requirements must be tested explicitly; cloud and OSS feature sets differ; published scores may be vendor measured. |
| Hindsight | Retain, recall, reflect; entities, source context, semantic/temporal/graph recall and experience vs world. | Candidate to improve semantic/episodic recall after source/consent bridging; JARVIS has live synthetic retrieval evidence. | Retain/extraction and reflect are model-backed, can infer incorrectly and cost money. Existing Step 10 only tests retrieval under oracle scope. |
| Letta (MemGPT lineage) | Always-in-context memory, archival/recall, sleep-time consolidation, Git-based context repositories in Letta Code. | Important lessons: tiered memory, inspectable editable context, background consolidation, progressive disclosure and memory hygiene. | Full Letta runtime would compete with JARVIS Work/authority; Git-based Context Repositories mainly demonstrated for coding agents. |
| LangGraph | Short-term checkpointed thread state vs long-term namespaced semantic/episodic/procedural memory. | Adopt conceptual separation where useful. | No evidence yet justifies installing a second durable orchestration engine alongside DBOS. |
| Graphiti / Zep | Temporal entity-relationship graphs with evolving facts and episode histories. | Candidate if relationship/history questions cannot be handled through current canonical schemas and retrieval. | Graph extraction/storage and consistency add complexity; no automatic authority or truth. |
| LiveKit Agents | Realtime audio/voice agent turn-taking, interruption, model/provider integration. | Already in JARVIS; invest in validated provider-context sync, latency and interrupts. | Voice layer is not a cross-session owner memory by itself. |
| Gemini 3.8 Live API | Streaming audio/video, asynchronous tool calls, context updates, session management/compression/resumption. | Relevant to current realtime provider; feasible to deliver just-in-time bounded context. | Short-lived live sessions and connection expiry; resumption is not durable personal memory. Preview API/model compatibility needs owner-machine verification. |

## 3. Sources inspected (dated or live technical docs)

Primary/current sources:

1. OpenAI (2026-06-04), "Dreaming: Better memory for a more helpful ChatGPT":
   https://openai.com/index/chatgpt-memory-dreaming/
2. Anthropic (2025-09-29), "Effective context engineering":
   https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
3. OpenAI Cookbook (2026-05-01), "Building Reliable Agents with Memory and Compaction":
   https://developers.openai.com/cookbook/examples/agents_sdk/building_reliable_agents_memory_compaction
4. OpenAI Agents SDK Sessions: https://openai.github.io/openai-agents-python/sessions/
5. Mem0 official architecture and v3 docs:
   https://github.com/mem0ai/mem0/blob/main/docs/core-concepts/how-it-works.mdx
   https://github.com/mem0ai/mem0/blob/main/docs/migration/oss-v2-to-v3.mdx
6. Hindsight Retain and Recall:
   https://github.com/vectorize-io/hindsight/blob/main/hindsight-docs/docs/developer/retain.md
   https://docs.hindsight.vectorize.io/api-reference/recall-memories/
7. Letta (2026-02-12), "Context Repositories: Git-based Memory":
   https://www.letta.com/blog/context-repositories/
8. Letta (2026-04-02), "Context Constitution":
   https://www.letta.com/blog/context-constitution/
9. Letta (2026-07-28), "Evaluating Memory in Production Agents":
   https://www.letta.com/blog/evaluating-memory-in-production-agents/
10. LangGraph memory concepts:
    https://github.com/langchain-ai/docs/blob/main/src/oss/concepts/memory.mdx
11. Graphiti v4 temporal graph docs:
    https://help.getzep.com/graphiti/getting-started/overview
12. Google Gemini Live API (updated 2026-09-18):
    https://ai.google.dev/gemini-api/docs/live-api/capabilities
    https://ai.google.dev/gemini-api/docs/live-api/session-management
13. LiveKit agents documentation: https://docs.livekit.io/agents/
14. OWASP (2026-05-13), memory poisoning:
    https://genai.owasp.org/2026/05/13/memory-is-a-feature-it-is-also-an-attack-surface/

Do not treat commercial or vendor-reported benchmark percentages as
cross-system rankings. Compare on fixed corpora, model budgets, task
distributions and scoring rules. Open-source and hosted features may differ.

## 4. Benchmarks should measure personal assistance, not only fact QA

Useful public evaluation references:

- **PersonaMem**, Jiang et al. (COLM 2025): evolving synthetic user profiles
  with up to 60 multi-session interactions, tasks requiring actual personalized
  *answers*, not merely retrieval.
  https://github.com/bowen-upenn/PersonaMem
- **PersonaLens**, ACL Findings 2025: task-oriented personalization and
  response quality with realistic preference profiles.
  https://aclanthology.org/2025.findings-acl.927/
- **Persona2Web**, ICML 2026: user-history-driven ambiguous web-agent tasks;
  tests when to infer preference versus clarify.
  https://proceedings.mlr.press/v306/kim26ap.html
- **LoCoMo**, ACL 2024: longitudinal conversations, multi-session temporal and
  causal questions.
  https://aclanthology.org/2024.acl-long.747/
- **LongMemEval**, ICLR 2025: five categories of long-term conversational
  memory, including updating and temporal reasoning.
  https://github.com/xiaowu0162/LongMemEval
- **LongMemEval-V2**, 2026: experience/workflow recall and environment failures,
  useful later for autonomous work, but not a substitute for PersonaMem.
  https://github.com/xiaowu0162/LongMemEval-V2

One source directly warns against conflating two abilities: Letta's
2026 production-agent study tests **memory generation** separately from
**memory usage/adherence**. A retrieval benchmark cannot establish either.

## 5. Architecture alternatives to evaluate; do not pick prematurely

**A. Existing JARVIS + own controlled context pipeline:**
SQLCipher canonical facts/history, LiveContext, source/temporal guards and
budgeted context projection; optionally Hindsight/Mem0/other replaceable index.
Strengths: ownership, safety, existing substrate. Risks: extraction and
context-policy engineering burden.

**B. Platform-centric memory/runtime:**
Use Letta or a comparable stateful agent platform as primary context manager.
Strengths: bundled learning/context strategies. Risks: competing truth,
security boundaries, migration and operational weight in existing JARVIS.

**C. Agent memory service with canonical bridge:**
Preserve SQLCipher as truth but leverage Hindsight, Mem0 or temporal graph
for approved ingestion/retrieval, with strict synchronization, deletion,
corrections and source-linking.
Strengths: mature semantics. Risks: propagation conflicts, dual-store
deletion, LLM extraction overhead, additional latency.

**D. Artifact-first personal context:**
Curated owner profile, versioned decision/episode records and on-demand
conversation/file search; the agent progressively loads detail.
Strengths: inspectability and provenance. Risks: prompt-maintenance,
search/use burden and retention consistency.

A composition of A + selective C/D is an initial *hypothesis*, not
a conclusion. First compare full workflows at comparable quality/cost.

## 6. Essential unanswered questions / research backlog

1. **What is truly worth remembering?** How to classify durable explicit
   facts, context-dependent preferences, weak behavioral inference,
   episodic history, ephemeral situations and sensitive signals.
2. **How are memories admitted?** Model extraction versus deterministic
   policies, audit/source proof, confirmation policies, background
   consolidation, correction and deletion.
3. **How is long-term memory used?** How to decide whether to look up a fact,
   how to resolve indirect phrasing, how to inject the *minimum* useful
   evidence, and how to avoid memory causing irrelevant personalization.
4. **How are changes reconciled?** Temporal boundaries, self-contradictions,
   alternate speakers, recency, uncertainty, versioning and TTL.
5. **How is memory secured?** Personal/guest voice isolation, sensitivity,
   local/cloud release, poisoning prevention, credential filtering,
   owner review and deletion propagation.
6. **How does voice obtain context fast?** Before the speech response,
   during a provider session, and after interruptions; does the live
   adapter really apply context safely? Could background prefetch
   reduce retrieval latency without eavesdropping?
7. **How do sensors become useful awareness?** Event-based device observations,
   trusted time/freshness, opt-in camera use, environmental uncertainty,
   consent for guests, no indiscriminate persistent recording.
8. **How can proactivity remain meaningful?** User-configured monitoring,
   salience threshold, escalation policy, quiet hours, cancellation,
   evidence of actionability and low false alarms.
9. **How do APIs/models fit local resources?** Measured memory footprint,
   embedding/RAG runtime, 24x7 idle vs active resource use, provider
   spend, latency, resilience and isolation on the owner's real desktop.
10. **How will we compare variants fairly?** Reusable fictional personas,
    hidden held-out follow-up questions, temporal updates, mixed subjects,
    genuinely missing information, personalization quality,
    reproducibility and security-critical guardrails.

## 7. A bounded research-and-decision process

No new technology implementation in this round.

1. Complete targeted architecture alternatives for each *missing* personal
   assistant requirement, using primary official docs and opposing sources.
2. Freeze a realistic fictional multi-session user-assistant evaluation suite
   with personalized-answer quality as the main outcome. Capture baseline
   JARVIS behavior first.
3. Compare minimum viable A/B/C/D workflows and map each option to existing
   code, migration effort, safety and expected ongoing cost.
4. Issue one owner-reviewable decision: keep/reuse/replace specific components,
   external adapter choices, rejected alternatives, measured uncertainties,
   interfaces, rollout flags and explicit activation gates.
5. Only then implement read-only shadow personal context; auto-write is
   **separately gated**.

**Decision quality check:** Any new research discovery must map to one of the
above requirements and demonstrate a net improvement; no framework chase and
no reset of the target experience because another product looks interesting.

## 8. Immediate research takeaway

The available techniques are sufficient to attempt a significantly more
personal, context-aware JARVIS **today**, while the exact movie-level
assistant is fictional. The central engineering difficulty is not data
storage alone but **the whole trustable memory-to-reasoning-to-action
lifecycle**. No surveyed framework independently covers owner memory,
voice, sensors, computer control, active work, permission boundaries and
proactive action to the required standard.

Keep this document as a time-stamped landscape, update it with verified new
findings, and record a final decision separately only after the specified
comparison and acceptance design.
