# JARVIS V1 Roadmap

This roadmap owns **sequence only**. It does not select technology, define current architecture, or authorize implementation. Detailed planning belongs in `CURRENT_PLAN.md` for the currently active step.

The sequence is dependency-driven. Lower-level trust, capability, knowledge, and observability foundations appear before higher-power actions and workflows so later features do not invent their own execution paths.

| Step | Product slice | Major capabilities | Status |
| ---: | --- | --- | --- |
| 0 | Clean Foundation | Minimal app lifecycle, package structure, config, logging, baseline tests | DONE |
| 1 | Natural Conversational Core | CAP-001, CAP-005, CAP-006, CAP-007 | DONE |
| 2 | Wake, Voice Session, and Audio Robustness | CAP-002, CAP-003 | DONE (long-utterance activity correction owner-accepted 2026-09-08) |
| 2.5 | Vision Sensor & Active Target Tracking Foundation | Camera/PTZ boundaries, local person detection/tracking, deterministic target lock, active following | DONE |
| 3 | Identity, Graduated Trust, Authority, and Observability Foundation | CAP-004, CAP-034, CAP-035, CAP-036, CAP-037 | DONE |
| 4 | Live Context and Personal Memory | CAP-008 through CAP-013 | DONE (BOUNDED; provider-assisted 4.5D recall accepted; strict independent verifier + 4.5E deferred) |
| 5 | Local/Offline Survival and Provider Resilience | CAP-048, CAP-049 | DONE (BOUNDED; minimal provider-failure diagnosis + local truthful status accepted; full local/offline stack deferred) |
| 6 | Knowledge, Current Research, and Truthfulness | CAP-014 through CAP-017 | DONE (BOUNDED; provider-neutral source-aware web research + truth/provenance policy accepted) |
| 7 | Governed Capability Runtime + Local Files/System/Project Safe Reads | CAP-018, CAP-021, CAP-022, CAP-032 | DONE — OWNER ACCEPTED 2026-09-09 |
| 8 | Notes, Tasks, Reminders, and Scheduling | CAP-027, CAP-028 | ACTIVE NEXT — REQUIREMENTS / RESEARCH |
| 9 | Computer, Application, and Device Control | CAP-023, CAP-024 | PLANNED |
| 10 | Browser and Web Interaction | CAP-025 | PLANNED |
| 11 | Calendar, Email, and External Communication | CAP-029, CAP-030 | PLANNED |
| 12 | Documents, File Writes, and Coding/Project Operations | CAP-026, CAP-031 | PLANNED |
| 13 | HUD, Visual Workspace, Health, and Diagnostics | CAP-038, CAP-039 | PLANNED |
| 14 | Passive World Awareness | CAP-019, CAP-020 | PLANNED |
| 15 | Proactive Monitoring and Background Work | CAP-040, CAP-041 | PLANNED |
| 16 | Extensibility and Plugin/Skill Lifecycle | CAP-033 | PLANNED |
| 17 | Daily Assistant and Multi-Capability Workflows | CAP-042 plus mature prior capabilities | PLANNED |
| 18 | Learning, Gap Detection, and Governed Skill Creation | CAP-043, CAP-044, CAP-045 | PLANNED |
| 19 | Governed Self-Diagnostics and Repair | CAP-046 | PLANNED |
| 20 | Governed Self-Improvement and Advanced Autonomy | CAP-047 | PLANNED |

## Why Step 2.5 Exists

Step 2.5 was a deliberately bounded roadmap interlude approved after Step 2. It established a reusable visual sensor and active-target foundation before Step 3. The DJI Pocket 3 experimentally proved USB webcam and programmable PTZ behavior, and the accepted visual runtime now provides presence/tracking/head evidence that later identity/awareness layers may consume.

Step 2.5 does **not** itself grant identity, authentication, permission, passive surveillance, semantic scene memory, or consequential device authority.

## Development Supervisor Interlude

After Step 2.5 acceptance and before Step 3 implementation, the development workflow received one bounded infrastructure improvement: `jarvis-dev`.

