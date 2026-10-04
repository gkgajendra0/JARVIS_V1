# Owner Communication & Interaction Layer — Research, Repo Sweep, and Implementation Plan

**Status:** PARKED / NOT IMPLEMENTED YET  
**Created:** 2026-10-04  
**Branch:** `feat/owner-communication-interaction-layer`  
**Baseline SHA:** `25551c72edde227cdca217cb50154a0f20eb26b6`  
**Resume rule:** before implementation, rebase this branch onto the final accepted D8 / capability-acquisition head. Do not implement from this frozen baseline if D8 has advanced.

---

## 1. Problem statement

JARVIS already has strong internal truth, governance, authority, durable work, capability acquisition, promotion, incident repair, and self-management models.

The user-facing communication layer is not equally consistent.

Some paths already convert canonical internal facts into natural speech. Other paths directly expose implementation details such as:

- `EngineeringChange`
- `WorkItem`
- `WorkStep`
- `gate_...`
- `work_...`
- `change_...`
- artifact digests / SHA-256
- DBOS
- GICC
- Phase numbers
- Exa
- JEV
- provider routing
- control-plane terminology
- internal exception names
- internal reason/status codes

This is acceptable in logs and engineering diagnostics, but not as the default interface for a normal user.

The desired product behavior is:

1. Assume the person using JARVIS is not technical unless they ask for technical detail.
2. Explain what happened in normal language.
3. Explain what it means for the user.
4. Tell the user what happens next or what action is required.
5. Keep all internal IDs, hashes, exact evidence, stack traces, reason codes, and Authority bindings available internally.
6. Reveal technical detail progressively only when requested.
7. Preserve all existing fail-closed Authority and governance guarantees.

---

## 2. Triggering evidence from D8

During the real TV capability-acquisition test, the following UX defects became visible.

### 2.1 Approval UX exposed internal gate identity

The architecture approval flow required the owner to say a phrase equivalent to:

`approve gate_<opaque-id>`

This is technically precise but poor human UX.

A normal interaction should be:

> “I’ve finished planning the TV-control capability. The next step will modify JARVIS and run tests. Shall I continue?”

Then the user should be able to answer:

- “Yes.”
- “Proceed.”
- “Go ahead.”
- “No.”
- “Reject it.”
- “Stop.”

The active bounded approval interaction must internally carry the exact gate identity.

### 2.2 Error wording leaked implementation language

Examples encountered or possible in current flows include:

- `bounded reasoning cycle budget exceeded`
- `research_credentials_missing`
- `no approved routing target is currently eligible`
- `ChangeConflict: no accepted owner turn`
- `DependencyResourceUnavailable`

These are valuable engineering diagnostics but should not be spoken verbatim by default.

### 2.3 Generic “internal error” loses useful information

Some domain exceptions can escape into the realtime tool layer. The user may then hear only that an internal error occurred.

This is also poor UX because it hides the useful meaning that JARVIS actually knows.

For example:

Internal truth:

`ChangeConflict: no accepted owner turn`

Owner-facing meaning:

> “I couldn’t reliably connect your response to the approval I was asking for, so I didn’t approve anything. I’ll ask you again.”

This preserves the safety outcome and tells the owner what happens next.

---

## 3. Repository sweep findings

### 3.1 Good existing pattern: Work status is structured, speech is natural

`src/jarvis/voice/work_tools.py` already treats canonical Work fields as facts rather than a spoken script.

The tool documentation explicitly says:

- milestone / completed_work / remaining_work are semantic identifiers;
- canonical facts should be phrased naturally;
- blockers and ETA truth must be preserved;
- the realtime provider must not invent a different state.

This is the right pattern and should be generalized.

### 3.2 Main gate UX problem: engineering change delivery constructs technical speech directly

`src/jarvis/engineering_change/delivery.py`

Current architecture-review delivery includes raw technical material such as:

- `EngineeringChange <change_id>`
- architecture revision number
- raw proposal JSON
- artifact SHA-256
- exact `approve <gate_id>` / `reject <gate_id>` phrases

This should stop being an owner-facing sentence generator.

It should instead emit structured owner-communication semantics while retaining exact gate/change/artifact metadata.

### 3.3 Voice runtime currently enforces exact spoken gate ID

`src/jarvis/voice/canonical_active_speaker_runtime.py`

