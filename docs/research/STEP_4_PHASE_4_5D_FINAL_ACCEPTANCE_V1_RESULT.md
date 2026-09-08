# Step 4 — Phase 4.5D Fresh Acceptance V1 Result and Statistical-Power Diagnosis

Date: 2026-09-06

## Status

**MEASUREMENT COMPLETE / NOT ACCEPTED / PHASE 4.5D REMAINS ACTIVE / PHASE 4.5E MUST NOT START.**

The first fresh 320-query final-acceptance corpus was executed exactly once on the accepted owner RTX environment and produced `FAIL_ACCEPTANCE`.

This is valid final evidence for that corpus. The corpus and its labels are now exposed and retired from final acceptance. It must never be rerun to tune or chase a pass.

## Owner result

Environment:

- Torch `2.13.0+cu132`;
- CUDA `13.2`;
- GPU `NVIDIA GeForce RTX 5060 Ti`;
- MAPIE `1.5.0`;
- accepted JARVIS-memory reranker instruction;
- peak CUDA allocation `2,532,575,744` bytes.

Frozen corpus:

- SHA-256 `1e41586f98028b35a9ce30514c28c74e13737ad1acf67a23b247d1870c504cad`;
- `320` total queries;
- calibration `96 release + 96 abstain`;
- held-out validation `64 release + 64 abstain`;
- no retired V1 query reuse.

Ranking quality was strong:

- calibration positive top-1 accuracy `1.0000`;
- calibration Recall@3 `1.0000`;
- validation positive top-1 accuracy `0.984375` (`63/64`);
- validation Recall@3 `1.0000` (`64/64`);
- validation English top-1 `1.0000`;
- validation Hindi top-1 `0.952381`;
- validation Hinglish top-1 `1.0000`.

The acceptance failure came from policy calibration, not retrieval ranking:

- target precision `0.95`;
- confidence level `0.95`;
- candidate score/margin pairs `30`;
- FWER method `bonferroni_holm`;
- MAPIE valid policies `0`;
- best policy `None`;
- therefore held-out released cases `0` and release recall `0`.

## Why the current multiple-testing design is over-constrained

MAPIE documents that risk-control power decreases as the number of tested prediction parameters grows because multiple-testing correction becomes more conservative. MAPIE also documents Split Fixed Sequence Testing (SFST) specifically for non-monotonic precision control under multiple testing; SFST learns a hypothesis order on independent data and then tests that sequence with a less conservative FWER procedure.

The JARVIS result makes the power issue concrete.

With target precision `0.95`, the null boundary error rate is `0.05`. If a candidate rule released `n` cases and made zero release errors, the best-case one-hypothesis lower-tail probability at that boundary is approximately:

```text
p = 0.95 ** n
```

The fresh V1 calibration contains only `96` safe-to-release top-1 cases. Even the hypothetical perfect candidate that released all `96` safe cases and zero unsafe cases therefore has:

```text
0.95 ** 96 ~= 0.0072688567
```

A single hypothesis at 95% confidence has alpha `0.05`, so a zero-error candidate needs about `59` effective released cases to clear that level.

The first step of a 30-way Holm/Bonferroni-style procedure is approximately:

```text
0.05 / 30 = 0.0016666667
```

A zero-error candidate would need about `125` effective released cases to clear that first step. But there are only `96` safe calibration cases in the balanced fixture, so a high-precision candidate cannot supply that effective sample size.

This means the failed MAPIE result is consistent with a **statistical-power/design limitation of the 30-way Holm search**, not evidence that Qwen retrieval quality is inadequate.

## Research-first replacement candidate

Use MAPIE `split_fixed_sequence` rather than lowering:

- target precision `0.95`;
- confidence level `0.95`;
- safety eligibility rules;
- multilingual quality floors.

Why SFST is the leading candidate:

- precision is non-monotonic, so ordinary fixed-sequence testing is not generally valid;
- MAPIE explicitly supports SFST for non-monotonic risks;
- MAPIE explicitly supports SFST with multi-dimensional prediction parameters;
- SFST learns the testing order from independent data and uses sequential testing to reduce the multiple-testing penalty;
- the now-retired 320-case artifact can serve as development/order-learning evidence for a future fresh calibration corpus without being reused as final acceptance.

No claim is made yet that SFST solves the JARVIS problem. It must first be measured on the exposed artifact in development-only mode.

## Development-only SFST diagnostic

Tool:

- `tools/research/step4_phase45d_sfst_diagnostic.py`.

The diagnostic:

1. reads the existing `.step4-phase45d-final-acceptance.json` without modifying it;
2. reproduces the original Bonferroni-Holm calibration failure;
3. uses the exposed former validation split only to learn an SFST order;
4. uses the original calibration split only to test the learned order;
5. reports valid SFST parameters and empirical development recall/precision;
6. records the theoretical zero-error power comparison;
7. marks all output `final_acceptance_eligible=false`.

No model inference, CUDA run or production-memory mutation is performed.

## Decision rule after the diagnostic

If SFST still finds no useful valid policy on the retired development evidence:

- do not lower the 95% precision / 95% confidence target merely to force acceptance;
- research a better confidence representation or selective-prediction architecture before another final corpus.

If SFST finds useful valid policies:

- freeze the SFST methodology and ordering strategy using retired development data;
- generate a new untouched acceptance corpus;
- use the retired 320-case artifact only as independent order-learning/development evidence;
- calibrate on fresh data;
- evaluate one new held-out split once;
- do not begin Phase 4.5E until Phase 4.5D formally passes.

## Phase boundary

Phase 4.5E remains explicitly blocked. No ContextAssembler semantic-retrieval integration, production release rule, or voice acceptance work begins until Phase 4.5D has an accepted release/abstention policy.
