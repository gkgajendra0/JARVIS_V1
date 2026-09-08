# Step 4 Phase 4.5D — Task-Guard Fine-Tune V3 Method

## Status

**SUPERSEDED BEFORE OWNER EXECUTION — NEVER RUN / NO RESULT EVIDENCE**

Phase 4.5D remains active. Phase 4.5E remains blocked.

This document is retained only as historical architecture evidence. The V3 corpus, harness, tests, temporary formatter workflow, and dedicated fine-tuning dependency group were removed before any owner GPU run. No V3 model was trained, no V3 holdout was scored, and no V3 result artifact exists.

## Why it was superseded

Method V2 had correctly rejected the frozen-encoder + LogisticRegression architecture. The first reaction was to make the encoder itself task-specific by fine-tuning mmBERT/XLM-R on the same eight query classes.

A deeper research pass before owner execution found that this still framed the release boundary too narrowly as **query-only intent classification**. The mature problem is instead **answerability / evidence sufficiency**:

> Given this exact user question and this exact already-eligible canonical memory evidence, does the evidence actually contain the requested answer?

The relevant established lines are SQuAD 2.0 unanswerable QA, Read + Verify, TyDi QA minimal answers, GAAMA/PrimeQA boolean QA with a no-answer state, retrieval/output rails, and modern grounding verification.

The architectural distinction is load-bearing:

- retrieval asks which eligible memories are related;
- answerability asks whether a particular memory contains the requested answer;
- boolean NLI asks whether a proposition is entailed, contradicted, or unknown given that memory;
- grounding verification checks whether final wording remains supported;
- JARVIS lifecycle/security/canonical policy remains the only release authority.

A query-only eight-class model cannot directly evaluate evidence sufficiency because it never sees the candidate canonical fact. Training such a model before benchmarking existing answerability components would violate the project's research-first rule.

## Replacement direction

The next development iteration benchmarks mature components with **zero task-specific training**:

1. extractive SQuAD-2-style readers for open current-value questions, using their native answer-span vs no-answer decision;
2. the already-pinned multilingual mDeBERTa NLI model in its **native premise/hypothesis entailment task** for current-value comparisons, instead of the retired zero-shot query-intent use;
3. only after those lanes are understood, a separate modern grounding/output rail such as LettuceDetect may be benchmarked against final response wording.

The replacement development corpus is fresh and must not reuse retired V4 or exposed Method V2 queries for training or scoring. No probability threshold fitting is permitted on the fresh holdout.

## What remains useful from V3

The old eight categories remain useful only as **diagnostic failure families** when constructing hard no-answer cases (reason, provenance, successor, related record, advice, contradiction). They are no longer the production output taxonomy or the metric being optimized.

## Research references

- SQuAD 2.0: https://aclanthology.org/P18-2124/
- Read + Verify: https://ojs.aaai.org/index.php/AAAI/article/view/4619
- TyDi QA: https://aclanthology.org/2020.tacl-1.30/
- Yes, No or IDK: https://aclanthology.org/2022.naacl-main.79/
- GAAMA 2.0: https://arxiv.org/abs/2206.08441
- Hugging Face QA pipeline: https://huggingface.co/docs/transformers/main_classes/pipelines#transformers.QuestionAnsweringPipeline
- `deepset/xlm-roberta-base-squad2`: https://huggingface.co/deepset/xlm-roberta-base-squad2
- `timpal0l/mdeberta-v3-base-squad2`: https://huggingface.co/timpal0l/mdeberta-v3-base-squad2
- native multilingual NLI model already pinned by JARVIS: https://huggingface.co/MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7

## Governance consequence

Superseding V3 before execution does not constitute tuning against V3 evidence because there is no V3 evidence. No production guard behavior is changed by this decision. Phase 4.5D can close only after a mature-component development architecture wins fresh evidence, is implemented cleanly, and then passes a completely fresh final acceptance. Phase 4.5E remains blocked until that closure.
