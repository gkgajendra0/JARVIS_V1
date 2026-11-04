# PR #303: Owner-machine six-case context-efficiency evidence (2026-11-01)

**Status:** Measured bounded development evidence, not full context-efficiency qualification or production acceptance.

## Provenance and scope

- Tested PR: [#303](https://github.com/gkgajendra0/JARVIS_V1/pull/303)
- Exact tested source commit: `ed4889a9c8bfc317a046fbca6a67acdd8d71ed38`
- Model: `gemini-3.5-flash-lite` (configured Free credential lane; no Paid fallback).
- Test mode: existing `tools/windows/Start-JarvisProjectMemoryLab.ps1 -DevelopmentBatch` with a fresh isolated owner-machine lab, supplied by the owner as a PowerShell console transcript.
- Batch start reported: `2026-11-01T12:06:36.210730+00:00`.
- Each case seeded 60 fictional events across three projects (20 in the target project); zero setup model calls. The six cases are development questions `p0-q0` through `p5-q5`. No held-out questions were run.
- This report summarizes **console-reported** results. Original `results.jsonl` / `summary.json` files were not separately inspected in this review. The raw console transcript, request IDs, owner machine paths and authorization identifiers are not committed here.

## Reported execution metrics

| Metric | Observation |
| --- | ---: |
| Planned / completed / failed / unrun | 6 / 6 / 0 / 0 |
| Returned provider steps | 7 (five one-step cases; one two-step case) |
| Reported total tokens | 23,302 |
| Input / output tokens (sum of reported step usage) | 23,067 / 235 |
| Unknown token usage cases | 0 |
| Turn latency nearest-rank p50 / p95 (n=6) | 2,752.34 / 7,004.27 ms |
| Reported provider latency nearest-rank p50 / p95 (n=6) | 1,575.26 / 3,133.41 ms |
| Foreign fixture source IDs | None observed in final contexts |
| Expected source coverage | Present in all five cases requiring source IDs |
| Reporter errors / incomplete stage spans | None reported |

Per-case numbers (milliseconds rounded; all source evidence checks passed):

| Case | Model steps | Input tokens | Output tokens | Total tokens | Elapsed ms | Reported provider ms | Manual evidence review |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `p0-q0` Nepal chosen resource | 1 | 3,210 | 45 | 3,255 | 7,004 | 1,575 | **Qualified:** correct Jimny, but answer links rental consideration to Jimny without a source establishing that specific relationship. |
| `p1-q1` interview status | 1 | 3,281 | 15 | 3,296 | 2,752 | 1,668 | **Qualified:** correct "sorted", but omits that this was an **owner-reported** status. |
| `p2-q2` corrected service budget | 1 | 3,302 | 32 | 3,334 | 2,569 | 1,464 | **Pass:** corrected budget 12000. |
| `p3-q3` rental ownership | 1 | 3,262 | 37 | 3,299 | 3,019 | 1,934 | **Pass:** ownership not established. |
| `p4-q4` external action | 1 | 3,281 | 28 | 3,309 | 2,405 | 1,275 | **Pass:** no executed external action. |
| `p5-q5` unknown diet | 2 | 6,731 | 78 | 6,809 | 6,925 | 3,133 | **Pass:** no diet established; actual personal tool returned `no_match`. |

**Manual interpretation:** 4/6 answers fully satisfy the expected source-qualified rubric; 2/6 recover the core fact but contain a grounding/qualification weakness. This is a reviewer judgment, not the harness's automatic quality score. The harness wrote `manual_review_required` and `manually_graded: 0` for all answers; these have not been modified.

## Efficiency observations and caveats

1. The first five answers required only one provider step; each carried around 3.2k input tokens despite asking a narrow question. The final contexts contained the 20 target-project fixture originals, which demonstrates bounded prefill and source availability, **not** an optimal/minimal selection.
2. The unknown-diet case took two steps and 6,809 tokens; it performed a protected personal query with `no_match`. Its stage spans include ~2.44 s Windows Hello verification and ~2.46 s personal authorization. These overlap and must not be summed with total turn time.
3. All six seeded three projects; no foreign fixture source IDs appeared in final contexts. This tests a specific project-isolation boundary, not all security properties.
4. The elapsed p95 is the maximum of only six samples; first-case setup/routing overhead and the extra personal authorization case make the distribution heterogeneous. No reliable production tail latency or speech-to-first-audio result follows.
5. These results have no same-machine baseline using full history, no 100/200-event scaling, no replay repetition and no before/after comparison. **No measured context-efficiency improvement or token-saving percentage is established by this batch.**
6. Provider-step counts are the reported returned steps, not guaranteed counts of failed lower-layer attempts; token telemetry is observed usage, not billing proof. No automatic extraction, native speech or installed Jarvis activation is accepted.

## Disposition

- **Pass** for bounded test execution, expected evidence presence, no reported foreign-project fixture IDs, and known token accounting.
- **Open** for strict answer grounding/attribution (cases `p0-q0` and `p1-q1`), long-history efficiency, representative latency and full 60-development/40-held-out accuracy.
- **No runtime changes recommended solely from these six samples.** Follow-up: compare source selection, input tokens, provider steps, latency and grounded answer quality at increasing same-project history sizes using isolated offline tests before limited model calls.
- Keep PR #303 in draft; do not merge or activate the installed Jarvis from this evidence.
