# PI-3A question-bound context: implementation and acceptance record

Date: 22 October 2026. Status: **IMPLEMENTED / SOFTWARE-VERIFIED CANDIDATE; all three Important review findings repaired and regression-verified.** Normal-app/model-quality acceptance remains pending. This is the first PI-3 slice, not completion of personal intelligence or acceptance of all PI-2 learning behavior.

## What changed for the owner

In a learning-APPLY voice session, JARVIS can request relevant categories of saved information for the current question, combine a bounded set of current facts, and identify an exact named item without selecting opaque memory indices. Two vehicles among unrelated devices are selected as vehicles; a broad request exceeding the evidence budget returns a narrowing clarification rather than an arbitrary first four. A general question should not request personal context. Those language/model behaviors still need observation in the whole normal app.

Correction, forget, changed candidate membership and changed source eligibility invalidate the old evidence before further guarded audio. An unselected item changing to the same name also invalidates a formerly unique answer. Existing private owner-session limits, exact mutation controls, process-scoped flags and default OFF remain intact. There is no per-fact save prompt, new memory backend, extra HTTP reasoner or new model dependency.

The owner approved the [written design](../superpowers/specs/2026-10-22-pi3-entity-aware-context-design.md), then the [seven-task Native plan](../superpowers/plans/2026-10-22-pi3-entity-aware-context.md). Base: `6f4f197d`, atop unmerged PI-2 candidate `6f52b8ea` / draft PR #295. Development remains in the owner's Desktop checkout. Older PR #295 is not silently updated or merged by this work.

## Runtime implementation

- `memory/personal_context_projection.py`: strict current-question requests, local exact-label selection, all-or-nothing scope union, evidence projection and private scope signature. Only the seven existing registered scopes are available.
- `memory/query.py` and `memory/retrieval.py`: public coherent snapshot facade over the existing eligible-current canonical query. One read savepoint captures current records and suppression state; existing admission-history registration for TEXT correction is reused.
- `voice/personal_context.py`: one serialized per-answer ledger across new and legacy read tools, three pre-release query evaluations, current permit/turn checks, scope/source/version validation and existing audio retirement. Query state is cleared on close/mutation lifecycle.
- `voice/agent.py`: the registered tool and learning-APPLY instructions agree. Ordinary advice uses the new tool; explicit correction/forget retains existing catalog targeting. Context-only and OFF behavior remains supported.
- Pinned LiveKit's raw function schema carries the same provider-visible request object while local strict parsing owns validation. This avoids SDK coercion/null-default substitution bypassing attempt accounting. Both current Google schema-conversion forms were exercised without an API call.

Canonical SQLCipher, Conversation, Authority and the existing realtime model retain their respective responsibilities. The code-owned query narrows an already-authorized read; a model argument does not create authority or prove semantic relevance. Returned text is inert evidence and cannot grant a write or device/Work/Hands action.

## Verification evidence

Per-task RED/GREEN evidence was observed before product implementation:

| Stage | Observed result |
| --- | --- |
| Baseline context/runtime/voice | 38 passed |
| Task 1 strict contracts | Missing-module RED; initial 34 passed; two malformed structured-scope cases added/fixed in Task 2 |
| Task 2 coherent canonical reader | Missing-interface RED; contracts/snapshot/prior regressions/query/retrieval 63 passed; real WAL writer interleaving proved snapshot consistency |
| Task 3 projection | Missing-interface RED; 53 contract/snapshot/projection cases passed, including 1,800/1,801 bytes and mixed-item ordering |
| Task 4 session/release | Eight missing-query RED failures; 44 session/context/runtime/memory-tool cases passed |
| Task 5 lifecycle/audio | Duplicate/suppression stale-audio and cleanup RED failures; 71 lifecycle/session/authority/forget/runtime/production cases passed |
| Task 6 normal composition | Six missing registered-tool/instruction/path RED failures; 38 production/voice/context-sync cases passed |
| Task 7 local measurement | Three bounded measurement cases passed; results below |

