# ADR-018 — Self-Awareness Evidence and Health Foundation

## Status

**OWNER-APPROVED IMPLEMENTATION INTERLUDE — NOT YET PRODUCTION-ACCEPTED.**

This ADR records the architecture boundary being implemented on `feature/self-awareness-foundation`. It does not mark roadmap Steps 13, 18, 19 or 20 complete.

## Context

JARVIS already has useful but fragmented operational evidence: startup preflight, capability discovery/results, authority audit, provider resilience, runtime profiling, tests, Git state and subsystem-specific recovery. Future self-diagnostics and self-repair require those facts to be correlated without allowing a model to invent health, permissions, or successful execution.

The research objective was to reuse mature observability and engineering-agent technology while keeping JARVIS-owned truth and authority.

## Decision

### 1. JARVIS owns the operational Self Model

A version-controlled Self Model describes components, source locations, product/capability relationships, dependencies, health probes, configuration surfaces and validation evidence. External observability products may store or visualize telemetry but do not become canonical component truth.

### 2. Health is deterministic and evidence-backed

Canonical operational health states are `UNKNOWN`, `STARTING`, `HEALTHY`, `DEGRADED`, `FAILED`, `RECOVERING` and `DISABLED`.

Every health observation has a source, timestamp/freshness TTL, reason code and summary. Stale observations become `UNKNOWN`. Dependency criticality is explicit (`BLOCKING`, `DEGRADING`, `OPTIONAL`) and health roll-up is deterministic. An LLM may explain evidence but cannot directly mint health state.

### 3. OpenTelemetry is the backend-neutral telemetry contract

OpenTelemetry is adopted for traces and metrics. OTLP export is disabled by default in the initial foundation and must remain replaceable. The OpenTelemetry Collector is the intended later receive/process/redact/batch/export boundary.

OpenTelemetry Python currently marks traces and metrics Stable while Logs remain Development. Therefore JARVIS does not make the Python OpenTelemetry Logs SDK its only logging truth in this interlude.

### 4. Structured logs remain locally usable and bounded

`structlog` is used above Python logging to produce structured events while preserving readable console output. A rotating local JSONL spool provides machine-readable operational evidence even when no collector/backend is running. Sensitive-key redaction runs before persistence, and raw audio/video/screenshots/provider payloads/prompts are not ordinary operational log fields.

### 5. Security audit, telemetry and personal memory remain separate

Authority audit continues to own permission/action evidence. Personal memory continues to own user memory. Operational incidents are stored separately and summarize engineering evidence rather than copying unrestricted raw telemetry into personal memory.

### 6. Incident memory is durable engineering knowledge

Incidents group meaningful degraded/failed transitions and may retain compact evidence references, affected components, confirmed root cause, accepted fix, regression tests, commit/PR, deployment result, rollback state and lessons. This is the durable input for future diagnosis; raw high-volume telemetry remains subject to bounded retention.

### 7. Repair/evolution agents remain outside authority

No model or coding agent gains production mutation authority from this foundation. Future repair must remain `evidence -> diagnosis -> proposal -> isolated branch/worktree/sandbox -> tests -> owner approval -> protected-main merge -> jarvis-dev readiness -> keep/rollback`.

## Technology disposition

- OpenTelemetry API/SDK + OTLP: **ADOPT** for traces/metrics and backend-neutral export.
- `structlog`: **ADOPT** for structured Python operational logging.
- OpenTelemetry Collector: **ADOPT LATER** as the telemetry pipeline boundary after local foundation acceptance.
- SigNoz: **PRIMARY BACKEND CANDIDATE, NOT CANONICAL**; deployment is deferred until resource/privacy acceptance on the owner machine.
- JARVIS Self Model / Health Registry / Incident semantics: **KEEP JARVIS-OWNED** because these encode product truth and governance rather than commodity telemetry transport.
- Autonomous repair/evolution: **OUT OF SCOPE** for this interlude.

## Privacy and retention boundary

Complete causal coverage does not mean recording every sensor sample. High-frequency numerical state belongs in metrics; operations belong in traces; meaningful state/error transitions belong in structured events. Secrets, credentials, raw audio/video, biometric crops and unnecessary screenshots are excluded from normal logs. Local structured logs rotate by size; longer-term incident records retain compact engineering evidence.

## Acceptance gates

This interlude is not production-accepted until:

1. repository lint/tests are green;
2. logging preserves existing human-readable runtime usability;
3. redaction tests prove representative secrets are absent from persisted events;
4. local runtime overhead is measured on the owner machine;
5. current hardware/provider/Hands/Pocket behavior is not regressed;
6. documentation is reconciled after real-use acceptance;
7. protected-main merge remains explicit owner approval.

## Reconsideration triggers

Revisit this decision if OpenTelemetry Python Logs becomes stable enough to replace the local structured-log path cleanly, if operational overhead is material on the owner workstation, or if a backend requires application-specific coupling that would weaken provider replaceability.

## Research references

- OpenTelemetry Python status: https://opentelemetry.io/docs/languages/python/
- OpenTelemetry components and Collector: https://opentelemetry.io/docs/concepts/components/
- OpenTelemetry overview/vendor neutrality: https://opentelemetry.io/docs/what-is-opentelemetry/
- structlog documentation: https://www.structlog.org/
- SigNoz overview: https://signoz.io/docs/what-is-signoz/
