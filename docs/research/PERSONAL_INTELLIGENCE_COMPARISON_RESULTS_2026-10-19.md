# Personal-context diagnostic: observed results and next decision

**Status:** exploratory fictional text experiment; no production acceptance or
vendor selection. **Date:** 19 October 2026.
**Tested code:** `89e87c369db59352a45ba30dcbbd5220cc6a27ae`.
**Authority:** [Current Plan](../CURRENT_PLAN.md) and the existing product/North Star.

## What was tested

Twenty [public fictional scenarios](../../benchmarks/personal_intelligence_v1.json)
were answered twice using the same `gpt-6.1-sol` account route, instructions,
schema and per-request limits. One arm supplied no personal context; the other
supplied the permitted source history after requester/destination filtering and
verified forgetting. Arm order was shuffled per case. No mutating tools were
available. The model never received evaluator rubrics or case classifications.

This measures a small context-use diagnostic. Neither arm is the accepted JARVIS
voice runtime or an external memory service. Source facts were supplied by the
fictional fixture; extraction, natural consent inference, durable storage,
restart, retrieval ranking and derived-profile quality were not tested.

The [input plan](../../benchmarks/results/personal_intelligence_context_diagnostic_2026-10-19/input_plan.json)
was frozen before execution. All 40 planned answers completed in this cohort.
The [raw answers and traces](../../benchmarks/results/personal_intelligence_context_diagnostic_2026-10-19/answers.json),
[manifest and artifact hashes](../../benchmarks/results/personal_intelligence_context_diagnostic_2026-10-19/manifest.json)
allow inspection of what actually reached the model.
Archive hashes use UTF-8 bytes after CRLF-to-LF normalization; the manifest also
records both the owner-run corpus byte digest and its LF-normalized digest.

## Answer review

The primary agent reviewed paired answers against the frozen public rubric,
with per-case A/B labels shuffled and the arm mapping withheld until the review
was written. This is an **agent-authored exploratory judgment**, not human
validation, an independently authored holdout or a calibrated benchmark score.
The same agent authored the research fixtures; that limits independence.

| Descriptive paired preference | Cases |
| --- | ---: |
| Permitted history preferred | 14 |
| No-context answer preferred | 1 |
| Tie or mixed tradeoff | 5 |

See the [locked blinded review](../../benchmarks/results/personal_intelligence_context_diagnostic_2026-10-19/blind_review.json),
[answer pairs](../../benchmarks/results/personal_intelligence_context_diagnostic_2026-10-19/blind_pairs.json),
[label mapping](../../benchmarks/results/personal_intelligence_context_diagnostic_2026-10-19/label_mapping.json)
and [revealed review](../../benchmarks/results/personal_intelligence_context_diagnostic_2026-10-19/revealed_review.json).
These counts are preferences, **not accuracy percentages or a vendor ranking**.

Concrete observations:

- Context carried the decaf correction, the concise-answer preference with a
  temporary exception, the laptop repair decision and the Hindi no-sugar correction.
- Purchase and travel answers used the already-owned hub, two-display need,
  departure city and unavailable dates rather than asking for all that again.
- PI014 exposed a weakness: a previous assistant claim about saving breakfast
  context encouraged wording that presupposed a save. The no-context answer was
  better qualified. A prior assistant sentence cannot establish a committed write.
- PI006 was mixed: the context answer correctly qualified an old budget, while
  the no-context answer more clearly asked for current commitments. Context
  presence alone does not guarantee the most useful next question.
- PI019 produced identical correct answers, but the history arm unnecessarily
  released an irrelevant gardening fact. This is a relevance/minimization failure,
  not automatically a privacy incident. Answer correctness can hide poor selection.
- Both arms withheld the private/guest and forgotten details in these fixtures.
  The trace audit confirms empty released context for PI010–012; it does not prove
  deletion from a real service, backups or resumed provider sessions.

The [separate trace audit](../../benchmarks/results/personal_intelligence_context_diagnostic_2026-10-19/trace_audit.json)
records the privacy/lifecycle exclusions and PI019's retrieval-minimization result.

The source fixture leaves egg policy within “vegetarian” unspecified. PI016 also
does not fully specify freshness of a dated Work-status snapshot. Production
should obtain current canonical Work state or qualify the last recorded status.
These limitations are recorded without changing the frozen corpus after outputs.

