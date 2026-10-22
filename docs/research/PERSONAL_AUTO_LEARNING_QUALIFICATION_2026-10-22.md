# Personal automatic learning qualification — 22 October 2026

**Current checkpoint:** code ede43720; fresh45 attempted,40complete/5unavailable; conditional29/30 correct effects with one partial Hindi correction. Conservative request upper262/270,8 remain. No release acceptance. Earlier sections below are dated historical checkpoints; the final section contains current totals.

Status: implementation candidate; **not production accepted, not ready to merge or activate**. Native execution and the written design/plan were owner approved. Main remains the separately accepted explicit/context release. Automatic learning remains OFF by default.

## Request-accounting correction

**Historical `provider_attempts` fields count outer SDK calls, not proven HTTP sends.** An offline installed-SDK transport regression discovered that google-genai 2.22 maps `attempts=1` to one Interactions retry, while `attempts=0` is normalized back to one. A mocked 429 produced two sends. Thus earlier statements that 33 was an exact inference-request count, that every historical operation had no SDK retry, or that the last approved case proved a three-send limit are not established. No further live inference has run while correcting this boundary; historical artifacts remain unchanged.

The dedicated Interactions resource now explicitly sets nullable `retry_config=None`. Real-SDK mocked transport tests for 429, 503 and read timeout prove one send and prompt error reporting, including long Retry-After headers. If the pinned SDK removes this configuration, startup fails rather than silently enabling retries. Retry waiting could have masked historical rate errors as outer timeouts; this is an inference, not a confirmed historical root cause.

Reserve **87 historical sends conservatively**: 26 regular outer calls at at most two sends, plus seven early transport diagnostics at at most five. The approved total remains **270**; at most **183 future single-send requests** are available, stricter than the owner's approval for up to 237 more. Actual earlier billing/transport counts are unknown; metadata-only and offline mocked calls are excluded. See the [accounting correction](../../benchmarks/results/personal-auto-learning-2026-10-22-budget-correction.json).

## What the candidate implements

Normal `jarvis-voice --personal-learning apply` opens one Windows Hello owner-operated delegation, maximum 15 minutes and 5 minutes idle. Ordinary eligible facts can enter canonical encrypted memory without per-fact questions. Source-grounded extraction, closed canonical identity resolution, atomic batches, replay protection, exact-version checks, lifecycle history, physical facet forgetting and category suppression share existing memory/Authority owners. Fresh wakes can reuse the live grant; provider private history still retires after one personal answer. Lock/expiry invalidates write/read/audio continuity. This does not verify every later speaker.

Scope: standard owned items, food/response preferences, routines and ongoing goals. Medical, financial, private/local-only, secrets and third-party profiles are outside automatic admission. Explicit destructive/private operations retain exact approval. Forgotten categories remain suppressed until a separately explicit re-enable; a local `--reenable-learning-category <category>` control requires a separate, exact-category Windows Hello approval and is not a model tool. Startup reports suppressed category names without personal values. Recognized full-category negative instructions persist suppression; a current-turn veto alone does not suppress a whole category.

## Software evidence

- Baseline before implementation: 2,636 passed, 8 skipped; dependency check clean.
- Whole suite after the independent review repair pass: **2,737 passed, 8 skipped**, exit 0, 171.65 seconds after the SDK retry fix. This includes the Gemini wire-format and evaluation-report repairs plus all six review fixes.
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

Each issue has an observed RED regression before its fix. The real installed OPA also passed delegated suppression and exact-category re-enable with a fictional canonical database and fake OS/Hello. The whole suite passed again with all new files tracked: 2,734 tests, 8 skipped before the SDK fix; 2,737 passed afterward. Initial CI exposed the missing self-model registration for the shared registry; the existing coverage regression was observed failing locally, the durable-memory descriptor was corrected, and the entire suite reran. These checks do not establish provider semantic quality or owner spoken acceptance.

## Frozen provider cohort

