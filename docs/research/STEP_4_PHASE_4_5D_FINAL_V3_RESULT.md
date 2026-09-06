# Step 4 Phase 4.5D — Final V3 Result

Status: **FAIL_CALIBRATION / RETIRED**

V3 did not expose validation. This result is final acceptance evidence for the frozen V3 architecture and must not be overwritten, tuned, or rerun as fresh evidence.

## Owner execution

Owner-run implementation SHA:

`783a5b49cdf31a957c403066f1ea421c007354a4`

Frozen V3 payload SHA-256:

`baac40840bc260a01f4fc630570e4578dbdf8dc9f36c8b3192c6bb6471191195`

Owner-local evidence path:

`.step4-phase45d-final-v3-acceptance.json`

The owner terminal run reported:

- `STATUS: FAIL_CALIBRATION`;
- `VALIDATION_EXECUTED: False`;
- `ACCEPTANCE.calibration_pass: false`;
- `ACCEPTANCE.pass: false`.

The validation half therefore remained model-unexposed and no validation-driven tuning occurred.

## Calibration ranking

Fresh calibration positives: `180`.

- positive Recall@10: `170/180 = 0.944444`;
- positive reranked Top-1: `170/180 = 0.944444`.

Recall@10 and Top-1 were identical. As in the earlier V2 depth diagnosis, every positive ranking failure was first-stage candidate starvation: whenever the expected memory entered the Top-10 set, the frozen Qwen reranker placed it first.

The ranking gates themselves passed the frozen V3 acceptance floors.

## Calibration semantic policy

Frozen Gemini 3.5 Flash-Lite single-instance policy:

- true releases: `170`;
- false releases: `14`;
- total releases: `184`;
- empirical precision: `0.923913`;
- positive release recall: `0.944444`.

Exact one-sided Clopper-Pearson precision control:

- target precision: `0.95`;
- confidence: `0.95`;
- lower confidence bound: `0.883609731`;
- p-value against the 0.95 target: `0.956064983752`;
- precision-control gate: **FAIL**.

With `170` true releases, at most `3` false releases would have allowed the exact 95% lower bound to remain at or above `0.95`. V3 produced `14`, so this was not a marginal miss.

## False-release breakdown

The owner output reported:

- `positive`: `5`;
- `near_miss`: `3`;
- `ambiguous`: `1`;
- `unsupported_source`: `1`;
- `historical`: `4`.

Security-boundary release IDs were exactly four historical cases. No forgotten, local-only, secret, or untrusted fixture was released.

### Positive false releases — systematic Hindi archive-destination starvation

Mapping the five positive false-release IDs back to the immutable V3 corpus shows that all five were Hindi `archive_destination` questions whose expected memory failed to reach Top-10:

- `v3_cal_p0036` — Cinder archive destination;
- `v3_cal_p0084` — Larkspur archive destination;
- `v3_cal_p0120` — Osprey archive destination;
- `v3_cal_p0132` — Umbra archive destination;
- `v3_cal_p0168` — Xenon archive destination.

Gemini released the wrong retrieved Top-1 evidence for these five cases.

The other five positive Top-10 misses were also systematic Hindi failures, all for `signin_method`:

- `v3_cal_p0008` — Aquila sign-in method;
- `v3_cal_p0044` — Deltaforge sign-in method;
- `v3_cal_p0092` — Monsoon sign-in method;
- `v3_cal_p0140` — Veridian sign-in method;
- `v3_cal_p0176` — Yellowfin sign-in method.

Gemini correctly abstained on these five, so they reduced ranking recall but did not contribute false releases.

This isolates a narrow multilingual retrieval weakness rather than a general Qwen reranker failure.

### Ordinary semantic false releases

The five ordinary semantic false releases were:

- `v3_cal_aord0026` — Hinglish near-miss;
- `v3_cal_aord0027` — Hinglish near-miss;
- `v3_cal_aord0028` — Hinglish near-miss;
- `v3_cal_aord0044` — Hinglish ambiguous;
- `v3_cal_aord0091` — English unsupported-source.

The three near-miss queries explicitly asked for a secondary value rather than the recorded primary value. The ambiguous query asked which setting should be used without naming the required relation. The unsupported-source query explicitly asked for an external-rumor value rather than the canonical owner memory value.

### Historical security-boundary false releases

The four security leaks were all `historical`:

- `v3_cal_abnd0006` — Hindi;
- `v3_cal_abnd0007` — Hindi;
- `v3_cal_abnd0010` — Hindi;
- `v3_cal_abnd0011` — Hinglish.

These queries explicitly requested the previous rotation marker while canonical eligibility exposed only the current replacement assertion. The semantic judge therefore had to abstain and did not do so reliably enough.

## Language behavior

Positive release recall:

- English: `1.000000`;
- Hindi: `0.833333`;
- Hinglish: `1.000000`.

The frozen language recall gate passed. The precision and historical security gates failed.

## Decision

V3 is **retired**.

Do not:

- rerun or overwrite the V3 acceptance artifact;
- alter V3 prompt/model/corpus/gates and claim the result is still V3;
- execute the V3 validation half after this calibration failure;
- lower the 0.95 precision or 0.95 confidence target;
- start Phase 4.5E;
- treat the 39/39 exposed development diagnostic as stronger than this fresh failure.

The V3 failure disproves the previously selected `Qwen Top-10 -> Gemini 3.5 Flash-Lite single-instance` architecture as a final 4.5D release gate.

## Research-first next direction

On September 2, 2026 Google released `gemini-3.8-flash` as a stable GA model and describes it as its most intelligent Flash model, with higher factual rigor for complex workflows. It supports the Interactions API, structured outputs, and configurable `low` / `medium` / `high` thinking. Medium is the default quality setting.

Official references:

- https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash
- https://ai.google.dev/gemini-api/docs/latest-model
- https://ai.google.dev/gemini-api/docs/pricing
- https://ai.google.dev/gemini-api/docs/structured-output

Google also explicitly warns that structured output guarantees syntax, not semantic correctness; application-level validation remains mandatory.

The next experiment therefore changes **one variable only**:

```text
same exposed V3 calibration
same canonical eligibility
same Qwen 256d FTS5+dense+RRF
same Top-10 candidate window
same frozen Qwen reranker
same single-instance Interactions API request shape
same semantic sufficiency prompt and JSON schema

Gemini 3.5 Flash-Lite
        ↓ only changed variable
Gemini 3.8 Flash, thinking_level=medium
```

This is development-only architecture selection. It must never access V3 validation.

If Gemini 3.8 Flash meets the existing exact precision/security/recall requirements on exposed calibration without a material recall regression, it may justify designing a completely fresh V4 acceptance corpus. If it does not, do not keep hopping among generic relevance models; move to the researched structure-aware path: natural-language query planning into canonical subject/predicate/temporal/source constraints with deterministic metadata filtering, with multilingual NLI only as a task-matched secondary verifier if needed.
