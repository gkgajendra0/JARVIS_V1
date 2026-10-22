# JARVIS — Current Execution Plan

**Reconciled with both development chats, 20 October 2026.** This file contains *current
priority and next actionable work*, not a complete chronology. The previous plan is
preserved verbatim at [the October 18 snapshot](archive/operations/CURRENT_PLAN_SNAPSHOT_2026-10-18.md).
Historical engineering milestones and evidence remain in [Project State](PROJECT_STATE.md)
and the [Documentation Index](README.md).

## Active owner decision — advance after software verification (22 October 2026)

The owner directed that, given the implementation and passing software checks, work should move forward rather than spend multiple days on quota-limited provider testing. Record this as **IMPLEMENTED / SOFTWARE-VERIFIED; BROADER QUALIFICATION DEFERRED**. It does not assert that unrun semantic cases passed, that whole-app owner acceptance occurred, or that protected promotion/automatic activation was authorized.

Draft PR#295 (`feat/personal-auto-learning-20261021`) contains the normal voice integration: session delegation, extraction, canonical reconciliation/admission, replay/suppression, bounded worker and current-context use. Product codefd7c7025 and research control5bb72ec0 are unchanged in evidence headc03666b7. All7exact-head CI checks on c03666b7 passed; latest full local software2,759passed/8skipped. Automatic learning is OFF by default. Earlier accepted main/explicit-memory behavior remains separate.

Deferred evidence stays visible: v4has15complete/one unavailable/74unrun semantic cases,18/18conditional expected effects, six complete/four failed answer pairs; no full quality pass. The old v1recall33/47(70.2%) and v2partial Hindi replacement remain recorded. Cold callback p95=20.99ms(n16) does not meet the proposed10ms qualification target. Normal-app owner acceptance and protected-promotion decisions are open, not completed by this deferral. CAP-053 remains PARTIAL.

The owner supplied the quota evidence: displayed Free tier, answering5RPM/20RPD and learning15RPM/500RPD; the screenshots show28-day peaks rather than current headroom. The three approved recovery opportunities are exhausted. Budget upper304/532,228remain, but no additional inference, automatic schedule, purchase, model/account/key change or local activation is authorized by moving development priority. The proposed next-reset batch and suggested paid/model-comparison alternatives are not adopted or running. Do not keep requesting screenshots or budget approvals to resume the deferred benchmark.

