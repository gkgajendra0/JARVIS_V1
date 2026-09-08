# Step 4 Phase 4.5D — Final V2 Confidence Acceptance Method

Status: **METHOD FROZEN FOR IMPLEMENTATION — PHASE 4.5D ACTIVE**

Phase 4.5E remains blocked until this method produces accepted owner evidence and CI/doc closure.

## Why V1 cannot be repaired

The retired V1/V1-final evidence established that the rectangular `reranker_score AND reranker_margin` family is not merely underpowered under Holm correction: none of its 30 candidate policies met the fixed precision target when audited individually. That family is permanently rejected.

The retired 320-case development corpus then showed that a low-capacity confidence classifier using existing retrieval evidence plus the selected lightweight independent mMARCO verifier is materially stronger. Those 320 cases may train/freeze the confidence architecture, but may never again be used as final acceptance evidence.

## Current research basis

Current MAPIE binary risk-control guidance supports precision/positive-predictive-value control through `BinaryClassificationController` and Learn-Then-Test.

Precision is non-monotonic in the decision threshold. MAPIE therefore documents Split Fixed Sequence Testing (`fwer_method="split_fixed_sequence"`) as the appropriate higher-power family-wise-error-control method: first learn an ordering of candidate thresholds on data independent of the calibration set, then test that fixed sequence on calibration data.

Required separation:

```text
learn_fixed_sequence_order(X_learn, y_learn)
calibrate(X_calibration, y_calibration)
```

Reusing the same rows for both steps invalidates the guarantee. The retired 320-case development evidence is independent of the new V2 calibration set, so it is eligible to fit the fixed low-capacity classifier and learn the threshold testing order. The new V2 calibration labels are used only for statistical calibration. V2 validation labels are not used for fitting, feature selection, threshold ordering, threshold selection, or architecture changes.

Primary references:

- MAPIE risk-control API: https://mapie.readthedocs.io/en/stable/api/risk-control/
- MAPIE Split Fixed Sequence Testing precision example: https://mapie.readthedocs.io/en/stable/generated/risk_control/2-advanced-analysis/plot_split_fixed_sequence_testing_fwer_method_for_precision_control/
- Learn Then Test: Angelopoulos, Bates, Candès et al., *Annals of Applied Statistics* / earlier arXiv development of LTT risk control.

## Frozen confidence architecture

### Retrieval / ranking inputs

Unchanged accepted stack:

- `Qwen/Qwen3-Embedding-0.6B`, revision `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3`, 256d normalized;
- FTS5 lexical + exact dense cosine + equal-weight RRF;
- top 3 candidates;
- `Qwen/Qwen3-Reranker-0.6B`, revision `e61197ed45024b0ed8a2d74b80b4d909f1255473`;
- frozen JARVIS memory-specific reranker instruction.

### Independent verifier

- model: `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`;
- immutable revision: `1427fd652930e4ba29e8149678df786c240d8825`;
- query/passage cross-encoding;
- `max_length=512`;
- `trust_remote_code=False`.

### Low-capacity confidence model

Fixed feature order:

1. `rerank_score`;
2. `rerank_margin`;
3. `dense_score`;
4. `fused_score`;
5. `lexical_hit`;
6. `reciprocal_lexical_rank`;
7. `reciprocal_dense_rank`;
8. `independent_verifier_score`.

Excluded deliberately:

- language;
- case/category identifiers;
- expected-memory ID;
- labels or any validation-only metadata.

Fixed estimator:

```text
StandardScaler
 -> LogisticRegression(
      solver="lbfgs",
      max_iter=2000,
      random_state=45
    )
```

The estimator is fit only on the retired 320 development cases. The already-selected verifier may be rescored over those retired query/top-document pairs only to reconstruct the frozen 8th feature; Qwen retrieval/reranking is not rerun on the retired corpus.

Fitted scaler/model parameters must be emitted in the V2 result artifact so the exact frozen model can later be promoted only if acceptance passes.

## Statistical controller

