# Phase 3 EngineeringChange Owner-Machine Acceptance

Status: **PENDING**. Run this procedure on the tested PR head after CI passes and before merging into protected main. Phase 3 is not accepted from CI alone.

## Prerequisites

- Run from the owner Windows profile that holds the existing WorkStore DPAPI key.
- Use an isolated Git worktree at the exact green PR head. Record that commit SHA and preserve the protected-main checkout. The acceptance evidence must identify this same tested commit.
- Confirm Windows Hello verification is configured for the owner, the normal supervised JARVIS voice runtime is healthy, and DBOS uses the accepted production PostgreSQL configuration. Do not point this run at a throwaway SQLite DBOS backend.
- Owner-machine acceptance must use **production-fidelity dependencies**. Reuse the already accepted protected-main JARVIS virtual environment as a read-only dependency/runtime substrate, while loading JARVIS source from the isolated Phase-3 worktree through a process-local `PYTHONPATH` overlay. Do **not** install, uninstall, upgrade, downgrade, or editable-install packages in the protected-main virtual environment during acceptance.
- A fresh acceptance virtual environment is not required for this live gate. Clean-environment/bootstrap reproducibility is a separate engineering concern and must not be mixed into Phase-3 functional acceptance.
- Before starting the acceptance runtime, verify that `jarvis.__file__` resolves inside the isolated Phase-3 worktree while `sys.executable` resolves to the protected-main virtual environment. Also verify the protected-main CUDA/RF-DETR stack remains healthy.
- Do not place secrets, access tokens or production credentials in an architecture proposal or evidence transcript.

From the protected-main checkout, create or update a separate branch worktree at the PR head:

```powershell
cd C:\Users\gkgaj\Desktop\jarvis_v1
git fetch origin refs/pull/108/head

# First creation only:
# git worktree add -b phase3_acceptance ..\jarvis_phase3_acceptance FETCH_HEAD

cd ..\jarvis_phase3_acceptance
git reset --hard FETCH_HEAD
git rev-parse HEAD
```

For the live acceptance process, use the existing production virtual environment without modifying it:

```powershell
$mainPython = "C:\Users\gkgaj\Desktop\jarvis_v1\.venv\Scripts\python.exe"
$acceptanceRoot = "C:\Users\gkgaj\Desktop\jarvis_phase3_acceptance"
$previousPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = "$acceptanceRoot\src"

Set-Location $acceptanceRoot

& $mainPython -c "import sys,jarvis,torch; print('python=',sys.executable); print('jarvis=',jarvis.__file__); print('torch=',torch.__version__); print('cuda=',torch.version.cuda); print('cuda_available=',torch.cuda.is_available()); print('gpu=',torch.cuda.get_device_name(0) if torch.cuda.is_available() else None)"

& $mainPython -c "from jarvis.vision.detector import RFDetrNanoDetector; RFDetrNanoDetector(); print('RF-DETR production dependency check: OK')"
```

Fail closed if the Python executable is not the protected-main virtual environment, if `jarvis.__file__` does not resolve under `jarvis_phase3_acceptance\src`, if CUDA is unavailable for the accepted GPU vision stack, or if RF-DETR initialization fails.

Stop the normal owner-machine supervisor cleanly before testing the worktree. Then start the Phase-3 source through the production dependency environment:

```powershell
& $mainPython -m jarvis.runtime_supervisor --branch phase3_acceptance
```

The production supervisor's local-only mode keeps Git update polling disabled and retains the configured PostgreSQL DBOS backend. Do not start two JARVIS voice runtimes against the same microphone and WorkStore concurrently. After the acceptance run, stop the test supervisor, restore `PYTHONPATH` to `$previousPythonPath`, and resume the ordinary main runtime.

## Live sequence

1. Give JARVIS one bounded engineering goal and start it through `start_engineering_change`. Record the returned `change_id` and research `work_id`. Confirm a second call grounded in the same accepted USER turn returns the same change and research WorkItem.
2. Let research finish. Submit the architecture for owner review and verify that the existing WorkDelivery channel presents the precise proposal, revision, SHA-256 digest and gate ID. Verify development has **not** started.
3. Say an unrelated “yes” and confirm it cannot approve the gate. Say `approve architecture` if there is exactly one pending review, or `approve gate_<ID>` using the exact gate ID when there are several. Complete the digest-bound Windows Hello prompt. Verify cancellation/unavailability fails closed. A successful verification records one decision for the exact revision; development starts in an isolated worktree only afterward.
4. With a separate disposable change, call `revise_change_architecture` with a materially changed proposal after the first architecture has been approved. Confirm the old WorkItem pauses before its next action; approving the revised gate creates a new development attempt with a distinct WorkItem ID. Retry the same revision once before approval and confirm it returns the same gate/revision instead of creating a duplicate. No older completed attempt may be counted as verification for the new plan.
5. For the main change, let development complete its normal isolated commit and sandbox test sequence. Confirm the acceptance gate is offered only when the canonical WorkItem result contains a verified commit and branch. A generic “yes” cannot approve. Explicitly review and decide the acceptance gate with Windows Hello. Then call `prepare_change_promotion`, confirm a generic “yes” still cannot approve it, and explicitly approve the promotion gate with Windows Hello. The resulting state must remain `WAITING_PROMOTION_APPROVAL`: this records owner promotion intent only; no push, protected-main merge, deployment, or `PROMOTED` state may occur.
6. Restart the normal supervised runtime while a separate disposable change has a research or owner gate pending. Confirm the same canonical change, WorkItems, gate digest and delivery resume without duplicate submissions or decisions. Inspect the production PostgreSQL DBOS workflow by canonical WorkItem ID and confirm it resumes under the same identity.
7. Run the evidence inspection from the same owner Windows profile:

   ```powershell
   & $mainPython -m jarvis.engineering_change.acceptance --change-id CHANGE_ID
   ```

   The JSON evidence is written under `%LOCALAPPDATA%\JARVIS\operations\acceptance\`. It contains only IDs, states, digests, and summarized gate outcomes. Attach the file and the observed PostgreSQL/restart, voice-delivery, and isolated development results for review.

## Result interpretation

All `store_gates` must be PASS for the main change, and `tested_commit` must equal the green PR head. The evidence command deliberately marks production PostgreSQL/restart, live voice gate delivery and isolated development review as PENDING: those need real owner-machine observation. Any FAIL or missing external proof blocks acceptance. The owner and reviewer then record the actual run, tested PR head, evidence location and final disposition in a dated Phase-3 acceptance record before merging.

R2 Self-Repair and Phase-2 EngineeringKnowledge retain their accepted independent baselines; this procedure does not repeat the Phase-2 live crash injection.
