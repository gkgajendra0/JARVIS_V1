# Gemini fallback: independent review and repair evidence

23 October 2026. Candidate only; no Paid API calls, owner activation or merge.

## Review identity and disposition

One actual fresh whole-branch reviewer: `review_gemini_free_paid_available`,
GPT-6.1-sol xhigh, reviewed immutable range211c3ade..acd33067 against the approved
spec/plan and all five adversarial review-focus categories. The initially selected
GPT-6-astra failed at capacity before performing a review; it was not a second
review. The actual verdict was **not ready to merge**. Root regraded every finding
before acting, and used one Critical/Important repair pass, without re-review.

| Grade | Observed failure | Repair and real regression |
|---|---|---|
| Critical | A fact forgotten during Free failure was sent again to Paid and returned as current | Exact canonical eligible snapshot revalidation before each dispatch and after answer; real SQLite lifecycle forget during Free/Paid. `test_forgotten_canonical_fact_never_released_again` |
| Important | Input-only custom pricing silently omitted output cost | Structured pricing requires both input/output dimensions for admission and settlement; zero and positive partial tables rejected. `test_incomplete_structured_price_never_admits_or_settles_free` |
| Important | WorkEngine blocker steps changed cycle identity and funded another request after an unknown outcome | Atomic WorkItem-wide unresolved-claim/exposure admission fence; actual `WorkEngine.advance` crash/resume changes steps but Paid call count stays1. `test_work_engine_bookkeeping_cannot_repeat_unknown_paid_call` |
| Important | Recovery TTL expired while the first Free request was still pending, allowing a second Free call | Durable actual-call process identity beyond provisional lease TTL; independent demand can use eligible Paid while the one Free call waits. `test_slow_free_recovery_keeps_one_inflight_owner_past_lease` |
| Important | An ordinary429 shortened an earlier verified daily/Retry-After deadline | Preserve the longer existing cooldown. `test_later_ordinary_pressure_cannot_shorten_verified_deadline` |
| Important | Scoped Hands/recall lost transient retries when hidden SDK retries were disabled | One recorded same-target retry when existing health policy permits; no Paid hop for503/timeout/connection. `test_scoped_transient_free_error_retries_same_target_within_policy` |
| Important, retained limitation | Actual Paid Live factory rejects every Paid target | Correct approved unsupported-SDK denial retained; full requested voice feature remains undelivered. Separate unapproved transport proposal, not a successful Live implementation |

The Critical source-release repair also exposed session-close/new-turn release
through actual `MemoryAgentTools`; RED2 then GREEN28 affected tests. Original
session/accepted turn/activity epoch is rechecked before each verifier dispatch
and after awaits. `test_recall_tool_rechecks_original_session_before_paid_release`.

The in-flight ownership repair also exposed cancelled Work retaining its fence;
RED1 then GREEN23 affected cases. `test_cancelled_work_recovery_releases_inflight_owner`.
Real child-process ownership/normal process exit additionally verifies the fence
survives TTL while alive and becomes reclaimable after death, with late stale
versions still rejected. That already-passing extra check is not claimed as RED.

Initial regression evidence: RED7 then GREEN58 for privacy/pricing/cooldown;
RED5 then GREEN33 for Work/recovery/transients. Complete fallback checkpoint210
passed41.93s before the final session/cancellation additions. Complete repository
checkpoint3069passed8skipped222.65s before the last session guard. Final repaired
whole-repository result: 3,071 passed, 8 skipped in293.63s (4m53s); full repository pytest, isolated machine profile. Ruff check passed,1,043 files formatted, git diff --check passed..

All providers are fake transport; actual routers, SDK adapters, canonical stores,
WorkEngine, original Authority and action boundaries are exercised. Tests isolate
machine configuration and block external network. No private owner DB was opened.

## Review boundaries resolved by root rulings

- Actual project separation, funding, valid keys, production price/FX/invoice and
  spoken provider acceptance remain **unverified**, not assumed valid from key
  presence or a synthetic model. Live Paid requests/account changes lack approval.
- The controlled-transport proposal was outside the reviewed commit, is DRAFT,
  unapproved and unimplemented. It does not complete Paid voice or relax35000paise
  admission. Exact live charging-trigger proof is a prerequisite for enabling it.
- Deferred minors: none.

All chronological rulings and their costs are preserved in the linked
[implementation report](GEMINI_FREE_PAID_FALLBACK_IMPLEMENTATION_2026-10-22.md).

## Final verification and integration

3,071 passed, 8 skipped in293.63s (4m53s); full repository pytest, isolated machine profile. Ruff check passed,1,043 files formatted, git diff --check passed..
[Draft PR#298](https://github.com/gkgajendra0/JARVIS_V1/pull/298). Exact current-head hosted results are tracked in its checks and verification record; at this report commit they are pending. No earlier-head result substitutes for final-head acceptance..

The branch is dependent on `feat/pi3-question-context-20261022` (PR296), itself
on PR295. Any PR here must remain draft and target that dependency, not main.
Default OFF; no local activation, Paid experiment, billing change or merge.
