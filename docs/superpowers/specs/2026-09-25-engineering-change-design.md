# Phase 3 EngineeringChange Design

Status: owner-approved architecture direction, 2026-09-25. Implementation is on an isolated branch.

## Intent and limits

One owner goal or incident owns several restart-safe WorkItems and one reviewable engineering lifecycle. The owner supplies architecture decisions, secrets or physical inputs, acceptance, and promotion decisions when required. JARVIS handles bounded preparation while existing Authority, WorkItem, sandbox, CI and protected-main rules remain authoritative. Phase 3 records promotion readiness and decisions but does not merge, deploy, provision secrets, or implement autonomous source repair.

The first executable process uses the existing RESEARCH and DEVELOPMENT actions. Future diagnostic, capability and other process families are registered and versioned rather than selected from a permanent enum. Unsupported process versions block execution. A process definition cannot remove the mandatory architecture-before-build, verified-before-promotion, and owner-approval gates.

## Ownership and persistence

The protected local SQLite WorkStore holds change identity, process key/version, state/version, immutable artifact revisions/digests, stage attempts, WorkItem bindings, gate decisions, and append-only event records. It uses the existing WorkPayloadCodec for sensitive text and bounded, checksum-verified additive migrations. Foreign keys link stages to actual WorkItems. Production DBOS continues on its accepted Postgres system database and executes only canonical WorkItems.

EngineeringKnowledge and incidents retain their accepted engineering store; changes hold validated stable references and canonical digests. Cross-store links are not assumed to be atomically committed. A reconciler detects missing or stale references and blocks the affected stage.

## Process and state

Core states: PROPOSED, RESEARCHING, ARCHITECTURE_READY, WAITING_OWNER_APPROVAL, APPROVED_FOR_BUILD, DEVELOPING, VERIFYING, WAITING_OWNER_ACCEPTANCE, READY_FOR_PROMOTION, WAITING_PROMOTION_APPROVAL, PROMOTED, OBSERVING, CLOSED. Additional BLOCKED_EXTERNAL is resumable; REJECTED, FAILED, SUPERSEDED and ROLLED_BACK end the current attempt. Accepted process handlers specify registered stage keys, stage requirements, and allowed transitions. The core validates cross-cutting safety gates independently of the handler.

Each stage attempt binds an immutable plan revision and at most one canonical WorkItem per deterministic attempt key. Multiple ready stages may run concurrently within existing WorkItem resource limits. A failed WorkItem stays terminal; any retry is a new linked attempt. Progress uses actual stage and WorkItem state, labels estimates as approximate, and never turns a model assertion into verification.

## Artifact and decision integrity

Architecture, verification and acceptance bundles are immutable typed artifacts with RFC-8785 canonical SHA-256 digests. Gate decisions bind change ID, gate type, artifact revision/digest, owner actor, trusted interaction reference, decision, time and unique request key. Only trusted owner-facing application code creates a decision from the canonical owner interaction; arbitrary model text, WorkItem owner-input replies and EngineeringKnowledge cannot approve a gate. Duplicate identical requests return the recorded decision; a changed request key or digest fails closed. Superseding an artifact invalidates downstream decisions and pauses/cancels unstarted dependent work. An already-running isolated action must recheck gate eligibility before its next protected step.

Change-level approval evidence is not an Authority permit. Protected actions continue through normal Authority evaluation and revalidation. Promotion remains blocked until an explicit accepted promotion decision and the separately governed promotion phase; recording a decision does not itself merge or deploy.

## Scheduling and recovery

The coordinator is a reconciliation service, not a new scheduler. It atomically creates a stage attempt, its WorkItem and link in one WorkStore transaction, then submits that WorkItem to the existing DBOS backend using its work ID. WorkItem completion, trusted gate decisions, and startup invoke the same idempotent reconcile function. On startup it first validates change schema and gate digests, then reconciles unsubmitted active WorkItems. Crash after local commit but before DBOS submission retries the submission. Crash after DBOS submission repeats the same work ID. Failure after a WorkItem finishes but before change advancement is repaired from canonical state.

When a WorkStep has an unknowable side effect after a crash, retain the existing INTERRUPTED / WAITING_FOR_OWNER behavior. Never replay a protected step simply to satisfy the change lifecycle. A malformed, unknown or unavailable process handler blocks the change without creating WorkItems.

Owner prompts use the existing WorkDelivery channel with event keys derived from change, gate and artifact digest; the completing stage's WorkItem supplies the delivery owner. Do not invent a second delivery queue. Approval responses must identify the intended gate unambiguously.

## Verification and acceptance

Unit tests cover lifecycle transition and cross-process invariants, process-version failure, exact artifact binding, rejection, owner interaction provenance, stage dependencies, concurrent changes, idempotent submission and reconciliation, stale or changed evidence, and no duplicate deliveries. Fault injection covers crashes before/after local transaction, DBOS submission, WorkItem terminal transition, decision persistence, and downstream stage admission. Existing R2 and EngineeringKnowledge tests must remain green. Owner-machine acceptance exercises actual Postgres DBOS, restarts, voice/owner gate delivery, isolated development, and fail-closed gates. Documentation and CI complete before the phase is called accepted.
