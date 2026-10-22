# Personal automatic learning qualification — 22 October 2026

Status: implementation candidate; **not production accepted, not ready to merge or activate**. Native execution and the written design/plan were owner approved. Main remains the separately accepted explicit/context release. Automatic learning remains OFF by default.

## What the candidate implements

Normal `jarvis-voice --personal-learning apply` opens one Windows Hello owner-operated delegation, maximum 15 minutes and 5 minutes idle. Ordinary eligible facts can enter canonical encrypted memory without per-fact questions. Source-grounded extraction, closed canonical identity resolution, atomic batches, replay protection, exact-version checks, lifecycle history, physical facet forgetting and category suppression share existing memory/Authority owners. Fresh wakes can reuse the live grant; provider private history still retires after one personal answer. Lock/expiry invalidates write/read/audio continuity. This does not verify every later speaker.

Scope: standard owned items, food/response preferences, routines and ongoing goals. Medical, financial, private/local-only, secrets and third-party profiles are outside automatic admission. Explicit destructive/private operations retain exact approval. Forgotten categories remain suppressed until a separately explicit re-enable; a local `--reenable-learning-category <category>` control requires a separate, exact-category Windows Hello approval and is not a model tool. Startup reports suppressed category names without personal values. Recognized full-category negative instructions persist suppression; a current-turn veto alone does not suppress a whole category.

## Software evidence

- Baseline before implementation: 2,636 passed, 8 skipped; dependency check clean.
- Whole suite after the independent review repair pass: **2,734 passed, 8 skipped**, exit 0, 173.91 seconds after all new files were tracked. This includes the Gemini wire-format and evaluation-report repairs plus all six review fixes.
- Entire-repo Ruff lint and format checks passed (977 formatted files); dependency check clean. Final exact-head CI is recorded with the draft PR.
- Actual installed OPA parsed the policy, then a fictional full save/read check committed two entities and released their context. A policy protocol-version mismatch found by the real engine was fixed and regression-pinned. Fake policy tests alone had missed it.
- Windows SQLCipher 4.17.0 / SQLite 3.53.3 / DPAPI production-adapter smoke passed all checks on a new fictional DB, including schema 3, ledger, reopen, FTS, protected key, plaintext denial and no marker leakage. No owner DB was opened or migrated.
- Packaged Windows Hello helper invalid-request contract returned exit 2 and the expected JSON. No actual Hello dialog, microphone, recording or camera was exercised during these checks.
- Relevant semantic boundary fixes: routine schedule updates now preserve identity and replace the supported value; normalized context includes that value. Original Pydantic bounds remain mandatory after parsing provider output.

## Independent review and repair pass

A completed independent review of `7de92b3d..f658c6e7` found six Important issues, no Critical issues and no deferred minors. The first reviewer stopped at its usage limit without a verdict; a fresh replacement reviewer completed the review. The single repair pass addresses:

1. Enforce the shared five-category relation registry in SQL before the catalog bound and again at delegated context release. Unrelated standard owner facts cannot reach the resolver/context provider under this grant.
2. Map supported legacy singular/plural vehicle/device facets to category suppression in the same physical forget transaction. Preserve opaque plural records without guessing separate identities.
3. Persist recognized English/Hindi/Hinglish category vetoes before cloud inference. Invalidate pending fact windows, retain queued privacy controls, and prevent a saturated queue from dropping them. Suppression survives database reopen.
4. Distinguish entity labels and kinds when deduplicating: separate vehicles with the same model name, or routines with the same time, can coexist.
5. Reject scalar updates whose selected canonical predicate differs from the candidate's registered relation (language versus response style).
6. Expose governed local recovery: `jarvis-voice --personal-learning apply --reenable-learning-category owned_item.vehicle`. A separate exact-category fresh Windows Hello approval is consumed once at the writer transaction; stale/wrong-category/fabricated approval fails. Old accepted sources remain invalid. This command is for later owner testing, not an activation performed by this audit.

Each issue has an observed RED regression before its fix. The real installed OPA also passed delegated suppression and exact-category re-enable with a fictional canonical database and fake OS/Hello. The whole suite passed again with all new files tracked: 2,734 tests, 8 skipped. Initial CI exposed the missing self-model registration for the shared registry; the existing coverage regression was observed failing locally, the durable-memory descriptor was corrected, and the entire suite reran. These checks do not establish provider semantic quality or owner spoken acceptance.

