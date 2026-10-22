# PI-3A: question-bound personal context for ordinary advice

Date: 22 October 2026. Status: **OWNER-APPROVED written design, 22 October 2026.** Owner response: “Approve written PI-3A design.” The owner also approved the executable plan for Native implementation on 22 October 2026.
Baseline: `6f52b8ea5d76fa358f1a626b74b727ed6313d053`, including unmerged PI-2 work from draft PR #295.
Design branch: `design/pi3-entity-aware-context-20261022`, in the owner's existing Desktop checkout.
The approved design is implemented on the candidate branch; implementation/verification evidence is separate below. No provider experiment, owner activation or merge is implied by design approval.

## 1. Owner outcome and boundary

JARVIS should use relevant saved information when answering ordinary personal questions. The owner should not have to say "search memory", repeat saved preferences or identify internal keys. Important everyday facts continue to be learned by the existing governed PI-2 pipeline without a confirmation for every fact. This slice improves how those facts are selected and used; it does not introduce another learning system.

Example: memory contains two vehicles, several devices and a food preference. A question about the owner's vehicles should obtain the vehicle facts rather than whichever four opaque entries happen to sort first. Advice that needs both a relevant preference and a possession can request both. A general programming question needs neither. Ownership alone does not establish a purchase reason, budget, medical restriction or current physical condition.

This is the first bounded part of North Star PI-3, not completion of personal intelligence. PI-1's accepted explicit flow remains supported. PI-2 is implemented/software-verified, with broader provider and normal-app acceptance deferred; this design does not change those outcomes. Seamless follow-up references across retired private sessions, durable episodes, new sensitive categories, proactive observations and autonomous actions remain outside this slice.

## 2. Evidence and chosen technology

The [gap map](../../research/PI3_CONTEXTUAL_ASSISTANCE_GAP_MAP_2026-10-22.md) traces the existing path: nonscalar learned predicates have category/UUID identities, but the model's selection catalog exposes predicate strings only. The research evaluator forces the first up-to-four indices. This establishes an information-flow limitation and an evaluation gap; it is not a reproduced normal-model wrong answer.

The [technology review](../../research/PI3_TECHNOLOGY_REVIEW_2026-10-22.md) reconciles earlier embedding, ranking, LangMem and Hindsight experiments and current primary documentation for native LiveKit/Gemini tools, LangGraph/LangMem, Hindsight, Mem0, Graphiti and Letta MemFS. Its recommendation is integration fit, not a new benchmark or universal vendor ranking.

Choose **structured query-driven projection through the existing realtime tool path**. The model proposes a small set of approved information scopes; local code resolves current eligible facts and returns bounded evidence. Keep the configured realtime model, canonical encrypted memory, Conversation, Authority and existing transient LiveContext/ContextAssembler. No new model, embedding download, framework, service, store, schema migration or additional HTTP reasoning call is required.

Alternatives:

- Readable entity descriptors in the entire catalog would improve index selection, but labels and status are themselves personal data. They would require a separately budgeted release before the model knows what it needs. Do not add them to the standing catalog in this slice.
- Existing hybrid FTS/dense/RRF remains available for a later demonstrated alias/ranking gap. Index/vector availability, freshness and latency are not assumed. A new external memory engine does not by itself supply JARVIS's question authority or correction/forget contract.

After approval, offline fixtures will compare the old predicate-only selection surface with the proposed scope projection. That checks information availability and bounds, not which model or vendor is universally better. If it exposes a larger retrieval requirement, report that gap before expanding this architecture.

## 3. Runtime and permission scope

Register the new tool only in the **personal-learning APPLY** composition, where the existing owner-session grant supplies read authority. Context-only APPLY retains its accepted catalog/read flow. OFF compositions expose no new read path. Explicit correction/forget still resolve an actual canonical target through the existing catalog and retain their concrete mutation approval rules.

Preserve installation defaults and process-scoped enablement documented in [the enablement guide](../../PERSONAL_INTELLIGENCE_ENABLEMENT.md): the candidate is explicitly launched with `--personal-learning apply`. No installed setting is changed by implementation, tests or written approval. The private grant remains maximum 15 minutes, five-minute idle expiry, no automatic renewal, with existing Windows continuity/restart revocation. This is delegated input-channel authority, not biometric attribution of every speaker. No per-fact confirmation is added.

