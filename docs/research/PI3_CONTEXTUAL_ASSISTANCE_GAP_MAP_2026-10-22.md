# PI-3 contextual assistance: gap map and proposed first slice

Date:22October2026. Status: read-only code inspection and initial current-tech comparison; NOT an approved design or implementation plan. No product code, dependencies, models, provider requests or owner configuration changed. The scope is North Star PI-3, with existing PI-2qualification/merge/normal-app gates retained.

## Intended outcome

A normal personal question should obtain relevant permitted current facts and use them together for helpful advice. The owner should not repeat saved facts or name storage keys. Unknown motives/restrictions must stay unknown; correction/forget must affect later answers. First slice focuses on existing standard fact categories; durable episodes, new private categories, seamless speaker attribution and autonomous actions are separate changes.

## Existing path — reuse

`voice/personal_context.py` already implements authorized catalog/read tools, version/currentness checks, standard-only eligibility, at most4selected facts and1800value bytes, source/session/turn binding and guarded private response retirement. `voice/agent.py` already instructs the realtime model to select relevant facts and avoid unsupported inferences. `memory/live_context.py` and `memory/context.py` own bounded transient conversation context. `MemoryService`/SQLCipher, canonical conversation and Authority retain their existing state/permission ownership. No fresh memory backend or independent personal brain is needed merely to implement context selection.

## Concrete information-flow limitation

`memory/learning_reconciliation.py` creates nonscalar predicates as category plus UUID, for example owned_item_<id>. `PersonalContextSession.catalog()` currently returns only those predicate strings as selectable facets; the separate read returns predicate/text after indices have been chosen. Thus several learned owned items have distinguishable IDs but no model-visible vehicle/device/entity identity in the selection catalog. The model cannot reliably distinguish their semantic content from the opaque suffix alone. Scalar names can be meaningful and tiny catalogs can fit the4fact read bound, so this is not proof every answer fails. A normal-model selection failure has NOT been reproduced in this inspection.

The research learning evaluator reads the first up to4catalog entries directly (`tools/research/personal_auto_learning_eval.py`, current line421). Its answer comparisons measure answers given that selected context, not the realtime model's ability to choose the right entries among many unrelated learned items. Existing fixture tests likewise use explicit indices. Preserve their valid scope; do not reinterpret them as natural catalog-selection qualification.

First verification case for the eventual implementation: more than4fictional learned owned items with several vehicles/devices, mixed ordering and a question about one target. Verify what information the selector actually sees. Add correction/deletion/restart and unknown-motive questions. This separates storage correctness, context selection and answer usefulness. No inference has been run for this new case.

## Initial alternatives considered

1. **Extend existing bounded tools (recommended direction).** Keep opaque canonical identity/version internally; provide enough authorized semantic information or a structured query/filter for useful selection. Return a compact current/source-bound evidence view for the existing realtime reasoning model. Any displayed entity label is itself owner data: it needs release authorization, explicit metadata/value budgets and currentness checks. Exact descriptor-vs-query choice needs the written design and an offline information-flow comparison; do not simply expose the entire owner profile.
2. **Inject a standing profile into every conversation.** Simple prompt access, but increases unrelated disclosure/staleness/context load and conflicts with selective release. It does not remove the source/version/privacy problem. Not recommended for this slice.
3. **Adopt an external memory/agent engine.** Letta exposes persistent context memory blocks; Hindsight exposes recall/reflect. These are credible components, but introduce different state/context responsibilities and do not alone repair the missing semantics in JARVIS's current selector. Existing repo experiments remain the evidence; no new vendor bake-off/install or superiority claim is proposed. Reconsider an adapter only for a concrete larger-scale gap.

## Current primary documentation

- [LiveKit external data/tools](https://docs.livekit.io/agents/logic/external-data/) supports tool-based external context. Its on_user_turn_completed RAG example is specifically for STT-LLM-TTS pipelines; do not transplant it blindly into realtime speech-to-speech.
- [Gemini Live tools](https://ai.google.dev/gemini-api/docs/live-api/tools) documents function calling and client-returned function responses. This supports reusing the existing tool pattern, not proof that every current doc feature works on the pinned plugin/model. Repo dependencies pin LiveKit1.8.3and google-genai2.22.0; no upgrade is proposed.
- [LiveKit chat context](https://docs.livekit.io/agents/logic/chat-context/) describes managed conversation context. Adapter/currentness/privacy behavior still requires the existing JARVIS capability checks and real normal-path verification.
- [Letta memory blocks](https://www.letta.com/blog/memory-blocks/) describes persistent context blocks. [Hindsight recall](https://docs.hindsight.vectorize.io/api-reference/recall-memories/) documents semantic/spreading-activation recall. These capabilities do not establish JARVIS-specific quality or authority compatibility.

## Proposed PI-3A scope and delivery sequence

1. Establish precise current behavior and an offline failing information-flow/selection contract with multiple entities. Preserve passing single-fact/legacy behavior. This work begins only after the design's implementation prerequisites are approved.
2. Improve bounded authorized entity selection, with code-owned identities, source/version/freshness status and honest ambiguity/no-match results. Compare readable authorized descriptors with a structured query-driven projection; freeze the chosen contract and budgets before coding.
3. Deliver the selected evidence to the EXISTING realtime voice model via supported tools. Use current request plus permitted transient context. Do not add a separate HTTP reasoner on every turn, assume support from a method name, broaden session authority or retain full transcripts.
4. Make grounded multi-fact use explicit: combine relevant current preferences/possessions/goals, mark last-known data, ask only material missing details, omit irrelevant personal facts and reject instructions embedded in memory. Model reasoning produces a reply/proposal, not an automatic memory write or action permit.
5. Verify correction/forget/lock/interruption invalidation through selection and audio release. Retain OFF behavior and accepted exact-consent path. Do not silently raise4fact/1800byte/authorization limits; any metadata-release or interface change must be reviewed.
6. Test the whole normal app with learning/context enabled, using general fictional English/Hindi/Hinglish situations covering relevant multi-fact advice, unrelated questions, ambiguous entities, unknown reasons and updated/forgotten facts. Actual voice-tool selection and answer usefulness must be observed separately from fake/index-forced tests. Use a predeclared bounded provider budget and actual model quotas; no new live run is authorized by this proposal.

Expected first user-visible result: an ordinary question about a specific possession or preference reliably finds the intended current facts and uses them with another relevant fact without a manual memory-search instruction. Seamless follow-ups/durable decision episodes and situated/proactive actions are later slices with their own constraints, not silently included here.

Next design stage: present this PI-3Abehavior/scope and the alternative-selection trade-off, then write the architectural spec for owner review. The selected tool interface affects release/privacy/version semantics; it is not a prompt-only patch. Written spec and implementation plan precede product changes. No skill/process gate is marked complete by this research record.
