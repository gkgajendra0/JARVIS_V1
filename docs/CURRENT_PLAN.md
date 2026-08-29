# JARVIS V1 Current Plan

## Active Step

**Step 3 — Identity, Graduated Trust, Authority, and Observability Foundation**

## Current Stage

**ACTIVE — RESEARCH / ARCHITECTURE DEFINITION**

Step 0, Step 1, Step 2, and Step 2.5 are complete. The development-only `jarvis-dev` supervisor is also implemented, automated-validated, human-accepted, merged to protected `main`, and now watches `origin/main` by default.

Step 3 is the next product slice. Earlier working research established the core direction, but no Step-3 implementation or final technology selection is accepted yet. The first Step-3 task is to complete and record current research, threat/risk assumptions, and the minimum architecture required before later capabilities may read, write, communicate, or control consequential resources.

## Step-3 Objective

Build the smallest trustworthy governance foundation that can answer four separate questions without conflating them:

1. **Who or what is present?** — identity/presence evidence.
2. **How much should JARVIS trust that evidence for this session/action?** — graduated trust.
3. **Is this specific requested action permitted?** — authority, policy, and consent.
4. **What happened and why?** — privacy-aware observability/audit evidence.

Step 3 does **not** yet implement the later generic capability runtime or broad computer/file/browser/email/device actions. It establishes the governance contracts those later steps must reuse.

## Frozen Prerequisites

The following are already accepted and must be treated as inputs, not redesigned casually:

- natural realtime conversation and canonical accepted conversation state;
- local wake detection and JARVIS-owned audio lifecycle;
- Pocket 3 visual capture, RF-DETR person detection, OC-SORT tracking, head evidence, explicit target selection, and safe PTZ follow;
- vision/head/person tracking as **evidence only**, never permission;
- wake word as an activation signal only, never authentication;
- `jarvis-dev` as development tooling outside model authority;
- protected `main` requiring PR flow plus `ruff` and `pytest` checks;
- explicit spoken software-update approval parsed deterministically outside the realtime model;
- last-known-good rollback for failed development updates.

## Step-3 Non-Negotiable Invariants

- Identity evidence is not execution permission.
- Face recognition, voice recognition, presence, Windows/session context, wake word, or model confidence must never directly grant consequential authority.
- The model may recommend or explain; deterministic JARVIS-owned policy decides whether an action may proceed.
- Capabilities cannot self-authorize or broaden their own permission.
- Approval must bind to the materially relevant action, target, and parameters.
- Ambiguous or missing approval must fail safely for consequential actions.
- Trust friction should increase with consequence rather than making ordinary conversation annoying.
- Observability must capture enough evidence to explain decisions without becoming hidden surveillance.
- Raw audio/video, full transcripts, biometric material, secrets, and sensitive payloads are not retained merely because they are available.
- Provider/device/model implementations remain replaceable behind JARVIS-owned contracts.

## Step-3 Research Questions

Before architecture is frozen, research must cover at least:

- owner identity and presence evidence sources suitable for the current Windows + Pocket 3 environment;
- current face-recognition/embedding options, local inference performance, licensing, and spoof/liveness limitations;
- voice identity/speaker-verification options and their limitations in TV/background/multi-speaker conditions;
- session continuity and identity-evidence fusion rather than single-sensor authentication;
- graduated-trust models appropriate for read, reversible, persistent, external, destructive, security-sensitive, and self-modifying actions;
- approval/consent state machines and exact-action binding;
- local policy/authority engine design that remains outside LLM authority;
- audit/observability event design, retention, redaction, and privacy boundaries;
- threat cases: replay, spoofed face/voice, nearby person saying “yes”, stale identity evidence, device/session changes, provider hallucination, compromised capability, and confused-deputy behavior;
- failure/degraded behavior when sensors, providers, or identity signals are unavailable.

## Expected Step-3 Deliverables

Before implementation begins, produce:

- a Step-3 research record with current evidence and realistic alternatives;
- one or more ADRs for major accepted identity/trust/authority/observability decisions;
- a concrete threat model and trust-level vocabulary;
- canonical JARVIS-owned contracts for identity evidence, trust/session state, authority decisions, approvals, and audit events;
- explicit scope/non-scope and human acceptance scenarios;
- measurable validation criteria for security, privacy, latency, and false-accept/false-reject behavior where applicable.

## Explicitly Out of Scope for Step 3

- broad file/system/browser/device/email/calendar execution;
- the Step-7 generic capability runtime;
- long-term personal memory;
- general scene understanding / VLM reasoning;
- OCR, gestures, or visual memory;
- proactive surveillance or continuous recording;
- smart-glasses/HUD work;
- unrestricted shell authority;
- autonomous self-modification.

## Completion Gate

Step 3 is complete only after:

```text
requirements
-> current research
-> technology/architecture decisions
-> human approval
-> implementation
-> automated validation
-> real human acceptance
-> documentation reconciliation
-> protected-main merge
```

No Step-3 component becomes authoritative merely because a model/provider API works in isolation.

## Immediate Next Actions

1. Complete current Step-3 research, including face/voice identity evidence, liveness limits, trust models, authority policy, approvals, observability, privacy, and threat cases.
2. Compare mature 2026 technologies before choosing any implementation.
3. Propose the minimum Step-3 architecture and trust-level model.
4. Obtain explicit human approval before implementation.