This is **not** a product step and does not change roadmap numbering. It watches protected `origin/main`, never pulls/restarts without explicit owner approval, performs clean child shutdown/restart, verifies readiness through the authenticated local control channel, and restores the previous last-known-good revision if the updated child fails readiness.

The normal user-facing runtime does not gain Git/self-update authority merely because this development supervisor exists.

## Why CAP-032 Moves To Step 7

The old JARVIS learned that useful reads/actions should not each invent a separate router, policy path, result shape, or execution boundary. A **minimal governed capability runtime** therefore arrived with the first real safe-read expansion, before notes, apps, browser, calendar, email, files, or device actions.

Step 7 did **not** build a giant universal agent framework. It established the smallest common contract needed by real capabilities: capability identity/discovery, bounded input, canonical authority binding, execution adapter boundary, structured result, provenance, verification, audit, and truthful failure state. Extensibility/plugin lifecycle remains later at Step 16.

## Universal Step Lifecycle

Every major step follows the same sequence:

```text
REQUIREMENTS
-> RESEARCH
-> TECHNOLOGY DECISION
-> ARCHITECTURE
-> HUMAN APPROVAL
-> IMPLEMENTATION
-> AUTOMATED VALIDATION
-> REAL HUMAN USE
-> CORRECTION IF NEEDED
-> HUMAN ACCEPTANCE
-> DOCUMENTATION RECONCILIATION
-> PROTECTED-MAIN MERGE
-> DONE
```

A step may also close **bounded with explicit deferrals** when the owner deliberately chooses not to weaken a safety/reliability boundary and the accepted subset is independently useful. Such a closure must document the residual limitation and must not silently mark the deferred capability as working.

Research for future steps is intentionally deferred until those steps become active. This keeps decisions current and avoids speculative architecture.

## Strategic Evolution Milestones

1. **Conversational Presence** — Steps 1-2.
2. **Perception Foundation** — Step 2.5.
3. **Governed Personal Foundation** — Steps 3-5.
4. **Source-Aware Intelligence** — Steps 6-7.
5. **Reliable Daily Actions** — Steps 8-12.
6. **Visible and Aware Assistant** — Steps 13-15.
7. **Extensible Daily Assistant** — Steps 16-17.
8. **Governed Learning and Improvement** — Steps 18-20.
9. **Personal Intelligence Runtime** — the integrated end state after the mature capabilities above work together coherently.

## Completed Outcomes Through Step 7

### Step 0 — Clean Foundation

Accepted clean repository, modern Python `src` layout, minimal app lifecycle, environment configuration, logging, baseline tests, and import/lifecycle safety.

### Step 1 — Natural Conversational Core

Accepted manual realtime conversation, multilingual English/Hindi/Hinglish use, contextual follow-ups/corrections, provider-backed interruption support where available, canonical accepted conversation state, and real human acceptance.

### Step 2 — Wake, Voice Session, and Audio Robustness

Accepted local wake detection, one JARVIS-owned audio path, preserved wake tail, realtime follow-up conversation, explicit return to idle, and clean re-wake work on the target Windows system. A later owner-accepted correction prevents long utterances from being killed by the outer inactivity lifecycle while preserving provider-native turn completion.

Acceptance evidence: `docs/research/STEP_2_LONG_UTTERANCE_ACTIVITY_ACCEPTANCE.md`.

### Step 2.5 — Vision Sensor & Active Target Tracking Foundation

Accepted one JARVIS-owned Pocket 3 camera path, replaceable detector/tracker/PTZ boundaries, RF-DETR Nano person detection, OC-SORT tracking, head-first framing evidence, deterministic target locking, and safe pan/tilt/adaptive-zoom follow.

### Step 3 — Identity, Graduated Trust, Authority, and Observability

Accepted deterministic trust/risk/proposal/approval/audit contracts, Windows-session invalidation, Windows Hello strong verification, encrypted OWNER face/voice profile boundaries, accepted face/liveness evidence, a single-microphone production audio path, and non-authoritative CAM++/LR-ASD speaker diagnostics.