## Observed resource use and provider failures

| Same-model cohort | No context | Permitted history |
| --- | ---: | ---: |
| Completed answers | 20 | 20 |
| Observed input tokens | 3,814 | 5,236 |
| Observed output tokens | 1,323 | 1,280 |
| Whole-call p50 | 5,586 ms | 5,562 ms |
| Whole-call p95, nearest rank | 8,968 ms | 8,328 ms |

These are observed text-call timings, not retrieval latency, time to first speech
or evidence that adding context makes inference faster. Sampling used server
defaults, repetitions were one per case/arm, and the hosted model revision was not
exposed by the current client. Exact currency cost and failed-call usage are unknown.

The production-configured model remained `gpt-5.6-sol`. An earlier exploratory
cohort stopped after provider failures; one failure explicitly reported
`server_is_overloaded`, while the initial failure's provider code was not captured.
A separate one-call diagnostic retry completed. The alternative model was confirmed
account-visible and used in a new frozen cohort; results from different models
were not pooled for the preference counts above.

Across the transport smoke, earlier attempts/recovery and complete cohort:
**47 inference attempts, 45 completed responses, 2 failed provider attempts**.
Model-discovery calls are excluded from inference counts. Earlier partial records
are preserved in [earlier attempts](../../benchmarks/results/personal_intelligence_context_diagnostic_2026-10-19/earlier_model_attempts.json)
and the [separate smoke record](../../benchmarks/personal_intelligence_transport_probe_2026-10-19.json).
The existing account connection was used; no paid API fallback or credit purchase
was introduced. Token counts are not a claim of zero account cost.

The inspected existing Hindsight lab was stopped and configured with LLM provider
`none` and observations disabled. It was not started or imported into for this
diagnostic. No Honcho, Supermemory or Hindsight performance result is claimed.

## Implemented verification

The isolated runner's 35 focused checks pass. The full local Windows suite passed
**2,488 tests / 8 skipped** after review fixes; repository formatting/lint passed.
All six GitHub checks passed on the tested code commit. These are software-contract
checks, not evidence that CAP-053 is accepted.

Independent code review found two important edge cases, reproduced before fixing:
private forget text could suppress invalidation, and an unknown actor with null
retention could pass validation. Both are covered, along with readiness after an
empty-history reset. Adapter-generated prose is not retained in the first runner;
only resolved original context is recorded. That evidence limitation is deferred.

## Owner-approved next step

Keep JARVIS's existing canonical stores and add the
[proposed read-only personal-context selector](../superpowers/specs/2026-10-19-personal-intelligence-comparison-design.md)
in shadow test mode. It should identify relevant current evidence, distinguish
verified memory operations from assistant claims, and compose permitted personal,
session and fresh Work/observation context. Shadow records selection outcomes;
provider apply, natural durable admission and production promotion remain later gates.

**Approved sequence adjustment (2026-10-19):** use that bounded native shadow path to measure
the incumbent workflow before investing in additional memory-service adapters.
Keep external engines replaceable and unselected. Native baseline measurements,
repeated/held-out evaluation and real service lifecycle tests remain open; this
diagnostic does not complete implementation-plan Task 2 or waive its later gates.

The owner explicitly replied **"Approve read-only test mode"**, approving this
sequence change and the bounded shadow design.
The [Current Plan](../CURRENT_PLAN.md) says: “After a separate architecture owner
approval, implement a read-only shadow personal-context path.” The complete
comparison evidence and bounded design are now reviewable together. The first
[native shadow boundary and fictional probe](PERSONAL_CONTEXT_SHADOW_2026-10-19.md)
are implemented on the research branch. No production runtime activation or
provider-context injection has been implemented under this PR.

The owner subsequently requested general multilingual scenarios instead of
personal examples. A separate [26-case multilingual pass](PERSONAL_INTELLIGENCE_MULTILINGUAL_RESULTS_2026-10-19.md)
records 78 answerer replies, native component behavior and nine native deadlines,
with a separate English route control. It does not replace the earlier frozen
diagnostic or complete Task 2's vendor/held-out/replicated evidence.
