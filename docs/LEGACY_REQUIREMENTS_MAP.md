# Legacy JARVIS Requirements Map

## Purpose

This is a one-time migration/reference map from the old `gkgajendra0/JARVIS` repository into JARVIS V1 product intent.

It exists so that useful old requirements are not forgotten while preventing the old architecture from becoming the new architecture by accident.

The old repository is evidence. `PRODUCT.md` owns the permanent V1 product definition. `ROADMAP.md` owns sequence. `CURRENT_PLAN.md` owns the active slice.

## Mapping Principles

- Preserve worthwhile **behaviour and user value**.
- Preserve useful tests, failure evidence, and safety lessons.
- Reuse old implementation only if later research proves it is still the best fit.
- Do not preserve duplication, hardcoded routing, giant composition files, overlapping state owners, or documentation bureaucracy.
- Retired autonomous development agents are not requirements; their useful goal is represented by governed repair/self-improvement capabilities.

## Old Capability Families -> V1

| Old JARVIS area/evidence | Product intent found | V1 destination | Migration decision |
| --- | --- | --- | --- |
| `runtime/voice/*`, `audio/*`, wake/auth tests | Wake word, command capture, follow mode, STT/TTS, barge-in, turn coordination, device ownership, fallback, echo/AEC concerns | CAP-001 through CAP-004 | Preserve behaviour; redesign/research implementation |
| `runtime/conversation/*`, understanding/continuity/context modules | Natural follow-ups, context retention, corrections, multi-turn conversation | CAP-006, CAP-007 | Preserve behaviour; do not preserve overlapping owners |
| old Brain/Composer/ContextGuardian/Continuity layering | Governed reasoning and coherent final response | CAP-006, CAP-007, CAP-017 | Preserve product goal; reject duplicated cognition pipeline |
| `memory/working_memory.py` and session continuity tests | Current task/goal/project/recent issue/pending work/idle-resume context | CAP-008 | Preserve behaviour; redesign ownership |
| `memory/episodic_memory.py` | Recall events and prior work | CAP-010 | Preserve product intent |
| `memory/semantic_memory.py` | Durable facts/preferences, provenance/confidence, conflict/supersession | CAP-009, CAP-011 | Preserve product intent |
| `memory/reflection_engine.py` | Session achievements/issues/decisions/next steps/memory candidates | CAP-012 | Preserve concept; keep reflection non-authoritative |
| `memory/emotional_context.py` and semantic-memory rejection rules | Temporary emotional/interaction context without permanent mood labeling | CAP-013 | Preserve principle |
| memory-capture shadows/confirmed-memory paths | Selective memory write, confirmation, safety boundaries | CAP-009 through CAP-013, CAP-034 | Preserve behaviour; simplify authority model |
| knowledge source router, source truthfulness guard | Choose appropriate knowledge source and avoid unsupported freshness claims | CAP-014, CAP-017 | Preserve strongly |
| CAP-020 research integration, citation tests, current affairs | Current web/deep research with bounded provider wrapper, provenance, citations | CAP-015, CAP-017 | Preserve product requirements; re-research technology later |
| trusted-domain/fact-check planning | Higher-quality domain sources and evidence verification | CAP-016, CAP-017 | Preserve |
| local project document retrieval plans | Read/search approved project docs/code/logs | CAP-018, CAP-022 | Preserve |
| `world/world_intelligence.py`, world model, passive-awareness tests | World/current-interest awareness that is passive until relevant | CAP-019, CAP-020 | Preserve aware-but-quiet behaviour |
| generic local-system safe reads, temporal activity recall | Time/uptime/status/activity/local system facts | CAP-021, CAP-022 | Preserve; ensure fallback never changes the question |
| file-read architecture plans | Bounded file metadata/text reads, approved roots, traversal protection | CAP-022 | Preserve |
| app-opening/brightness/device experiments and tests | Application, desktop-setting, and device control | CAP-023, CAP-024 | Preserve capability goal; re-research implementation |
| Hisense/Vidaa/device-control experiments | TV/device actions | CAP-024 | Preserve as example, not hardcoded product architecture |
| browser/search future roadmap | Web read/search first, later controlled interaction | CAP-025 | Preserve |
| file-action future roadmap | Create/edit/move/rename/delete with stronger safeguards | CAP-026 | Preserve |
| governed notes read + legacy note write | Practical notes lifecycle | CAP-027 | Preserve feature; reject split/duplicated note authority |
| reminders/notifications roadmap | Future tasks and reminders | CAP-028 | Preserve |
| calendar roadmap | Calendar read then approved write | CAP-029 | Preserve |
| email roadmap | Read, draft, review, send as separate authority levels | CAP-030 | Preserve |
| development tooling, repository validation, Codex/repair scaffolding | Coding/project engineering and repository health | CAP-031, CAP-050 | Preserve product value; development scaffolding remains separate from normal runtime authority |
| generic capability planner/policy/guard/bridge/result envelope | Common capability discovery/selection/execution boundary | CAP-032 | Preserve goal; simplify dramatically |
| skill discovery/registry/manifests/staged skills | Extensible plugin/skill lifecycle | CAP-033 | Preserve extensibility; reject duplicate registries and hidden activation |
| `decision/consent_*`, approval state, policy/phase guards | Permission, consent, approval binding, decision gating | CAP-034, CAP-036 | Preserve strongly; simplify component count |
| graduated trust work | Frictionless normal conversation with step-up identity for consequential actions | CAP-035 | Preserve strongly |
| execution traces/result envelopes | Truthful attempted/success/failure/partial/unverified action states | CAP-036, CAP-037 | Preserve |
| runtime observability/trace specs | Session/turn/capability IDs, latency and governance traces | CAP-037 | Preserve; privacy-safe |
| diagnostics/health reports/hardcoding audit | Runtime health, project health, route visibility, architecture drift detection | CAP-038, CAP-050 | Preserve |
| React HUD/JARVIS workspace | Conversation/status/context/execution/memory/skills/world/repair visual workspace | CAP-039 | Preserve product intent; redesign later |
| interactive globe/world feed/media/context panels | Visual world intelligence, sources, why-it-matters, alerts, workspace context | CAP-039, CAP-019 | Preserve experience goals; mock data is not a requirement |
| scheduling/proactivity roadmap | Monitoring, reminders, selected topic alerts, background work | CAP-040, CAP-041 | Preserve with explicit user control |
| cross-capability daily workflows | Multi-step goals using mature capabilities | CAP-042 | Preserve; do not create a second autonomous brain |
| outcome/learning concepts | Learn from confirmed successes/failures | CAP-043 | Preserve with bounded authority |
| gap detection/evolution modules | Recognize missing capability instead of pretending | CAP-044 | Preserve |
| skill generation/staging/lifecycle | Propose/create/test/stage new capabilities before activation | CAP-045 | Preserve goal, keep approval-gated |
| repair planning/executor/backup/rollback/sandbox tests | Diagnose/propose/test/backup/apply/verify/rollback repairs | CAP-046 | Preserve; no normal autonomous repair |
| quarantined `engineer.py`, `self_corrector.py`, `upgrade_agent.py` | Desire for self-evolution | CAP-047 | Retire implementation; preserve only governed future goal |
| local/offline voice/model fallback discussions | Survival during provider/network outage | CAP-048 | Preserve; research when Step 5 activates |
| provider wrappers/adapters | Replaceable external mechanics | CAP-049 | Preserve as permanent architecture principle |
| research-first development policy, architecture audits, test suites | Avoid rebuilding commodity tech blindly; validate real behaviour | CAP-050 | Preserve as permanent process |

