# JARVIS V1 Roadmap

This roadmap owns **sequence only**. It does not select technology, define current architecture, or authorize implementation. Detailed planning belongs in `CURRENT_PLAN.md` for the currently active step.

The sequence is dependency-driven. Lower-level trust, capability, knowledge, and observability foundations appear before higher-power actions and workflows so later features do not invent their own execution paths.

| Step | Product slice | Major capabilities | Status |
| ---: | --- | --- | --- |
| 0 | Clean Foundation | Minimal app lifecycle, package structure, config, logging, baseline tests | DONE |
| 1 | Natural Conversational Core | CAP-001, CAP-005, CAP-006, CAP-007 | ACTIVE - PLANNING |
| 2 | Wake, Voice Session, and Audio Robustness | CAP-002, CAP-003 | PLANNED |
| 3 | Identity, Graduated Trust, Authority, and Observability Foundation | CAP-004, CAP-034, CAP-035, CAP-036, CAP-037 | PLANNED |
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
-> IMPLEMENTATION
-> AUTOMATED VALIDATION
-> REAL HUMAN USE
-> CORRECTION IF NEEDED
-> HUMAN ACCEPTANCE
-> DONE
```

Research for future steps is intentionally deferred until those steps become active. This keeps decisions current and avoids speculative architecture.

## Strategic Evolution Milestones

The old JARVIS strategic roadmap expressed the desired evolution as governed foundation -> perception -> memory -> reliable action -> daily assistant -> multi-capability orchestration -> governed agents -> governed learning/improvement -> personal intelligence runtime. V1 preserves that product direction while simplifying the implementation sequence.

The V1 milestones are:

1. **Conversational Presence** — Steps 1-2.
2. **Governed Personal Foundation** — Steps 3-5.
3. **Source-Aware Intelligence** — Steps 6-7.
4. **Reliable Daily Actions** — Steps 8-12.
5. **Visible and Aware Assistant** — Steps 13-15.
6. **Extensible Daily Assistant** — Steps 16-17.
7. **Governed Learning and Improvement** — Steps 18-20.
8. **Personal Intelligence Runtime** — the integrated end state after the mature capabilities above work together coherently.

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

High-level completion means:

- manual start works;
- natural multi-turn conversation works;
- English, Hindi, and Hinglish are usable;
- contextual references and corrections work naturally;
- interruptions are handled by the selected realtime stack where in scope;
- JARVIS owns the canonical accepted conversation record;
- real human usage is acceptable;
- no duplicated conversation/context owners are introduced.

The exact technology and architecture must be confirmed through the Step-1 planning/research process before implementation.

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