`_run_change_gate_interaction()` currently instructs the realtime model to:

- ask for exact `approve <gate_id>` / `reject <gate_id>`;
- reject generic yes/no;
- call `decide_change_gate` only after the exact phrase.

This is secure but unnecessarily pushes internal identity onto the human.

The safer UX pattern is not to weaken the exact gate internally. It is to bind the active interaction to the exact gate and let normal language express only the decision.

### 3.4 Work delivery fallback can expose raw technical text

The normal cloud path asks the model to make background notifications sound natural.

However, critical delivery fallback can pass the prebuilt delivery text directly to local TTS.

Therefore, any raw technical status embedded in `WorkDelivery.message` can reach the owner if the realtime provider is unavailable.

Owner-safe wording must therefore be produced before the cloud/local speech fork.

### 3.5 Raw domain exceptions still exist at tool boundaries

Examples in current paths include:

- `ChangeConflict`
- `WorkStoreError`
- promotion session errors
- acquisition protocol errors
- dependency resource errors

Technical exceptions should remain technical internally.

User-facing tools should translate them into typed semantic outcomes rather than allow them to become the spoken explanation.

### 3.6 Promotion already has partial natural-language grammar

The promotion path supports typed phrases such as “approve promotion”, but exact gate identity is still used in some flows and ambiguity handling can require the ID.

The same bound-context approval architecture should be shared across:

- architecture approval
- promotion approval
- activation or other protected decisions where appropriate

### 3.7 Existing voice instructions already support the design direction

`src/jarvis/voice/agent.py` already establishes:

- concise answers;
- truthful capability reporting;
- natural status phrasing;
- internal IDs treated as opaque in some domains;
- do not expose internal implementation unnecessarily;
- structured tool truth remains authoritative.

This feature should extend that principle rather than replace the existing voice contract.

---

## 4. External research

The implementation should follow established human-computer interaction guidance rather than inventing an ad-hoc wording system.

### 4.1 Apple Human Interface Guidelines — Alerts

Source:
https://developer.apple.com/design/human-interface-guidelines/alerts

Relevant guidance:

- be direct;
- use a neutral, approachable tone;
- clearly describe what happened and why;
- avoid useless titles such as “Error” or opaque numeric error codes;
- present only essential information and useful actions;
- make important decisions actionable.

Application to JARVIS:

- do not speak gate IDs or opaque error codes by default;
- explain the situation first;
- state the actual decision or action required;
- keep technical identity internal.

### 4.2 Apple Human Interface Guidelines — Writing

Source:
https://developer.apple.com/design/human-interface-guidelines/writing

Relevant guidance:

- write clear error messages;
- avoid blame;
- explain what the person can do to fix or recover;
- provide clear next steps.

Application to JARVIS:

Every owner-facing failure/blocker should answer:

1. What happened?
2. What does it mean?
3. What happens next / what can I do?

### 4.3 Apple Human Interface Guidelines — Design principles

Source:
https://developer.apple.com/design/human-interface-guidelines/design-principles

Relevant guidance:

- keep people informed;
- make recovery easy;
- provide clear feedback;
- use familiar concepts consistently;
- explain permissions and important actions clearly.

Application to JARVIS:

The owner should hear product concepts such as:

- “I need your approval before I change my code.”
- “I couldn’t connect to the TV.”
- “I stopped because I was repeating the same step.”

They should not need internal control-plane vocabulary.

### 4.4 Microsoft HAX Toolkit — Guidelines for Human-AI Interaction

Source:
https://www.microsoft.com/en-us/haxtoolkit/ai-guidelines/

Relevant principles:

- make clear what the system can do;
- make clear why the system did what it did;
- plan for AI interaction failures;
- help users recover efficiently.

Specific explanation guidance:
https://www.microsoft.com/en-us/haxtoolkit/guideline/make-clear-why-the-system-did-what-it-did/

Application to JARVIS:

- explanations should be available, but not overload every normal interaction;
- default explanation should be local and task-relevant;
- deeper technical evidence should be available progressively on request.

### 4.5 Microsoft HAX Playbook

Source:
https://www.microsoft.com/en-us/haxtoolkit/playbook/

Relevant principle:

Common AI interaction failures should be anticipated and designed for before deployment.

Application to JARVIS:

Owner communication must have acceptance tests for:

- ambiguous approvals;
- stale approvals;
- failed actions;
- unavailable resources;
- model/provider failure;
- retries;
- partial completion;
- inability to determine a safe target;
- multiple pending actions.

### 4.6 Nielsen Norman Group — Error Message Guidelines

Source:
https://www.nngroup.com/articles/error-message-guidelines/

Relevant guidance:

- use human-readable language;
- avoid jargon;
- avoid obscure codes except for diagnostics;
- precisely explain the problem;
- provide constructive recovery information;
- respect the user’s effort.

Application to JARVIS:

Internal reason codes stay in telemetry/logs. Owner messages use plain language plus a concrete next step.

---

## 5. Target architecture

Introduce a single cross-cutting owner communication layer.

```text
Internal domains
  Work
  GICC
  Hands
  Capability Acquisition
  EngineeringChange
  Promotion
  Incident Repair
  Memory
  Vision
  Self-Awareness
  Authority
        |
        v
Typed internal state / evidence / reason codes
        |
        v
OWNER COMMUNICATION LAYER
  - semantic event model
  - privacy / disclosure policy
  - owner-safe deterministic presenter
  - decision-context binding
  - progressive-detail policy
  - local fallback renderer
        |
        +-------------------+
        |                   |
        v                   v
Realtime conversational   Deterministic local
voice/text rendering      fallback rendering
        |
        v
Human-facing JARVIS
```

Recommended package:

```text
src/jarvis/owner_communication/
    __init__.py
    models.py
    events.py
    presenter.py
    decision_context.py
    policy.py
    fallback.py
```

Names are provisional; architecture is more important than exact file names.

---

## 6. Owner message model

Do not make arbitrary strings the primary cross-domain contract.

Use a typed semantic object such as:

```python
OwnerMessageV1(
    category="approval_required",
    severity="action_required",
    subject="TV-control capability",
    what_happened="I finished planning how to add TV control.",
    user_impact="The next step will change JARVIS code and run tests.",
    next_action="Do you want me to continue?",
    choices=("approve", "reject"),
    safety_outcome=None,
    reason_code="engineering_change.architecture_approval",
    internal_refs={
        "gate_id": "gate_...",
        "change_id": "change_...",
        "artifact_digest": "...",
    },
)
```

The internal refs are never automatically spoken.

---

## 7. Plain-language error contract

Every owner-visible error/blocker should provide semantic fields equivalent to:

```text
WHAT HAPPENED
WHAT IT MEANS FOR YOU
WHAT HAPPENS NEXT / WHAT YOU CAN DO
SAFETY OUTCOME, when relevant
```

Examples:

### Repeated reasoning loop

Internal:

`bounded reasoning cycle budget exceeded`

Owner:

> “I got stuck repeating the same reasoning step, so I stopped the task rather than letting it run indefinitely.”

### Missing local dependency runtime

Internal:

`DependencyResourceUnavailable: reviewed uv runtime is not configured`

Owner:

> “I can’t verify the software dependency yet because one required local tool isn’t configured. I need that tool available before I can continue.”

### No eligible acquisition route

Internal:

`no approved routing target is currently eligible`

Owner:

> “I found possible ways to add this capability, but none has passed the checks required for me to use it yet.”

### Approval turn not bound

Internal:

`ChangeConflict: no accepted owner turn`

Owner:

> “I couldn’t reliably connect your response to the approval I was asking for, so I didn’t approve anything. I’ll ask you again.”

---

## 8. Natural approval architecture

### 8.1 Current model

```text
owner speaks opaque gate ID
        |
        v
exact gate lookup
        |
        v
GateService / Authority
```

### 8.2 Target model

```text
JARVIS opens bounded approval interaction
        |
        v
interaction is internally bound to exactly one gate
        |
        v
JARVIS explains decision in normal language
        |
        v
owner says "yes" / "proceed" / "no" / "reject"
        |
        v
bounded decision interpreter
        |
        v
exact internally bound gate
        |
        v
existing GateService / Authority
```

### 8.3 Fail-closed rules

Natural language must never weaken Authority.

Rules:

1. “Yes” in an ordinary conversation approves nothing.
2. Natural approval is valid only inside an active bounded decision context.
3. The decision context must be bound to exactly one current gate.
4. The gate must still be pending/current when the decision is consumed.
5. The approval still binds the exact artifact digest/version.
6. A stale owner turn must fail.
7. Two or more unresolved candidate gates require clarification by human-readable description.
8. The model never chooses a hidden gate based on guesswork.
9. Gate IDs remain available in logs and technical-detail mode.
10. Existing one-shot Authority permits and promotion protections remain unchanged.

---

## 9. Progressive disclosure

Default mode: non-technical.

Example:

> “I couldn’t connect to the TV. I’ll try again when it becomes reachable.”

If user asks “why?”:

> “The connection to the TV’s control service timed out.”

If user asks for technical details:

```text
Target: <address/port if releasable>
Transport: TCP
Reason code: device.transport.timeout
Work ID: ...
Evidence: ...
```

Technical details must still pass privacy/secrecy policy.

Never expose:

- credentials
- tokens
- private keys
- OTPs
- secret-store values
- hidden security evidence not intended for the owner-facing channel

---

## 10. Deterministic semantics first, model phrasing second

Do not solve this only with a prompt such as “make errors easy to understand.”

Required architecture:

```text
domain emits typed reason/event
        |
        v
deterministic owner-safe semantic representation
        |
        +----------------------------+
        |                            |
        v                            v
realtime model adds natural style   deterministic local fallback
        |                            |
        +-------------+--------------+
                      v
                owner hears it
```

The realtime model may improve wording, but must not be the only safety/clarity layer.

This avoids the current asymmetry where cloud speech may paraphrase technical text while local fallback can expose the raw message.

---

## 11. Proposed reason-code taxonomy

Stable semantic codes should replace string parsing at communication boundaries.

Examples:

```text
work.reasoning_loop_stopped
work.retry_submission_failed
work.resource_unavailable
work.owner_input_required

approval.required
approval.owner_turn_not_bound
approval.ambiguous
approval.stale
approval.rejected

capability.no_eligible_candidate
capability.research_unavailable
capability.verification_blocked
capability.activation_failed

device.unreachable
device.authentication_required
device.pairing_required

promotion.approval_required
promotion.candidate_stale
promotion.ci_failed
promotion.merge_blocked

provider.rate_limited
provider.quota_unavailable
provider.temporarily_unavailable

memory.target_ambiguous
vision.capability_unavailable
authority.permission_required
authority.denied
```

Exact taxonomy should be finalized during implementation after inventorying all owner-visible domain conditions.

---

## 12. Repo integration points

### Voice

`src/jarvis/voice/agent.py`

Add a global communication contract:

- assume no technical knowledge by default;
- prefer familiar concepts;
- never speak internal IDs unless requested or strictly necessary;
- explain errors using cause/effect/next action;
- never hide a safety outcome;
- technical-detail escalation is explicit.

`src/jarvis/voice/canonical_active_speaker_runtime.py`

- consume OwnerMessage rather than arbitrary raw strings;
- keep realtime phrasing bounded by semantic truth;
- ensure local fallback receives owner-safe rendered text;
- implement bounded approval conversation using decision context.

### EngineeringChange

`src/jarvis/engineering_change/delivery.py`

- stop constructing raw technical speech;
- emit structured approval-required event;
- retain gate/change/artifact identity as hidden metadata.

`src/jarvis/engineering_change/service.py`

- preserve exact gate verification;
- accept a trusted bound decision context as the identity source;
- do not require the human to pronounce the gate ID.

### Work

`src/jarvis/work/models.py`
`src/jarvis/work/orchestrator.py`
`src/jarvis/work/runtime.py`

- keep detailed internal `status_detail`;
- add stable semantic reason/event fields where owner-facing delivery is required;
- avoid formatting owner speech in orchestration code.

### Work voice tools

`src/jarvis/voice/work_tools.py`

- translate known domain failures to structured outcomes;
- do not let expected domain conflicts escape as generic tool exceptions;
- preserve canonical source turn and target binding.

### Capability acquisition

`src/jarvis/capability_acquisition/`

- emit typed blockers and completion semantics;
- no direct owner wording from acquisition internals.

### Development Engine

`src/jarvis/development_engine/`

- report semantic state / blocker;
- no raw Codex/provider/internal exception in default user speech.

### Promotion

`src/jarvis/promotion/`

- use the same decision-context model for protected promotion approval;
- retain exact evidence digest and one-shot Authority;
- natural approval only when unambiguously bound.

