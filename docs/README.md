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

## Preservation and traceability

**57 historical documents** were copied under `docs/archive/` and **4 supporting designs** were moved under `docs/reference/`, all with the **same exact Git blob hashes as their originals**. The original CURRENT_PLAN is separately preserved as an additional snapshot. Git history retains earlier paths and committed versions.

Archived files are deliberately unchanged historical evidence. Old internal relative links inside those snapshots may still refer to their original locations; use this mapping to find the preserved content. For *current* references, prefer the canonical files above.

| Former top-level file | Preserved location | Verified Git blob (prefix) |
| --- | --- | --- |
| `docs/PHASE10_CLOSED_LOOP_ENGINEERING_LEARNING_ACCEPTANCE.md` | [archive/acceptance/PHASE10_CLOSED_LOOP_ENGINEERING_LEARNING_ACCEPTANCE.md](archive/acceptance/PHASE10_CLOSED_LOOP_ENGINEERING_LEARNING_ACCEPTANCE.md) | `2dcf82623fa3` |
| `docs/PHASE10A_AUTONOMOUS_OPERATIONS_CONTROL_PLANE_ACCEPTANCE.md` | [archive/acceptance/PHASE10A_AUTONOMOUS_OPERATIONS_CONTROL_PLANE_ACCEPTANCE.md](archive/acceptance/PHASE10A_AUTONOMOUS_OPERATIONS_CONTROL_PLANE_ACCEPTANCE.md) | `54d504a11ebc` |
| `docs/PHASE2_ENGINEERING_KNOWLEDGE_ACCEPTANCE_2026-09-25.md` | [archive/acceptance/PHASE2_ENGINEERING_KNOWLEDGE_ACCEPTANCE_2026-09-25.md](archive/acceptance/PHASE2_ENGINEERING_KNOWLEDGE_ACCEPTANCE_2026-09-25.md) | `1eb2df648ac4` |
| `docs/PHASE2_ENGINEERING_KNOWLEDGE_OWNER_ACCEPTANCE.md` | [archive/acceptance/PHASE2_ENGINEERING_KNOWLEDGE_OWNER_ACCEPTANCE.md](archive/acceptance/PHASE2_ENGINEERING_KNOWLEDGE_OWNER_ACCEPTANCE.md) | `c95e3617988d` |
| `docs/PHASE3_ENGINEERING_CHANGE_ACCEPTANCE_2026-09-25.md` | [archive/acceptance/PHASE3_ENGINEERING_CHANGE_ACCEPTANCE_2026-09-25.md](archive/acceptance/PHASE3_ENGINEERING_CHANGE_ACCEPTANCE_2026-09-25.md) | `e54a4060bfcb` |
| `docs/PHASE3_ENGINEERING_CHANGE_OWNER_ACCEPTANCE.md` | [archive/acceptance/PHASE3_ENGINEERING_CHANGE_OWNER_ACCEPTANCE.md](archive/acceptance/PHASE3_ENGINEERING_CHANGE_OWNER_ACCEPTANCE.md) | `6e5e95737371` |
| `docs/PHASE4_MODEL_ROUTER_ACCEPTANCE_2026-09-26.md` | [archive/acceptance/PHASE4_MODEL_ROUTER_ACCEPTANCE_2026-09-26.md](archive/acceptance/PHASE4_MODEL_ROUTER_ACCEPTANCE_2026-09-26.md) | `455be060a823` |
| `docs/PHASE4_MODEL_ROUTER_OWNER_ACCEPTANCE.md` | [archive/acceptance/PHASE4_MODEL_ROUTER_OWNER_ACCEPTANCE.md](archive/acceptance/PHASE4_MODEL_ROUTER_OWNER_ACCEPTANCE.md) | `aac187cda9da` |
| `docs/PHASE5_SECURE_ENGINEERING_SUBSTRATE_ACCEPTANCE_2026-09-27.md` | [archive/acceptance/PHASE5_SECURE_ENGINEERING_SUBSTRATE_ACCEPTANCE_2026-09-27.md](archive/acceptance/PHASE5_SECURE_ENGINEERING_SUBSTRATE_ACCEPTANCE_2026-09-27.md) | `963503a707d4` |
| `docs/PHASE6_UNKNOWN_INCIDENT_SOURCE_REPAIR_ACCEPTANCE_2026-09-27.md` | [archive/acceptance/PHASE6_UNKNOWN_INCIDENT_SOURCE_REPAIR_ACCEPTANCE_2026-09-27.md](archive/acceptance/PHASE6_UNKNOWN_INCIDENT_SOURCE_REPAIR_ACCEPTANCE_2026-09-27.md) | `f24ac3c0e92c` |
| `docs/PHASE7_GOVERNED_PROMOTION_ACCEPTANCE_2026-09-27.md` | [archive/acceptance/PHASE7_GOVERNED_PROMOTION_ACCEPTANCE_2026-09-27.md](archive/acceptance/PHASE7_GOVERNED_PROMOTION_ACCEPTANCE_2026-09-27.md) | `5b139aefc0dc` |
| `docs/PHASE8_CAPABILITY_PACKAGE_REGISTRY_ACCEPTANCE_2026-09-27.md` | [archive/acceptance/PHASE8_CAPABILITY_PACKAGE_REGISTRY_ACCEPTANCE_2026-09-27.md](archive/acceptance/PHASE8_CAPABILITY_PACKAGE_REGISTRY_ACCEPTANCE_2026-09-27.md) | `8a0e836e7a4f` |
| `docs/PHASE9_OWNER_REQUESTED_CAPABILITY_ACQUISITION_ACCEPTANCE_2026-09-27.md` | [archive/acceptance/PHASE9_OWNER_REQUESTED_CAPABILITY_ACQUISITION_ACCEPTANCE_2026-09-27.md](archive/acceptance/PHASE9_OWNER_REQUESTED_CAPABILITY_ACQUISITION_ACCEPTANCE_2026-09-27.md) | `177c3b1f5b88` |
| `docs/STEP4_CORE_ENCRYPTED_MEMORY_OWNER_ACCEPTANCE_2026-10-15.md` | [archive/acceptance/STEP4_CORE_ENCRYPTED_MEMORY_OWNER_ACCEPTANCE_2026-10-15.md](archive/acceptance/STEP4_CORE_ENCRYPTED_MEMORY_OWNER_ACCEPTANCE_2026-10-15.md) | `87456b32e02c` |
| `docs/PHASE10_CLOSED_LOOP_ENGINEERING_LEARNING_ARCHITECTURE.md` | [archive/architecture/PHASE10_CLOSED_LOOP_ENGINEERING_LEARNING_ARCHITECTURE.md](archive/architecture/PHASE10_CLOSED_LOOP_ENGINEERING_LEARNING_ARCHITECTURE.md) | `35c20a5a5881` |
| `docs/PHASE10A_AUTONOMOUS_OPERATIONS_CONTROL_PLANE_ARCHITECTURE.md` | [archive/architecture/PHASE10A_AUTONOMOUS_OPERATIONS_CONTROL_PLANE_ARCHITECTURE.md](archive/architecture/PHASE10A_AUTONOMOUS_OPERATIONS_CONTROL_PLANE_ARCHITECTURE.md) | `974f12046d1b` |
| `docs/PHASE2_ENGINEERING_KNOWLEDGE_ARCHITECTURE.md` | [archive/architecture/PHASE2_ENGINEERING_KNOWLEDGE_ARCHITECTURE.md](archive/architecture/PHASE2_ENGINEERING_KNOWLEDGE_ARCHITECTURE.md) | `49dcec7e2b88` |
| `docs/PHASE4_MODEL_ROUTER_ARCHITECTURE.md` | [archive/architecture/PHASE4_MODEL_ROUTER_ARCHITECTURE.md](archive/architecture/PHASE4_MODEL_ROUTER_ARCHITECTURE.md) | `a84a846575e2` |
| `docs/PHASE5_SECURE_ENGINEERING_SUBSTRATE_ARCHITECTURE.md` | [archive/architecture/PHASE5_SECURE_ENGINEERING_SUBSTRATE_ARCHITECTURE.md](archive/architecture/PHASE5_SECURE_ENGINEERING_SUBSTRATE_ARCHITECTURE.md) | `3481263e604f` |
| `docs/PHASE6_UNKNOWN_INCIDENT_SOURCE_REPAIR_ARCHITECTURE.md` | [archive/architecture/PHASE6_UNKNOWN_INCIDENT_SOURCE_REPAIR_ARCHITECTURE.md](archive/architecture/PHASE6_UNKNOWN_INCIDENT_SOURCE_REPAIR_ARCHITECTURE.md) | `d378a7ccaf2c` |
| `docs/PHASE7_GOVERNED_PROMOTION_ARCHITECTURE.md` | [archive/architecture/PHASE7_GOVERNED_PROMOTION_ARCHITECTURE.md](archive/architecture/PHASE7_GOVERNED_PROMOTION_ARCHITECTURE.md) | `d5d731a92514` |
| `docs/PHASE8_CAPABILITY_PACKAGE_REGISTRY_ARCHITECTURE.md` | [archive/architecture/PHASE8_CAPABILITY_PACKAGE_REGISTRY_ARCHITECTURE.md](archive/architecture/PHASE8_CAPABILITY_PACKAGE_REGISTRY_ARCHITECTURE.md) | `05b814b00986` |
| `docs/PHASE9_OWNER_REQUESTED_CAPABILITY_ACQUISITION_ARCHITECTURE.md` | [archive/architecture/PHASE9_OWNER_REQUESTED_CAPABILITY_ACQUISITION_ARCHITECTURE.md](archive/architecture/PHASE9_OWNER_REQUESTED_CAPABILITY_ACQUISITION_ARCHITECTURE.md) | `aa05ec767ad1` |
| `docs/SELF_REPAIR_AND_EVOLUTION_TECHNICAL_PLAN.md` | [archive/architecture/SELF_REPAIR_AND_EVOLUTION_TECHNICAL_PLAN.md](archive/architecture/SELF_REPAIR_AND_EVOLUTION_TECHNICAL_PLAN.md) | `522388c7cbfd` |
| `docs/JARVIS_COST_CALL_INVENTORY.md` | [archive/cost/JARVIS_COST_CALL_INVENTORY.md](archive/cost/JARVIS_COST_CALL_INVENTORY.md) | `b0d6360af910` |
| `docs/JARVIS_COST_OPTIMIZATION_DECISIONS.md` | [archive/cost/JARVIS_COST_OPTIMIZATION_DECISIONS.md](archive/cost/JARVIS_COST_OPTIMIZATION_DECISIONS.md) | `bb1b7228cd1a` |
| `docs/GICC_CHAT_HANDOVER_2026-10-01.md` | [archive/handovers/GICC_CHAT_HANDOVER_2026-10-01.md](archive/handovers/GICC_CHAT_HANDOVER_2026-10-01.md) | `e29f7405437e` |
| `docs/INTERACTIVE_OWNER_INPUT_VOICE_HANDOFF_2026-09-30.md` | [archive/handovers/INTERACTIVE_OWNER_INPUT_VOICE_HANDOFF_2026-09-30.md](archive/handovers/INTERACTIVE_OWNER_INPUT_VOICE_HANDOFF_2026-09-30.md) | `23efcaa95b2e` |
| `docs/GICC_IMPLEMENTATION_AND_MIGRATION_PLAN.md` | [archive/implementation/GICC_IMPLEMENTATION_AND_MIGRATION_PLAN.md](archive/implementation/GICC_IMPLEMENTATION_AND_MIGRATION_PLAN.md) | `2840fb8b5c40` |
| `docs/JARVIS_C3_GLOBAL_BRAIN_ROUTER_IMPLEMENTATION.md` | [archive/implementation/JARVIS_C3_GLOBAL_BRAIN_ROUTER_IMPLEMENTATION.md](archive/implementation/JARVIS_C3_GLOBAL_BRAIN_ROUTER_IMPLEMENTATION.md) | `fdf0f4dbd822` |
| `docs/PHASE10_CLOSED_LOOP_ENGINEERING_LEARNING_IMPLEMENTATION_PLAN.md` | [archive/implementation/PHASE10_CLOSED_LOOP_ENGINEERING_LEARNING_IMPLEMENTATION_PLAN.md](archive/implementation/PHASE10_CLOSED_LOOP_ENGINEERING_LEARNING_IMPLEMENTATION_PLAN.md) | `a2d6676a47f5` |
| `docs/PHASE10A_AUTONOMOUS_OPERATIONS_CONTROL_PLANE_IMPLEMENTATION_PLAN.md` | [archive/implementation/PHASE10A_AUTONOMOUS_OPERATIONS_CONTROL_PLANE_IMPLEMENTATION_PLAN.md](archive/implementation/PHASE10A_AUTONOMOUS_OPERATIONS_CONTROL_PLANE_IMPLEMENTATION_PLAN.md) | `a54364db88cb` |
| `docs/PHASE2_ENGINEERING_KNOWLEDGE_IMPLEMENTATION_PLAN.md` | [archive/implementation/PHASE2_ENGINEERING_KNOWLEDGE_IMPLEMENTATION_PLAN.md](archive/implementation/PHASE2_ENGINEERING_KNOWLEDGE_IMPLEMENTATION_PLAN.md) | `8e000bb4d9b3` |
| `docs/PHASE4_MODEL_ROUTER_IMPLEMENTATION_PLAN.md` | [archive/implementation/PHASE4_MODEL_ROUTER_IMPLEMENTATION_PLAN.md](archive/implementation/PHASE4_MODEL_ROUTER_IMPLEMENTATION_PLAN.md) | `baec7e0a269e` |
| `docs/PHASE5_SECURE_ENGINEERING_SUBSTRATE_IMPLEMENTATION_PLAN.md` | [archive/implementation/PHASE5_SECURE_ENGINEERING_SUBSTRATE_IMPLEMENTATION_PLAN.md](archive/implementation/PHASE5_SECURE_ENGINEERING_SUBSTRATE_IMPLEMENTATION_PLAN.md) | `99158f66e5bc` |
| `docs/PHASE6_UNKNOWN_INCIDENT_SOURCE_REPAIR_IMPLEMENTATION_PLAN.md` | [archive/implementation/PHASE6_UNKNOWN_INCIDENT_SOURCE_REPAIR_IMPLEMENTATION_PLAN.md](archive/implementation/PHASE6_UNKNOWN_INCIDENT_SOURCE_REPAIR_IMPLEMENTATION_PLAN.md) | `b2ea7638546c` |
| `docs/PHASE7_GOVERNED_PROMOTION_IMPLEMENTATION_PLAN.md` | [archive/implementation/PHASE7_GOVERNED_PROMOTION_IMPLEMENTATION_PLAN.md](archive/implementation/PHASE7_GOVERNED_PROMOTION_IMPLEMENTATION_PLAN.md) | `4a69a431f240` |
| `docs/PHASE8_CAPABILITY_PACKAGE_REGISTRY_IMPLEMENTATION_PLAN.md` | [archive/implementation/PHASE8_CAPABILITY_PACKAGE_REGISTRY_IMPLEMENTATION_PLAN.md](archive/implementation/PHASE8_CAPABILITY_PACKAGE_REGISTRY_IMPLEMENTATION_PLAN.md) | `8840673ed348` |
| `docs/PHASE8_CAPABILITY_PACKAGE_REGISTRY_IMPLEMENTATION_RESEARCH.md` | [archive/implementation/PHASE8_CAPABILITY_PACKAGE_REGISTRY_IMPLEMENTATION_RESEARCH.md](archive/implementation/PHASE8_CAPABILITY_PACKAGE_REGISTRY_IMPLEMENTATION_RESEARCH.md) | `a803bf698554` |
| `docs/PHASE9_OWNER_REQUESTED_CAPABILITY_ACQUISITION_IMPLEMENTATION_PLAN.md` | [archive/implementation/PHASE9_OWNER_REQUESTED_CAPABILITY_ACQUISITION_IMPLEMENTATION_PLAN.md](archive/implementation/PHASE9_OWNER_REQUESTED_CAPABILITY_ACQUISITION_IMPLEMENTATION_PLAN.md) | `2e048c5e7f48` |
| `docs/PHASE9H_AUTONOMOUS_EXTERNAL_CAPABILITY_COMPLETION.md` | [archive/implementation/PHASE9H_AUTONOMOUS_EXTERNAL_CAPABILITY_COMPLETION.md](archive/implementation/PHASE9H_AUTONOMOUS_EXTERNAL_CAPABILITY_COMPLETION.md) | `9170f4beda75` |
| `docs/SELF_REPAIR_PHASE1H_HARDENING.md` | [archive/implementation/SELF_REPAIR_PHASE1H_HARDENING.md](archive/implementation/SELF_REPAIR_PHASE1H_HARDENING.md) | `7f9938a5bb86` |
| `docs/GEMINI_LIVE_38_MIGRATION_2026-09-30.md` | [archive/operations/GEMINI_LIVE_38_MIGRATION_2026-09-30.md](archive/operations/GEMINI_LIVE_38_MIGRATION_2026-09-30.md) | `be42a6c43e9e` |
| `docs/INTELLIGENT_GOAL_CAPABILITY_ORCHESTRATION_RESEARCH.md` | [archive/research/INTELLIGENT_GOAL_CAPABILITY_ORCHESTRATION_RESEARCH.md](archive/research/INTELLIGENT_GOAL_CAPABILITY_ORCHESTRATION_RESEARCH.md) | `a9fa28921df3` |
| `docs/JARVIS_C3_GLOBAL_BRAIN_ROUTER_RESEARCH.md` | [archive/research/JARVIS_C3_GLOBAL_BRAIN_ROUTER_RESEARCH.md](archive/research/JARVIS_C3_GLOBAL_BRAIN_ROUTER_RESEARCH.md) | `8b46e4e0ebef` |
| `docs/JARVIS_C4_C5_BOUNDED_LOCAL_BRAIN_RESEARCH.md` | [archive/research/JARVIS_C4_C5_BOUNDED_LOCAL_BRAIN_RESEARCH.md](archive/research/JARVIS_C4_C5_BOUNDED_LOCAL_BRAIN_RESEARCH.md) | `0a3a492b5cf6` |
| `docs/PHASE10_CLOSED_LOOP_ENGINEERING_LEARNING_RESEARCH.md` | [archive/research/PHASE10_CLOSED_LOOP_ENGINEERING_LEARNING_RESEARCH.md](archive/research/PHASE10_CLOSED_LOOP_ENGINEERING_LEARNING_RESEARCH.md) | `57208fcce31e` |
| `docs/PHASE10A_AUTONOMOUS_OPERATIONS_CONTROL_PLANE_RESEARCH.md` | [archive/research/PHASE10A_AUTONOMOUS_OPERATIONS_CONTROL_PLANE_RESEARCH.md](archive/research/PHASE10A_AUTONOMOUS_OPERATIONS_CONTROL_PLANE_RESEARCH.md) | `f2d1af364f32` |
| `docs/PHASE2_ENGINEERING_KNOWLEDGE_EVALUATION.md` | [archive/research/PHASE2_ENGINEERING_KNOWLEDGE_EVALUATION.md](archive/research/PHASE2_ENGINEERING_KNOWLEDGE_EVALUATION.md) | `7df40501b2d8` |
| `docs/PHASE2_ENGINEERING_KNOWLEDGE_RESEARCH.md` | [archive/research/PHASE2_ENGINEERING_KNOWLEDGE_RESEARCH.md](archive/research/PHASE2_ENGINEERING_KNOWLEDGE_RESEARCH.md) | `ae2db744be91` |
| `docs/PHASE2_ENGINEERING_KNOWLEDGE_RETRIEVAL_EXPERIMENTS.md` | [archive/research/PHASE2_ENGINEERING_KNOWLEDGE_RETRIEVAL_EXPERIMENTS.md](archive/research/PHASE2_ENGINEERING_KNOWLEDGE_RETRIEVAL_EXPERIMENTS.md) | `a5242ffc1b9c` |
| `docs/PHASE4_MODEL_ROUTER_RESEARCH.md` | [archive/research/PHASE4_MODEL_ROUTER_RESEARCH.md](archive/research/PHASE4_MODEL_ROUTER_RESEARCH.md) | `fa18ca2e56b1` |
| `docs/PHASE5_SECURE_ENGINEERING_SUBSTRATE_RESEARCH.md` | [archive/research/PHASE5_SECURE_ENGINEERING_SUBSTRATE_RESEARCH.md](archive/research/PHASE5_SECURE_ENGINEERING_SUBSTRATE_RESEARCH.md) | `6400fefc0095` |
| `docs/PHASE6_UNKNOWN_INCIDENT_SOURCE_REPAIR_RESEARCH.md` | [archive/research/PHASE6_UNKNOWN_INCIDENT_SOURCE_REPAIR_RESEARCH.md](archive/research/PHASE6_UNKNOWN_INCIDENT_SOURCE_REPAIR_RESEARCH.md) | `d39e8431b397` |
| `docs/PHASE7_GOVERNED_PROMOTION_RESEARCH.md` | [archive/research/PHASE7_GOVERNED_PROMOTION_RESEARCH.md](archive/research/PHASE7_GOVERNED_PROMOTION_RESEARCH.md) | `08caa68a4da1` |
| `docs/PHASE8_CAPABILITY_PACKAGE_REGISTRY_RESEARCH.md` | [archive/research/PHASE8_CAPABILITY_PACKAGE_REGISTRY_RESEARCH.md](archive/research/PHASE8_CAPABILITY_PACKAGE_REGISTRY_RESEARCH.md) | `7d2a52c7ab47` |
| `docs/PHASE9_OWNER_REQUESTED_CAPABILITY_ACQUISITION_RESEARCH.md` | [archive/research/PHASE9_OWNER_REQUESTED_CAPABILITY_ACQUISITION_RESEARCH.md](archive/research/PHASE9_OWNER_REQUESTED_CAPABILITY_ACQUISITION_RESEARCH.md) | `ca846dd08f99` |
| `docs/GICC_GOAL_INTELLIGENCE_ARCHITECTURE.md` | [reference/GICC_GOAL_INTELLIGENCE_ARCHITECTURE.md](reference/GICC_GOAL_INTELLIGENCE_ARCHITECTURE.md) | `d3b92b9c4aee` |
| `docs/JARVIS_C6_CONTEXT_OPTIMIZATION_RESEARCH.md` | [reference/JARVIS_C6_CONTEXT_OPTIMIZATION_RESEARCH.md](reference/JARVIS_C6_CONTEXT_OPTIMIZATION_RESEARCH.md) | `53c7ba7198da` |
| `docs/JARVIS_COST_OPTIMIZATION_IMPLEMENTATION_PLAN.md` | [reference/JARVIS_COST_OPTIMIZATION_IMPLEMENTATION_PLAN.md](reference/JARVIS_COST_OPTIMIZATION_IMPLEMENTATION_PLAN.md) | `8573188af6c6` |
| `docs/PROVIDER_MODEL_LIFECYCLE_SELF_EVOLUTION.md` | [reference/PROVIDER_MODEL_LIFECYCLE_SELF_EVOLUTION.md](reference/PROVIDER_MODEL_LIFECYCLE_SELF_EVOLUTION.md) | `8220d7692fbb` |
| `docs/CURRENT_PLAN.md` (pre-reconciliation) | [archive/operations/CURRENT_PLAN_SNAPSHOT_2026-10-18.md](archive/operations/CURRENT_PLAN_SNAPSHOT_2026-10-18.md) | exact copy, verified separately |

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