Pre-review full local repository suite: **2,843 passed / 8 skipped**, exit 0, 390.86 seconds, with an isolated machine-config path. Four skips concern unavailable symlink creation and four are Linux/non-Windows negative controls. Full Ruff lint and formatting checks passed; 1,002 files formatted at this checkpoint; whitespace/new-link checks passed. The fresh independent review found three Important issues; their repairs and final rerun are described below. This does not substitute for exact-head GitHub CI, SQLCipher production IO, actual-model or owner-machine acceptance.

These are software contracts and forced normal-controller tool/audio checks. They do not prove the live model independently chooses a tool, resolves the intended meaning or gives a useful spoken answer. No new Gemini inference batch, paid fallback, account/model change or local JARVIS activation was performed.

## Local latency measurement

Windows 10 build 26300, Python 3.11.9; fictional temporary canonical databases. Five warmups followed by 30 measured fresh-session operations per path/size. Existing owner authority is real code with fake OS/Hello; no provider latency, microphone, encrypted production-database IO or startup is measured. Each operation includes context acquisition plus an audio authorization/currentness guard. The legacy baseline explicitly selects the known correct index, so this compares local path cost, not selection quality.

| Current scoped records | Legacy p50 / p95 / max (ms) | New query p50 / p95 / max (ms) | Legacy / query max heartbeat delay (ms) |
| --- | --- | --- | --- |
| 1 | 5.75 / 7.22 / 7.73 | 4.63 / 5.74 / 6.47 | 1.11 / 1.51 |
| 8 | 7.06 / 8.46 / 9.49 | 4.96 / 6.67 / 6.73 | 1.35 / 1.18 |
| 32 | 9.06 / 11.14 / 12.04 | 7.04 / 8.59 / 8.66 | 1.85 / 1.95 |

The query path had lower local p95 in this small run; heartbeat variation was about 1-2 ms. This is not a voice SLA, a general performance guarantee or the older unqualified 10 ms cold-callback target. Timing is environment-sensitive. Raw first-run results were retained in this plan's workspace while work was active; this table preserves the measured outcome after scratch cleanup. The test harness remains reproducible as `tests/learning/test_context_query_performance.py`. The full-suite invocation may execute the harness again; its incidental timing is not substituted for this first measurement.

### Measurement after the review repairs

The mandatory authorization changes justify a fresh bounded measurement. Both legacy and query paths include the repaired post-storage authority checks; this run is not a retry/rescore of the earlier code. Five warmups and 30 samples per path/size were retained with the same fixture method.

| Current scoped records | Repaired legacy p50 / p95 / max (ms) | Repaired query p50 / p95 / max (ms) | Legacy / query max heartbeat delay (ms) |
| --- | --- | --- | --- |
| 1 | 9.69 / 21.59 / 23.00 | 6.93 / 14.01 / 16.28 | 5.62 / 5.10 |
| 8 | 12.21 / 18.43 / 23.21 | 8.27 / 16.42 / 20.14 | 4.47 / 4.23 |
| 32 | 15.75 / 21.94 / 24.22 | 12.30 / 18.20 / 18.21 | 4.36 / 4.44 |

Both paths were slower than the earlier run; the data do not isolate the contribution of added validation versus host scheduling/load. The query path's p95 remained lower than legacy within this run. Use this post-repair table for the final code; do not cite the first 5.74-8.59 ms query p95 as the repaired candidate's performance. No 10 ms guarantee, end-to-end voice claim or optimization acceptance is inferred. No additional run was used to select a better score.

## Boundaries still visible

