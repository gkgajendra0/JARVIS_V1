# JARVIS Personal Intelligence — Repository Audit (2026-10-18)

**Status: DOCUMENTATION-ONLY AUDIT / no implementation authorized.**
**Baseline:** protected main at \`632a7ac88305a03eed21c03624a3ba58ebe71f8f\`, observed 2026-10-18.
**Scope:** current repository documentation and inspected production code paths.
**Owner intent:** personal context and genuinely personalized life assistance are the
primary user-facing reason to build JARVIS; project management and self-repair support
that purpose, not define it. The authoritative clarified requirements are Section 17
of \`docs/AUTONOMOUS_SELF_MANAGEMENT_MASTER_PLAN.md\` and the new product behavior
contract in \`docs/PRODUCT.md\`.

## 1. Documentation authority and preexisting scope

- \`docs/PRODUCT.md\` is the durable product contract; \`docs/AUTONOMOUS_SELF_MANAGEMENT_MASTER_PLAN.md\`
  is the constitutional operating North Star. Its Section 15 explicitly says **do
  not create competing North Star documents**. This audit is evidence, not a new North Star.
- \`docs/UNIVERSAL_KNOWLEDGE_AND_DISCOVERY_MASTER_PLAN.md\` is a subordinate advanced
  intelligence program; it must not displace personal assistance.
- \`docs/ROADMAP.md\` identifies bounded Step 4 memory/context (CAP-008–013) and
  the next numbered Step 8. \`docs/CURRENT_PLAN.md\` owns active implementation
  scheduling. This documentation PR does not silently change accepted sequence.
- \`docs/CURRENT_ARCHITECTURE.md\` and \`docs/PROJECT_STATE.md\` represent
  accepted/deferred production truth; proposals and isolated research cannot be
  described as running features.

## 2. Confirmed existing production/substrate capabilities

| Area | Inspected evidence | Implication |
| --- | --- | --- |
| Canonical memory | \`src/jarvis/memory/runtime.py\`, \`service.py\`, \`query.py\`, \`retrieval.py\`; Step 4 acceptance record | SQLCipher canonical memory with explicit remember/correct/forget/inspect and limited searchable assertions exists; reuse it. |
| Live context | \`src/jarvis/memory/live_context.py\`, \`context.py\` | Typed transient goals/topics/recent turns and budgeted packet assembly exist. No need to create a second session-memory owner. |
| Provider release | \`src/jarvis/memory/query_coordinator.py\`, \`provider_verified_query.py\`, \`release_guard.py\`, \`evidence_gate.py\` | Bounded eligible fact release with explicit planners/gates exists. It is not a general-purpose personal knowledge answerer yet. |
| Voice memory tools | \`src/jarvis/voice/memory_tools.py\`, \`agent.py\`, \`production_runtime.py\` | Voice offers explicit storage/inspection and optional \`recall_memory\`; the semantic tool resolves the latest accepted user turn and may abstain; it is not automatic broad context injection. |
| Candidate extraction | \`src/jarvis/memory/candidate_runtime.py\`, \`src/jarvis/voice/production_runtime.py\` | Model candidate extraction is optional, session-scoped quarantine/shadow; no approved implicit durable admission. |
| Context sync | \`src/jarvis/voice/context_adapter.py\`, \`context_sync.py\` | Provider-specific context update policy is modeled. Actual safe mid-session provider behavior and context insertion need end-to-end proof. |
| Work truth | \`src/jarvis/work/store.py\`, \`dbos_backend.py\`, \`engine.py\`, \`reasoner.py\`; Current Architecture | Durable WorkItem/Step state, recovery and bounded tool reasoning exist, but do not constitute personal intelligence. |
| Work context | \`src/jarvis/work/context.py\`, \`context_knowledge.py\`, \`context_evaluation.py\`; C6 research | WorkContextPack projection and quality comparison exist; default shadow, not authorized full apply. |
| Wider capabilities | Product catalogue, Current Architecture and GICC design | Voice, camera, device/Hands, research, identity/Authority and learning foundations can supply *permitted* contextual signals later. Not every roadmap vision is deployed. |

## 3. Gaps and blockers verified against acceptance records

1. **Automatic personal memory admission is not production-approved.**
   \`docs/STEP4_CORE_ENCRYPTED_MEMORY_OWNER_ACCEPTANCE_2026-10-15.md\` explicitly
   accepts encrypted explicit storage but defers natural-language semantic recall
   owner-machine proof and forbids automatic/implicit admission.
2. **Automatic conversational memory context injection remains disabled.**
   \`docs/CURRENT_ARCHITECTURE.md\` identifies deferred strict 4.5D verification,
   unaccepted complete shadow resource-profile gate for 4.5E.1, rejected Qwen
   utility/steering influence gate 4.5E.2 and disabled automatic 4.5E injection.
3. **Cross-session personalized response quality is unproven**: no accepted
   whole-assistant measurement that personal memory improves advice in daily
   life, handles correction/temporal truth and maintains privacy.
4. **A memory query currently targets tightly eligible current facts.**
   \`src/jarvis/voice/memory_tools.py\` describes \`recall_memory\` as retrieving
   one current personal fact using the latest grounded user question; advice,
   episodes, disputed facts and broad recall need separate safe design.
5. **Provider/model operational issues are documented**: Step 4 acceptance
   observed structured-planner HTTP 429/503 and a separate owner-turn grounding
   denial for inspect. Neither proves the entire memory architecture deficient.
6. **WorkContext C6 is separate from everyday personalization**:
   \`src/jarvis/work/engine.py\` constructs WorkContextPack but default mode is
   SHADOW. \`reasoner.py\` still sends legacy Work payload in that mode. C6
   must not be conflated with live owner-personal memory.
7. **Source diversity isn't fully composed** into a single context-selection
   decision across authorized personal memory, transient conversation, live
   observations and optional task state.
8. **Memory utility, safety and resource consumption at realistic scale are
   unmeasured** on natural cross-session owner-assistant workflows.

## 4. Explicitly separate research from production

Isolated Step 7–10 Hindsight research (draft PRs and owner-local disposable
fictional banks) compared retrieval methods. The latest 240-fact synthetic
test supplied question scope/intent and measured rule-based structured decisions,
not autonomous natural extraction, actual personalization, user-facing answer
quality or production integration. Even strong Hindsight recall does not
authorize replacing canonical memory or turning on automatic injection.

## 5. Required end-to-end audit before implementation

Trace with call sites and fixture tests:
- canonical accepted USER turn -> live-context packet -> voice provider history;
- explicit memory write/correction/forget -> SQLCipher rows/indexes;
- memory query -> eligibility -> provenance/release checks -> tool result;
- any automatic candidate extraction -> quarantine/consent/admission (currently shadow);
- actual realtime provider context synchronization; initial vs mid-session behavior;
- Work context shadow/apply; quality decisions and rollback;
- identity/speaker rules; personal/guest separation; local-only sensitivity;
- cancellation, restart, transcript lifecycle, data removal and retention;
- model, CPU/RAM, 24x7 latency and ongoing provider cost.

Unknowns must remain **unknowns** until observed, not inferred from a config
flag or imported code. User-approved private tests require separate authorization.

## 6. Working research hypothesis, NOT final architecture

Aim for one **JARVIS-owned personal-context policy and assembly boundary**
composing existing canonical SQLCipher owner memory, transient session context,
eligible episodic/decision history and current authorized observations;
external retrievers (including Hindsight) may be optional, rebuildable adapters.

Prioritize first a **read-only**, fail-closed, contextual personalization
shadow path. Measure against a frozen fictional-persona multi-session test set
before any provider input changes. Natural memory admission is a distinct
future phase and must never be silently enabled to make demos look impressive.

This is a hypothesis for comparative architecture research, not approval
of new runtime code.

## 7. Auditable first delivery outcome

A fictional persona says on day 1 that they are vegetarian, have a stated
goal and own a particular vehicle; later changes a preference. On day 8,
after restart, they ask open-ended food, purchase and travel questions.
JARVIS should use only relevant current evidence and produce materially
more useful, properly qualified, safe answers **without requiring explicit
recall commands**. It should detect when live prices, medical data or
permission are missing rather than improvising.

The evaluation must compare default/no-context vs proposed context, include
hidden holdout scenarios, measure latency and costs, and report all privacy
failures. Only later, with explicit owner consent and safety gates, use
eligible owner-machine real personal memory.

## 8. Immediate next step

Research the **complete movie-inspired personal-assistant experience**:
memory capture/admission, temporal/relation memory, retrieval/context
assembly, real-time voice/vision integration, dependable execution,
proactivity, privacy, operational costs and verified quality. Compare
credible approaches at an architectural layer using a fixed evaluation
matrix. Record rejected alternatives and uncertainty *before* committing
a memory engine or activation plan. Do not start implementation from this
documentation-only PR.
