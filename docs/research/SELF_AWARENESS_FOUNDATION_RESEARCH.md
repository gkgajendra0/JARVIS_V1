# JARVIS Self-Awareness Foundation — Research and Implementation Baseline

## Scope

This record supports an owner-approved implementation interlude for the prerequisites of later health/diagnostics, learning, self-repair and self-improvement. It does **not** authorize autonomous code mutation and does not mark future roadmap slices complete.

The problem is operational self-knowledge: JARVIS must be able to answer, with evidence, what components it has, what they implement, what depends on what, what is healthy/degraded/failed, what changed, what evidence supports the state, and which prior incidents/fixes are relevant.

## Existing production assets reused

The current codebase already contains strong reusable foundations:

- startup preflight with fail-fast hardware/provider/authority checks;
- provider-neutral capability discovery/runtime and explicit availability states;
- deterministic authority, approvals, one-time permits and privacy-aware audit;
- runtime CPU/RAM/thread/GPU profiling plus Git revision metadata;
- provider failure classification/recovery;
- Hands postcondition/result verification;
- protected-main workflow and `jarvis-dev` readiness/rollback support;
- repository tests, Windows CI and hardware acceptance gates.

The missing piece is primarily a common evidence model and operational dependency/health view, not a new unrestricted agent.

## Technology research

### OpenTelemetry

OpenTelemetry is vendor-neutral and is designed to instrument, generate, collect and export traces, metrics and logs. The Collector can receive, process/filter and export telemetry independently from the application backend. This fits JARVIS's provider-replaceability rule.

OpenTelemetry Python currently reports **Stable traces**, **Stable metrics**, and **Development logs**. The first implementation therefore adopts the stable trace/metric SDK surface while avoiding a hard dependency on the Python Logs SDK as the only logging truth.

Decision: **ADOPT** OpenTelemetry API/SDK + OTLP as the telemetry contract; keep export disabled by default until owner-machine acceptance.

Primary references:
- https://opentelemetry.io/docs/languages/python/
- https://opentelemetry.io/docs/concepts/components/
- https://opentelemetry.io/docs/what-is-opentelemetry/

### structlog

JARVIS needs structured events without losing useful console output or compatibility with existing Python logging. `structlog` provides processors, context handling and stdlib integration, while allowing JARVIS to run redaction before persistence.

Decision: **ADOPT** for operational structured logging above the existing Python logging call sites.

Reference: https://www.structlog.org/

### Telemetry backend

SigNoz is an OpenTelemetry-native open-source observability backend for logs, metrics, traces and exceptions. It is a strong initial visualization/query candidate while leaving the application instrumented with vendor-neutral OpenTelemetry.

Decision: **PRIMARY CANDIDATE, DEFER DEPLOYMENT**. Do not make SigNoz canonical Self Model truth and do not install it automatically on the owner workstation until resource and retention behavior are accepted.

Reference: https://signoz.io/docs/what-is-signoz/

### Code intelligence and repair agents

The broader architecture research found mature code/engineering-agent capabilities that should be evaluated later instead of building an unrestricted coding loop. The planned sequence is deterministic evidence first, then a read-only diagnostic agent, then an isolated coding-agent bake-off and only later governed repair.

This implementation interlude intentionally stops before those agents gain write authority.

## Implementation contracts

### Canonical identifiers

Operational evidence should be correlatable through explicit IDs such as session, turn, goal, capability, component, authority proposal and incident IDs. Trace/span IDs are transport/observability correlation, not product authority.

### Static Self Model

A component descriptor may identify:

- component ID and purpose;
- source paths/code symbols;
- product capabilities and runtime capability keys;
- dependencies and optional fallbacks;
- configuration/resource dependencies;
- relevant tests/docs;
- expected health probes and freshness expectations.

The Self Model is version-controlled so its code/dependency statements evolve through the same reviewed Git workflow as the software.

### Dynamic health

Health is derived only from evidence with a source, reason, timestamp and TTL. Stale evidence becomes `UNKNOWN`. Dependency health propagation is deterministic using explicit `BLOCKING`, `DEGRADING` or `OPTIONAL` criticality.

Canonical states for the foundation are:

`UNKNOWN`, `STARTING`, `HEALTHY`, `DEGRADED`, `FAILED`, `RECOVERING`, `DISABLED`.

### Logs, traces and metrics

Use the correct signal for the job:

- **metrics** — high-frequency numerical state and resource/load trends;
- **traces** — bounded operations and causal execution paths;
- **structured events/logs** — meaningful state transitions, failures and diagnostic context.

Do not interpret “log everything” as storing every audio/video frame or unrestricted prompt/provider payload.

### Privacy

Redaction is layered and deny-by-default for common secret/credential keys. Normal operational logs exclude raw audio/video, biometric crops, screenshots, provider payloads and prompt/completion content unless a separately approved diagnostic workflow has a concrete need and retention boundary.

### Incident memory

Operational incident memory is separate from personal memory and authority audit. It stores compact engineering facts: symptoms, affected components, evidence references, confirmed root cause, accepted fix, regression tests, commit/PR and deployment/rollback outcome.

## First implementation slice

The branch `feature/self-awareness-foundation` implements the smallest useful foundation:

1. component/dependency Self Model contracts;
2. deterministic Health Registry with TTL and dependency roll-up;
3. correlation context and privacy redaction;
4. structured rotating JSONL operational logging while preserving console logging;
5. OpenTelemetry trace/metric adapter with network export disabled by default;
6. separate SQLite incident/engineering-memory lifecycle;
7. automated contract tests;
8. ADR/documentation describing the safety boundary.

## Explicit non-scope

- no autonomous root-cause claims;
- no coding agent execution;
- no automatic repair;
- no self-modification authority;
- no automatic protected-main merge;
- no background telemetry upload by default;
- no claim that Steps 13, 18, 19 or 20 are complete.

## Next evidence after CI

After repository CI is green, real owner-machine acceptance should measure log correctness/redaction, CPU/RAM/disk overhead, startup/runtime behavior, and non-regression of voice, Hands, Pocket 3 and provider workflows. Collector/backend deployment should happen only after that local evidence is satisfactory.
