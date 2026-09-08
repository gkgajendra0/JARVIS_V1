# Step 4 Phase 4.5D — Question-Role Bake-Off V1 Result

## Status

**OWNER EVIDENCE COMPLETE — DEVELOPMENT FAIL / RETIRED**

Phase 4.5D remains active. Phase 4.5E remains blocked.

Owner repository SHA:

`bd67a91ff6dda4875ca62375c8a497d56c5ae315`

Frozen corpus SHA-256:

`bb09a6a6b7c6f9248c48f35a39e5f4f8002f678a471d4752152c6a6b26cd4c21`

Owner environment:

- Torch `2.13.0+cu132`
- Torchvision `0.28.0+cu132`
- Transformers `5.16.1`
- GLiClass `0.1.20`
- psutil `7.2.2`
- GPU: NVIDIA GeForce RTX 5060 Ti
- zero cloud/provider calls

Evidence artifact written locally by the frozen harness:

`.step4-phase45d-question-role-bakeoff-v1.json`

Do not rerun V1, alter its prompt/labels/cases, fit thresholds on it, train on it, or score replacement candidates on these 480 exposed queries.

---

## Frozen experiment shape

V1 tested two multilingual GLiClass checkpoints as zero-training native single-label question-role classifiers:

- `480` fresh cases;
- English / Hindi / Hinglish;
- `10` requested-answer roles;
- `96` allow cases (`current_value`, `current_value_comparison`);
- `384` veto cases;
- no exact-normalized query overlap with exposed Answerability V1, Method V2 train+holdout, or retired V4;
- no task-specific training;
- no fitted decision threshold;
- single-label softmax argmax only;
- fixed task prompt and fixed descriptive labels;
- Safetensors-only, `trust_remote_code=False`.

Candidates:

1. `knowledgator/gliclass-multilang-mini`
   - revision `0bd888b6c3ef9fca5f0a9d407bddfbbc7623486b`
2. `knowledgator/gliclass-multilang-ultra`
   - revision `9d6ca10258a3bddcf05b88c89cb8a8390e87e90c`

---

## Owner results

| Candidate | Unsafe false approvals | Wrong allow modes | False vetoes | Allow recall | Exact 10-role accuracy | Macro-F1 | EN allow recall | HI allow recall | Hinglish allow recall | ms/case | CUDA delta peak | Gate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| GLiClass Multilang Mini | 0 | 0 | 96 | 0.000000 | 0.100000 | 0.018182 | 0.000000 | 0.000000 | 0.000000 | 6.5374 | 752,743,936 B | FAIL |
| GLiClass Multilang Ultra | 0 | 0 | 96 | 0.000000 | 0.100000 | 0.018182 | 0.000000 | 0.000000 | 0.000000 | 28.3396 | 3,689,218,048 B | FAIL |

### Collapse pattern

The failure was pathological rather than a normal partial-classification miss:

- Mini predicted `broad_recall` for all `480/480` cases;
- Ultra predicted `historical_value` for all `480/480` cases;
- neither candidate predicted `current_value` even once;
- neither candidate predicted `current_value_comparison` even once;
- both therefore produced all `96` allow cases as false vetoes;
- both achieved only the trivial `48/480 = 0.10` exact accuracy from the one class they selected universally.

Because both universal predictions were veto roles, `unsafe_false_approval_cases = 0` is not a meaningful safety success. The models simply never approved any current-fact path.

---

## Frozen gate decision

The frozen development gates required simultaneously:

- zero unsafe false approvals;
- zero wrong allow modes;
- overall exact allow-role recall >= `0.90`;
- exact `current_value` recall >= `0.90`;
- exact `current_value_comparison` recall >= `0.90`;
- EN / HI / Hinglish allow recall >= `0.85` each;
- single-label argmax only / no threshold;
- zero cloud calls.

Both candidates fail decisively because allow recall is exactly `0.0` in every language and both allowed roles have recall `0.0`.

Frozen harness decision:

- selected candidate: `null`
- candidate selected: `false`
- production change authorized: `false`
- fresh composite integration test authorized: `false`
- fresh final acceptance authorized: `false`
- Phase 4.5E authorized: `false`

**Question-Role V1 is retired.**

---

## Runtime observations

Mini loaded and completed inference. Transformers emitted a generic model-type warning and a `use_return_dict` deprecation warning.

Ultra also completed inference, but Transformers emitted a tied-weight / missing-key load report for:

`model.encoder_model.encoder.embed_tokens.weight`

The same Ultra warning is currently reported upstream against Transformers v5. GLiClass maintainers have publicly acknowledged the report; one contributor said it would be fixed in a later release, while another maintainer later described it as a warning and stated that the model works as expected. Therefore the warning alone is insufficient to explain this owner result.

The more important anomaly is that **both** Mini and Ultra collapsed to one class across all 480 cases despite the family being documented for multilingual zero-shot intent classification and despite published nontrivial classification benchmarks.

---

## Architectural interpretation

This owner result proves only the frozen V1 formulation fails. It does **not** justify claiming that GLiClass is generally incapable of intent classification.

Possible failure classes still needing separation are:

1. accepted-runtime / checkpoint compatibility;
2. GLiClass batch/shared-label behavior under this package/runtime;
3. interaction between the long descriptive role labels and the fixed task prompt;
4. genuine inability of the frozen checkpoints to solve the JARVIS question-role taxonomy zero-shot.

V1 is exposed, so none of those hypotheses may be tested by modifying and rerunning the same 480 cases.

---

## Next diagnostic — upstream-contract sanity only

Before abandoning the GLiClass family or designing another JARVIS corpus, run a tiny compatibility diagnostic using only public examples from the GLiClass Multilang model card:

- NASA topic classification;
- multilingual/cross-lingual NASA examples;
- the documented alarm intent example;
- the documented French government classification example.

The diagnostic must:

- use the same pinned Mini/Ultra revisions;
- use the accepted owner runtime;
- contain **no JARVIS V1 query text**;
- contain no custom question-role labels;
- contain no JARVIS task prompt;
- compare individual and batched pipeline behavior where applicable;
- write a separate non-acceptance diagnostic artifact;
- never authorize production or Phase 4.5E.

Interpretation:

- if the documented examples also collapse or batch/individual behavior diverges materially, reject GLiClass from the accepted runtime path;
- if the documented examples behave normally, the runtime is usable and Question-Role V1 is retained as a formulation/design failure. Do not rerun V1; move to a separately researched/frozen next architecture.
