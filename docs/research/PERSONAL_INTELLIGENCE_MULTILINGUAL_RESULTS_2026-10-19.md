# General multilingual personal-context test results

The requested general test pass ran **26 fictional scenarios across ten languages
plus Hinglish**, producing **78 answerer replies**. The reviewed replies used the
requested language/style, and source-aware replies applied the corrected preference
in the simple scenarios. No protected source disclosure was observed in the
request audit or qualitative answer review.

Two capability limits remain: the native exact-fact path does not select context
for everyday advice, and native lookup became unavailable during part of the run.
The latter prevents certifying native recall for the eight additional languages.
This is text/component evidence, not full voice or production acceptance.

## Coverage and method

[Protocol and corpus](../../benchmarks/personal_intelligence_multilingual_v1.md)
were frozen before inference: 26 cases, 43 source events, one pass, three arms.
Hindi, English and Latin-script Hinglish each have six scenarios: preference
correction, verified forgetting, cloud-restricted local fact, guest isolation,
breakfast advice and unrelated arithmetic. Bengali, Tamil, Telugu, Marathi,
Gujarati, Arabic, Spanish and French each have one correction scenario.

The common answerer was the existing ChatGPT-plan `gpt-6.1-sol` route. Arms used
no personal context, permitted dated source history, or native exact shadow
selection. The native component used the configured Gemini `gemini-3.8-flash`
planner/verifier and actual canonical readers/lifecycle with operator-seeded
fictional facts in disposable SQLite stores. It is not a natural-capture test,
vendor trial or the complete accepted JARVIS voice/tool baseline.

Actual [requests, replies and native outcomes](../../benchmarks/results/personal_intelligence_multilingual_2026-10-19/results.json)
and the [frozen input plan](../../benchmarks/results/personal_intelligence_multilingual_2026-10-19/frozen_plan.json)
are retained. Production models/settings, canonical owner data and live provider
context were unchanged. No external memory service or paid alternate fallback ran.

## Observed behavior

| Language/style | Cases | Source-aware text answers | Native component |
| --- | ---: | --- | --- |
| English | 6 | Corrected decaf, private/forgotten/guest facts withheld, tailored breakfast, arithmetic 102 | Exact correction ready; five abstentions |
| Hindi | 6 | Same behavior in Devanagari, including arithmetic १०२ | Exact correction ready; four abstentions; one local-only query timed out |
| Hinglish | 6 | Same behavior in Latin-script Hindi/English | Exact correction ready; five abstentions |
| Bengali, Tamil, Telugu, Marathi, Gujarati, Arabic, Spanish, French | 1 each | Permitted-history answers used the corrected decaf preference in the requested language | All eight native selections timed out; native language support is inconclusive |

For breakfast, the history-informed replies proposed a vegetarian mushroom-free
toastie in English, poha in Hindi and besan chilla in Hinglish, within the stated
time constraint. Native selection abstained on all three advice queries, preserving
its existing exact-fact boundary. Generic empty-context replies cannot demonstrate
that JARVIS used the saved preferences, even when their suggested meal happens to fit.

All nine arithmetic replies gave 102 and omitted the irrelevant gardening fact.
Guest, forgotten and local-only facts were withheld across the tested requests
and answers. The native Hindi local-only timeout is an unavailable read, not
evidence that its semantic classification completed.

Some empty-context replies asserted that no preference was saved when the input
only established that it was unavailable to this request. Examples include
ML003-C and ML015-A/C in the blinded set. Missing memory, policy exclusion and
lookup failure must not collapse into an unsupported global absence claim.
The common answerer here received an empty context without the native availability
reason; this is an important limit of this diagnostic bridge, not a finding that
the production voice bridge already behaves that way.

## Native availability finding

Native selection returned **3 ready, 14 abstain and 9 unavailable packets**.
The three ready packets carried the correct current source/value for English,
Hindi and Hinglish. Nine selections hit the fixed 45-second deadline: ML009 and
ML019–ML026. Their logical invocation records remain `started` at cancellation
because no provider response was captured; they are not completed semantic errors.

A separately frozen [route control](../../benchmarks/results/personal_intelligence_multilingual_2026-10-19/route_control.json)
then tried the English native interpreter with SDK retries configured to zero.
It also timed out after 35 seconds, so its planned Bengali follow-up was not run.
No HTTP status, quota error or underlying cause was observed. The evidence supports
an unavailable native route during this period; it does not establish that those
eight languages caused the failure. Do not replay/replace these outcomes silently.

The diagnostic retry settings were checked against the installed SDK's Interactions
bridge and [Google's SDK source](https://github.com/googleapis/python-genai/blob/main/google/genai/_gaos/google_genai.py).
They applied only to the separate control. The original cohort retained its native
SDK defaults, with actual wire retry counts uninstrumented.

## Budgets, usage and review

The frozen cohort allowed at most 130 logical invocations. It attempted
**26 native invocations and 78 answer calls**; all 78 answer calls completed.
Seventeen native invocations returned responses and nine reached the selector
deadline. The separate control used one additional logical call and timed out.

The 78 answer calls reported 19,879 input and 3,609 output tokens. The 17 observed
native responses reported 9,939 input, 928 output and 4,146 thought tokens
(15,013 total). Native deadline/control usage and currency cost are unknown.
[Per-arm usage and whole text-call timing](../../benchmarks/results/personal_intelligence_multilingual_2026-10-19/summary.json)
are recorded separately; none is a first-spoken-output measurement.

The A/B/C [qualitative review was locked](../../benchmarks/results/personal_intelligence_multilingual_2026-10-19/blind_review.json)
before the [arm map was revealed](../../benchmarks/results/personal_intelligence_multilingual_2026-10-19/revealed_review.json).
The reviewing agent also authored the cases/translations, so independence is
limited. No native-speaking human fluency certification or calibrated accuracy
score is claimed. The undefined egg policy was not used to turn generic Hinglish
egg suggestions into a blocking dietary score.

Independent protocol review verified input isolation and seed/permission alignment
without reading candidate answers. The [trace audit](../../benchmarks/results/personal_intelligence_multilingual_2026-10-19/trace_audit.json)
found no evaluator-field leakage, forbidden native source release or protected
fixture content in requests. Semantic review found no paraphrased protected-fact
disclosure. These small synthetic checks cannot prove universal privacy.

## Software verification and next work

The harness now accepts the eleven explicitly tested language/style labels;
production language behavior is unchanged. The 35 existing comparison safety
checks pass, and the full local suite passed **2,528 tests / 8 skipped** after
this change. Repository Ruff format/lint passes. The preceding native-shadow code
commit also passed all six main CI jobs and the additional SQLCipher Windows gate.

Next, evaluate advice-relevant selection through the existing canonical evidence
boundary, preserve unavailable/absent distinctions at the answer boundary, and
establish reliable native route operation before interpreting further native
language results. Keep the exact-recall guard intact. Broad language coverage,
natural admission, held-out/repeated comparisons, external service selection and
live voice timing remain open. No vendor or production rollout is selected here.