Next development priority is **PI-3: contextual assistance across life domains**, following the explicit sequence in [North Star Section17.9](AUTONOMOUS_SELF_MANAGEMENT_MASTER_PLAN.md#179-prioritized-capability-delivery-and-gono-go-tests). PI-1has bounded owner acceptance; PI-2natural learning is implemented/software-verified with broader qualification deferred, not fully accepted. PI-3already has basic context-selection/read/prompt wiring. Inspect its actual missing behaviors and complete useful, multi-fact, current/source-backed ordinary advice without inventing a new memory store or personal brain. Conversation reference/continuity must respect the current provider-history and speaker/session boundaries. Relevant Work/Hands decisions follow within PI-3when justified; standalone tasks/reminders are not the immediate priority selected from the numbered roadmap. PI-4situated/proactive awareness and PI-5continual adaptation remain later. See the [corrected next-gap inspection](research/PERSONAL_ASSISTANCE_NEXT_GAP_TRIAGE_2026-10-22.md) and [handoff](research/PERSONAL_AUTO_LEARNING_IMPLEMENTED_HANDOFF_2026-10-22.md). No new feature design, model switch, retention scope or implementation is approved by this alignment.

## Recorded activation and dependent-test workflow —22October2026

Maintain the [personal-intelligence enablement record](PERSONAL_INTELLIGENCE_ENABLEMENT.md) across future milestones. Earlier PR294was owner-tested in the whole app with personal-context APPLY and merged, while OFF remained default and saved settings were unchanged. Automatic learning in PR295is separately implemented/software-verified, defaultOFF, with whole-app acceptance pending. After integration, normal-app validation and any milestone depending on learning/context must launch with `--personal-learning apply`; APPLY enables both for that process, without making the default/persistent machine setting ON. Repeat the intended mode after restart. OFF-only tests do not prove the dependent enabled experience. Keep implementation, merge, actual mode, normal-owner acceptance and default/persistent activation distinct in reports. No merge or owner-app activation was performed by this documentation update.

## Owner direction — active personal intelligence (2026-10-19)

The owner approved architecture PR #288, PI-1A #289, and PI-1B #290.
All three passed their prescribed GitHub CI and were merged to `main`.
The owner has also explicitly requested **real activated personal-context assistance,
not an indefinite shadow feature**, after thorough testing. The owner subsequently
tested an existing saved preference in the configured Windows deployment.

**Goal:** in a reliably authenticated OWNER conversation, JARVIS automatically
retrieves relevant permitted canonical facts and correctly *uses* them in
personalized advice, without an explicit memory search instruction. Empty
memory must yield an honest "I don't have that information yet", not fabricated
personal understanding. This is a permanent active product requirement.

**Release gates before activation on the owner machine:**
1. Confirm the actual Windows checkout/main SHA, configured memory enablement,
   SQLCipher/DPAPI health, voice model and plugin versions. No passwords or keys
   in reports.
2. Verify a trusted identity/turn binding that distinguishes owner requests
   from nearby guest speech. Existing speaker scoring is SHADOW diagnostics
   (not accepted proof of ownership); seeing an owner candidate on camera is
   not a verified speech attribution. Never release private owner history to
   an unverified speaker.
3. Validate real Gemini/LiveKit delivery with **fictional** memory facts,
   both initial and follow-up turns, and show the answer uses the right context.
   Test interruptions, correction, deletion, stale claims, absent memory,
   provider outages, no mid-session instruction spoofing, and token/cost.
4. Implement an **APPLY** path in the actual voice runtime with the existing
   canonical owner memory and Authority controls; do not represent isolated
   shadow-packet generation as activation. A provider tool or chat-context
   update must be proven on the pinned SDK/model.
5. Run full automated and owner-machine acceptance, then turn on the approved
   active path for the authenticated owner only. Preserve a documented OFF
   switch and fail-closed behavior on identity/provider failures.

**Automatic capture is a separate capability.** No indiscriminate recording,
implicit sensitive storage, or retention of all raw daily conversations is
approved by activating read-only context. Start with explicitly permitted facts
and add carefully governed natural learning after the initial active recall
release is proven.

**Status:** PRs #288–#291 MERGED. PR #294 and its dependencies #292/#293 supply the first
opt-in active owner-memory path in normal `jarvis-voice`, with fresh Windows Hello
consent for each exact canonical request, current reads and private audio guarding.
It retires the provider session after one personal answer; subsequent requests
require a fresh wake. This exact-consent fallback does not claim qualified
biometric speaker attribution. On October 21 the owner confirmed the normal-app
saved-preference recall/correction/restart/restore sequence and authorized checked
stack promotion. See the [bounded acceptance record](acceptance/PERSONAL_MEMORY_OWNER_ACCEPTANCE_2026-10-21.md);
the PRs record actual merge status. Broader everyday advice quality remains open.
Automatic learning is still separate. See the
[runtime report](research/PERSONAL_INTELLIGENCE_RUNTIME_2026-10-20.md).

The two chats pursued the same native-extension direction. PR #289 supplies
an offline evaluation contract, #290 a policy-tested read-only foundation,
and #291 an opt-in fictional provider-delivery probe. None proves automatic
personalization. The previous chat's [draft PR #287](https://github.com/gkgajendra0/JARVIS_V1/pull/287)
contains separate native-shadow and multilingual diagnostic evidence; it is
unmerged and must not be counted as code or acceptance on `main`, or merged
wholesale over the newer implementation. Preserve useful evidence and compare
individual contracts before reuse.

The [October 20 reconciliation audit](research/PERSONAL_INTELLIGENCE_RECONCILIATION_AUDIT_2026-10-20.md)
records the handover, verified scope, defects and remaining qualification.

The subsequent [fictional provider/usefulness qualification](research/PERSONAL_CONTEXT_DELIVERY_QUALIFICATION_2026-10-20.md)
demonstrated initial-history delivery and automatic realtime tool selection for
three ordinary dinner questions after an explicit context-use instruction to the
isolated test agent. Tool availability alone failed. Mid-session history updates
remain unqualified. A names-only structured relevance adapter now has offline
contracts, but actual semantic selections were unavailable due provider HTTP
timeouts/503. None of these experiments activates production memory or proves
trusted spoken-owner attribution, populated-session forgetting or held-out quality.

## Owner priority: personal intelligence, before more framework work

The owner has clarified that JARVIS's defining product must be an intelligent,
deeply contextual **personal assistant who knows the owner over time**, understands
preferences, experiences, relationships, decisions and evolving circumstances,
and proactively assists where permitted. The movie-inspired behavior is a goal,
not a claim of current capability. Coding/project continuity and autonomous
self-repair are *supporting* functions, not the primary end-user test.

Permanent requirements: [Product](PRODUCT.md) and Section 17 of
[Autonomous Self-Management North Star](AUTONOMOUS_SELF_MANAGEMENT_MASTER_PLAN.md).
CAP-053 is **PARTIAL**: the opt-in saved-preference flow has bounded owner
acceptance; the broader personal-intelligence contract is not complete.

### Earlier PI-1 release sequence — promotion complete; qualification retained

The owner-log correction failure is repaired in the same candidate: natural
correction/deletion proposals resolve the actual canonical target, then require
fresh concrete owner approval. See the [October 21 repair report](research/MEMORY_INTENT_REPAIR_2026-10-21.md).
The owner confirmed correct spoken results for the prescribed saved-diet
sequence. Promotion was explicitly authorized conditional on checks; this does
not accept broader advice quality, automatic learning or seamless attribution.

1. **Completed:** authorized #292 → #293 → #294 promotion. Preserve owner acceptance
   and exact-head/protected-main verification evidence.
2. Qualify personally useful everyday advice with general fictional scenarios in
   English/Hindi/Hinglish, including relevant/irrelevant context and honest absence.
   Saved-preference recall acceptance alone does not prove this broader behavior.
3. Record language, latency, provider failures and cost honestly. Prepare the
   bounded natural-learning design through existing memory/authority contracts;
   new automatic durable capture requires its own architecture approval.
4. Seamless verified-speaker follow-ups remain later work. Do not restart vendor
   comparisons as a substitute for completing this native personal-assistant path.

The native architecture is already owner-approved. Do not ask for that same
decision again or restart a vendor benchmark as a substitute for integration.
The owner requested general fictional tests instead of supplying personal
examples; no owner-authored examples are a prerequisite to continued development.

**First behavioral acceptance:** after several sessions and a restart, JARVIS
responds meaningfully to personally relevant everyday questions using
previously authorized, corrected and still-current facts *without* explicit
"search memory" prompting, while refusing to guess facts or leak restricted
information. Natural, accurate assistant use is the measure—not only a
retrieval benchmark score.

## What is already accepted vs deferred

- Steps 0–3: conversation, wake/voice, vision foundation, identity/trust and
  observability accepted to their documented scope.
- Step 4: **BOUNDED**. Encrypted SQLCipher persistent memory and explicit
  operations accepted; automatic candidate admission remains **disabled**.
  Opt-in exact-consented context and natural correction now have bounded
  owner recall/correction/restart acceptance; broader semantic quality remains open.
- Steps 5–6: provider resilience/research **BOUNDED**.
- Step 7: generic capability runtime and safe reads **DONE**.
- WorkStore/DBOS durable work, Self-Awareness, Hands foundations and bounded
  deterministic R2 recovery are accepted for their documented boundaries.
- Engineering Phases 2–10A are accepted to their defined scopes; Phase 9
  full external-device lifecycle remains deferred; full proactive autonomy
  has not been promoted. Phase 11 is **next in that engineering program**,
  not the current owner-directed implementation instruction.
- Cost optimization C6 Work Context is **SHADOW**, not accepted as applied
  production reasoning context.

See [Current Architecture](CURRENT_ARCHITECTURE.md) and
[Project State](PROJECT_STATE.md) for authoritative scope and evidence.

## Previous work and parallel obligations — not cancelled

- PR #243 provider-model lifecycle is merged. That status alone does not prove
  the new personal-context delivery path or spoken owner attribution.
- The previously requested bounded Cost Optimization program is recorded in
  [Cost Optimization Master Plan](JARVIS_COST_OPTIMIZATION_MASTER_PLAN.md)
  and its original [implementation plan](reference/JARVIS_COST_OPTIMIZATION_IMPLEMENTATION_PLAN.md).
  The prior rule not to purchase paid-brain credits before the documented
  pre-credit gate remains unchanged.
- The Phase 9 full external TV capability lifecycle has **not** been proven
  end to end. Its acceptance gate is still deferred.
- Step 8 notes/tasks/reminders remains the next *numbered product* step if
  that program resumes.
- Phase 11 autonomous capability-gap detection remains the next planned
  *cross-cutting engineering* research/architecture step, without
  implementation authorization.
- Open issues and accepted, bounded or deferred details remain in Project
  State and GitHub; no previous owner approval is silently revoked by a
  documentation cleanup.

## Governance and change gates

Use the established sequence: research -> architecture -> explicit owner
approval -> isolated PR -> automated tests -> applicable owner-machine
acceptance -> documentation reconciliation -> protected promotion.

The owner authorized audit reconciliation and repairs to reproduced contract
violations. This does not authorize new personal-data retention, cloud release
of local-only data, a different canonical store, paid fallback purchases or
bypass of Authority/OPA. The approved active product goal still requires the
release gates above. **Protected main remains unchanged until the owner
approves and all required checks pass.**

## Active slice: PI-3A question-bound contextual assistance

The owner approved the [written design](superpowers/specs/2026-10-22-pi3-entity-aware-context-design.md) and [seven-task Native plan](superpowers/plans/2026-10-22-pi3-entity-aware-context.md) on 22 October 2026. Tasks 1-6 are implemented on the dependent candidate in the existing Desktop checkout; Task 7 software verification and review repairs are complete (2,858 tests / 8 skips). This supersedes the earlier inspect/research-only next action. The [gap map](research/PI3_CONTEXTUAL_ASSISTANCE_GAP_MAP_2026-10-22.md) and [technology review](research/PI3_TECHNOLOGY_REVIEW_2026-10-22.md) preserve how native structured projection was selected.

Implemented: question-bound registered-scope queries, exact current label matching/clarification, bounded multi-fact evidence, one shared read budget, coherent canonical snapshots, scope/source/version invalidation and normal learning-APPLY tool/instruction integration. Context-only/OFF, explicit mutations, default OFF, existing grants and provider-history retirement remain supported. No new memory engine, HTTP reasoner, model/dependency change, provider request or owner activation occurred.

Draft [PR #296](https://github.com/gkgajendra0/JARVIS_V1/pull/296) contains this candidate against unmerged PR #295. Next: follow its exact-head hosted checks and the [implementation/acceptance record](research/PI3_CONTEXT_QUERY_IMPLEMENTATION_2026-10-22.md), then owner-selected whole normal-app validation. Actual-model selection and spoken usefulness are not proven by forced tool/audio harnesses. Exact-head CI, dependency integration, applicable owner acceptance and explicit protected merge remain separate gates. PI-2 broad qualification is still deferred, never counted as passed; PI-3 as a whole and CAP-053 remain PARTIAL. Do not restart quota-bound benchmarks, replace this with Step8 reminders, or broaden alias/episode/proactive behavior silently.


## Requested architecture: Gemini Free-first / Paid-fallback

The owner requested shared Free/Paid credential-aware fallback for Gemini Live, eligible Hands/Work/memory inference and a cumulative INR350 internal paid ceiling. Baseline is the clean Desktop PI-3A candidate `211c3ade`; protected main and the unmerged PI-2/PI-3A dependency status are unchanged. The [written design](superpowers/specs/2026-10-22-gemini-free-paid-fallback-design.md) records repository findings, existing-router reuse, durable compatibility, privacy/Authority continuity, bounded recovery, reservation/unknown-cost behavior and the verification/owner-acceptance matrix. Status: written design owner-approved; the [12-task implementation plan](superpowers/plans/2026-10-22-gemini-free-paid-fallback.md) is owner-approved for Native implementation. Software implementation is in progress; no live API calls or activation are authorized by this approval. Keep Native execution preference. The new request authorizes this software work but does not authorize paid inference, billing changes, purchases, saved-setting activation or merge; earlier benchmark deferrals are not reopened.