- Maximum 32 current scoped assertions; four released assertions; 1,800 bytes for the entire serialized facts array including metadata. Broad/large requests ask for narrowing; a legacy plural assertion still counts as one stored assertion.
- A named target must use an exact quote from the accepted current question and match a current validated typed label after NFKC/case/whitespace normalization. Translation, transliteration, fuzzy aliases and unresolved pronouns are not implemented. Legacy/TEXT records remain readable by scope; their old labels are not revived after correction.
- Last-known facts are not current physical observation. Recording time is not purchase/event time. Ownership does not reveal motives, budget or medical restrictions.
- One private delegated session is not per-speaker biometric attribution. Private provider history still retires after a personal answer; a fresh wake is required for another request within the existing grant.
- SDK transport syntax rejection can happen before the tool is invoked; such failures are not local query evaluations. This feature does not replace the upstream JSON repair/transport parser. Locally handled invalid requests use fixed diagnostics and never echo owner values.
- PI-2 broad provider/resource qualification and automatic-learning normal-app acceptance remain deferred/open. The request budget ledger is not authorization for new inference.

## Whole normal-app acceptance protocol — pending, not executed

Use the intended candidate checkout in `C:\Users\gkgaj\Desktop\jarvis_v1`. This report does not merge main, change a saved machine profile or start the microphone. The actual selected memory profile should be agreed before adding fictional data; do not replace, reset or delete an owner database to run this protocol. Fictional facts can coexist with prior authorized facts; absence of another item is not a complete-profile claim.

Launch the complete app when the owner chooses to test:

```powershell
.\.venv\Scripts\jarvis-voice.exe --personal-learning apply
```

1. Open the private owner session through the normal Hello flow. In ordinary conversation introduce fictional vehicles with distinctive names and several fictional devices, plus a relevant fictional ongoing goal. Use English, Hindi and Hinglish naturally; no "remember this" or save-confirmation prompt should be necessary. Record actual canonical admissions separately from what a spoken reply claims. Keep total current scoped data within the existing 32-record bound.
2. After a fresh wake, ask a normal broad vehicle question; then ask about one named vehicle using the same label/script as stored. Verify actual tool selection and that device facts do not displace the relevant vehicles. Broad old+new vehicle data may require narrowing when it exceeds four facts/the byte cap.
3. Ask for advice needing a saved preference and a relevant goal, an unrelated programming question, an ambiguous item question and an unknown purchase reason. Expect relevant grounded use, no irrelevant memory lookup, natural clarification and truthful unknowns respectively. Do not credit a forced/mock tool call as model behavior.
4. Correct a fictional item through ordinary speech, ask again after a fresh wake, restart and explicitly relaunch APPLY, then verify the current value. Source/update timing and spoken outcome must be distinguished if learning/provider processing is unavailable.
5. Run the forget case last. Verify no later use of the forgotten fact and that category suppression prevents automatic relearning. Re-enable only through the existing explicit owner control if desired; no automatic renewal or re-enable is part of this slice.
6. Retain context-only and both-OFF regression launches from the [enablement guide](../PERSONAL_INTELLIGENCE_ENABLEMENT.md). An OFF-only test does not validate this new feature.

Record expected/observed behavior, resolved modes, candidate identity and provider/unavailable cases without raw private transcripts. Acceptance is pending until the owner actually runs and observes it. No new automated provider protocol or account spending is requested by this document.

## Rollback and promotion

Remove the new tool and its matching learning instructions together to restore the prior catalog/read behavior; stored facts need no migration. Existing flags can disable learning/context per process. Disabling is not forgetting. Exact-head CI, explicit protected-merge approval and applicable owner acceptance remain separate promotion requirements. A dependent candidate does not establish its dependency's acceptance by merely passing software tests.

## Native execution decisions and deferred review findings

Ruling: targeted verification commands group learning test paths before root paths. The interleaved command produced 18 missing-fixture setup errors; the same authority/forget tests passed separately and all 71 cases passed after regrouping. Cost if wrong: a collection interaction could hide until the required full repository suite, which is still required.

