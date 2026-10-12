# Capability Acquisition System Acceptance Implementation Plan

**Goal:** Prove the production capability-acquisition lifecycle before owner-machine acceptance.

**Architecture:** Keep the original D8 lineage and approval digests intact. Exercise production stores, contracts, governed development tools, candidate verification, promotion, registry activation and goal continuation with controlled external boundaries. Never count a simulated physical effect or CI response as live acceptance.

**Tech Stack:** Python, pytest, Hypothesis, SQLite, Git, DBOS, Docker sandbox.

**Spec:** User instruction: complete acquisition testing as one system; only final owner-machine acceptance should remain.

## Global Constraints

- No canonical database reset or fabricated production approvals.
- Preserve legacy ticket digests and fail-closed path/tool authorization.
- No arbitrary local-device sandbox aliases or permission widening.
- Report blocked and untested boundaries explicitly.

## Review Focus

- Unknown model-generated sandbox profiles must fail before approval/development.
- Explicit executable targets must override prose and survive durable serialization.
- Legacy tickets must retain exact digest and authorization semantics.
- Stale artifacts, duplicate actions and interrupted workflows must remain recoverable.
- Activation must lead to original-goal continuation and subsequent reuse.

## Task 1: Baseline and traceability

- [x] Map acquisition production stages and existing integration test substitutes.
- [x] Install pinned dependencies and run the acquisition/development baseline.
- [x] Record Docker, Windows, cloud engineering and GitHub execution availability.

## Task 2: Registered sandbox contracts

Files: acquisition/workflow.py, acquisition/architecture.py, related tests.

- [x] Reproduce unknown profile reaching architecture using production plan derivation.
- [x] Expose registered IDs to research; reject unknown profile IDs before finalization and architecture readiness.
- [x] Verify valid IDs preserve exact profile digests and unknown IDs do not acquire permissions.

## Task 3: Typed test-target contract

Files: development_engine/contracts.py, phase9.py, tools.py, related tests.

- [x] Add failing tests for typed targets, digest binding, target tampering, legacy round trips and explicit empty targets.
- [x] Carry optional typed verification_targets through ticket creation and persistence; preserve absent-field legacy payloads.
- [x] Keep exact target authorization and relative non-option target validation.
- [x] Run development engine and candidate-verification regressions.

## Task 4: Vertical acquisition and faults

- [x] Exercise real candidate creation and actual pytest results, then independent candidate verification.
- [x] Connect promotion, admission, activation, external acceptance, goal continuation and reuse; identify every controlled external boundary.
- [x] Run restart, retry, stale-approval, malformed-output, concurrency and failure tests.
- [x] Generate reproducible stage evidence tied to Git revision and environment.

## Task 5: Completion gate

- [ ] Run full pytest: blocked by automatic approval review; Ruff passes.
- [x] Obtain independent review and fix substantive findings.
- [ ] Mark pre-machine PASS: full suite, real Docker, live external boundaries and Windows acceptance still outstanding.

## Execution ledger

- Base: fc2c4f14c088df69a321bb5635347a057bb11d5b; clean clone, branch fix/capability-acquisition-system-acceptance.
- Ruling: execute inline without another confirmation, as user explicitly instructed continuous completion.
- Confirmed: default registry has test/diagnostic/dependency profiles, no local_device_control. Research finalization accepts unconstrained profile IDs.
- Confirmed: Phase9 factory converts verification_targets to pytest-prefixed acceptance text; tool port reads that text.
- Baseline setup initially lacked pytest, rfc8785, hypothesis and psutil; installing project-pinned dependencies.
- Docker executable absent. Windows physical runtime is external.

- Pinned Python 3.11.17 environment installed successfully; Python 3.12 cannot satisfy pinned tflite-runtime.
- Three regression-proven fixes: typed digest-bound executable test targets, registered sandbox validation before approval, and verifier resource lease key artifact.
- Acquisition/development/substrate/registry/GICC regressions: 612 tests, 610 passed, two Windows DPAPI skips; 241.024 seconds.
- Additional Phase 7/8 and continuation regressions: 48 passed; 3.002 seconds.
- Connected normal and actual-pytest-failure recovery scenarios pass. Unknown-profile finalization has no persisted plan/architecture side effect. Actual coordinator replanning and original-goal execution pass with controlled model output.
- Independent review found an evidence gap in fixture replanning; replaced manual plan persistence with production coordinator/planner/runtime continuation. Controlled model output remains declared.
- Required Docker CI job prepared and connected to promotion-policy; not run here (Docker unavailable), not triggered remotely.
- Full suite was interrupted near 97% by automatic approval review detecting outbound Microsoft telemetry; no final JUnit result, no full-suite PASS claimed. Endpoint/test not established. Do not rerun or trigger equivalent CI without resolving the disclosure block.
- Runtime fixtures use disposable stores only. Original D8 owner-machine database and approval lineage were not modified.
