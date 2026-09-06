# Step 4 Phase 4.5D — Multilingual NLI Release-Guard Diagnostic Result

## Status

**DEVELOPMENT DIAGNOSTIC COMPLETE — REJECT NLI-AS-ANSWERABILITY GUARD. NOT ACCEPTANCE EVIDENCE. PHASE 4.5E REMAINS BLOCKED.**

This result evaluates the frozen development-only method in `STEP_4_PHASE_4_5D_NLI_RELEASE_GUARD_DIAGNOSTIC_METHOD.md` against the 16 rows released by the completed structured-query planner diagnostic.

The model was:

- `MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7`
- revision `b5113eb38ab63efdd7f280f8c144ea8b13f978ce`
- local CUDA inference on the accepted owner RTX 5060 Ti environment
- no Gemini calls
- no Qwen calls
- veto-only development semantics

## Frozen source rows

The source structured-query planner artifact contained:

- 16 released rows;
- 10 correct exact canonical releases;
- 6 false ordinary-semantic releases.

The six false releases were already known to be concentrated in question-focus errors:

- `near_miss`: 2;
- `negation`: 2;
- `adversarial_lexical`: 1;
- `unsupported_source`: 1.

No historical, forgotten, local-only, secret, or untrusted boundary was released by the source planner.

## Owner result

The frozen NLI guard produced:

- source release rows: `16`;
- source correct releases: `10`;
- source false releases: `6`;
- guarded releases: `0`;
- retained correct releases: `0`;
- blocked correct releases: `10`;
- surviving false releases: `0`;
- blocked false releases: `6`;
- guarded precision: `1.0` only because nothing was released;
- correct-release retention: `0.0`.

Per language, correct-release retention was:

- English: `0/4 = 0.0`;
- Hindi: `0/3 = 0.0`;
- Hinglish: `0/3 = 0.0`.

Top NLI labels on the ten source-correct releases were:

- `neutral`: 9;
- `contradiction`: 1;
- `entailment`: 0.

Top NLI labels on the six source-false releases were:

- `neutral`: 4;
- `contradiction`: 2;
- `entailment`: 0.

Entailment-score ranges overlapped heavily:

- source-correct: min `0.03959819`, median `0.08716117`, max `0.25025803`;
- source-false: min `0.01969788`, median `0.07977144`, max `0.14993663`.

Frozen continuation checks:

- zero surviving false releases: PASS;
- retain at least 8/10 correct: FAIL;
- English retain at least 3/4: FAIL;
- Hindi retain at least 2/3: FAIL;
- Hinglish retain at least 2/3: FAIL;
- veto-only invariant: PASS;
- query/hypothesis/value non-persistence invariant: PASS.

Final diagnostic decision:

```text
promising_for_architecture_review = false
phase45e_authorized = false
```

## Interpretation

The result is a task-formulation failure, not evidence that multilingual NLI is generally weak.

The frozen hypothesis asked the NLI model to decide a meta-level statement of the form:

```text
The user's question can be answered solely by the current recorded <relation> for <subject>.
```

The pinned model is trained for natural-language inference and zero-shot classification. The owner result shows that this meta answerability statement is not represented as entailment by either direct current-value questions or ordinary-semantic false-release questions: almost all rows were classified neutral.

Therefore:

- do not tune an entailment threshold on this exposed result;
- do not reverse labels or construct an empirical score rule from these 16 rows;
- do not keep this formulation as a production veto;
- do not reject the base model for other task-matched uses.

## What the result confirms about the architecture

The structured exact-facet direction remains valuable:

- canonical lifecycle/security boundaries remained deterministic;
- exact-facet retrieval removed Qwen candidate-starvation from exact current facts;
- the remaining development problem is question-focus / answer-type understanding, especially in Hindi/Hinglish;
- the six demonstrated false releases ask for a reason, provenance actor, successor/replacement, or related record rather than the stored canonical value itself.

The next research step must therefore test **typed question-intent classification**, not passage relevance or meta answerability.

The same pinned mDeBERTa model is explicitly published as suitable for multilingual zero-shot classification. A development-only zero-shot answer-type diagnostic may reuse the already-downloaded weights, but its label taxonomy and evaluation protocol must be frozen before observing any scores.

## Boundaries

This result does not:

- authorize Phase 4.5E;
- constitute fresh acceptance evidence;
- alter canonical security/lifecycle policy;
- alter the single production brain selector `JARVIS_AI_PROVIDER`;
- authorize threshold fitting on the exposed 16 rows;
- justify re-running Gemini;
- justify adding hand-written Hindi/Hinglish keyword rules.