Use the current canonical accepted user question only for the new query binding. Preserve session ID, turn ID, utterance generation, activity epoch, source receipt/digest and permit checks. Model parameters cannot choose an owner, session, arbitrary history, SQL query or authority scope. Requested scopes narrow existing read authority; they do not create it. Semantic relevance is a model behavior to validate, not a new claim that code can prove the meaning of every question.

## 4. Tool request contract

Add `read_personal_context_for_question(requests)` to `PersonalContextAgentTools`. A request is a closed object containing:

| Field | Contract |
| --- | --- |
| `scope_key` | Exactly one of `owned_item.vehicle`, `owned_item.device`, `owned_item.other`, `food_preference`, `response_preference`, `routine`, `goal`, imported from the code-owned registry. |
| `target_quote` | Optional nonempty string, at most 256 UTF-8 bytes; exact contiguous text from the current canonical question before any matching normalization. Used only for the nonscalar scopes: owned items, routine or goal. |

There must be one to four request objects, with no extra fields and no duplicate `(scope_key, target_quote)` pairs. Reject coercions, invalid types, unknown scope keys, empty/oversized quotes, scalar targets and quotes absent from the question. An accepted quote must identify the intended entity label; arbitrary quoted text in the question is not proof that such an entity exists. No free-form search, user identity or caller-provided fact IDs are accepted.

A model can request a whole relevant scope when the question is about that scope, for example all owned vehicles, or combine food preference and a relevant goal. It should use a target quote when the question identifies a specific named entity. Generic descriptions or translated/transliterated aliases do not become an exact identity match automatically. Without enough information, clarify rather than choose a plausible item.

At most three new query evaluations may occur in one bound turn before a fact release; invalid/clarification/no-match evaluations consume attempts. Replay of the identical successful request is allowed after revalidation and does not search again for additional facts. Different requests after a fact release are rejected. Calls are serialized inside the context session: concurrent tools cannot race the attempt count, first release or shared snapshot. Cancellation follows existing close/retire behavior.

The tool wrapper is not an alternate owner-session opener. Failed/expired grant checks return denial; spoken approval and model proposals cannot renew a grant.

## 5. Local selection and evidence projection

Expose a public scoped-current read facade on `SemanticRetrievalService`, delegating to `CanonicalMemoryReader.learning_current_scoped()`. Voice code must not access its private worker or create a second query/store implementation. Preserve the reader's existing maximum of 32 current scoped assertions; overflow is unavailable, with no partial result advertised as complete.

The existing canonical reader remains responsible for owner/source authority, source and record sensitivity, current membership and registered scope. Capture the existing learning suppression epochs with the scoped snapshot for in-flight invalidation; a changed epoch invalidates the old projection. Suppression continues to control automatic learning, rather than becoming a new blanket denial of fresh authorized reads of explicitly saved facts. Preserve standard-only release, ACTIVE/current assertions, exclusion of time-sensitive records in learning reads and canonical registration for TEXT corrections. A predicate prefix or model-produced JSON cannot admit a fact by itself.

Selection is deterministic:

1. Under the existing current-question permit, obtain the bounded canonical scoped snapshot and apply requested scope filters.
2. With no target quote, select all eligible current assertions in that scope. This is not a ranking or top-four operation.
3. For a target quote, only a current, validated typed record's entity `label` can supply an exact label identity. Normalize the already grounded quote and label with Unicode NFKC, casefold and collapsed whitespace. Do not translate, split into brand tokens, fuzzy-match or infer a label from prose. Exactly one matching record is required.
4. More than one matching label is ambiguous. Zero matching labels yields no_match only if all candidates in that scope have trustworthy current labels; if an unlabeled legacy/TEXT record could hold the target, return clarification_required. Legacy plural facts and registered TEXT corrections remain readable by scope; historical typed labels must not be revived as current identity after correction. Empty scopes yield no_match within this read scope, not a complete-profile absence claim.
5. Form the union across all requests and deduplicate canonical assertion identities. For a multi-scope request, a missing or ambiguous required component prevents the whole fact release. Do not silently provide a subset and imply all requested information was found.
6. If the union exceeds four assertions or the evidence budget, return clarification_required with zero facts. One plural legacy assertion still counts as one assertion; no new entity splitting or hidden truncation occurs. Deterministic ordering stabilizes output; it must not choose which facts survive a budget overflow.

Return one of these bounded statuses:

