# Step 4 Phase 4.5D — Answerability Component Bake-Off V1 Result

## Status

**OWNER EVIDENCE COMPLETE — DEVELOPMENT FAIL / RETIRED**

Phase 4.5D remains active. Phase 4.5E remains blocked.

Owner repository SHA:

`97c26819ddcaa66e7b3a8822ef23fe40ee8c4ced`

Frozen corpus SHA-256:

`3e2bd6830df3d08b3ea4ce8e045ee78cf562c228c5b0d2e5e094ffa42b6b44a3`

Owner environment:

- Torch `2.13.0+cu132`
- Torchvision `0.28.0+cu132`
- Transformers `5.16.1`
- SentencePiece `0.2.2`
- psutil `7.2.2`
- GPU: NVIDIA GeForce RTX 5060 Ti
- zero cloud/provider calls

Evidence artifact written locally by the frozen harness:

`.step4-phase45d-answerability-bakeoff-v1.json`

Do not rerun V1, tune thresholds on this corpus, rewrite these cases and call them V1, or use this exposed corpus for training/model selection.

---

## Frozen experiment shape

V1 tested mature zero-training components against 384 fresh component cases:

- 288 extractive-QA cases:
  - 96 answerable;
  - 192 no-answer;
- 96 native-NLI cases;
- English / Hindi / Hinglish;
- no exact normalized query overlap with retired V4 or exposed Method V2;
- no JARVIS task-specific training;
- no fitted probability thresholds.

QA candidates:

1. `deepset/xlm-roberta-base-squad2`
   - revision `a5fab9908c8d856e8c583fd41ba6d92444e46477`
2. `timpal0l/mdeberta-v3-base-squad2`
   - revision `08d6e89c7a6557f967db2e1021f7f640483400ed`

Native NLI candidate:

- `MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7`
- revision `b5113eb38ab63efdd7f280f8c144ea8b13f978ce`

The first owner launch on the earlier SHA failed before any case scoring because Transformers 5 removed the legacy QA pipeline registration. That pre-scoring compatibility failure did not expose model outcomes. The final V1 evidence above used the documented native `AutoModelForQuestionAnswering` start/end-logit adapter and completed successfully.

---

## QA results

| Candidate | Unauthorized no-answer releases | Wrong evidence releases | Answerable recall | Null recall | EN recall | HI recall | Hinglish recall | ms/case | CUDA delta peak | Gate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| XLM-R SQuAD2 | 45 | 2 | 0.604167 | 0.765625 | 0.750000 | 0.593750 | 0.468750 | 12.6875 | 1,145,211,392 B | FAIL |
| mDeBERTa-v3 SQuAD2 | 39 | 8 | 0.718750 | 0.796875 | 0.968750 | 0.593750 | 0.593750 | 33.1702 | 1,126,054,912 B | FAIL |

Frozen QA gates required simultaneously:

- zero unauthorized non-empty releases on no-answer cases;
- zero wrong non-empty evidence spans;
- overall answerable recall >= `0.90`;
- each language answerable recall >= `0.85`.

Neither QA candidate is remotely close to the safety boundary. The stronger mDeBERTa reader still released evidence on 39/192 insufficient-context cases and produced eight wrong non-empty evidence spans. Its Hindi/Hinglish recall also remained only 0.59375.

### QA conclusion

**Generic English-SQuAD2 no-answer fine-tuning on a multilingual backbone is not an acceptable JARVIS evidence-release authority.**

The result supports the research concern that multilingual backbone coverage does not imply calibrated multilingual abstention. Do not rescue these checkpoints through null-score threshold tuning on this exposed corpus.

---

## Native NLI results

- unauthorized boolean releases on neutral/unknown cases: `24`
- wrong boolean verdicts on answerable comparisons: `0`
- comparison recall: `1.000000`
- overall NLI accuracy: `0.750000`
- English comparison recall: `1.000000`
- Hindi comparison recall: `1.000000`
- Hinglish comparison recall: `1.000000`
- inference: `3.0616 ms/case`
- CUDA delta peak: `677,767,680 B`
- development gate: **FAIL**

Frozen NLI gates required simultaneously:

- zero YES/NO releases on neutral/unknown cases;
- zero wrong boolean verdicts;
- comparison recall >= `0.90`;
- each language comparison recall >= `0.85`.

### NLI conclusion

The native NLI checkpoint demonstrates an important partial success:

- it correctly distinguishes the truth value of every answerable comparison in all three languages;
- it never flips a correct YES into NO or vice versa;
- however, it fails the release boundary because all 24 neutral/unknown cases are converted into a non-neutral verdict.

Therefore **native NLI is promising as a downstream truth evaluator only after an independent answerability/sufficiency gate has established that the canonical fact is allowed to answer the proposition.** It is not safe as the abstention authority itself.

---

## Composite decision

Frozen harness decision:

- selected QA candidate: `null`
- QA candidate selected: `false`
- native NLI task passes: `false`
- composite development pass: `false`
- production change authorized: `false`
- fresh final acceptance authorized: `false`
- Phase 4.5E authorized: `false`

**V1 is retired.**

---

## Architectural diagnosis

V1 isolates the remaining problem much more sharply than prior experiments:

1. Retrieval/reranking is not the blocker; that was already proven in 4.5C / retrieval-depth diagnosis.
2. Truth classification for an already-answerable boolean proposition is not the blocker; native NLI achieved perfect answerable comparison recall with zero wrong boolean verdicts.
3. The blocker is **selective answerability / evidence sufficiency / abstention**:
   - does this canonical fact actually contain the information requested by this question/proposition?
   - if not, JARVIS must return NULL before span extraction or boolean truth evaluation is allowed to release anything.
4. Generic SQuAD2 readers and generic NLI do not provide a sufficiently reliable abstention boundary for this contract.

This points toward a dedicated answerability/sufficiency component rather than another generic QA reader or generic NLI model.

---

## Research-first next direction

Do not train a JARVIS-specific classifier yet.

The next research pass should prioritize mature models/systems whose **native task explicitly includes an answerability/no-answer class**, especially:

- TyDiQA / GAAMA / PrimeQA-style answerability and boolean-answer components;
- dedicated `has-answer / no-answer / yes-no` classifiers;
- evidence-sufficiency / selective-prediction components designed to abstain before downstream answering;
- safe-weight multilingual checkpoints that can be loaded without remote code or pickle.

PrimeQA is architecturally relevant because its public BoolQA flow explicitly includes `no_answer` as a label and separates question type, evidence extraction, boolean answering and score normalization. However, the currently surfaced public boolean-answer checkpoint uses a legacy 2.24 GB PyTorch pickle, so it must not be introduced directly into the accepted JARVIS safe-weight path without a separately justified safe conversion/reproducibility contract.

Only after a fresh zero-training candidate family is frozen should a new never-exposed development corpus be created. V1 case text/results are now deny-listed development evidence only.
