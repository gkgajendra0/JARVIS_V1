# JARVIS Documentation — Start Here

**Repository-wide product/documentation audit — 18 October 2026.**

This is the navigation and reconciliation record, not another North Star, second product plan or a claim of completed runtime features.

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
| Automatic remembering and everyday personalization | **Not accepted**: automatic durable admission and proactive provider-context injection disabled; CAP-053 planned |
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

## Current personal intelligence research (not selected architecture)

- [Repository and integration audit](research/PERSONAL_INTELLIGENCE_REPOSITORY_AUDIT_2026-10-18.md)
- [Movie-inspired assistant technology landscape, round 1](research/MOVIE_INSPIRED_PERSONAL_INTELLIGENCE_TECH_LANDSCAPE_2026-10-18.md)

These research documents are part of draft PR #285 and remain pending owner review. No research evidence authorizes new memory writes or context injection.

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