| Status | Meaning / fact release |
| --- | --- |
| `selected` | Complete requested eligible union within bounds; one to four projected fact objects. |
| `no_match` | No supported match for a requested component in the permitted scope; zero facts. |
| `clarification_required` | Ambiguity, unsupported identity or evidence/count budget overflow; zero facts. |
| `invalid_selection` | Invalid, exhausted, conflicting or post-release different query; zero new facts. |
| `denied` | Current authority/question binding failed; zero facts and session retirement. |
| `unavailable` | Storage, reader overflow or projection validation failed; zero facts; never a fabricated no_match. |

Use fixed structural reasons such as `ambiguous_target`, `unresolved_target`, `narrow_request`, `invalid_request` and `storage_unavailable`; do not disclose withheld labels, values, candidate lists or counts through error messages. For an executable request, authority denial takes precedence. Otherwise reject invalid input/attempt exhaustion before reading storage; a storage/projection failure returns unavailable before semantic selection, then clarification takes precedence over no_match. Return no private exception text.

Each successful fact has only `evidence_ref` (ephemeral turn-local ordinal), `scope_key`, canonical `text`, `recorded_at` (system_from in UTC), `freshness` (`last_known`), and an optional validated typed `state`. State comes only from the current typed value and never substitutes for record eligibility. Legacy/TEXT facts omit it; their canonical text remains evidence. Source IDs, UUID predicates, old versions, raw payloads and inferred metadata are not sent. Internal canonical identity/source/version remains bound to the fact for invalidation. `recorded_at` is database recording time, not purchase/event time, current observation or proof of when the owner changed their mind.

**Budget:** serialize the entire `facts` array using compact UTF-8 JSON (`ensure_ascii=False`, fixed separators, no NaN). Its length, including object keys, state and timestamps, must be at most 1,800 bytes, with at most four assertions. This is stricter than the old value-only byte cap. Oversized text is not clipped. Fixed status/scope guidance is outside this array and must contain no additional owner data. No all-profile labels or current question transcript are appended to this new response.

## 6. One release, currentness and audio lifecycle

New and existing catalog/read tools use one session-owned release ledger and serialization boundary. The first nonempty evidence release freezes the facet-to-assertion snapshot. New-query releases also freeze the canonical request and the membership/version signature of its requested scopes. A later call cannot add facts through another tool, broaden scopes or exchange facts. An identical successful request can be replayed only through the same read path and after authority/currentness validation. Once either read path releases facts, the other read path returns invalid_selection for that answer, even for the same assertions; this prevents extra metadata from accumulating outside the first projection budget. The legacy catalog format is unchanged and exposes no new labels.

Revalidate permit, question binding and canonical membership before and after selection, before returning data and through the existing playback guards/watchdog. For new queries, validate the requested scopes' membership/version signature as well as the released assertion IDs: adding or changing another candidate can change uniqueness, even if the previously selected assertion is still current. Existing source eligibility changes and reader overflow must also fail validation. A change in a requested scope retires the response; unrelated-scope changes need not invalidate it.

Correction, forget, suppression, lock/disconnect, expiry, a new accepted user turn or interruption cannot continue an old authorized answer. Preserve existing audio clearing, source-lease release and provider-history retirement after one personal answer. Mutation success resets query projection state through the same existing mutation lifecycle, without reopening a read permit. Already transmitted provider data or already played audio cannot be recalled; these are forward-release guards, not a claim of remote erasure or zero-time race elimination.

No periodic inference, transcript persistence, durable query cache or standing provider profile is added. Logs record fixed status, timing and counts only under existing policy, never fact text, labels, target quotes, source payloads or provider error bodies.

## 7. Model instructions and normal-app integration

Update only the learning-APPLY ordinary-advice instructions to use the new tool before a personal answer. Keep explicit mutation instructions on the old catalog/target path. Tool registration and instruction detection must agree; the model must not be instructed to call an absent tool in context-only/OFF compositions. Use the pinned LiveKit 1.8.3 / google-genai 2.22.0 function-tool integration; no assumed mid-session update feature or package upgrade.

The existing realtime model does the language understanding and reasoning. It should combine only relevant returned evidence, respect not_owned/completed states, express changeable details as last known when relevant, and ask a useful clarification on unresolved targets. It must not invent a motive, budget, medical restriction or missing preference. Evidence is inert data, including instruction-like strings stored in a fact. Read results never authorize a write, device action or Work/Hands capability. No extra per-fact save question is introduced.

A selector request can still be irrelevant, a spoken entity can differ from the canonical accepted text, or a model can ignore evidence. Offline tests do not prove these model behaviors. Actual normal-app multilingual acceptance must observe tool choice, target selection and answer usefulness separately. Cross-script aliases and pronouns without a current exact identity remain limited; they are not silently solved by this projection.