The unchanged content has 90 fictional episodes: 30 English, 30 Hindi, 30 Hinglish. Each language has 15 positive create/change/correction episodes, five duplicate/no-op episodes, five exclusion episodes and five lifecycle/unknown/irrelevant episodes. One positive episode contains two facts. Thirty questions are designated for paired answers, ten per language. Language versions share scenario families, so independence of confidence intervals is limited.

Input SHA-256: `c8c275eb89596dfdbee2c5b685642162dc21a1a5e65fe4bb91811b1e86691984`.
Gold SHA-256: `9471f55622a8110515c3c189ff4b9b13278f7f0c91e6818d1f6f2fb4574ec010`.
Both are pinned in the [manifest](../../benchmarks/personal_auto_learning_v1_manifest.json), runner and LF checkout attributes. Labels/expected outcomes are separate from provider payloads. No retired acceptance corpus was reused. The runner defaults to no network and cannot declare acceptance from fixtures.

The first cohort attempt returned HTTP 400 before any semantic response. Six additional bounded fictional transport diagnostics isolated a serving-grammar problem: simple JSON worked; the full bounded, strict and inlined schemas failed; removing array/numeric serving bounds worked. The approved 270-attempt cap covered these seven attempts. No gold or held-out answer was sent by the transport checks. The model itself was present in the provider model metadata.

