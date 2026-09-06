# Step 4 Phase 4.5D — Structured Query Planner Development Diagnostic Method

## Status

**Frozen development-only method. Not acceptance evidence. Does not authorize Phase 4.5E.**

The exposed V2 corpus is reused only to diagnose the newly selected structured-query architecture. No result from this diagnostic may be presented as fresh V3 acceptance evidence.

This method was corrected before any planner diagnostic output was observed: the old V2 `relation_mismatch` label measured whether one already-retrieved document answered a different relation. Under the new structured architecture, those same user queries can legitimately select the actually requested canonical relation and compare its value. They are therefore treated as resolvable relation-comparison lookups in this diagnostic, while their original V2 label is retained for traceability.

## Why this diagnostic exists

Phase 4.5D verifier experiments showed that asking a learned semantic verifier to decide whether retrieved free text may be released is the wrong trust boundary for exact current facts.

The canonical memory store already owns structured semantics:

- `subject_scope`
- `subject`
- `predicate`
- current/historical lifecycle state
- source authority
- sensitivity
- verification/freshness metadata

The new exact-fact path therefore moves semantic interpretation before retrieval:

```text
USER query
  -> replaceable MemoryQueryInterpreter proposal
  -> JARVIS deterministic grounding
  -> JARVIS MemoryQueryPolicy
  -> exact eligible-current canonical facet lookup
  -> one row: TrustedMemoryEvidence
  -> zero or multiple rows: ABSTAIN
```

The interpreter has no release authority. JARVIS does not inject canonical memory values into interpreter context; the only value-like text it may see is text the USER already supplied in the query itself.

## Research basis

This design follows two mature principles rather than inventing another learned verifier:

1. structured query / metadata-first retrieval: semantic interpretation chooses structured metadata and deterministic filtering happens before semantic retrieval;
2. complete mediation for agents: model output is untrusted tool input and application-owned policy enforces authorization and release.

Google's current Gemini structured-output guidance explicitly states that schema-valid JSON does not guarantee semantically correct values and applications must validate the values before use. The JARVIS coordinator therefore treats every model proposal as untrusted structured input and revalidates it deterministically.

References:

- https://ai.google.dev/gemini-api/docs/structured-output
- https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite
- https://ai.google.dev/gemini-api/docs/rate-limits

## One production brain selector

The diagnostic is intentionally pinned to Gemini because it is a controlled experiment. This does **not** introduce a second production provider selector.

Production JARVIS keeps exactly one active provider field:

```text
JARVIS_AI_PROVIDER -> JarvisConfig.ai_provider
```

Provider-specific adapters are implementation plugs behind that selection. Changing the production brain/provider must not require separate memory, voice, vision, or tool provider switches. CI protects this invariant.

## Frozen interpreter

For this development diagnostic only:

- provider: Gemini
- model: `gemini-3.5-flash-lite`
- adapter: `GeminiMemoryQueryInterpreter`
- request shape: **one user query per request**
- concurrency: **1**
- default request pace: **12 RPM**
- structured schema: production `MemoryQueryProposal`
- `store=False`

The request contains exactly:

```json
{
  "user_query": "...",
  "eligible_facets": [
    {
      "subject_scope": "...",
      "subject": "...",
      "predicate": "..."
    }
  ]
}
```

JARVIS must not inject canonical memory values, normalized assertion text, source IDs, provenance payloads, labels, case IDs, categories, split names, or expected memory IDs into planning context.

## Frozen JARVIS authority path

Every interpreter proposal is passed unchanged through production code:

1. `MemoryQueryGroundingPolicy`
2. `MemoryQueryPolicy`
3. `MemoryEvidenceGate`
4. `SemanticRetrievalService.retrieve_exact_current_facet`

The diagnostic must not add a research-only release rule around these components.

For an exact allowed facet:

- zero eligible current rows -> abstain;
- exactly one eligible current row -> release typed evidence;
- multiple eligible current rows -> conflict and abstain.

No Qwen embedding or reranker is used for the exact-fact diagnostic path.

## Why the old V2 database seeding cannot be reused verbatim

The old retrieval acceptance harness intentionally flattened every synthetic document to:

```text
subject_scope = owner
subject = owner
```

That representation was sufficient for free-text vector retrieval, but it is incompatible with an exact `(subject_scope, subject, predicate)` architecture because several profile fixtures legitimately share the same predicate. Reusing the flattened fixture would manufacture false canonical conflicts.

Therefore the diagnostic keeps the **exact exposed V2 query texts** but reconstructs the structured metadata already encoded by the V2 generator.

### Current V2 facts

For each `CurrentFact`:

- `subject_scope = "v2_profile"`
- `subject = CurrentFact.profile`
- `predicate = CurrentFact.predicate`
- value/text remain the existing synthetic fixture value/text
- authority = owner explicit
- sensitivity = standard
- lifecycle = current

### Historical boundary

For the selected historical fixture:

