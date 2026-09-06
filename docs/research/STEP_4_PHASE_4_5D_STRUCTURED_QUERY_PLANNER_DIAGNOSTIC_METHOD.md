# Step 4 Phase 4.5D — Structured Query Planner Development Diagnostic Method

## Status

**Frozen development-only method. Not acceptance evidence. Does not authorize Phase 4.5E.**

The exposed V2 corpus is reused only to diagnose the newly selected structured-query architecture. No result from this diagnostic may be presented as fresh V3 acceptance evidence.

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

The interpreter has no release authority. JARVIS does not inject canonical memory values into planner context; the only value-like text the interpreter may see is text already present in the user's own query.

## Research basis

This design follows two mature principles rather than inventing another learned verifier:

1. structured query / metadata-first retrieval: semantic interpretation chooses structured metadata and deterministic filtering happens before semantic retrieval;
2. complete mediation for agents: model output is untrusted tool input and application-owned policy enforces authorization and release.

Google's current Gemini structured-output guidance explicitly states that schema-valid JSON does not guarantee semantically correct values and applications must validate the values before use. Gemini 3.5 Flash-Lite remains a stable structured-output-capable model suitable for low-cost structured extraction/subagent work.

References:

- https://ai.google.dev/gemini-api/docs/structured-output
- https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite
- https://ai.google.dev/gemini-api/docs/rate-limits

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

JARVIS must not add canonical assertion values, normalized assertion text, source IDs, provenance payloads, labels, case IDs, categories, split names, or expected memory IDs to that request. A retired V2 query may itself contain one of its synthetic values; that remains user-query text and is not planner context injected from canonical memory.

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

Therefore the diagnostic keeps the **exact exposed V2 query texts and labels** but reconstructs the structured metadata already encoded by the V2 generator.

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

Thus the current facet can exist while the query itself explicitly asks for the previous value; correct behavior is still abstention through temporal query policy.

### Forgotten boundary

Create the frozen synthetic forgotten fixture under its deterministic boundary subject, then physically forget it through the normal lifecycle service before building the cloud facet catalog.

### Local-only boundary

Create it with `Sensitivity.LOCAL_ONLY`. It must be absent from the cloud-eligible facet catalog.

### Secret boundary

Do not seed it into canonical memory, matching existing fixture policy.

### Untrusted boundary

Create it with `AuthorityClass.UNTRUSTED`. It must be absent from the cloud-eligible facet catalog.

## Frozen case selection: 45 total requests

Use **validation** rows from the already-exposed V2 corpus. Selection is deterministic and frozen before observing this planner's outputs.

### Positive current exact facts: 9

Select one validation release case for every:

```text
(domain in project, travel, workspace)
  x
(language in en, hi, hinglish)
```

Within each cell choose the lexicographically first `case_id` whose expected current fact belongs to that domain.

Expected final disposition for all 9: **RELEASE** the exact expected memory ID.

### Abstain cells: 36

For every V2 abstain category:

- absent
- near_miss
- ambiguous
- adversarial_lexical
- negation
- relation_mismatch
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

Expected final disposition for all 36: **ABSTAIN**.

## What is measured

Per case, persist only diagnostic metadata, never query text or canonical memory value:

- case ID
- label
- language
- category
- expected memory ID only for positive synthetic rows
- proposed intent
- proposed temporal scope
- whether a canonical facet was proposed
- proposed facet identity when present
- whether subject reference was grounded
- whether relation reference was grounded
- grounding/policy/evidence decision reason
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
- release-label cases
- abstain-label cases
- TP / FP / FN / TN for final deterministic release
- precision
- positive release recall
- positive release recall by language
- false-release IDs by category/language
- security-boundary release IDs
- interpreter intent distribution by category
- grounding abstain reasons
- query-policy abstain reasons
- exact-facet misses/wrong selections
- Gemini request latency p50/p95/max

## Frozen continuation gates

This is architecture-development evidence, not statistical acceptance. The architecture is eligible to proceed to a larger retired-data development review only if all of the following hold:

1. **zero false releases** across all 36 abstain cells;
2. **zero releases** from historical, forgotten, local-only, secret, or untrusted cells;
3. at least **8/9** positive exact-current cases release the expected memory;
4. each language releases at least **2/3** of its three positive cells;
5. every released case is the exact expected canonical memory ID;
6. JARVIS injects **no canonical memory value fields or assertion text** into interpreter context beyond value-like text already present in the user's query;
7. no Qwen model is invoked by the exact-fact diagnostic path.

Failure does not authorize lowering these gates. It identifies the next architecture problem to research.

## Interpretation rules

### Zero false releases, good positive recall

The structured-query architecture remains the preferred development candidate. Inspect any positive misses before deciding whether a larger retired-data diagnostic is necessary. Do not create fresh V3 acceptance until the method is frozen after this review.

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