- library: MAPIE `1.5.0` research-only;
- controlled metric: precision / positive predictive value;
- target precision: `0.95`;
- confidence level: `0.95`;
- secondary objective among valid thresholds: recall;
- FWER method: `split_fixed_sequence`;
- `learn_fixed_sequence_order(..., binary=True)`;
- candidate probability thresholds are pre-registered in code before V2 labels are exposed;
- no valid parameter is a legitimate fail-closed result.

The threshold-order learning set is the retired development set. The statistical calibration set is entirely new V2 data.

## V2 corpus size

### Calibration

`1,200` new cases:

- `600` release-labelled queries;
- `600` abstain-labelled queries;
- English, Hindi and Hinglish represented across both labels;
- adversarial/security abstain categories distributed deterministically.

### Validation

`600` completely held-out new cases:

- `300` release-labelled queries;
- `300` abstain-labelled queries;
- exactly `100` positive/release cases per language where possible by deterministic construction;
- labels never influence the calibrated threshold.

Total new V2 acceptance corpus: `1,800` queries.

## Sample-size rationale

At a `0.95` precision target and one-sided `0.05` significance level, exact binomial scale calculations for a single fixed release rule give the following minimum released-sample counts:

- 0 observed false releases: `59` releases;
- 1 false release: `93`;
- 2 false releases: `124`;
- 3 false releases: `153`;
- 4 false releases: `181`;
- 5 false releases: `208`;
- 6 false releases: `234`.

These numbers are **power/scale intuition only**; MAPIE uses its own finite-sample testing machinery and the V2 harness must accept MAPIE's result rather than substitute these counts.

The calibration positive-recall floor is `0.40`. With `600` positive calibration cases, exactly meeting that floor implies `240` true-positive releases before counting any false releases. That is intentionally well above the 59-release zero-error lower bound and remains in the useful range even when a small number of errors exists. This corrects the underpowered 96-positive V1 calibration design.

## New corpus construction constraints

The V2 generator must be deterministic and committed before the owner run.

It must provide:

- exact query uniqueness;
- no exact query reuse from the retired 64-case or 320-case corpora;
- separate V2 case IDs and result filename;
- deterministic payload SHA-256;
- current facts plus historical, forgotten, local-only, secret-prohibited and untrusted fixtures;
- absent, near-miss, ambiguous, adversarial lexical overlap, negation, relation-mismatch and unsupported-detail queries;
- English/Hindi/Hinglish coverage;
- no real credentials/secrets.

The old `.step4-phase45d-final-acceptance.json` is input only as retired development evidence. The new acceptance artifact must use a new filename and must never overwrite any exposed evidence.

## Frozen validation gates

After calibration chooses/fails to choose a threshold, V2 validation is evaluated once.

Required gates remain:

1. MAPIE finds a statistically valid threshold at precision `>=0.95`, confidence `0.95`;
2. validation positive top-1 retrieval accuracy `>=0.85`;
3. validation positive Recall@3 `>=0.90`;
4. validation observed false releases `=0`;
5. validation positive release recall `>=0.40`;
6. English positive release recall `>=0.25`;
7. Hindi positive release recall `>=0.25`;
8. Hinglish positive release recall `>=0.25`;
9. no secret/local-only/untrusted/forgotten security-boundary release;
10. no validation-driven retuning.

A failed gate rejects the frozen architecture. It does not authorize tuning on the exposed V2 validation set.

## Exchangeability limitation

The V2 corpus remains synthetic. Passing it cannot establish that future real owner traffic is exchangeable with this benchmark. MAPIE's real-world guarantee depends on that assumption. Phase-4.5D closure must therefore retain a later operational shadow-labelled risk/drift monitoring requirement rather than claiming a universal 95% traffic guarantee.

## Owner-run rule

Run V2 once only after the exact implementation SHA is green in CI. Preserve either `PASS` or `FAIL_ACCEPTANCE` as valid evidence. Do not modify the architecture and rerun the same V2 validation corpus.
