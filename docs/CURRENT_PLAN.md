# JARVIS V1 Current Plan

## Active Step

**Step 3 — Identity, Graduated Trust, Authority, and Observability Foundation**

## Current Stage

**RESEARCH READY — IMPLEMENTATION UNAUTHORIZED**

Step 2 was human-accepted on 2026-08-29 after automated validation and real Windows
use. The implemented wake/audio architecture is recorded in
`docs/CURRENT_ARCHITECTURE.md` and ADR-002.

The human owner explicitly waived the extended endurance matrix because the working
runtime had already demonstrated the required core path. The two-hour TV trial,
20-cycle repetition trials, device unplug/reconnect trial, and measured latency trials
remain **unverified**, not passed. They are residual reliability work and
reconsideration triggers if field use exposes problems.

## Step 3 Objective

Define the smallest trustworthy foundation that later capabilities can use to answer:

- who or what is present, when identity actually matters;
- what an operation would do and how risky it is;
- whether the user has authorized that exact operation;
- what was proposed, attempted, completed, failed, or remains unverified;
- what operational evidence may be recorded without leaking secrets or personal data.

Step 3 must establish governance boundaries before JARVIS gains tools or computer
control. It must not pre-build the Step-7 capability runtime or a speculative universal
policy engine.

## Required Behaviour

### Identity and Presence

- represent identity, session, and presence evidence without treating evidence as permission;
- distinguish unknown, claimed, observed, and verified identity states;
- never claim voice identity from wake-word recognition;
- allow stronger verification to be requested only when consequence requires it.

### Graduated Trust and Consent

- classify proposed operations by consequence using a small, explainable risk model;
- bind approval to the exact operation, target, important parameters, and validity period;
- support denial, expiry, cancellation, and revocation;
- prevent a model, provider, prompt, or tool from granting its own authority;
- keep low-risk conversation free from unnecessary authentication friction.

### Truthful Execution State

- distinguish proposal, approval, attempt, success, partial success, failure,
  cancellation, rollback, and unverified outcome;
- never convert intent, provider text, or an attempted call into a success claim;
- preserve enough evidence for later capability implementations to explain outcomes.

### Privacy-Safe Observability

- define useful session/event correlation without recording secrets by default;
- specify redaction, retention, and access boundaries before durable audit data exists;
- keep operational logs separate from canonical conversation and future personal memory;
- make degraded or unavailable governance state explicit.

## Explicit Non-Scope

- actual computer, browser, file, email, calendar, device, or external-service actions;
- durable personal memory;
- a production speaker-biometric system unless research proves a narrowly required
  identity mechanism and it receives separate approval;
- the common capability runtime planned for Step 7;
- HUD, proactive monitoring, self-repair, or self-improvement;
- autonomous permission changes or model-authored policy;
- speculative abstractions for capabilities that do not yet exist.

## Required Research

Research must be technology-neutral and use current primary sources plus relevant
old-JARVIS evidence. It must answer:

1. Which identity and presence signals are useful on the local Windows/voice runtime,
   and what can each signal actually prove?
2. What small graduated-risk model can be applied consistently to future reads,
   writes, external effects, and destructive actions?
3. How should approvals be scoped, expired, revoked, and protected from replay or
   confused-deputy behavior?
4. Which security and privacy standards should inform authentication, authorization,
   consent, audit, secret handling, and data minimization?
5. What minimum event/result schema truthfully represents proposals, attempts,
   outcomes, evidence, and rollback without building the Step-7 runtime?
6. Which observability data is necessary for diagnosis, and which content must be
   redacted, bounded, or excluded?
7. Which old-JARVIS identity, permission, authentication, audit, and failure lessons
   should become requirements or tests rather than copied architecture?
8. What threat model and measurable acceptance gates are appropriate before any later
   capability can perform consequential work?

## Architecture and Approval Gate

After research, document candidate comparisons and proposed ownership boundaries.
Record `KEEP_OURS / ADOPT / ADAPT / WRAP / REWRITE / REJECT` decisions in research and
ADR documents—not in this plan.

Architecture must define identity evidence ownership, risk classification, scoped
approval, truthful outcome state, observability/redaction, replacement boundaries, and
tests. Human approval is required after architecture review and before implementation.

## Completion Gate

Step 3 is `DONE` only after research, a recorded decision, approved architecture,
implementation, automated validation, real human acceptance, cleanup, and documentation
reconciliation.

## Immediate Next Action

**Research Step 3 only. Do not implement identity, permissions, audit storage, or
capability execution until the research and architecture receive explicit human
approval.**
