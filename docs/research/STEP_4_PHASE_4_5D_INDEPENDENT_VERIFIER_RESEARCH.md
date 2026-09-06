# Step 4 Phase 4.5D — Independent verifier research

Status: **ACTIVE DEVELOPMENT RESEARCH — NOT FINAL ACCEPTANCE**

## Why this branch exists

The retired 320-case Phase-4.5D artifact established that the selected retrieval stack is very strong at ranking, but the release-confidence family is not strong enough:

- Qwen reranker score + margin: insufficient;
- Bonferroni-Holm: no valid policy;
- corrected binary SFST: no valid policy;
- every one of the 30 score/margin rules tested individually: no valid rule;
- low-capacity logistic regression over all already-computed retrieval evidence improved the development operating point to about 29.6% recall at >=95% empirical precision, still below the frozen 40% release-recall floor.

Therefore Phase 4.5D remains open. Phase 4.5E is blocked.

## Research-first technology refresh

### Pure NLI is not the first choice

Natural-language inference models solve premise -> declarative-hypothesis entailment/neutral/contradiction. JARVIS instead has an interrogative user query and a candidate memory passage. Converting arbitrary questions into declarative NLI hypotheses would add a new unmeasured transformation layer.

The better immediate fit is a second, independently trained multilingual **query-passage cross-encoder**. This asks the same input-shape question JARVIS actually has while contributing an independent model family/training signal.

### Candidate screen

#### `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` — selected first challenger

Reasons:

- direct query/passage relevance cross-encoder;
- trained on multilingual MS MARCO (mMARCO);
- mMARCO includes Hindi;
- multilingual MiniLM/XLM-R lineage;
- Apache-2.0;
- about 0.1B parameters and ~471 MB safetensors weights;
- standard Sentence Transformers `CrossEncoder` loading;
- no `trust_remote_code=True` requirement;
- far cheaper than adding another ~0.6B verifier.

This model is **not** selected for production. It is only the first measured challenger.

#### `BAAI/bge-reranker-v2-m3` — deferred heavyweight challenger

Reasons it remains credible:

- Apache-2.0;
- multilingual query/passage reranker;
- standard XLM-R sequence-classification architecture;
- no custom remote-code requirement in the Hugging Face Transformers loading path.

Why it is deferred:

- ~568M parameters / ~2.27 GB weights;
- materially larger GPU/RAM cost than the mMARCO MiniLM challenger.

It should be tested only if the smaller mature challenger fails to add enough independent information.

### Rejected first-line alternatives

- Jina multilingual reranker: attractive size/performance, but current model license is CC-BY-NC-4.0 and its documented loading path uses custom remote code.
- Alibaba GTE multilingual reranker: Apache-2.0 and ~306M, but its documented Sentence Transformers path requires `trust_remote_code=True`.
- another prompt rewrite for Qwen: rejected because the production reranker instruction is already explicitly tuned for direct/sufficient memory answering and the instruction bake-off is already complete.

## Development experiment contract

The independent verifier bake-off MUST:

1. read `.step4-phase45d-final-acceptance.json`;
2. reconstruct the original synthetic query text and returned top-memory passage from the frozen Phase-4.5D corpus generator;
3. never rerun Qwen embedding, FTS5, RRF, or Qwen reranking;
4. score exactly the already-exposed 320 query/top-document pairs with the independent cross-encoder;
5. use no language/category/case-id/expected-answer metadata as learned features;
6. compare 5-fold out-of-fold logistic confidence using:
   - existing full retrieval evidence;
   - independent verifier score alone;
   - existing full retrieval evidence + independent verifier score;
7. report ROC-AUC, average precision, empirical >=95% precision operating point, recall and language breakdown;
8. remain `final_acceptance_eligible=false`.

The challenger is only considered **promising enough for a new untouched acceptance corpus** if the combined out-of-fold development signal:

- materially improves ROC-AUC and average precision over existing full retrieval evidence;
- finds an empirical >=95% precision operating point;
- reaches at least 40% positive release recall;
- does not starve English, Hindi or Hinglish below the existing 25% language recall floor.

These are development-selection gates only, not statistical production acceptance.

## Next decision

- If the small mMARCO challenger clears the development gates: freeze that architecture and design a new untouched Phase-4.5D calibration/validation corpus.
- If it improves but remains below the gates: do **not** weaken the gates; benchmark the heavier BGE-v2-m3 independent signal.
- If independent cross-encoder evidence does not improve separation: research a different answerability architecture rather than stacking correlated rerankers.

Phase 4.5E remains blocked until Phase 4.5D has valid final acceptance evidence.
