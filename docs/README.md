# JARVIS Documentation — Start Here

**Read first for the active memory workstream — 31 October 2026:** [Project conversations and personal memory](PROJECT_CONVERSATION_MEMORY.md) is the current scoped contract; its [build plan](superpowers/plans/2026-10-31-project-conversation-memory.md) owns tasks. Gemini plus existing local encrypted memory is selected. Earlier hosted/local-model/vendor alternatives are research, not competing build directions. Replacement implementation has not started.

**Gemini Free/Paid candidate (23 October 2026):** existing routers and one
cumulative INR350 governor support bounded Work/Hands/memory fallback. The
controlled public Live adapter and normal handoff are implemented and software
verified: 3,177 tests passed / 8 platform skips. Actual Paid voice remains
unavailable because auxiliary billing/usage bounds are unqualified; a funded key
alone does not enable it. Default OFF; no real API calls, saved activation,
billing changes or merge. Final docs-inclusive hosted evidence is recorded in
[draft PR #298](https://github.com/gkgajendra0/JARVIS_V1/pull/298). See the
[implementation, remaining work and exact owner steps](research/GEMINI_CONTROLLED_LIVE_IMPLEMENTATION_2026-10-23.md).

**PI-3A candidate (22 October 2026):** question-bound selection of relevant current personal facts is implemented on the dependent candidate branch. Local software verification passed (2,858 tests / 8 skips) after all three Important review findings were repaired; actual-model selection and whole normal-app spoken acceptance remain pending. Default OFF and CAP-053 PARTIAL are unchanged. See [PI-3A implementation/acceptance record](research/PI3_CONTEXT_QUERY_IMPLEMENTATION_2026-10-22.md).

**Repository-wide product/documentation audit — 18 October 2026.**

This is the navigation and reconciliation record, not another North Star, second product plan or a claim of completed runtime features.

Automatic learning: [implemented/software-verified handoff](research/PERSONAL_AUTO_LEARNING_IMPLEMENTED_HANDOFF_2026-10-22.md), [decision](research/PERSONAL_AUTO_LEARNING_ARCHITECTURE_DECISION_2026-10-22.md) and [preserved qualification](research/PERSONAL_AUTO_LEARNING_QUALIFICATION_2026-10-22.md). The owner chose to advance development; broader provider testing is deferred. DefaultOFF/unpromoted; owner acceptance and protected promotion are not implied.

[Enablement and validation record](PERSONAL_INTELLIGENCE_ENABLEMENT.md) — which personal features are defaultOFF, which opt-in tests passed, how to enable normal-app testing, and how future dependent milestones must be checked.

## Read these documents first

**One product, one hierarchy:**

| Authoritative document | What it owns |
| --- | --- |
| [PRODUCT.md](PRODUCT.md) | What JARVIS is, primary owner-centered assistant behavior and CAP-001–053 catalogue |
| [AUTONOMOUS_SELF_MANAGEMENT_MASTER_PLAN.md](AUTONOMOUS_SELF_MANAGEMENT_MASTER_PLAN.md) | Owner-approved constitutional North Star; Section 17 makes personal intelligence a permanent user-facing goal |
| [UNIVERSAL_KNOWLEDGE_AND_DISCOVERY_MASTER_PLAN.md](UNIVERSAL_KNOWLEDGE_AND_DISCOVERY_MASTER_PLAN.md) | Subordinate long-horizon knowledge and discovery vision, not current capability |
| [GOVERNED_AUTONOMOUS_ENGINEERING_MASTER_PLAN.md](GOVERNED_AUTONOMOUS_ENGINEERING_MASTER_PLAN.md) | Supporting self-management, engineering and governed evolution program |
| [SELF_REPAIR_AND_EVOLUTION_MASTER_PLAN.md](SELF_REPAIR_AND_EVOLUTION_MASTER_PLAN.md) | Specialized repair/evolution sequence, subordinate to engineering |
| [ROADMAP.md](ROADMAP.md) | Numbered product sequence; cross-cutting priority does not renumber steps |
| [CURRENT_PLAN.md](CURRENT_PLAN.md) | Current owner priorities and next work only |
| [CURRENT_ARCHITECTURE.md](CURRENT_ARCHITECTURE.md) | Accepted code architecture on protected main (not proposals) |
| [PROJECT_STATE.md](PROJECT_STATE.md) | Canonical DONE/BOUNDED/DEFERRED/REJECTED evidence ledger |
| [QUALITY_GATES.md](QUALITY_GATES.md) | Security, validation, owner-machine acceptance and merge rules |
| [DEPENDENCY_PROVENANCE.md](DEPENDENCY_PROVENANCE.md) | Recorded third-party provenance for pinned dependencies |
| [JARVIS_COST_OPTIMIZATION_MASTER_PLAN.md](JARVIS_COST_OPTIMIZATION_MASTER_PLAN.md) | Still-relevant bounded optimization program; not a parallel product vision |

Use **PRODUCT** for desired behavior, **AUTONOMOUS NORTH STAR** for enduring intent and owner authority, **ROADMAP** for long-term sequence, **CURRENT_PLAN** for the next task, **CURRENT_ARCHITECTURE** for what is running, **PROJECT_STATE** for acceptance and **QUALITY_GATES** for safe delivery. Do not create new competing master plans or call research production.

## Overall product audit — what is actually built

| Product area | Current evidence-based position |
| --- | --- |
| Voice, wake, conversation, identity | Accepted foundations; realtime model/provider and owner voice limitations still subject to actual acceptance |
| Camera, device and computer control | Bounded Vision/Hands foundations; full movie-style environmental control not achieved |
| Canonical personal memory | Encrypted SQLCipher, explicit remember/correct/forget and bounded recall accepted |
| Automatic remembering and everyday personalization | **PARTIAL**: opt-in context with bounded saved-preference owner acceptance; automatic durable admission and broader advice quality remain open |
| Background Work, recovery and knowledge | Durable WorkItem/DBOS and EngineeringKnowledge accepted to documented bounded scope; distinct from knowing the owner |
| Reliability/self-management | Deterministic recovery and engineering Phases 2–10A accepted to stated scope; production autonomy does not imply unrestricted self-operation |
| Personal intelligence across life domains | **Primary owner-facing requirement**: use authorized stable/evolving preferences, context and episodes to improve actual advice/actions |
| Next numbered feature | Step 8 notes/tasks/reminders; current owner has prioritized a cross-cutting personal-intelligence design initiative |
| Research | Hindsight synthetic recall and broader 2026 personal-memory landscape are experimental; neither has production owner-data integration approval |

### Concrete documentation problems corrected

1. Root README previously stated Phase 5 was still being implemented, conflicting with accepted later-phase evidence; fixed to a bounded status overview.
2. Previous CURRENT_PLAN combined many dated status histories with mutually competing 'next actions'; the full original is preserved under archive/operations and CURRENT_PLAN is now short and owner-priority-based.
3. Historical research/architecture/acceptance files formerly competed in the docs/ root with authoritative product documents; preserved byte-for-byte in archive/reference and indexed below.
4. The movie-inspired user experience is now explicit in the *existing* product and North Star, rather than a competing 'JARVIS 2' specification.
5. Personal-memory automatic injection, implicit admission, Hindsight research and C6 shadow Work context remain explicitly differentiated from production acceptance.

## Supporting designs (not a second source of runtime truth)

- [GICC_GOAL_INTELLIGENCE_ARCHITECTURE.md](reference/GICC_GOAL_INTELLIGENCE_ARCHITECTURE.md) — approved, candidate, or shadow supporting specification; read its status before implementation
- [JARVIS_C6_CONTEXT_OPTIMIZATION_RESEARCH.md](reference/JARVIS_C6_CONTEXT_OPTIMIZATION_RESEARCH.md) — approved, candidate, or shadow supporting specification; read its status before implementation
- [JARVIS_COST_OPTIMIZATION_IMPLEMENTATION_PLAN.md](reference/JARVIS_COST_OPTIMIZATION_IMPLEMENTATION_PLAN.md) — approved, candidate, or shadow supporting specification; read its status before implementation
- [PROVIDER_MODEL_LIFECYCLE_SELF_EVOLUTION.md](reference/PROVIDER_MODEL_LIFECYCLE_SELF_EVOLUTION.md) — approved, candidate, or shadow supporting specification; read its status before implementation

## Personal intelligence design and qualification

- [Repository and integration audit](research/PERSONAL_INTELLIGENCE_REPOSITORY_AUDIT_2026-10-18.md)
- [Movie-inspired assistant technology landscape, round 1](research/MOVIE_INSPIRED_PERSONAL_INTELLIGENCE_TECH_LANDSCAPE_2026-10-18.md)
- [Approved native architecture and evaluation contract](research/PERSONAL_INTELLIGENCE_ARCHITECTURE_CANDIDATE_2026-10-19.md)
- [Cross-chat reconciliation audit and remaining gates](research/PERSONAL_INTELLIGENCE_RECONCILIATION_AUDIT_2026-10-20.md)
- [Normal-app personal-context candidate](research/PERSONAL_INTELLIGENCE_RUNTIME_2026-10-20.md)
- [Natural memory-intent and canonical-target repair](research/MEMORY_INTENT_REPAIR_2026-10-21.md)
- [Bounded normal-app owner acceptance and release](acceptance/PERSONAL_MEMORY_OWNER_ACCEPTANCE_2026-10-21.md)
- [Automatic conversational learning: approved written design](superpowers/specs/2026-10-21-personal-auto-learning-design.md)
- [Automatic conversational learning: implementation plan for review](superpowers/plans/2026-10-21-personal-auto-learning.md)

PRs #285–#286 established the product/documentation hierarchy; #288 approved
the native direction and #289–#291 added evaluation, shadow and fictional
provider-probe foundations. PR #294 supplies opt-in context and natural existing-memory
correction/deletion. The owner confirmed the saved-preference spoken test and
authorized checked promotion; PR status records the actual merge. Broader advice
quality and natural learning remain open.
The earlier draft PR #287 retains separate research/test evidence; it is not
merged runtime truth. No research result authorizes implicit writes or private
context release. Use Current Plan for execution, rather than repeating the
approved architecture decision.

## Historical evidence preserved

**57 historical source records** were preserved by identical Git blobs under
[`docs/archive/`](archive/README.md), along with the verbatim previous
CURRENT_PLAN snapshot (58 archived source records total). **Four supporting
designs** remain in [`docs/reference/`](archive/README.md), also exact
copies of their original document contents.

The [archive index](archive/README.md) contains the **complete 62-record
old-path-to-new-path map with exact Git object hashes**, acceptance context
and links. Historical records are evidence, not current product authority.
Git history also retains their original locations.

## Other retained development records

- `docs/superpowers/plans/2026-09-25-engineering-change.md`
- `docs/superpowers/specs/2026-09-25-engineering-change-design.md`

These are tool-specific historical artifacts, not independent product plans. Do not treat them as current production architecture.

## Safe documentation maintenance policy

- Never replace product status with feature proposals or acceptance with synthetic benchmarks.
- Preserve owner-approved technical evidence, exact release/CI digests and provenance before moving/removing a document.
- Document technical details in code/tests or bounded supporting designs; keep core product documents readable.
- Maintain an explicit mapping for moved records; update active links and run checks before protected merge.
- Keep current-plan instructions short and updated; long finished phase histories belong in the state ledger and archive.
- Merges require the usual owner review and quality gates. The documentation changes do not modify production code.
