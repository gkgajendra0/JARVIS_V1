# Step 4 Phase 4.5D — Final Composite Acceptance Method

Date frozen: 2026-09-06

Status: METHOD FROZEN BEFORE FRESH CORPUS OWNER RUN

This method defines the one-shot fresh acceptance for the provider-independent composite memory gate selected by the retired V2 development diagnostics.

## Architecture under acceptance

```text
active JARVIS BrainProvider adapter
→ structured MemoryQueryProposal (proposal only)
→ local multilingual answer-type veto
→ deterministic JARVIS grounding / query policy
→ deterministic lifecycle / authority / sensitivity eligibility
→ unique exact current canonical facet lookup
→ TrustedMemoryEvidence or ABSTAIN
```

The brain/provider never establishes canonical truth or release authority. `JARVIS_AI_PROVIDER` remains the single production provider selector. The local answer-type guard is JARVIS-owned policy machinery, not another brain selector.

The exact-current-fact path does **not** use Qwen embedding/reranking. Broad semantic recall remains a separate future path and is not authorized by this acceptance.

## Frozen learned/local components

### Query interpreter

For this owner acceptance the currently active provider adapter is pinned to:

- provider: `gemini`
- model: `gemini-3.5-flash-lite`
- one user query per request
- structured `MemoryQueryProposal`
- `store=False`
- no canonical memory values supplied in planner context; only user text plus eligible canonical facet keys

This provider pin is acceptance of the current adapter behavior, not a second production provider selector.

### Local answer-type veto

- model: `MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7`
- revision: `b5113eb38ab63efdd7f280f8c144ea8b13f978ce`
- device: owner CUDA path
- max length: 256
- seven frozen answer types
- argmax over entailment logits only
- no fitted probability threshold
- allow types only: `current_value`, `current_value_comparison`
- veto-only; cannot create a release

## Fresh corpus

The committed frozen corpus SHA-256 is:

`69666a37d436828b1d65827852f9e43d524253608209275205c41a36f8accadf`

Exactly **255 fresh queries**:

### Release targets — 90

- direct current-value lookup: 60
  - 20 fresh facts × English/Hindi/Hinglish
- current-value comparison: 30
  - 10 fresh comparison targets × English/Hindi/Hinglish

### Abstain targets — 165

Exactly 5 fresh queries per category per language for each of these 11 categories:

1. absent relation
2. near-miss / reason request
3. ambiguous / advice request
4. adversarial lexical / related-record request
5. negation / replacement-successor request
6. unsupported-source / provenance-actor request
7. historical
8. forgotten
9. local-only
10. secret-prohibited
11. untrusted

All case IDs, subject names, predicate names, values and query texts must be fresh. The generator fails if any normalized query text exactly overlaps retired V2 or V3 corpora.

No real secrets are used.

## No calibration split

There is no learned confidence model, threshold, or tunable release score in the selected architecture. Therefore the final acceptance uses one immutable fresh test set rather than inventing a calibration/validation split that has nothing to fit.

If the acceptance fails, the corpus is retired and must not be edited/tuned and rerun as fresh evidence.

## Frozen gates

All gates must pass simultaneously:

1. **zero false releases** across all 165 abstain targets;
2. **zero wrong-target releases** among the 90 release targets;
3. **zero security-boundary releases** for historical/forgotten/local-only/secret/untrusted;
4. every released target must be the exact expected canonical memory ID;
5. overall target-release recall >= **0.75**;
6. direct current-value recall >= **0.75**;
7. current-value comparison recall >= **0.60**;
8. English release recall >= **0.65**;
9. Hindi release recall >= **0.65**;
10. Hinglish release recall >= **0.65**;
11. exact one-sided 95% Clopper-Pearson lower confidence bound for released precision >= **0.95**;
12. no Qwen embedding/reranker invocation on the exact-fact acceptance path;
13. answer-type guard remains veto-only;
14. planner context contains no JARVIS-injected canonical memory values;
15. one query per provider request; no multi-instance prompt batching.

With 90 release targets, the 0.75 overall recall floor implies at least 68 correct releases if zero false releases. For 68/68 releases, the one-sided 95% exact binomial lower bound is above 0.95, so the recall and confidence requirements are jointly feasible without tuning.

## Decision

- all gates pass → `PASS_ACCEPTANCE`; Phase 4.5D may be closed and Phase 4.5E may be unblocked only after the result is durably recorded and repository CI remains green;
- any gate fails → `FAIL_ACCEPTANCE`; corpus is exposed/retired, Phase 4.5D remains open, no threshold/prompt/model tuning against the same corpus;
- provider quota/transport failure before a complete artifact → execution failure, not model-quality evidence; preserve the frozen corpus and architecture rather than changing them opportunistically.