A fresh most-capable reviewer examined `6f4f197d..9bbf3303` and reported three Important findings, zero Critical and zero separately graded Minor findings. The reviewer independently reproduced the legacy/query race in both orders without expanded release. One repair pass followed; no second reviewer or re-review was dispatched.

| Finding | Verified reproduction and repair |
| --- | --- |
| Authority changed during a storage await before audio release | Five real audio-chain RED cases: grant expiry, Windows continuity, mutation-inflight, replacement permit and changed operation. Guard now pins authorization and revalidates after storage; 19 lifecycle cases passed. A separate RED case confirmed the analogous inherited legacy final-read data-release interval; it now also revalidates before returning facts. |
| Prior history denied a valid current question / digest covered different turns | An 8,000-byte earlier turn plus `My City?` produced RED denial. Current-only source construction now precedes bounds/digest; default four-turn learning behavior remains tested. 38 current-question/contract cases passed. |
| Corrected TEXT exported its UUID-bearing display prefix | Real admit -> correct-to-Nexon -> broad-query RED exported the opaque key. Projection now combines canonical TEXT value with a safe registered scope label. Typed/legacy semantic labels remain supported; 15 projection/correction cases passed. |

All eight failure cases were observed before repairs. Supplemental plan coverage retains the two mixed-read race orders, successful preference+goal composition and non-object/unparseable SDK rejection without query evaluation. All learning tests passed: **222**. The final whole-repository rerun after the one repair pass passed: **2,858 passed / 8 skipped**, exit 0, 358.97 seconds. The eight skips are four unavailable Windows symlink cases and four non-Windows negative controls. Final full Ruff lint/format and whitespace checks passed. The tested source commit is `74836bbc469019313c39bd1d5ec3d4df2db14d1b`; subsequent handoff edits change documentation only. No second reviewer or re-review was dispatched. No deferred minor finding remains.

Additional rulings, including every behavior the reviewer set aside:

1. R1 also repairs the inherited legacy final-read interval because its separate reproduction returned facts after expiry. Cost if wrong: added validation latency or legacy regression; targeted/full checks and repeat timing cover it.
2. The shared accepted-source factory gains an opt-in `current_only` argument outside the initially listed file set; the default four-turn behavior stays intact. Cost if wrong: learning-source regression; explicit window/bound checks and the full suite cover it.
3. Actual model relevance/tool choice/spoken multilingual usefulness remains pending until whole-app/provider observation. Cost if wrong: software correctness can coexist with poor live assistance or latency.
4. Cross-script/fuzzy aliases and references across retired private sessions remain explicit non-goals. Cost if wrong: these requests need clarification instead of seamless recall.
5. PI-2 extraction/provider qualification stays deferred and its dependency remains unmerged. Cost if wrong: automatic-learning behavior remains unqualified in the whole normal app.
6. Hosted/platform/production-SQLCipher checks and protected merge authorization remain separate from the local review. Cost if wrong: a green local suite cannot establish deployed readiness. No owner database was inspected or changed by these tests.

## Candidate handoff identity

Final tested source: `74836bbc469019313c39bd1d5ec3d4df2db14d1b`. Review branch: `feat/pi3-question-context-20261022`, based on the unmerged `feat/personal-auto-learning-20261021` / PR #295. The isolated dependent draft [PR #296](https://github.com/gkgajendra0/JARVIS_V1/pull/296) is published for review against PR #295. The source-tested commit is unchanged; the handoff commits change documentation only. Hosted checks are tracked on that PR and must be assessed against its actual head; their outcome is not inferred from the local suite. The Desktop CLI imports this checkout and its launcher points to this checkout's virtual environment; no reinstall or local activation was performed. Defaults remain OFF. The full test log and per-task receipts were inspected during execution; this report preserves their outcomes before plan-specific scratch cleanup.

Deferred minors: **none**. The seven rulings above include every deferred reviewer judgment and its practical cost.
