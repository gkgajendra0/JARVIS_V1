# Capability acquisition validation — 2026-10-09

## Current checkpoint

Source branch: `fix/capability-acquisition-system-acceptance`, draft [PR #253](https://github.com/gkgajendra0/JARVIS_V1/pull/253), stacked on #252.

**Pre-machine PASS.** Final tested source: `a8b543f8ae54a936953bc713d6511ee1de32321c` (tree `faf982ea6e5c3e21bb1e83c8b34a647e639d58df`). All six required jobs passed in [run 37898831210](https://github.com/gkgajendra0/JARVIS_V1/actions/runs/37898831210): Ruff, full Linux pytest, required Docker acquisition, Windows Hello, Windows DPAPI/acquisition, and promotion-policy. Only live owner-machine acceptance remains.

## Repairs

1. Development tickets carry digest-bound typed executable verification targets. Legacy tickets without the field retain their canonical payload/digest. Explicit empty targets do not fall back to prose, and expanded pytest scope is rejected.
2. Unknown sandbox profile IDs are rejected before plan/architecture persistence. Research advertises exact registered IDs. No local-device permission alias was introduced.
3. Substrate verification uses the registered `artifact` resource lease instead of nonexistent `artifact_store`.
4. Architecture and research finalization reject prose, traversal, pytest options and empty selectors before plan persistence. The shared target normalizer preserves existing valid ticket canonicalization and legacy digests. Four new architecture regressions and connected persistence checks reproduced the issue before the fix.

## Verified evidence

- Full hosted Linux suite: **3,016 passed, six Windows-only skips, zero failures** (3,022 outcomes in the latest completed job logs). The skipped cases cover Windows DPAPI and real Windows Job Objects; these receive separate Windows CI validation.
- Required real-Docker connected acquisition: **three tests passed** — normal acquisition, actual failing candidate-test recovery, and the registered resource-capacity regression. `JARVIS_E2E_REQUIRE_DOCKER=1` was set; absence of Docker cannot silently skip or select the fixture runner.
- Windows Hello helper, Windows DPAPI/Hands, Phase 6–9 regressions/adversarial acquisition, Ruff, and promotion-policy: **passed** on the final source revision. The Windows adversarial/connected acquisition batch passed all 89 tests, including normal acquisition and candidate-test-failure recovery.
- Earlier related suites: 658 passed, two Windows DPAPI skips. Latest focused reruns: 48 target/acquisition tests and 31 workflow/verifier/coordinator/cold-import regressions passed. Ruff formatting and lint passed.
- Connected tests execute actual candidate pytest, real Git commits/worktrees and SQLite stores, digest-bound approval handling, independent candidate verification, promotion policy, release staging, package admission/activation, runtime readback, production original-goal continuation/replanning/completion, and reuse. Unknown-profile finalization has no persisted plan, architecture or change mutation.
- Fresh independent reviews completed. The initial manually persisted fixture plan was replaced by production coordinator/planner/runtime continuation. Controlled planner/model output remains declared.

## Telemetry containment and local harness results

Automatic approval review interrupted the initial broad local run after flagging possible metadata disclosure to a Microsoft telemetry endpoint. That unrestricted run was not retried or indirectly triggered. Linux hosted tests now run in an isolated network namespace with loopback enabled and no Internet route; .NET/PowerShell telemetry optouts are also preserved. The production Docker test profile uses `--network none`. Dependency installation and image construction occur before isolation.

A stricter temporary local syscall-denial harness completed all 3,018 cases with five environment/harness failures: one intentional loopback connection denial, two multiprocessing imports affected by the temporary launcher, and two SDK constructors requiring the environment's SOCKS proxy dependency. The launcher and local dependency were corrected; the two cold-import cases and SDK extractor suite passed (11 tests), and the loopback suite passed separately (33 tests). The affected tests were `test_dev_control_client_answers_authenticated_liveness_probe`, `test_engineering_knowledge_acceptance_cold_import_has_no_cycle`, `test_engineering_knowledge_package_cold_import_has_no_cycle`, `test_pinned_openai_client_exposes_production_parse_surface`, and `test_pinned_gemini_client_exposes_production_and_bakeoff_surfaces`. None of these required a production code change. The clean hosted full-suite result is the authoritative broad validation.

Hosted evidence artifacts:

- [Full-suite JUnit](https://github.com/gkgajendra0/JARVIS_V1/actions/runs/37898831210/artifacts/11601234780), SHA-256 `c993a47011f9f7d59e23eb18e83273c0101ff8382d6ce7b00cbf202282a8fb10`.
- [Real-Docker JUnit and stage JSON](https://github.com/gkgajendra0/JARVIS_V1/actions/runs/37898831210/artifacts/11601448595), SHA-256 `4da6f835acee4e1b96ecabf16b0b728b1516466e743a7b342227416124bf80db`.

- [Windows acquisition JUnit and stage JSON](https://github.com/gkgajendra0/JARVIS_V1/actions/runs/37898831210/artifacts/11602770357), SHA-256 `dd2a3abedda4e58726f0824dd658b655771a02be9ebde3abc1a102c9f9d3c6ef`.

The adjacent `vertical-evidence.json` files describe earlier disposable local fixture runs, not the hosted Docker run or production owner approvals. The connector exposed artifact download references, but direct local retrieval returned HTTP 403; the hosted artifacts remain available through GitHub.

## Final owner-machine acceptance

The remaining live checks require the owner environment: existing ChatGPT-plan/Codex connection, actual owner authentication/approval, real GitHub promotion, runtime process restart, external device/resource readback, durable original-goal completion and reuse after restart. These boundaries are controlled fixtures in hosted tests and are not claimed as live acceptance.

The original D8 owner database and approval lineage are untouched. Updating code does not rewrite its approved architecture, pinned source revision or permission scopes. An invalid old profile requires supported architecture revision and fresh exact owner approval. See `MACHINE_ACCEPTANCE.md`; do not reset stores, invent approvals, or start a replacement goal to hide a stalled lineage.

No test suite guarantees all future model-generated implementations or physical devices will work.
