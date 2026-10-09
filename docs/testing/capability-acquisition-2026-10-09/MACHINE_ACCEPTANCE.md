# Owner-machine acceptance

Tested source commit: `a8b543f8ae54a936953bc713d6511ee1de32321c` on `fix/capability-acquisition-system-acceptance`, draft PR #253, stacked on #252. The original feature branch and owner D8 database have not been modified.

CI run: https://github.com/gkgajendra0/JARVIS_V1/actions/runs/37898831210

All six CI jobs passed on this exact source revision. Linux: 3,016 passed, six Windows-only skips, zero failures. Required real-Docker acquisition: three passed. Windows adversarial/connected acquisition: 89 passed. Pre-machine testing is complete; live owner-machine acceptance can begin.

## Update and read-only preflight

Shut down JARVIS normally. Open PowerShell in the actual existing JARVIS repository; do not create another owner goal, delete stores, or fabricate gate decisions.

```powershell
& {
    $ErrorActionPreference = 'Stop'
    if (-not (Test-Path '.git')) { throw 'Run this from the existing JARVIS repository.' }
    if (git status --porcelain) { throw 'Working tree is not clean. Preserve local changes.' }
    git fetch origin fix/capability-acquisition-system-acceptance
    if ($LASTEXITCODE -ne 0) { throw 'Fetch failed.' }
    git switch fix/capability-acquisition-system-acceptance
    if ($LASTEXITCODE -ne 0) { throw 'Switch failed.' }
    git pull --ff-only origin fix/capability-acquisition-system-acceptance
    if ($LASTEXITCODE -ne 0) { throw 'Update failed.' }
    $revision = (git rev-parse HEAD).Trim()
    if ($revision -ne 'a8b543f8ae54a936953bc713d6511ee1de32321c') {
        throw "Revision differs from the tested source: $revision"
    }
    if (-not (Test-Path '.venv\Scripts\python.exe')) { throw 'Owner Python environment is missing.' }
    & '.\.venv\Scripts\python.exe' tools/research/development_engine_owner_acceptance.py --preflight-only
    if ($LASTEXITCODE -ne 0) { throw 'Owner preflight failed. Preserve the JSON output.' }
}
```

This preflight does not consume an engineering inference turn. It checks the existing Git/Docker image/Codex/ChatGPT-plan prerequisites. Do not start the runtime if these checks fail.

## Final live acceptance

When using the development supervisor, select the tested branch in PowerShell:

```powershell
$env:JARVIS_DEV_BRANCH = 'fix/capability-acquisition-system-acceptance'
```

Use the established owner-machine startup command. Preserve the original goal, gap, change, work attempts and approval history.

1. Read the original D8 mission through the existing monitor or `gicc_phase9_live_status.py` using its actual identifiers.
2. Verify current architecture/admission/source-revision provenance before approving anything. Updating source files does not change an already approved architecture digest or its pinned development base. Any required revision must use the supported architecture/research flow and receive a fresh exact owner approval.
3. Confirm corrected research uses registered sandbox IDs and typed repository-relative pytest targets. `local_device_control` and `local_device_control.v1` remain invalid; no permission alias has been introduced.
4. Resume the original mission through the normal owner interface. Perform the actual requested approval/authentication gates. Do not bypass them or start a replacement mission to conceal a stalled lineage.
5. Observe live ChatGPT/Codex engineering, real governed Docker tests, candidate verification, actual CI/promotion, release restart, package admission and activation.
6. Verify the actual external effect/readback, then original-goal completion. Do not count activation alone as completion.
7. Reissue a compatible request and confirm reuse rather than another development change. Confirm durable capability readiness after a normal restart.

The hosted connected tests use controlled model decisions, owner authentication, GitHub promotion port, process switching and external effect. These final live checks are still required on the owner machine. Passing software tests does not guarantee every future model-generated implementation or physical device will work.
