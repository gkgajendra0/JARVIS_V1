# Capability acquisition validation — 2026-10-09

Status: **partial validation; complete pre-machine acceptance is not established.**

Validated on Python 3.11.17 against base fc2c4f14c088df69a321bb5635347a057bb11d5b, branch fix/capability-acquisition-system-acceptance.

## Repairs

1. Development tickets carry digest-bound typed executable verification targets. Legacy tickets without the field retain their exact canonical payload and digest. Explicit empty targets do not fall back to prose.
2. Research exposes registered sandbox profiles; unknown IDs are rejected before a plan or architecture can be persisted. No local-device permission alias was introduced.
3. Substrate verification requests the registered `artifact` resource lease instead of nonexistent `artifact_store`.

## Evidence

- Related acquisition, development, substrate, registry and GICC suite: 610 passed, two Windows-only DPAPI skips, zero failures/errors (612 total).
- Additional promotion/deployment/continuation suite: 48 passed, zero failures/errors.
- Connected normal and failing-candidate-test recovery scenarios pass, plus registered-resource regression.
- Real candidate pytest, Git commits/worktrees, SQLite stores, digest-bound approvals, independent candidate verification, promotion policy, package admission/lifecycle activation, runtime operation and readback, production goal continuation/replanning and verified goal completion, then reuse are exercised.
- Unknown sandbox finalization is rejected without persisted acquisition plan, architecture or change mutation. Expanded pytest scope and commit after failing tests are rejected.
- Final focused rerun after the continuation changes: 44 passed, zero failures/errors.
- Ruff checks and formatting pass.
- Fresh independent review completed; the original fixture-plan evidence gap was corrected to invoke production coordinator/planner/runtime. Model output remains controlled.

The accompanying JSON files record disposable test lineage, artifact digests and controlled boundaries. They are test evidence, not owner-machine production approvals.

## Remaining gates

- **Full repository pytest: BLOCKED.** Automatic approval review stopped the run near 97% after detecting an outbound request to an untrusted Microsoft telemetry endpoint, citing possible disclosure of sensitive test/environment/failure metadata. No final report exists. The responsible endpoint/test has not been established. It was not retried or indirectly triggered through CI.
- **Real Docker: NOT RUN.** No Docker executable/daemon is available here. A required `acquisition-docker` job is prepared and included in promotion-policy dependencies. It requires the production Docker runner and preserves evidence; missing Docker does not silently skip. Host and image install carry the existing LiveKit wheel workaround. No remote CI was triggered.
- **Live external boundaries: NOT PROVEN.** Research/model decisions, owner authentication, GitHub CI/merge, process switching and external effect use declared controlled fixtures. Live cloud engineering and remote promotion require independent acceptance.
- **Windows/physical owner acceptance: NOT RUN.** Two DPAPI tests are skipped on Linux. The original D8 database and approval lineage are untouched. Existing unknown-profile architecture requires legitimate revision and exact owner reapproval; no approval was forged or reset.

The connected test can require Docker using `JARVIS_E2E_REQUIRE_DOCKER=1` and `JARVIS_DEVELOPMENT_TEST_IMAGE=<built image>` when the remaining approval/environment blockers are resolved. Do not treat the current controlled-boundary pass as complete live-system acceptance.