## Frozen provider cohort

The unchanged content has 90 fictional episodes: 30 English, 30 Hindi, 30 Hinglish. Each language has 15 positive create/change/correction episodes, five duplicate/no-op episodes, five exclusion episodes and five lifecycle/unknown/irrelevant episodes. One positive episode contains two facts. Thirty questions are designated for paired answers, ten per language. Language versions share scenario families, so independence of confidence intervals is limited.

Input SHA-256: `c8c275eb89596dfdbee2c5b685642162dc21a1a5e65fe4bb91811b1e86691984`.
Gold SHA-256: `9471f55622a8110515c3c189ff4b9b13278f7f0c91e6818d1f6f2fb4574ec010`.
Both are pinned in the [manifest](../../benchmarks/personal_auto_learning_v1_manifest.json), runner and LF checkout attributes. Labels/expected outcomes are separate from provider payloads. No retired acceptance corpus was reused. The runner defaults to no network and cannot declare acceptance from fixtures.

The first cohort attempt returned HTTP 400 before any semantic response. Six additional bounded fictional transport diagnostics isolated a serving-grammar problem: simple JSON worked; the full bounded, strict and inlined schemas failed; removing array/numeric serving bounds worked. The approved 270-attempt cap covered these seven attempts. No gold or held-out answer was sent by the transport checks. The model itself was present in the provider model metadata.