- subject is its `Ledger-NNN` entity;
- predicate is the frozen boundary predicate;
- create the previous assertion and then perform the same historical transition to the replacement current assertion.

Thus the current facet can exist while the query explicitly asks for the previous value; correct behavior remains abstention through temporal query policy.

### Forgotten boundary

Create the frozen synthetic forgotten fixture under its deterministic boundary subject, then forget it through the normal lifecycle service before building the cloud facet catalog.

### Local-only boundary

Create it with `Sensitivity.LOCAL_ONLY`. It must be absent from the cloud-eligible facet catalog.

### Secret boundary

Do not seed it into canonical memory, matching existing fixture policy.

### Untrusted boundary

Create it with `AuthorityClass.UNTRUSTED`. It must be absent from the cloud-eligible facet catalog.

## Frozen case selection: 45 total requests

Use **validation** rows from the already-exposed V2 corpus. Selection is deterministic and fixed before observing this planner's outputs.

### Direct current exact facts: 9

Select one validation release case for every:

```text
(domain in project, travel, workspace)
  x
(language in en, hi, hinglish)
```

Within each cell choose the lexicographically first `case_id` whose expected current fact belongs to that domain.

Expected final disposition for all 9: **RELEASE** the exact expected memory ID.

### Resolvable relation comparisons: 3

For the old V2 `relation_mismatch` category, choose the lexicographically first validation case for each language.

The original V2 label remains `abstain` for provenance, because the old verifier was evaluating whether a previously retrieved document answered a different relation. For the new architecture, derive the relation actually asked by the unchanged query and require the planner to select that canonical current facet.

Expected final disposition for all 3: **RELEASE** the exact memory ID of the requested relation facet. The final answer layer may compare that trusted value with the value supplied by the user; this diagnostic tests only evidence selection/release.

### True abstain cells: 33

For every remaining V2 abstain category:

- absent
- near_miss
- ambiguous
- adversarial_lexical
- negation
- unsupported_source
- historical
- forgotten
- local_only
- secret
- untrusted

and every language:

- en
- hi
- hinglish

choose the lexicographically first validation `case_id` in that category/language cell.

Expected final disposition for all 33: **ABSTAIN**.

## What is measured

Per case, persist diagnostic metadata, never query text or canonical memory value:

- case ID
- original V2 label
- diagnostic target disposition
- language
- category
- expected synthetic memory ID only for target-release rows
- proposed intent
- proposed temporal scope
- proposed facet identity when present
- whether subject reference was grounded
- whether relation reference was grounded
- grounding/policy/evidence reason
- final release/abstain
- released synthetic memory ID when applicable
- request latency

Do not persist:

- query text
- assertion value
- normalized assertion text
- external evidence text

## Development summary metrics

Report:

- total cases
- direct-release targets
- relation-comparison release targets
- true-abstain targets
- exact TP / FP / FN / TN for final deterministic release
- precision
- target release recall
- target release recall by language
- false-release IDs by category/language
- security-boundary release IDs
- interpreter intent distribution by category
- grounding abstain reasons
- query-policy abstain reasons
- exact-facet misses/wrong selections
- Gemini request latency p50/p95/max

## Frozen continuation gates

This is architecture-development evidence, not statistical acceptance. The architecture is eligible to proceed to a larger retired-data development review only if all of the following hold:

1. **zero false releases** across all 33 true-abstain cells;
2. **zero releases** from historical, forgotten, local-only, secret, or untrusted cells;
3. at least **8/9** direct exact-current cases release the expected memory;
4. **3/3** relation-comparison cases release the exact requested-relation memory;
5. each language releases at least **3/4** of its four target-release cells;
6. every released case is the exact expected canonical memory ID;
7. JARVIS injects no canonical memory value into interpreter context;
8. no Qwen model is invoked by the exact-fact diagnostic path.

Failure does not authorize lowering these gates. It identifies the next architecture problem to research.

## Interpretation rules

### Zero false releases, good target recall

The structured-query architecture remains the preferred development candidate. Inspect any target-release misses before deciding whether a larger retired-data diagnostic is necessary. Do not create fresh V3 acceptance until the method is frozen after this review.

### Any ordinary-semantic false release

Inspect the proposed intent, grounded references, and selected facet. Determine whether the problem is:

- wrong canonical facet selection;
- failure to identify a qualified/explanatory/negative query;
- cross-lingual relation mapping;
- grounding ambiguity;
- an insufficient query-intent schema.

Research mature solutions for the demonstrated failure before adding any hand-written lexicon or custom parser rule.

### Any security-boundary false release

Stop progression toward V3. The exact cause must be fixed at the deterministic authority/query-planning boundary. Do not compensate with a later semantic verifier.

## Non-goals

This diagnostic does not:

- validate real-world exchangeability;
- tune a confidence threshold;
- compare embedding dimensions;
- rerun Qwen retrieval;
- select a semantic verifier;
- alter canonical security policy;
- wire memory into `ContextAssembler` or live voice;
- authorize Phase 4.5E;
- constitute V3 acceptance.
