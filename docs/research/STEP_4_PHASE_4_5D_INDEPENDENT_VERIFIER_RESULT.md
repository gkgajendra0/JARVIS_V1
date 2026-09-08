# Step 4 Phase 4.5D — Independent Verifier Development Result

Status: **DEVELOPMENT EVIDENCE ONLY — NOT FINAL ACCEPTANCE**

Phase 4.5D remains active. Phase 4.5E remains blocked.

## Owner environment

The owner ran `tools/research/step4_phase45d_independent_verifier_bakeoff.py` against the already exposed/retired 320-case Phase-4.5D artifact. The run did not rerun Qwen retrieval and is not eligible for final acceptance.

Independent verifier:

- model: `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`;
- immutable revision: `1427fd652930e4ba29e8149678df786c240d8825`;
- batch size: `32`;
- max length: `512`;
- device: CUDA / NVIDIA GeForce RTX 5060 Ti;
- Torch: `2.13.0+cu132`;
- CUDA runtime: `13.2`;
- peak CUDA allocation: `531,291,648` bytes;
- first model load/download: approximately `141.6809 s`;
- scoring 320 query/document pairs: approximately `0.5169 s` (`1.6153 ms/pair`).

The long first load was model download/cache setup; measured pair scoring itself was cheap.

## Raw verifier signal

- ROC-AUC: `0.795422`;
- average precision: `0.835098`.

Safe verifier score:

- min `-3.70056`;
- median `5.320145`;
- max `10.763732`.

Unsafe verifier score:

- min `-9.552159`;
- median `-0.320412`;
- max `6.50275`.

The verifier is not a replacement for the Qwen retrieval evidence. Its value is as an independent/orthogonal signal.

## Out-of-fold confidence comparison

All learned results used five-fold stratified out-of-fold prediction on the retired development data. Language/category/case identifiers and expected-memory identifiers were excluded from learned features.

### Existing retrieval evidence only

Features:

- reranker score;
- reranker margin;
- dense cosine;
- fused RRF score;
- lexical-hit indicator;
- reciprocal lexical rank;
- reciprocal dense rank.

Result:

- ROC-AUC `0.892574`;
- average precision `0.885079`;
- best development point at empirical precision >= `0.95`: threshold `0.893408`, `47 TP / 2 FP`, precision `0.959184`, positive release recall `0.295597`.

### Independent verifier only

- ROC-AUC `0.793859`;
- average precision `0.833733`;
- best development point at empirical precision >= `0.95`: threshold `0.769`, `66 TP / 3 FP`, precision `0.956522`, positive release recall `0.415094`.

### Existing evidence + independent verifier

Features are the seven retrieval features above plus the mMARCO verifier score.

Result:

- ROC-AUC `0.895972`;
- average precision `0.910776`;
- best development point at empirical precision >= `0.95`: threshold `0.817936`;
- released `91`;
- TP `87`;
- FP `4`;
- precision `0.956044`;
- positive release recall `0.547170`.

This materially improves development release recall from `29.56%` to `54.72%` at approximately the same empirical precision requirement.

## Development language result

- English: positive release recall `0.462963`; false release `fcal_a049`;
- Hindi: positive release recall `0.769231`; false release `fval_a037`;
- Hinglish: positive release recall `0.396226`; false releases `fval_a021`, `fcal_a050`.

The pre-registered development floors were cleared:

- empirical precision target `0.95`;
- overall positive release recall floor `0.40`;
- per-language positive release recall floor `0.25`.

Harness recommendation: `independent_signal_promising` / `combined_oof_signal_clears_pre_registered_development_gates`.

## Decision

The lightweight mMARCO verifier is the selected independent signal for the next Phase-4.5D acceptance architecture. The deferred BGE reranker is **not** justified at this point.

Candidate architecture to freeze before new acceptance data:

```text
canonical eligibility
 -> FTS5 + Qwen dense
 -> equal-weight RRF
 -> top-3 Qwen reranker
 -> returned top memory
 -> independent mMARCO query/passage verifier
 -> StandardScaler + low-capacity LogisticRegression confidence score
 -> statistically controlled precision release/abstain threshold
```

This decision does **not** accept Phase 4.5D. The 320 source cases are exposed and permanently retired from final acceptance.

## Permanent methodological constraints

- no retired-case metric or threshold is production acceptance evidence;
- no final-validation label may affect model fitting, features, threshold choice, or architecture;
- final validation may reject the frozen system but may not tune it;
- the `0.95` precision target and `0.95` confidence target remain unchanged;
- overall release recall floor remains `0.40`;
- EN/HI/Hinglish release-recall floors remain `0.25` each;
- canonical eligibility/security filtering remains authoritative and occurs independently of learned confidence;
- synthetic acceptance evidence cannot establish exchangeability with future owner traffic.