### GICC

- keep goal and plan truth;
- communicate goal progress in task language, not GICC terminology.

### Incident repair / self-awareness

- distinguish:
  - “what happened”
  - “what JARVIS knows”
  - “what JARVIS is doing”
  - “what remains uncertain”
- hide component IDs unless technical detail is requested.

---

## 13. Acceptance tests

Add dedicated suites:

```text
tests/test_owner_communication.py
tests/test_owner_communication_voice.py
tests/test_owner_decision_context.py
```

Plus integration cases in existing Work, EngineeringChange, Promotion, Capability Acquisition, GICC, Voice and Authority tests.

Required acceptance cases:

1. Bound single gate + “yes” -> exact gate approved.
2. Bound single gate + “proceed” -> exact gate approved.
3. Bound single gate + “no” -> exact gate rejected.
4. Ordinary conversation + “yes” -> no gate approval.
5. Two unbound pending gates + “yes” -> clarification, no approval.
6. Stale decision context -> no approval.
7. Artifact changed after prompt -> no approval.
8. Replayed old owner turn -> no approval.
9. Raw gate ID absent from default spoken approval prompt.
10. Raw change/work IDs absent from default spoken status.
11. Exception class names absent from default spoken errors.
12. Stack traces absent from owner communication.
13. Raw reason codes absent from default speech.
14. Local fallback remains plain-language when cloud voice fails.
15. Technical-detail request can reveal permitted internal diagnostics.
16. Secrets/credentials never appear in owner messages.
17. Existing GateService digest binding remains intact.
18. Existing Authority one-shot permit tests remain intact.
19. Existing promotion stale-candidate protection remains intact.
20. Existing Work durable-delivery/retry behavior remains intact.
21. Language matching continues to work for English/Hindi/Hinglish.
22. Safety outcome is preserved in owner-facing failure wording.

---

## 14. Implementation sequence

Do not implement this while D8 capability acquisition is still being proven.

When resumed:

### Phase A — inventory and contracts

- inventory all owner-visible `WorkDeliveryKind` paths;
- inventory domain exception/status/reason sources;
- finalize OwnerMessageV1;
- finalize reason-code taxonomy;
- add no-behavior-change translation tests.

### Phase B — owner-safe notification layer

- implement deterministic presenter;
- route background delivery through it;
- ensure local fallback is owner-safe;
- keep technical logs unchanged.

### Phase C — bounded natural approvals

- add decision-context model;
- bind active voice approval session to exact gate;
- support natural approve/reject language;
- preserve stale/ambiguous fail-closed behavior.

### Phase D — domain adoption

Migrate:

- EngineeringChange
- Work
- Capability Acquisition
- Development Engine
- Promotion
- GICC
- Incident Repair
- Self-Awareness
- Hands / device blockers
- Memory / Vision where owner-facing failures exist

### Phase E — progressive disclosure

- “why?”
- “more detail”
- “technical details”
- deterministic disclosure policy

### Phase F — acceptance

- Linux tests
- Windows voice/runtime tests
- Authority/gate regression
- promotion regression
- local fallback test
- owner-machine voice acceptance

---

## 15. Non-goals

This feature must NOT:

- weaken Authority;
- auto-approve risky actions;
- let the model select arbitrary hidden gates;
- remove technical logs;
- remove exact identifiers from durable state;
- hide uncertainty;
- hide failures;
- make every error vague;
- use LLM paraphrasing as the sole safety layer;
- introduce a second engineering lifecycle;
- replace Work / EngineeringChange / Promotion truth;
- expose secrets under “technical details.”

---

## 16. Product-level communication rule

Default owner communication should sound like this:

> “Here is what happened, what it means for you, and what happens next.”

Not like this:

> “Here is the internal subsystem name, opaque identifier, exception class, and state-machine code.”

JARVIS should be technically rigorous internally and ordinary-human friendly externally.

---

## 17. Deferred status / next action

This feature is intentionally parked until the current D8 TV capability-acquisition lifecycle has been completed and accepted end to end.

Before implementation:

1. finish D8;
2. identify the final accepted D8 head;
3. rebase this branch onto that head;
4. rerun the repo-wide communication inventory;
5. implement from the refreshed baseline.

No runtime behavior should be changed on this branch yet.