## Explicit Legacy CAP Coverage Check

The old authoritative capability inventory contained CAP-001 through CAP-036. This table confirms that every one is either preserved as V1 product intent or deliberately retired as an implementation pattern.

| Old CAP | Old capability | V1 coverage |
| --- | --- | --- |
| 001 | Owner Voice Authentication | CAP-004 Identity and Presence + CAP-035 Graduated Trust |
| 002 | Wake Word and Conversational Follow Mode | CAP-002 Wake and Conversational Presence + CAP-003 Audio Robustness |
| 003 | Speech-to-Text | CAP-001 Natural Voice Conversation / provider mechanics researched in Step 1-2 |
| 004 | Speech Output, Barge-In, Spoken Response Boundary | CAP-001, CAP-003, CAP-005 |
| 005 | Generic Conversational Understanding | CAP-006 Conversation Intelligence |
| 006 | Conversation Continuity and Context Guardian | Behaviour preserved in CAP-006/CAP-007; old separate ownership architecture rejected |
| 007 | Deterministic Brain Governance and Decision Handling | Product intent split into CAP-006 reasoning + CAP-034/CAP-036 authority/execution; no giant Brain requirement |
| 008 | Universal GPT Composer and Response Contract | Behaviour preserved by CAP-005/CAP-006/CAP-017; separate Composer architecture is not mandatory |
| 009 | Working and Session Memory | CAP-008 Live Session Context |
| 010 | Confirmed Local Memory V1 | CAP-009 Long-Term Personal Memory + CAP-034 authority |
| 011 | Generic Memory-Capture Shadow Observation | Memory-write safety/evaluation preserved in CAP-009/CAP-050; shadow component itself not mandatory |
| 012 | Episodic and Semantic Retrieval Context | CAP-010/CAP-011 |
| 013 | Live Semantic Memory Write Authority | CAP-009/CAP-011 with future governed write policy; no unrestricted write authority |
| 014 | Generic Capability Planning, Policy, Guard, Bridge, Result Envelope | CAP-032 Generic Capability Runtime + CAP-034/CAP-036 |
| 015 | Approved Local-System Safe Reads | CAP-021/CAP-022 |
| 016 | Temporal Activity Recall | CAP-008/CAP-021 |
| 017 | Notes Read and Note Lifecycle | CAP-027 Notes |
| 018 | Knowledge Source Router V1 | CAP-014 Knowledge and Source Routing |
| 019 | Governed Local Project Document Retrieval | CAP-018 Local Project and Document Intelligence |
| 020 | Governed External Current-Information Retrieval | CAP-015 Current Information and Deep Research |
| 021 | Trusted Domain Knowledge Sources | CAP-016 Trusted Domain Knowledge |
| 022 | Evidence Verification and Fact-Checking | CAP-017 Fact Checking and Truthfulness |
| 023 | Source Truthfulness Guard V1 | CAP-017 + permanent truthfulness contract |
| 024 | Phase, Policy, Approval, and Execution Guarding | CAP-034/CAP-035/CAP-036; old Phase bureaucracy not preserved |
| 025 | Passive Runtime Observability | CAP-037 Runtime Observability |
| 026 | World Snapshot and Aware-but-Quiet Context | CAP-019/CAP-020 |
| 027 | Runtime Health Reporting and Diagnostics | CAP-038 Health and Diagnostics |
| 028 | Skill Discovery and Capability Registry | CAP-032/CAP-033 |
| 029 | Approval-Gated Skill Staging and Lifecycle | CAP-033/CAP-045 |
| 030 | Controlled Manual Sandbox Repair | CAP-046 Self-Diagnostics and Repair |
| 031 | Autonomous or Normal Live Repair | Governed goal represented by CAP-046/CAP-047; unrestricted old form explicitly rejected |
| 032 | Local System, Application, Device, and File Actions | CAP-023/CAP-024/CAP-026 and later action steps |
| 033 | JARVIS Web/HUD Interface | CAP-039 HUD and Visual Workspace |
| 034 | Scheduling, Proactive Monitoring, and Background Autonomy | CAP-028/CAP-040/CAP-041 |
| 035 | Repository Validation and Development Operations | CAP-031/CAP-050 |
| 036 | Legacy Autonomous Development Agents | **RETIRED implementation.** Useful intent is CAP-044 through CAP-047 under explicit governance. |

