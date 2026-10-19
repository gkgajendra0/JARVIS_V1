# JARVIS — Current Execution Plan

**Updated for owner-directed priority, 18 October 2026.** This file contains *current
priority and next actionable work*, not a complete chronology. The previous plan is
preserved verbatim at [the October 18 snapshot](archive/operations/CURRENT_PLAN_SNAPSHOT_2026-10-18.md).
Historical engineering milestones and evidence remain in [Project State](PROJECT_STATE.md)
and the [Documentation Index](README.md).

## Owner direction — active personal intelligence (2026-10-19)

The owner approved architecture PR #288, PI-1A #289, and PI-1B #290.
All three passed their prescribed GitHub CI and were merged to `main`.
The owner has also explicitly requested **real activated personal-context assistance,
not an indefinite shadow feature**, after thorough testing. There are no
known existing personal memories in the owner's current deployment.

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

**Status:** PRs #288–#290 MERGED; active owner memory -> live voice model
integration **NOT IMPLEMENTED / NOT ACTIVE**. The owner-machine identity and
provider acceptance are required; do not claim otherwise. The objective is
active release, with isolated tests only as a means to validate it.

## Owner priority: personal intelligence, before more framework work

The owner has clarified that JARVIS's defining product must be an intelligent,
deeply contextual **personal assistant who knows the owner over time**, understands
preferences, experiences, relationships, decisions and evolving circumstances,
and proactively assists where permitted. The movie-inspired behavior is a goal,
not a claim of current capability. Coding/project continuity and autonomous
self-repair are *supporting* functions, not the primary end-user test.

Permanent requirements: [Product](PRODUCT.md) and Section 17 of
[Autonomous Self-Management North Star](AUTONOMOUS_SELF_MANAGEMENT_MASTER_PLAN.md).
CAP-053 (Personal Intelligence and Automatic Context Use) is **PLANNED**.

### Immediate next work — documentation and bounded architecture research

1. Reconcile product documents into a small authoritative set and preserve
   previous technical/acceptance evidence without losing information.
2. Finish a requirements-first, **end-to-end personal-assistant architecture**
   comparison using existing JARVIS modules and credible external options.
   Use official sources, independent benchmarks and explicit unknowns, not a
   string of unrelated framework experiments.
3. Freeze owner-facing acceptance tasks and baseline measurements: changing
   preferences, food, purchases, travel, finances, relationship references,
   multi-session corrections, missing information, model use and privacy.
4. Produce a single architecture decision identifying exactly what to **reuse,
   modify, or add**; interfaces, cost, latency, security and revert gates.
5. After a separate architecture owner approval, implement a **read-only shadow
   personal-context path**. Do not turn on implicit durable memory writes or
   automatic provider-context injection as part of this documentation work.
6. Validate safe recall and *actual personalized answer improvement* before
   considering a bounded owner-machine production rollout.

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
  operations accepted; automatic candidate admission and automatic
  provider-context memory injection **disabled**. Natural-language live
  semantic recall has a deferred owner-machine acceptance gate.
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

- PR #243 provider-model lifecycle / Gemini voice behavior was previously
  designated for real owner-machine acceptance. Recheck the PR's **actual
  current GitHub status** before treating it as pending, merged or actionable.
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

No work in this documentation branch authorizes code modification, new
retention of personal data, cloud release of local-only data, production
injection, a different canonical memory/work store, spending, or bypass of
Authority/OPA. **Protected main remains unchanged until the owner approves
and all required checks pass.**

## Next action

Complete this documentation reconciliation, compare personal intelligence
architecture options against the fixed owner requirements and acceptance
scenarios, then ask for the **single bounded architecture decision** before
implementation. Do not start another retrieval-engine experiment simply
because a different tool is fashionable.
