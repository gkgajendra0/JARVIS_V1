# General multilingual personal-context diagnostic

The owner requested general tests instead of supplying personal examples, with
Hindi, Hinglish, English and broader language coverage. These are public,
author-generated fictional regression cases, not an independent holdout.
The original 20-case public corpus remains unchanged.

[Observed run and findings](../docs/research/PERSONAL_INTELLIGENCE_MULTILINGUAL_RESULTS_2026-10-19.md).

## Frozen coverage

[Corpus](personal_intelligence_multilingual_v1.json): 26 cases / 43 events.

| Query language/style | Cases | Scenarios |
| --- | ---: | --- |
| English | 6 | Correction, verified forgetting, local-only fact, guest, breakfast advice, unrelated arithmetic |
| Hindi | 6 | Same six scenarios |
| Hinglish in Latin script | 6 | Same six scenarios |
| Bengali, Tamil, Telugu, Marathi, Gujarati, Arabic, Spanish, French | 1 each | Corrected current coffee preference |

This covers ten languages plus the Hinglish style, not every language. Most
source events use the query language. The private local-only source remains an
English control; canonical seeded values use English consistently. This is text
testing, not speech recognition, pronunciation or accent certification. Translations
have not been reviewed by native-speaking human evaluators.

## Native fixture preparation

[Seed operations](personal_intelligence_multilingual_native_seeds_v1.json) map the
fictional source events to explicit canonical remember/correct/forget operations.
They are operator-authored inputs, not model extraction output or relevance gold.
The seed file and evaluator rubric never enter model requests. Native tests use
the actual schema, lifecycle, eligible retrieval, query coordinator, semantic
verifier and shadow selector in a disposable SQLite store per case. Real owner
memories are never opened or modified.

The native store contains local-only and guest-protected facts, so native release
gates face actual stored fixtures. Verified forget is applied through the canonical
lifecycle. Identity and consent labels are fixture inputs; these tests do not
establish real speaker recognition or natural consent/admission behavior.

## Arms and fixed configuration

1. `no_personal_context_ablation`: query only.
2. `permitted_history_diagnostic`: permitted source quotations, chronological
   corrections preserved as dated history, verified-forgotten sources removed.
   Guest/cloud-restricted sources are excluded through the existing projection.
3. `native_exact_shadow_diagnostic`: only locally revalidated evidence selected
   by the existing configured native exact-fact planner/verifier and shadow path.

The native arm is a component diagnostic, not the full accepted JARVIS voice/tool
baseline. The history arm is a simple diagnostic, not a vendor memory engine or
new relevance selector. Its raw quotations differ from native canonical structured
facts; comparisons include that representation difference.

Native planner/verifier: existing configured Gemini `gemini-3.8-flash`.
Common answerer for all arms: existing ChatGPT-plan route, `gpt-6.1-sol`, fixed
instructions/schema, independent requests, no tools and no action authorization.
Production settings are unchanged. No external memory service or alternate paid
fallback is introduced. Hosted sampling/revision and native SDK wire retries are
not controlled by this diagnostic.

The execution plan is frozen before inference: same 26 cases, deterministic
shuffled arm order, one pass, at most 52 native logical calls plus 78 answer calls
(130 total), no lab retries, stop after three consecutive provider failures.
Native selection deadline: 45 seconds; answer call timeout: 35 seconds. Context
is bounded at 4,096 local UTF-8 byte units/serialized bytes; this is not a provider
token budget. Actual usage/failures are retained; currency cost is unobserved.

## Review and limits

Keep requirements, prohibitions, domain labels and seed operations out of candidate
inputs. Trace-audit released source IDs and request payloads for guest/local-only/
verified-forget violations. Record native infrastructure failures separately from
semantic abstention. A historical correction quote in the history arm is not a
current canonical assertion; assess whether its answer uses the corrected value.

Freeze A/B/C labels before qualitative answer review; lock the review before
revealing the arm map. The reviewing agent also authored these fixtures, so this
has limited independence. Check correctness, relevant preference use, language/
style, unsupported personal claims and privacy. Report findings per case and
language, not a calibrated accuracy score or universal language-support claim.

One pass, small synthetic fixtures and prepared canonical seeds cannot establish
natural capture, restart persistence, large-catalog ranking, real voice timing,
external-service superiority or production acceptance. The narrower native exact
recall guard is preserved; advice failures must be reported as missing capability,
not repaired by silently weakening its semantic release rule.