This coverage check means there is no known old authoritative capability with no V1 destination.

## Concrete Old Features/Experiments Not To Forget

The old repository also contained or tested concrete examples that should remain represented by the broader V1 capabilities even if they are not implemented as dedicated modules:

- owner voice authentication;
- wake word and conversational follow mode;
- local and cloud STT/TTS experiments;
- interruption/barge-in;
- echo/AEC and speaker-to-microphone leakage handling;
- audio-device ownership/fallback;
- temporal activity recall;
- system time/status/uptime reads;
- notes;
- current affairs;
- Indian market updates;
- local files/project documents;
- application launch/focus;
- brightness/system-setting control;
- Hisense/Vidaa TV and device-power experiments;
- presence guarding via camera/OS/presence signals;
- world intelligence and user-interest ranking;
- citations and source validation;
- skill discovery, staging, validation, activation gates;
- runtime health and diagnostics;
- repair console and governed repair concepts;
- interactive globe/world feed;
- memory and skills views;
- issues/alerts and live communications UI;
- project/repository validation and anti-hardcoding checks.

## Old Strategic Outcomes Preserved

The old strategic roadmap targeted more than isolated features. V1 explicitly preserves these outcomes:

- source-aware knowledge orchestration rather than storing all world knowledge locally;
- perception from local/external evidence;
- approved personal/project memory with correction and forgetting;
- reliable governed action;
- a useful daily assistant;
- multi-capability orchestration without a second decision authority;
- bounded/governed agents where they provide real value;
- governed learning and improvement;
- a final Personal Intelligence Runtime that remains trustworthy, private, source-aware, reversible, and user-governed.

