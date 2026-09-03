# JARVIS V1 Roadmap

This roadmap owns **sequence only**. It does not select technology, define current architecture, or authorize implementation. Detailed planning belongs in `CURRENT_PLAN.md` for the active product slice.

The sequence is dependency-driven: trust, context, knowledge, observability, and governed execution foundations appear before higher-power actions and workflows.

| Step | Product slice | Major capabilities | Status |
| ---: | --- | --- | --- |
| 0 | Clean Foundation | Minimal app lifecycle, package structure, config, logging, baseline tests | DONE |
| 1 | Natural Conversational Core | CAP-001, CAP-005, CAP-006, CAP-007 | DONE |
| 2 | Wake, Voice Session, and Audio Robustness | CAP-002, CAP-003 | DONE |
| 2.5 | Vision Sensor & Active Target Tracking Foundation | Camera/PTZ boundaries, local person detection/tracking, deterministic target lock, active following | DONE |
| 3 | Identity, Graduated Trust, Authority, and Observability Foundation | CAP-004, CAP-034, CAP-035, CAP-036, CAP-037 | DONE |
| 4 | Live Context and Personal Memory | CAP-008 through CAP-013 | NEXT / ACTIVE AFTER STEP-3 MERGE |
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

---

## Universal step lifecycle

Every major product step follows:

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

Research for future steps is intentionally deferred until those steps become active so decisions use current technology rather than stale speculative plans.

---

## Step 0 — Clean Foundation

Completed baseline:

- clean repository separate from legacy JARVIS;
- modern Python `src` layout;
- minimal application lifecycle;
- configuration/logging/import safety;
- baseline tests;
- no model/audio/memory/capability side effects at import time.

## Step 1 — Natural Conversational Core

Completed outcome: realtime natural conversation, multilingual English/Hindi/Hinglish use, contextual follow-ups/corrections, provider-backed interruption, canonical conversation state, and real human acceptance.

## Step 2 — Wake, Voice Session, and Audio Robustness

Completed outcome: local wake detection, one JARVIS-owned audio path, preserved wake tail, realtime follow-up conversation, explicit return to idle, clean re-wake, and accepted target-machine audio routing. Extended endurance/device-failure trials were explicitly waived and remain residual risks.

## Step 2.5 — Vision Sensor & Active Target Tracking Foundation

Completed outcome: one JARVIS-owned Pocket3 camera path, replaceable detector/tracker/PTZ boundaries, RF-DETR Nano person detection, OC-SORT tracking, head-first framing evidence, deterministic target locking, safe pan/tilt/adaptive-zoom follow, canonical visual state, and real target-machine human acceptance.

Step 2.5 does not itself grant identity, authentication, permission, passive surveillance, or semantic scene memory.

---

## Step 3 — Identity, Graduated Trust, Authority, and Observability

Completed product outcome: the trustworthy identity/governance foundation required before later capabilities may act.

Accepted Step-3 architecture includes:

- T0–T3 graduated trust;
- deterministic R0–R5 risk floors;
- immutable proposal-bound actions/approvals;
- fail-closed OPA policy;
- one-time revalidation/execution permits;
- structured privacy-aware audit;
- Windows-session invalidation;
- Windows Hello T3 strong verification;
- encrypted OWNER FACE + VOICE profile;
- YuNet/SFace temporal OWNER identity;
- MiniFAS passive liveness and active-liveness fallback;
- one production Pocket3 LiveKit/WebRTC audio owner;
- production bounded T2 `CORROBORATED_OWNER` context;
- CAM++ speaker shadow;
- LR-ASD visible active-speaker shadow;
- native Sortformer overlap/speaker-change shadow.

### Step-3 accepted limitation

Production T2 proves fresh live OWNER presence in the current Windows session, but it **does not yet prove that a specific spoken turn came from the OWNER**.

Therefore current normal T2 keeps:

```text
actor_unambiguous = false
```

and spoken R3 persistent/external actions remain fail-closed until turn-specific spoken actor binding is intentionally resumed and accepted.

This hardening is explicitly deferred rather than blocking the rest of the roadmap. CAM++ calibration, anti-spoof work, overlap semantics, and short-turn continuity are part of that future actor-binding package only when needed—not independent reasons to keep Step 3 open.

Critical R4 actions remain T3 / Windows Hello strong verification.

Decisions/evidence:

- `docs/decisions/ADR-015_BOUNDED_T2_OWNER_CONTEXT.md`
- `docs/decisions/ADR-016_DEFER_SPOKEN_ACTOR_BINDING_AND_RESUME_ROADMAP.md`
- `docs/research/STEP_3_CLOSURE_ACCEPTANCE.md`

---

## Step 4 — Live Context and Personal Memory

Goal: give JARVIS one coherent, privacy-aware context/memory owner so useful personal/project continuity survives beyond one conversation without turning every utterance into permanent memory.

Step 4 covers:

- live session/task/project context;
- durable semantic facts/preferences/rules;
- episodic events/milestones;
- reflection and memory-candidate generation;
- provenance, confidence, correction, supersession, and forgetting;
- retrieval of relevant personal/project memory;
- transient emotional interaction context that does not become permanent identity labeling by default.

**Technology is not selected yet.** Step 4 must begin with requirements recovery and current-2026 technology research. Models may propose memory candidates but may not directly mutate canonical durable memory.

Deferred Step-3 spoken actor binding is not a prerequisite for Step 4.

---

## Why CAP-032 remains Step 7

Useful reads/actions must not each invent a separate router, policy path, result shape, or execution boundary. A minimal governed capability runtime therefore arrives with the first real safe-read expansion in Step 7. It will reuse the authority foundation accepted in Step 3.

This does not mean building a giant universal agent framework. Extensibility/plugin lifecycle remains Step 16.

---

## Development supervisor interlude

`jarvis-dev` is development infrastructure rather than a numbered product step. It watches the selected protected branch, requires explicit owner approval for updates/restarts, verifies child readiness, can restore last-known-good state, and must never become ordinary model authority.

---

## Strategic evolution milestones

1. **Conversational Presence** — Steps 1–2.
2. **Perception Foundation** — Step 2.5.
3. **Governed Personal Foundation** — Steps 3–5.
4. **Source-Aware Intelligence** — Steps 6–7.
5. **Reliable Daily Actions** — Steps 8–12.
6. **Visible and Aware Assistant** — Steps 13–15.
7. **Extensible Daily Assistant** — Steps 16–17.
8. **Governed Learning and Improvement** — Steps 18–20.
9. **Personal Intelligence Runtime** — integrated end state after mature capabilities cooperate coherently.

---

## Final target — Personal Intelligence Runtime

The roadmap is not complete merely because every step has code. The final target is one coherent personal intelligence runtime in which mature capabilities cooperate under shared conversation, context, memory, truthfulness, authority, observability, and execution boundaries.

JARVIS should eventually be able to:

- converse naturally and remain present across sessions;
- know approved personal/project context and accept correction;
- choose among reasoning, fresh research, trusted sources, memory, project evidence, and capabilities;
- verify current/high-risk claims appropriately;
- perform routine computer/file/browser/device/note/calendar/email/project workflows with proportional consent;
- monitor explicitly selected conditions and perform bounded background work;
- coordinate mature capabilities without creating an uncontrolled second brain;
- degrade truthfully when provider/network/device capability is unavailable;
- expose understandable state through a HUD/workspace;
- diagnose faults and eventually propose/apply only governed, reversible, auditable improvements;
- remain replaceable at provider/storage/tool boundaries.

## Roadmap change rule

A future idea may be recorded without interrupting the active slice. The active step changes only through deliberate planning and human approval.