T2 `CORROBORATED_OWNER` remains disabled and CAM++/LR-ASD remain shadow evidence only.

Acceptance evidence: `docs/research/STEP_3_CLOSURE_ACCEPTANCE.md`.

### Step 4 — Live Context and Personal Memory

Bounded complete with encrypted canonical durable memory, explicit remember/inspect/correct/forget, candidate quarantine, FTS5 + Qwen derived retrieval/reranking, and bounded provider-assisted semantic recall. Strict independent semantic verification and automatic conversational semantic-memory injection remain deferred.

### Step 5 — Local/Offline Survival and Provider Resilience

Bounded complete with deterministic terminal provider-failure diagnosis, Windows-local truthful status speech, safe failed-session closure, and provider health recovery state. Full local/offline conversation remains deferred.

Acceptance evidence: `docs/research/STEP_5_MINIMAL_PROVIDER_RESILIENCE_ACCEPTANCE.md`.

### Step 6 — Knowledge, Current Research, and Truthfulness

Bounded complete with provider-neutral live-web research, Exa as the accepted first replaceable retrieval adapter, JARVIS-owned evidence/provenance/truth status, deterministic research-warrant gating, and fail-closed source sufficiency.

Acceptance evidence: `docs/research/STEP_6_KNOWLEDGE_TRUTHFULNESS_ACCEPTANCE.md`.

### Step 7 — Governed Capability Runtime + Local Files/System/Project Safe Reads

Owner accepted on 2026-09-09.

Accepted outcome:

- provider-neutral capability discovery/resolution/runtime;
- Microsoft `winapp` semantic schema discovery while desktop execution remains disabled;
- truthful Windows ODR unavailability/degradation when not present;
- bounded `system_status` and process inspection;
- approved-root file/project metadata, listing, search, text read, and document read;
- Git/ripgrep preferred mature project primitives with bounded fallback;
- canonical `ActionProposal -> AuthorityService -> Windows Hello/T3 -> one-time permit` for private reads;
- path/symlink/sensitive/secret release protections;
- Microsoft MarkItDown isolated sidecar for PDF/DOCX/PPTX/XLS/XLSX conversion without downgrading the accepted JARVIS vision ONNX runtime;
- production voice `inspect_local` tool with deterministic current-user-request grounding;
- no file writes, arbitrary shell, browser execution, desktop/app/device control, installation, deletion, or coding mutation.

Owner-machine acceptance proved positive private reads, explicit Windows Hello cancel/fail-closed behavior, a real XLSX read through the isolated sidecar, routine live system telemetry, and live voice private project reading. During unrelated meeting audio, an ambiguous local-inspection attempt was rejected because the current user turn did not explicitly authorize inspection.

Acceptance evidence: `docs/research/STEP_7_GOVERNED_CAPABILITY_RUNTIME_ACCEPTANCE.md`.

Ambient-meeting false USER-turn admission remains a separate voice/identity residual because CAM++/LR-ASD thresholds are still intentionally unpromoted.

## Step 8 — Notes, Tasks, Reminders, and Scheduling

Step 8 becomes the next active slice **only after Step 7 merges to protected `main`**.

It must begin with requirements recovery and fresh research for CAP-027 and CAP-028. It must reuse the existing conversation, memory, authority, and Step-7 capability-runtime foundations rather than inventing parallel scheduling truth, execution, or permission paths.

Detailed active planning belongs in `CURRENT_PLAN.md`.

## Final Target — Personal Intelligence Runtime

The roadmap is not complete merely because all steps have code. The final target is one coherent personal intelligence runtime in which mature capabilities cooperate under shared conversation, context, memory, truthfulness, authority, observability, and execution boundaries.

At that point JARVIS should be able to converse naturally, know approved personal/project context, choose the right evidence/capability source, perform governed daily workflows, monitor explicitly selected conditions, degrade truthfully, expose understandable state, and eventually propose/apply only governed and auditable improvements while remaining replaceable at provider boundaries.

## Roadmap Change Rule

A future idea may be added here when it represents real product intent, but it must not automatically interrupt the active step. The active step changes only through deliberate planning and human approval.