## Old Lessons That Become V1 Rules

1. Do not build custom infrastructure before researching strong current alternatives.
2. Do not create multiple owners for conversation/context/memory truth.
3. Do not let a fallback answer a different question (for example, uptime -> current time).
4. Do not let wake acknowledgement repeat unrelated substantive content.
5. Do not allow silence/update-only events to extend conversation deadlines indefinitely.
6. Do not allow audio acquisition from invalid voice-session states.
7. Do not make ordinary conversation repeatedly authenticate the owner.
8. Do not let passive world context override explicit user text.
9. Do not write temporary mood/emotional observations into durable semantic memory.
10. Do not let read capability secretly invoke write capability.
11. Do not let approval-like text activate or install a skill.
12. Do not let a model or capability grant itself broader authority.
13. Do not claim success when execution was skipped, partial, unavailable, or unverified.
14. Do not let interesting technology detours replace the active release without a demonstrated blocker.
15. Do not embed normal development/repair machinery into ordinary runtime startup.
16. Do not recreate giant control-document hierarchies; Git and small authoritative docs are enough.
17. Do not preserve dead implementations merely because they were expensive to build.
18. Introduce a common capability execution boundary before broad action expansion so each new capability does not create its own router/policy/result architecture.
19. Separate read, draft/proposal, and commit/write authority for external or persistent actions.
20. Treat data retention/privacy as product behaviour, not an afterthought.

## Explicit Non-Migrations

The following are not requirements to reproduce:

- the old giant `main.py`;
- duplicate context/conversation owners;
- separate Continuity/ContextGuardian/pronoun/topic layers merely for ordinary model-history understanding;
- multiple capability registries/bridges/switches where one boundary is sufficient;
- duplicated notes read/write architecture;
- phase-lock/document-control bureaucracy;
- giant decision logs and work-package archives;
- phrase-specific hardcoded command routing as the primary intelligence layer;
- normal live autonomous repository editing;
- retired autonomous development agents.

Their lessons remain valuable; their architecture does not.
