# Phase 4 Model Router Owner-Machine Acceptance

Status: **READY AFTER PR #118 EXACT-HEAD CI IS GREEN**.

This is the final live gate for Phase 4. It verifies real routed background reasoning, durable route provenance, bounded target-aware fallback and health behavior, restart continuity, and no Authority or security regression.

## Prerequisites

- Run from the owner Windows profile that holds the existing WorkStore DPAPI key.
- Use an isolated Git worktree at the exact green PR #118 head. Do not test from protected main.
- Reuse the accepted protected-main virtual environment as a read-only dependency and runtime substrate while loading Phase-4 source through a process-local PYTHONPATH.
- Do not install, uninstall, upgrade, downgrade, or editable-install packages in the protected-main virtual environment during acceptance.
- Use the accepted PostgreSQL DBOS backend. Do not switch the live acceptance run to a disposable DBOS backend.
- Stop the normal JARVIS supervisor before starting the acceptance supervisor. Never run two voice or work runtimes against the same microphone, WorkStore, or DBOS queue at the same time.
- At least one approved routing target must have a valid credential. A live cross-provider fallback requires both approved targets to be available. If only one target is configured, record that limitation rather than weakening policy.
- Do not manufacture a fallback by corrupting credentials, causing a content or policy rejection, or changing Authority. A natural provider-pressure event is acceptable. Otherwise use the exact-head deterministic fallback and health test below and record that live provider failure was not forced.

## Prepare the exact PR head

From the protected-main checkout:

    cd C:\Users\gkgaj\Desktop\jarvis_v1
    git fetch origin refs/pull/118/head

    # First creation only:
    # git worktree add -b phase4_acceptance ..\jarvis_phase4_acceptance FETCH_HEAD

    cd ..\jarvis_phase4_acceptance
    git reset --hard FETCH_HEAD
    git rev-parse HEAD

Record the SHA. It must match the final green PR #118 head used for acceptance.

Use the protected-main Python environment without modifying it:

    $mainPython = "C:\Users\gkgaj\Desktop\jarvis_v1\.venv\Scripts\python.exe"
    $acceptanceRoot = "C:\Users\gkgaj\Desktop\jarvis_phase4_acceptance"
    $previousPythonPath = $env:PYTHONPATH
    $env:PYTHONPATH = "$acceptanceRoot\src"

    Set-Location $acceptanceRoot

    & $mainPython -c "import sys,jarvis; print('python=',sys.executable); print('jarvis=',jarvis.__file__)"

Fail closed if sys.executable is not the protected-main virtual environment or jarvis.__file__ does not resolve under jarvis_phase4_acceptance\src.

Before the live run, execute the exact routing regression surface:

    & $mainPython -m pytest -q tests/test_model_routing_models.py tests/test_model_routing_registry.py tests/test_model_routing_eligibility.py tests/test_model_routing_health.py tests/test_model_routing_store.py tests/test_model_routing_strategy.py tests/test_routed_work_reasoner.py tests/test_model_routing_fallback.py tests/test_model_routing_status.py tests/test_model_routing_evaluation.py tests/test_model_routing_acceptance.py

All must pass before the live sequence.

## Start the acceptance runtime

Stop the normal supervisor cleanly, then launch the exact Phase-4 source through the production dependency environment:

    & $mainPython -m jarvis.runtime_supervisor --branch phase4_acceptance

The acceptance runtime must use the existing WorkStore and accepted DBOS PostgreSQL configuration.

## Live sequence

1. Give JARVIS one bounded background engineering or research request that is safe to run and does not require protected-main promotion. Record the canonical work_id. If the task is part of an EngineeringChange, also record the change_id.

2. Allow at least one real background reasoning cycle to execute. Confirm the WorkItem is not replaced. The model router must persist a routing decision before provider invocation.

3. Run the Phase-4 evidence inspector against that canonical WorkItem:

       & $mainPython -m jarvis.model_routing.acceptance --work-id WORK_ID

   The generated JSON is written under %LOCALAPPDATA%\JARVIS\operations\acceptance\.

   Expected store gates are all PASS. The evidence must show:
   - engineering_stage.v1;
   - strategy, registry, and policy digests;
   - selected role or target and reason codes;
   - at least one routing attempt;
   - the same canonical work_id;
   - bounded attempt lineage;
   - target health and fallback path;
   - no prompt text, credential material, API keys, or correlation keys.

4. Inspect the same WorkItem again after another bounded reasoning cycle. Routing decisions may change only when the canonical reasoning-cycle key changes. The WorkItem identity must remain unchanged.

5. Demonstrate target-health and fallback behavior using the safest available method:
   - Preferred: if natural rate-limit, quota, or service pressure occurs on the selected target, confirm the target becomes degraded or cooldown and another already-approved eligible target is used within the configured fallback budget.
   - If no natural provider pressure occurs: do not damage credentials or trigger policy rejection. Run:

         & $mainPython -m pytest -q tests/test_model_routing_fallback.py tests/test_model_routing_health.py

     Record that the live provider-failure path was not artificially forced. This is an allowed equivalent target-health test and does not weaken routing policy.

6. Restart continuity:
   - while the bounded WorkItem is active or waiting on a routed resource, stop the Phase-4 supervisor cleanly;
   - start the same acceptance supervisor again;
   - confirm the same canonical WorkItem resumes;
   - rerun the evidence inspector;
   - confirm no duplicate WorkItem and no duplicate routing decision for the same routing-request ID;
   - if a fallback lineage already existed, confirm its persisted attempt ordinals and path remain coherent.

7. Authority and security regression:
   - confirm no Phase-4 step bypassed owner approval, Windows Hello, sandboxing, EngineeringChange gates, protected-main governance, or credential controls;
   - if an owner gate naturally appears during the acceptance task, a generic unrelated "yes" must still not approve it and the existing explicit digest-bound verification path must remain unchanged;
   - do not create a new privileged action merely to exercise Authority.

8. Run the final evidence inspector again using the exact canonical WorkItem:

       & $mainPython -m jarvis.model_routing.acceptance --work-id WORK_ID

   Attach the JSON evidence plus the observed restart result and fallback or health result for review.

## Cleanup

Stop the acceptance supervisor, restore the previous Python path, then resume the ordinary main runtime:

    if ($null -eq $previousPythonPath) {
        Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    } else {
        $env:PYTHONPATH = $previousPythonPath
    }

    Set-Location C:\Users\gkgaj\Desktop\jarvis_v1

Do not merge PR #118 merely because automated CI is green. Phase 4 is complete only after the live evidence is reviewed and the final acceptance disposition is recorded in the project documentation.

## Acceptance interpretation

A successful owner-machine run must demonstrate:

- a real routed background reasoning decision;
- visible bounded route provenance;
- one safe provider-pressure or fallback event, or the approved equivalent target-health regression when live failure is not practical;
- one canonical WorkItem identity across routing and fallback;
- durable route lineage across runtime restart;
- no provider hopping for content or policy rejection;
- no Authority, security, sandbox, or protected-main regression;
- no new paid routing proxy or service requirement.

If the live provider environment prevents a requested test from occurring, record the external limitation explicitly. Do not weaken eligibility, privacy, Authority, verification, or provider-policy controls to force a green acceptance result.