The Gemini wire schema now omits those grammar bounds and requires all fields. Canonical Pydantic validation still enforces candidate count, spans, text sizes, enum/intent fields and numeric limits. Responses have a 4,096 output-token cap and the worker has 10-second inference deadlines. This is a transport fix, not a looser write policy. [Google documents this schema-complexity failure mode](https://ai.google.dev/gemini-api/docs/structured-output). OpenAI strict schemas require all properties and closed objects, which are projected independently; this follows [official OpenAI structured-output guidance](https://developers.openai.com/api/docs/guides/structured-outputs).

The same unexposed frozen cohort resumed on `2a7c7136` with a maximum 263 remaining attempts. It stopped at **HTTP 429 RateLimitError** from active-provider `gemini-3.5-flash` answering. No retry, paid fallback, model switch, quota purchase or new account was used.

Observed evidence:

- Semantic episodes completed: **4/90**, all English. Hindi/Hinglish: **0/30 each**; 86 episodes unrun.
- Learning requests: 4. Paired-answer requests: 7, of which 6 returned and one hit 429. Complete pairs: **3/30**. No full advice-success claim.
- Total inference attempts across initial cohort, transport diagnostics and resumed cohort: **18/270**. Provider metadata lookup is not inference. Later non-retry continuations are reported below; the 18-attempt figure describes this historical stage.
- First four episodes expected five facts; three were committed correctly (two vehicles and a camera). Routine and goal capture were missed. Observed admission precision 3/3, capture recall 3/5, with a tiny exposed English-only denominator. These are **not release-floor evidence** and do not establish all-language quality. Do not tune and rescore these exposed cases as a fresh holdout.
- Resumed run reported 4,208 total tokens for returned responses. One minimal preflight did not retain usage; failed/cancelled request billing is unknown, so no complete monetary/cost claim is made. The successful bounds preflight separately reported 34 tokens.
- Resumed request latency: n=11, p50 approximately 2.46 s, p95 approximately 3.92 s. This includes the failure; it is not time to first voice speech.
- Callback measurements are from four fictional OS/Hello cases only. They do not qualify the <=10 ms p95 target, voice interruption UX, owner hardware, GPU/RAM impact or normal audio latency.

The raw immutable artifacts are [initial request](../../benchmarks/results/personal-auto-learning-2026-10-22-v1/summary.json) and [resumed partial cohort](../../benchmarks/results/personal-auto-learning-2026-10-22-v1-resumed/summary.json), with shuffled answer arms saved beside them. The old runner retained the completed semantic row but omitted a dedicated answer-unavailable field when the later answer failed; usage/status and incomplete pairs expose that failure. A regression now preserves this field for subsequent runs. Historical artifacts are not rewritten to manufacture a pass.

## Non-retry continuation on reviewed candidate

After the six review repairs, only previously unexecuted cases ran on `5af652a6`. The fixed order alternated language groups, and the first segment waited 45 seconds between episodes. Its [predeclared protocol and journal](../../benchmarks/results/personal-auto-learning-2026-10-22-v1-continued/continuation_plan.json) bind the candidate, hashes, prior artifact and remaining 252-attempt allowance.

Four additional semantic episodes completed: two English, one Hindi and one Hinglish. All six expected facts in those cases were admitted correctly. Three additional answer pairs completed; the later English language-preference answer was unavailable at approximately the 10-second deadline, with no returned response or provider error detail. A separate [remaining-only segment](../../benchmarks/results/personal-auto-learning-2026-10-22-v1-continued-2/summary.json), paced 45 seconds after answer episodes and 10 seconds otherwise, then stopped on a new semantic case's recorded timeout. Neither failed/exposed case was retried. Returned-response token usage across both later segments was 4,749; failed/cancelled billing remains unknown.

At this checkpoint: **30/270 total inference attempts**, 8/90 unique semantic episodes completed, 1 additional semantic episode unavailable, 81 unrun; 6/30 complete answer pairs. New candidate-only evidence is four completed episodes/six expected facts, with very small denominators; do not combine different candidate revisions into a current-head release pass. A read-only model metadata request succeeded in 0.32 seconds after the timeouts: credentials/metadata access are available, but that does not prove inference availability or identify the timeout cause. No paid fallback, account/key change or quota purchase was performed.

The three new complete pairs were judged by the author agent before opening their arm key: each supported arm used the requested fact, and each empty-context arm truthfully lacked it, with no observed invented owner fact in those three pairs. This is a small author review, not independent human acceptance or all-language advice qualification. Historical rows, unavailable answers and failed requests are preserved unchanged. The current mode remains an unaccepted candidate.

A later automatic approval review stopped the proposed next live request, interpreting the earlier stop statement as a request boundary. The owner then explicitly authorized **one new Hindi case, at most three requests** on the same account. That [bounded check](../../benchmarks/results/personal-auto-learning-2026-10-22-v1-continued-3/summary.json) saved and retrieved the fictional camera correctly. One answer arm returned; the other was unavailable at the 10-second boundary, so no complete pair was scored. No further inference was sent after that approved case.

Latest checkpoint: **33/270 total inference attempts**, **9/90 unique semantic episodes completed**, one additional semantic episode unavailable, **80 unrun**, **6/30 complete answer pairs**. On the reviewed implementation alone, five semantic episodes completed (EN2, HI2, Hinglish1) with all seven expected facts captured correctly; this is still far short of the frozen all-language qualification. No total cash-cost estimate, all-language quality pass, hardware/voice latency pass, normal-app owner acceptance or feature-complete claim follows from it.

## Remaining release gates

1. Obtain sufficient existing-provider availability and explicitly resume only unrun qualification work under the remaining budget. Preserve exposed/unavailable outcomes; do not silently retry a failed case for a higher score. Any changed semantic approach needs a separately frozen fresh holdout and honest accounting.
2. Finish all-language capture/precision, identity and relation-use checks, complete paired-answer review and publish denominators/uncertainty. No claim that native learning outperforms every external framework is justified by this partial run.
3. Complete final exact-candidate verification/CI after the independent review repair pass. The completed review found six Important issues and no Critical/minor findings; their fixes and failing-then-passing regressions are listed below. Keep CAP-053 partial and draft status while quality is unqualified.
4. Only after software/provider gates pass, have the owner run the **whole normal local app** with fictional facts, fresh wakes, restart, change and forget. Record spoken behavior/session UX per Quality Gates §11. No isolated microphone demo or owner-written corpus is required.
5. The owner separately approves checked-candidate promotion. Earlier PR #292–#294 approval does not authorize merging this feature.

## Reproducibility and rollback

Default contract check: `python tools/research/personal_auto_learning_eval.py --output <new-directory>`.
The explicit fictional-provider opt-in is `--allow-fictional-provider-run`; do not rerun it casually against the exposed cohort. Attempt caps apply across learning and answering, without retries. Exact commands, commits and outcomes are retained in the implementation ledger and PR.

Stop JARVIS to revoke grants. Launch with `--personal-learning off --personal-context apply` to retain exact-consent context/explicit memory, or `--personal-learning off --personal-context off` for both modes off. A launch flag does not downgrade storage: schema 3 cannot be opened with an older schema-2 binary. Use a schema-3-compatible rollback build or a separately reviewed encrypted backup restoration; never delete/downgrade owner data as rollback.
