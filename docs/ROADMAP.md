# JARVIS V1 Roadmap

This roadmap owns **sequence only**. It does not select technology, define current architecture, or authorize implementation. Detailed planning belongs in `CURRENT_PLAN.md` for the currently active step.

The sequence is dependency-driven. Lower-level trust, capability, knowledge, and observability foundations appear before higher-power actions and workflows so later features do not invent their own execution paths.

| Step | Product slice | Major capabilities | Status |
| ---: | --- | --- | --- |
| 0 | Clean Foundation | Minimal app lifecycle, package structure, config, logging, baseline tests | DONE |
| 1 | Natural Conversational Core | CAP-001, CAP-005, CAP-006, CAP-007 | DONE |
| 2 | Wake, Voice Session, and Audio Robustness | CAP-002, CAP-003 | DONE |
| 2.5 | Vision Sensor & Active Target Tracking Foundation | Camera/PTZ boundaries, local person detection/tracking, deterministic target lock, active following | ACTIVE |
| 3 | Identity, Graduated Trust, Authority, and Observability Foundation | CAP-004, CAP-034, CAP-035, CAP-036, CAP-037 | PAUSED - RESEARCH CONTINUES AFTER 2.5 |
| 4 | Live Context and Personal Memory | CAP-008 through CAP-013 | PLANNED |
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

Step 2.5 is a deliberately bounded roadmap interlude approved after Step 2. It establishes a reusable visual sensor and active-attention foundation before Step 3 is completed. The immediate reason is practical: the available DJI Pocket 3 has experimentally proven USB webcam and programmable PTZ behavior, and visual presence will later provide one evidence source to Step 3.

Step 2.5 does **not** grant identity, authentication, permission, passive surveillance, semantic scene memory, or consequential device authority. Vision may later emit evidence; Step 3 remains the owner of trust and authority decisions.

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
-> DONE
```

Research for future steps is intentionally deferred until those steps become active. This keeps decisions current and avoids speculative architecture.

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

Goal: prove that JARVIS can hold a natural, realtime, multi-turn conversation before wake word, memory, tools, autonomy, or HUD are added.

## Step 2 - Wake, Voice Session, and Audio Robustness

Completed outcome: local wake detection, one JARVIS-owned audio path, preserved wake tail, realtime follow-up conversation, explicit return to idle, and clean re-wake work on the target Windows system. Extended endurance and device-failure trials were explicitly waived and remain recorded as unverified residual risks.

## Step 2.5 - Vision Sensor & Active Target Tracking Foundation

Goal: establish one JARVIS-owned camera path, replaceable detector/tracker/PTZ boundaries, deterministic target locking, and safe closed-loop target following on the validated Pocket 3 hardware. Technology-specific detector/tracker choices must be benchmarked on the real Windows + RTX 5060 Ti environment before being frozen.

## Step 3 - Identity, Graduated Trust, Authority, and Observability

Goal: research and define the minimum trustworthy governance foundation required before later capabilities may read, write, communicate, or control anything. Step 3 does not implement those actions or the Step-7 capability runtime. Step-3 research is paused only while Step 2.5 is active and resumes after Step 2.5 acceptance.

## Final Target - Personal Intelligence Runtime

The roadmap is not complete merely because all steps have code. The final target is one coherent personal intelligence runtime in which mature capabilities cooperate under shared conversation, context, memory, truthfulness, authority, observability, and execution boundaries.

## Roadmap Change Rule

A future idea may be added here when it represents real product intent, but it must not automatically interrupt the active step. The active step changes only through deliberate planning and human approval. Step 2.5 is such an explicitly approved interruption.