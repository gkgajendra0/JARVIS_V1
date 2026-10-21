# Personal automatic learning qualification — 22 October 2026

Status: implementation candidate; **not production accepted, not ready to merge or activate**. Native execution and the written design/plan were owner approved. Main remains the separately accepted explicit/context release. Automatic learning remains OFF by default.

## What the candidate implements

Normal `jarvis-voice --personal-learning apply` opens one Windows Hello owner-operated delegation, maximum 15 minutes and 5 minutes idle. Ordinary eligible facts can enter canonical encrypted memory without per-fact questions. Source-grounded extraction, closed canonical identity resolution, atomic batches, replay protection, exact-version checks, lifecycle history, physical facet forgetting and category suppression share existing memory/Authority owners. Fresh wakes can reuse the live grant; provider private history still retires after one personal answer. Lock/expiry invalidates write/read/audio continuity. This does not verify every later speaker.

Scope: standard owned items, food/response preferences, routines and ongoing goals. Medical, financial, private/local-only, secrets and third-party profiles are outside automatic admission. Explicit destructive/private operations retain exact approval. Forgotten categories remain suppressed until a separately explicit re-enable; current public service control is not a model tool.

## Software evidence

- Baseline before implementation: 2,636 passed, 8 skipped; dependency check clean.
- Whole suite on `a25d40a9`: **2,716 passed, 8 skipped**, exit 0. This precedes the later Gemini wire-format fix; final review verification must cover subsequent changes.
- Ruff format and lint passed before that fix; focused schema/evaluation tests subsequently passed. Final exact-head checks are recorded with the PR.
- Actual installed OPA parsed the policy, then a fictional full save/read check committed two entities and released their context. A policy protocol-version mismatch found by the real engine was fixed and regression-pinned. Fake policy tests alone had missed it.
- Windows SQLCipher 4.17.0 / SQLite 3.53.3 / DPAPI production-adapter smoke passed all checks on a new fictional DB, including schema 3, ledger, reopen, FTS, protected key, plaintext denial and no marker leakage. No owner DB was opened or migrated.
- Packaged Windows Hello helper invalid-request contract returned exit 2 and the expected JSON. No actual Hello dialog, microphone, recording or camera was exercised during these checks.
- Relevant semantic boundary fixes: routine schedule updates now preserve identity and replace the supported value; normalized context includes that value. Original Pydantic bounds remain mandatory after parsing provider output.

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
- Total inference attempts across initial cohort, transport diagnostics and resumed cohort: **18/270**. Provider metadata lookup is not inference. No additional provider execution has been performed after the 429.
- First four episodes expected five facts; three were committed correctly (two vehicles and a camera). Routine and goal capture were missed. Observed admission precision 3/3, capture recall 3/5, with a tiny exposed English-only denominator. These are **not release-floor evidence** and do not establish all-language quality. Do not tune and rescore these exposed cases as a fresh holdout.
- Resumed run reported 4,208 total tokens for returned responses. One minimal preflight did not retain usage; failed/cancelled request billing is unknown, so no complete monetary/cost claim is made. The successful bounds preflight separately reported 34 tokens.
- Resumed request latency: n=11, p50 approximately 2.46 s, p95 approximately 3.92 s. This includes the failure; it is not time to first voice speech.
- Callback measurements are from four fictional OS/Hello cases only. They do not qualify the <=10 ms p95 target, voice interruption UX, owner hardware, GPU/RAM impact or normal audio latency.

The raw immutable artifacts are [initial request](../../benchmarks/results/personal-auto-learning-2026-10-22-v1/summary.json) and [resumed partial cohort](../../benchmarks/results/personal-auto-learning-2026-10-22-v1-resumed/summary.json), with shuffled answer arms saved beside them. The old runner retained the completed semantic row but omitted a dedicated answer-unavailable field when the later answer failed; usage/status and incomplete pairs expose that failure. A regression now preserves this field for subsequent runs. Historical artifacts are not rewritten to manufacture a pass.

## Remaining release gates

1. Obtain sufficient existing-provider availability and explicitly resume only unrun qualification work under the remaining budget. Preserve exposed/unavailable outcomes; do not silently retry a failed case for a higher score. Any changed semantic approach needs a separately frozen fresh holdout and honest accounting.
2. Finish all-language capture/precision, identity and relation-use checks, complete paired-answer review and publish denominators/uncertainty. No claim that native learning outperforms every external framework is justified by this partial run.
3. Finish independent whole-branch review and exact-candidate checks/CI. Keep CAP-053 partial and draft status while quality is unqualified.
4. Only after software/provider gates pass, have the owner run the **whole normal local app** with fictional facts, fresh wakes, restart, change and forget. Record spoken behavior/session UX per Quality Gates §11. No isolated microphone demo or owner-written corpus is required.
5. The owner separately approves checked-candidate promotion. Earlier PR #292–#294 approval does not authorize merging this feature.

## Reproducibility and rollback

Default contract check: `python tools/research/personal_auto_learning_eval.py --output <new-directory>`.
The explicit fictional-provider opt-in is `--allow-fictional-provider-run`; do not rerun it casually against the exposed cohort. Attempt caps apply across learning and answering, without retries. Exact commands, commits and outcomes are retained in the implementation ledger and PR.

Stop JARVIS to revoke grants. Launch with `--personal-learning off --personal-context apply` to retain exact-consent context/explicit memory, or `--personal-learning off --personal-context off` for both modes off. A launch flag does not downgrade storage: schema 3 cannot be opened with an older schema-2 binary. Use a schema-3-compatible rollback build or a separately reviewed encrypted backup restoration; never delete/downgrade owner data as rollback.
