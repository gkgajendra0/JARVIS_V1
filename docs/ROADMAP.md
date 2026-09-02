# JARVIS V1 Roadmap

This roadmap owns **sequence only**. It does not select technology, define current architecture, or authorize implementation. Detailed planning belongs in `CURRENT_PLAN.md` for the currently active step.

The sequence is dependency-driven. Lower-level trust, capability, knowledge, and observability foundations appear before higher-power actions and workflows so later features do not invent their own execution paths.

| Step | Product slice | Major capabilities | Status |
| ---: | --- | --- | --- |
| 0 | Clean Foundation | Minimal app lifecycle, package structure, config, logging, baseline tests | DONE |
| 1 | Natural Conversational Core | CAP-001, CAP-005, CAP-006, CAP-007 | DONE |
| 2 | Wake, Voice Session, and Audio Robustness | CAP-002, CAP-003 | DONE |
| 2.5 | Vision Sensor & Active Target Tracking Foundation | Camera/PTZ boundaries, local person detection/tracking, deterministic target lock, active following | DONE |
| 3 | Identity, Graduated Trust, Authority, and Observability Foundation | CAP-004, CAP-034, CAP-035, CAP-036, CAP-037 | DONE |
| 4 | Live Context and Personal Memory | CAP-008 through CAP-013 | ACTIVE |
| 5 | Local/Offline Survival and Provider Resilience | CAP-048, CAP-049 | PLANNED |
| 6 | Knowledge, Current Research, and Truthfulness | CAP-014 through CAP-017 | PLANNED |
| 7 | Governed Capability Runtime + Local Files/System/Project Safe Reads | CAP-018, CAP-021, CAP-022, CAP-032 | PLANNED |
| 8 | Notes, Tasks, Reminders, and Scheduling | CAP-027, CAP-028 | PLANNED |
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

This is **not** a product step and does not change roadmap numbering. It:

- watches protected `origin/main`;
- never pulls/restarts without explicit owner approval;
- asks through JARVIS voice using fixed scripted TTS;
- keeps approval interpretation deterministic and outside model authority;
- performs clean child shutdown and restart;
- verifies restarted-child readiness through the authenticated local control channel;
- restores the previous last-known-good revision if the updated child fails readiness;
- relies on protected `main` PR flow with required quality gates.

The normal user-facing runtime does not gain Git/self-update authority merely because this development supervisor exists.

## Why CAP-032 Moves To Step 7

The old JARVIS learned that useful reads/actions should not each invent a separate router, policy path, result shape, or execution boundary. A **minimal governed capability runtime** therefore arrives with the first real safe-read expansion, before notes, apps, browser, calendar, email, files, or device actions.

This does **not** mean building a giant universal agent framework in Step 7. It means defining the smallest common contract needed by real capabilities at that point: capability identity/description, bounded input, policy/authority check, execution adapter boundary, structured result, and truthful failure state. Extensibility/plugin lifecycle remains later at Step 16.

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

## Step 0 - Clean Foundation

Completed baseline:

- clean repository separate from old JARVIS;
- modern Python `src` layout;
- minimal `JarvisApp` lifecycle;
- environment configuration;
- console logging;
- import/lifecycle safety tests;
- no voice, model, network, audio, memory, or capability side effects at import time.

## Step 1 - Natural Conversational Core

Completed outcome: manual realtime conversation, multilingual English/Hindi/Hinglish use, contextual follow-ups/corrections, provider-backed interruption support where available, canonical accepted conversation state, and real human acceptance.

## Step 2 - Wake, Voice Session, and Audio Robustness

Completed outcome: local wake detection, one JARVIS-owned audio path, preserved wake tail, realtime follow-up conversation, explicit return to idle, and clean re-wake work on the target Windows system. Extended endurance and device-failure trials were explicitly waived and remain recorded as residual risks.

## Step 2.5 - Vision Sensor & Active Target Tracking Foundation

Completed outcome: one JARVIS-owned Pocket 3 camera path, replaceable detector/tracker/PTZ boundaries, RF-DETR Nano person detection, OC-SORT tracking, head-first framing evidence, deterministic target locking, safe pan/tilt/adaptive-zoom follow, canonical visual state, and real Windows + RTX 5060 Ti + Pocket 3 human acceptance.

## Step 3 - Identity, Graduated Trust, Authority, and Observability

Completed outcome: the minimum trustworthy governance/identity foundation required before later capabilities may act. Step 3 established deterministic trust/risk/proposal/approval/audit contracts, Windows-session invalidation, Windows Hello strong verification, encrypted OWNER face/voice profile boundaries, accepted face/liveness evidence, a single-microphone LiveKit production audio path, and non-authoritative CAM++/LR-ASD speaker diagnostics.

Step 3 deliberately closes with T2 `CORROBORATED_OWNER` disabled and biometric speaker/active-speaker thresholds unpromoted. Known overlap, replay/deepfake, non-owner calibration, short-turn continuity, and attention improvements are deferred until a later product capability makes them necessary. This preserves the rule that identity evidence never directly grants consequential execution permission.

Closure evidence: `docs/research/STEP_3_CLOSURE_ACCEPTANCE.md`.

## Step 4 - Live Context and Personal Memory

Goal: give JARVIS one coherent, privacy-aware context/memory owner so useful personal/project continuity survives beyond a single conversation without turning every utterance into permanent memory.

Step 4 covers:

- live session/task/project context;
- durable semantic facts/preferences/rules;
- episodic events/milestones;
- reflection and memory-candidate generation;
- provenance, confidence, correction, supersession, and forgetting;
- retrieval of relevant personal/project memory;
- transient emotional interaction context that does not become permanent identity labeling by default.

Technology is **not selected yet**. Step 4 begins with requirements recovery and current-2026 technology research. Models may propose memory candidates but may not directly mutate canonical durable memory.

## Final Target - Personal Intelligence Runtime

The roadmap is not complete merely because all steps have code. The final target is one coherent personal intelligence runtime in which mature capabilities cooperate under shared conversation, context, memory, truthfulness, authority, observability, and execution boundaries.

At that point JARVIS should be able to:

- converse naturally and remain present across sessions;
- know approved personal/project context and correct it when the user corrects JARVIS;
- choose whether a request needs model reasoning, fresh external information, trusted sources, memory, local project evidence, or a capability;
- verify current/high-risk claims appropriately;
- perform routine daily computer, file, browser, device, note, calendar, email, and project workflows with proportional consent;
- monitor explicitly selected topics/conditions and do bounded background work;
- coordinate mature capabilities without creating an uncontrolled second brain;
- degrade truthfully when cloud/provider/network/device capability is unavailable;
- expose understandable state through the HUD/workspace;
- diagnose faults and eventually propose/apply only governed, reversible, auditable improvements;
- remain replaceable at provider boundaries rather than becoming permanently coupled to one model/framework/provider.

## Roadmap Change Rule

A future idea may be added here when it represents real product intent, but it must not automatically interrupt the active step. The active step changes only through deliberate planning and human approval.