The Gemini wire schema now omits those grammar bounds and requires all fields. Canonical Pydantic validation still enforces candidate count, spans, text sizes, enum/intent fields and numeric limits. Responses have a 4,096 output-token cap and the worker has 10-second inference deadlines. This is a transport fix, not a looser write policy. [Google documents this schema-complexity failure mode](https://ai.google.dev/gemini-api/docs/structured-output). OpenAI strict schemas require all properties and closed objects, which are projected independently; this follows [official OpenAI structured-output guidance](https://developers.openai.com/api/docs/guides/structured-outputs).

The same unexposed frozen cohort resumed on `2a7c7136` with a maximum 263 remaining attempts. It stopped at **HTTP 429 RateLimitError** from active-provider `gemini-3.5-flash` answering. No deliberate harness retry, paid fallback, model switch, quota purchase or new account was used; the historical SDK retry caveat above applies.

Observed evidence:

- Semantic episodes completed: **4/90**, all English. Hindi/Hinglish: **0/30 each**; 86 episodes unrun.
- Learning requests: 4. Paired-answer requests: 7, of which 6 returned and one hit 429. Complete pairs: **3/30**. No full advice-success claim.
- Total inference attempts across initial cohort, transport diagnostics and resumed cohort: **18 recorded outer calls at this historical stage**. Provider metadata lookup is not inference. Later non-retry continuations are reported below; the 18-attempt figure describes this historical stage.
- First four episodes expected five facts; three were committed correctly (two vehicles and a camera). Routine and goal capture were missed. Observed admission precision 3/3, capture recall 3/5, with a tiny exposed English-only denominator. These are **not release-floor evidence** and do not establish all-language quality. Do not tune and rescore these exposed cases as a fresh holdout.
- Resumed run reported 4,208 total tokens for returned responses. One minimal preflight did not retain usage; failed/cancelled request billing is unknown, so no complete monetary/cost claim is made. The successful bounds preflight separately reported 34 tokens.
- Resumed request latency: n=11, p50 approximately 2.46 s, p95 approximately 3.92 s. This includes the failure; it is not time to first voice speech.
- Callback measurements are from four fictional OS/Hello cases only. They do not qualify the <=10 ms p95 target, voice interruption UX, owner hardware, GPU/RAM impact or normal audio latency.

The raw immutable artifacts are [initial request](../../benchmarks/results/personal-auto-learning-2026-10-22-v1/summary.json) and [resumed partial cohort](../../benchmarks/results/personal-auto-learning-2026-10-22-v1-resumed/summary.json), with shuffled answer arms saved beside them. The old runner retained the completed semantic row but omitted a dedicated answer-unavailable field when the later answer failed; usage/status and incomplete pairs expose that failure. A regression now preserves this field for subsequent runs. Historical artifacts are not rewritten to manufacture a pass.

## Non-retry continuation on reviewed candidate

After the six review repairs, only previously unexecuted cases ran on `5af652a6`. The fixed order alternated language groups, and the first segment waited 45 seconds between episodes. Its [predeclared protocol and journal](../../benchmarks/results/personal-auto-learning-2026-10-22-v1-continued/continuation_plan.json) bind the candidate, hashes, prior artifact and remaining 252-attempt allowance.

Four additional semantic episodes completed: two English, one Hindi and one Hinglish. All six expected facts in those cases were admitted correctly. Three additional answer pairs completed; the later English language-preference answer was unavailable at approximately the 10-second deadline, with no returned response or provider error detail. A separate [remaining-only segment](../../benchmarks/results/personal-auto-learning-2026-10-22-v1-continued-2/summary.json), paced 45 seconds after answer episodes and 10 seconds otherwise, then stopped on a new semantic case's recorded timeout. Neither failed/exposed case was deliberately replayed by the harness; the SDK retry caveat applies. Returned-response token usage across both later segments was 4,749; failed/cancelled billing remains unknown.

At this checkpoint: **30 recorded outer SDK calls at that stage**, 8/90 unique semantic episodes completed, 1 additional semantic episode unavailable, 81 unrun; 6/30 complete answer pairs. New candidate-only evidence is four completed episodes/six expected facts, with very small denominators; do not combine different candidate revisions into a current-head release pass. A read-only model metadata request succeeded in 0.32 seconds after the timeouts: credentials/metadata access are available, but that does not prove inference availability or identify the timeout cause. No paid fallback, account/key change or quota purchase was performed.

The three new complete pairs were judged by the author agent before opening their arm key: each supported arm used the requested fact, and each empty-context arm truthfully lacked it, with no observed invented owner fact in those three pairs. This is a small author review, not independent human acceptance or all-language advice qualification. Historical rows, unavailable answers and failed requests are preserved unchanged. The current mode remains an unaccepted candidate.

A later automatic approval review stopped the proposed next live request, interpreting the earlier stop statement as a request boundary. The owner then explicitly authorized **one new Hindi case, at most three requests** on the same account. That [bounded check](../../benchmarks/results/personal-auto-learning-2026-10-22-v1-continued-3/summary.json) saved and retrieved the fictional camera correctly. One answer arm returned; the other was unavailable at the 10-second boundary, so no complete pair was scored. No further inference was sent after that approved case.

Latest checkpoint: **33 recorded outer SDK calls**, **9/90 unique semantic episodes completed**, one additional semantic episode unavailable, **80 unrun**, **6/30 complete answer pairs**. On the reviewed implementation alone, five semantic episodes completed (EN2, HI2, Hinglish1) with all seven expected facts captured correctly; this is still far short of the frozen all-language qualification. No total cash-cost estimate, all-language quality pass, hardware/voice latency pass, normal-app owner acceptance or feature-complete claim follows from it.

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


## Latest checkpoint: completed original attempts and fresh capture subset

The older checkpoints above are historical, not the current totals. Every original v1 episode has now been attempted without deliberate harness replay: 89 completed, one semantic timeout, none unrun, across multiple candidate revisions. Descriptive automatic admission was 33 correct of 47 expected facts (70.2% recall), zero observed false admissions. English: 10/15, Hindi: 12/16, Hinglish: 11/16. This fails the approved recall floor and is not current-head acceptance. Explicit-control correction phrases bypassed the automatic-only harness in some cases; these remain recorded misses rather than being relabeled. Complete answer pairs are 8/30, four incomplete/failed and 18 skipped for provider quota. No skipped answer is a pass.

After the single-send SDK repair, two fresh transport development probes returned promptly. Later answering surfaced actual HTTP429. Answering-model requests stopped; 77 unrun memory/context episodes were completed separately (101 sends). Four new development cases used six sends and isolated goal value/state and routine new/change ambiguity. The structured schema descriptions now clarify these roles with two disjoint examples; no source-grounding, authority, sensitivity or admission limit was relaxed. The exposed v1 corpus will not be rescored as a fresh holdout.

Conservative historical reserve87 plus verified later single sends gives an upper bound205/270, leaving65. Exact historical HTTP/billing counts remain unknown. A proposed live replay of known development cases was rejected by automatic approval review for quota/evidence risk and did not execute. A safer alternative freezes 45 entirely new capture-only cases, 15 per language, before any call: [manifest](../../benchmarks/personal_auto_learning_capture_v2_manifest.json). This smaller subset can provide preliminary evidence under the remaining65 sends; it cannot replace the approved90-case, paired-answer or owner release gates. It uses the same account and no paid fallback, provider retry or work-role answer call. Its result is pending at this checkpoint.

A separate observed failing regression showed that explicit text correction of an automatically learned typed facet lost delegated recall. Classification now follows matching canonical typed admission history, with current scope rechecked before release; forged names and forget/recreate cannot inherit registration. Actual installed OPA plus SQLCipher/DPAPI on fictional data passed admission, correction, scoped read and forget/recreate. Fake OS/Hello only; no owner data/device access.

Latest full local suite: 2,743 passed, 8 skipped, exit0 (174.52s). Repository Ruff lint/format979 files, dependency consistency and whitespace checks pass. Exact-head CI remains required after committing these changes; earlier842a5cba passed all seven checks. Feature remains default-OFF, draft, unaccepted and unmerged.


## Final bounded validation checkpoint — capture v2 on ede43720

All45 new capture-only cases were attempted once: **40 completed, five unavailable, zero unrun**. A remaining-only continuation excluded every attempted ID and preserved the first unavailable result. No failed case was deliberately replayed. Availability was40/45 (88.9%); three language groups completed13/15,13/15,14/15 respectively. Complete-corpus and release flags remain false.

Conditional on completed cases, the frozen scorer found29 correct effects, one unmatched effect and one missing expected fact: precision29/30 (96.7%), recall29/30 (96.7%), approximate95% Wilson intervals83.3%–99.4% for each. English10/10, Hindi9/10, Hinglish10/10 expected facts. Shared scenario families limit independence; unavailable cases are not clean abstentions. This smaller, different corpus cannot establish a statistically comparable improvement over v1 or satisfy the approved90-case gate.

The unmatched Hindi effect is specifically partial correction: old Sony camera became not_owned, but the requested Nikon replacement was not retained. This is a gold mismatch and missing replacement, not proof that the old retirement itself was false. Do not relax the gold to hide it. V2 did not retain intermediate model proposals, so the exact failing stage is unknown. An offline counterfactual confirmed that a correctly structured single replacement correction is preserved by the reconciler; that is code-path evidence only. One NEW fictional Hindi headphones development case attempted to observe the intermediate output, but timed out before any raw response. It consumed one single-send request and did not resolve the cause. No further inference followed.

The two capture segments used56 verified single-send requests and reported36,178 returned-response tokens. Failed/cancelled billing is unknown. First segment request p50/p95:2.40/7.33s (n44); continuation:9.54/10.01s (n12). Accepted-turn callback p50/p95:0.493/0.875ms versus baseline0.023/0.036ms (n48, controlled fictional harness). These do not establish voice latency, hardware profile or owner UX. The separate development timeout had a17.5ms callback outlier and is not included in the frozen cohort metric.

Final conservative cumulative upper bound: **262/270**, leaving8 sends. Historical actual send/billing counts remain unknown; the reserve methodology is unchanged. No paid fallback/account change/quota purchase, no work-role answer request after429, and no owner-device activation. The eight remaining sends cannot complete a genuinely fresh full90/30-pair qualification. Further live investigation/qualification requires a concrete new bounded budget and existing-provider availability; until then retain the draft/unaccepted/default-OFF state.

Reproducible combined evidence: [aggregate](../../benchmarks/results/personal-auto-learning-2026-10-22-capture-v2-aggregate.json), [first segment](../../benchmarks/results/personal-auto-learning-2026-10-22-capture-v2/summary.json), [remaining-only segment](../../benchmarks/results/personal-auto-learning-2026-10-22-capture-v2-remaining/summary.json), [new development probe](../../benchmarks/results/personal-auto-learning-2026-10-22-new-correction-diagnosis/summary.json). Existing v1 artifacts remain immutable.