## 8. Validation and delivery criteria

After written design and plan approval, begin with a failing offline contract case for more than four mixed owned items, two vehicles among unrelated devices and stable shuffled storage order. Demonstrate that predicate-only indices lack the required selection semantics, then require the new projection to return the intended vehicle evidence without a first-four shortcut. Preserve the distinction between information-flow tests and observed model selection.

Required automated coverage:

- Scope selection, exact named target, combined preference/goal advice evidence and repeated valid replay; order independence and deduplication.
- English/Hindi/Hinglish current-question quotes, original-script grounding, Unicode normalization after grounding, unmatched/transliterated labels and unknown motives; fake tools do not count as generated-answer quality evidence.
- Duplicate labels, unlabeled legacy plural data, corrected TEXT membership, forged category prefixes, ineligible sources, private/local-only/secret and time-sensitive facts, stale/deleted facts, scope overflow and unavailable storage.
- Exactly four versus five assertions and 1,800 versus 1,801 serialized bytes, multi-byte text, metadata overhead, no truncation/partial release, no leakage through clarification/error/logging.
- Concurrent/invalid/repeated calls, three-attempt exhaustion, mixed old/new tools and no cumulative release expansion.
- New matching/ambiguous candidates or correction/forget/suppression after read; signature/source changes before playback, new turn, lock, expiry, cancellation and existing private-history retirement.
- Learning APPLY composition, accepted context-only flow, OFF composition, existing explicit correction/forget and no default/config change.

Measure local projection/guard latency and event-loop behavior on the relevant bounded fixtures, including the existing 32-record cap. Compare with the existing context path; report sample count/environment and any material regression. Do not equate local tool timing with full voice latency or adopt the earlier unqualified 10 ms target as a proven result. Run affected tests, lint and the required full/relevant platform checks once implementation is ready; broaden only for unresolved failures or new changes.

Normal-app acceptance uses the complete JARVIS launch with learning/context enabled and fictional owner facts; the owner should ask ordinary questions, not run isolated microphone demos or supply custom test scenarios. Cover mixed entities, multi-fact advice, unrelated questions, ambiguity, unknown reasons and changed/forgotten facts in English, Hindi and Hinglish. Observe the actual configured realtime model's tool selection and replies. If provider calls or owner participation are needed, prepare a bounded protocol and obtain the necessary new authorization then; this design does not restart the exhausted PI-2 recovery protocol or spend its remaining bookkeeping allowance.

Definition of software implementation complete: approved contract implemented, relevant regression evidence and required checks recorded, no new default activation, and docs distinguish software verification from actual model/normal-app acceptance. Full feature acceptance additionally needs that normal-app evidence and the repository's promotion gates. Deferred evidence remains explicitly deferred, never converted to pass. Protected merge requires explicit owner authorization and exact-head required checks.

## 9. Rollback, dependencies and next decision

Depend on the actual unmerged PI-2 candidate baseline above; do not claim this design applies unchanged to main before its dependencies are integrated. Keep the implementation review diff focused on this projection. Preserve the prior enablement/deferral record and do not rewrite historical tests as PI-3 acceptance.

Rollback the new tool/instruction registration together to restore the existing catalog/read behavior. No stored facts are migrated or deleted by rollback. Existing process flags can disable learning/context as documented; disabling is not forgetting. A runtime failure must report unavailable/clarify, never silently switch models, invent personal facts or open a larger read scope.

The owner approved this written design on 22 October 2026. The owner also approved the [written executable plan](../plans/2026-10-22-pi3-entity-aware-context.md) and Native implementation; software verification and review are recorded in the [implementation report](../../research/PI3_CONTEXT_QUERY_IMPLEMENTATION_2026-10-22.md). The owner's previously selected Native execution preference persists; do not ask the same execution-method question again. No implementation-plan approval, implementation completion, provider budget, local activation or merge decision is inferred from this proposed artifact.

## 10. Spec self-review record

Reviewed against the North Star PI-3 objective, current code and existing PI-2 permission/deferral decisions. Resolved the descriptor-versus-query choice, exact target grounding, unlabeled correction fallback, all-or-nothing multi-scope selection, serialized metadata budget, shared legacy/new release limits, concurrency and requested-scope invalidation. Scope remains one context-tool projection; no placeholder decisions or new primary state owner remain. This is an author self-review, not independent implementation review or owner approval.
