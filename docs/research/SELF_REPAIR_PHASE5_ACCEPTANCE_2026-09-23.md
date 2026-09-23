# Self-Repair Phase 5 Acceptance — 2026-09-23

Related:
- issue #65
- ADR-019 Self-Repair Foundation
- PR #77 bounded runtime liveness watchdog
- PR #82 bounded direct control I/O and Git polling timeout
- PR #83 watchdog isolation from background update polling
- PR #84 Windows runtime process-tree fault injection
- PR #85 Windows runtime process-tree force cleanup

## Purpose

This is the final deterministic-foundation fault-injection gate before the
Self-Repair R1/R2 foundation is production-accepted on the owner machine.

The acceptance path does not authorize source mutation, protected-main writes,
Authority changes, model-selected effectors, or unregistered repair actions.

## Repository acceptance matrix

| ADR / issue property | Automated evidence |
| --- | --- |
| Unexpected child exit uses only the registered bounded R2 restart | `test_unexpected_exit_requires_stabilization_before_recovered` |
| Recovery requires explicit core-runtime readiness plus authenticated liveness stabilization | `test_wait_for_child_ready_requires_explicit_runtime_ready`, `test_dev_control_connects_before_audio_start_and_marks_ready_after_audio`, `test_stabilization_requires_repeated_liveness_probes`, and `test_stabilization_fails_when_authenticated_liveness_fails` |
| Repeated identical failure exhausts durable budget and stops | `test_restart_budget_survives_store_reopen_and_exhausts`, `test_readiness_failures_exhaust_restart_budget`, and `test_liveness_failures_consume_budget_and_stop_restarting` |
| Provider quota/degradation cannot authorize runtime restart | `test_phase5_provider_quota_has_no_registered_runtime_restart` |
| Changed local revision aborts the old repair plan | `test_phase5_revision_change_aborts_before_any_restart_attempt` |
| Incident persistence unavailable disables automatic repair | `test_phase5_incident_persistence_failure_disables_automatic_repair` |
| Runtime hang requires consecutive liveness failures plus confirmation | `test_liveness_watchdog_requires_threshold_and_confirmation` |
| A transient liveness miss does not restart JARVIS | `test_liveness_watchdog_ignores_transient_failure` and `test_liveness_watchdog_confirmation_can_cancel_restart` |
| Crash and liveness policies have independent restart budgets | `test_crash_and_liveness_restart_budgets_are_independent` |
| Existing owner-approved update rollback remains unchanged | `test_approved_update_rolls_back_when_new_revision_never_becomes_ready` |
| Fault injection cannot target an unrelated process | `test_select_supervised_runtime_refuses_unsupervised_process` and `test_select_supervised_runtime_refuses_ambiguous_targets` |
| Windows venv launcher + interpreter are faulted as one supervised runtime tree | `test_inject_fault_targets_only_supervised_runtime_tree` and `test_partial_hang_rolls_back_already_suspended_descendants` |
| Forced recovery cleanup removes surviving runtime descendants before the root wrapper | `test_force_runtime_tree_cleanup_targets_descendants_before_root` and `test_stop_jarvis_force_cleans_captured_runtime_tree` |
| PID reuse is revalidated before destructive fault injection | `test_inject_fault_revalidates_process_identity` |

Repository gate:

```powershell
python -m pytest -q tests/test_self_repair_domain.py tests/test_self_repair_persistence.py tests/test_self_repair_supervisor.py tests/test_dev_supervisor.py tests/test_self_repair_fault_injection.py tests/test_self_repair_phase5_acceptance.py
```

Normal CI remains authoritative for full Ruff, pytest, Windows DPAPI and Windows
Hello gates.

## Owner-machine fault injection

Preconditions:
- use a clean repository on the accepted Self-Repair revision;
- run JARVIS through `jarvis-dev`, not `jarvis-voice` directly;
- confirm the child establishes authenticated control and then publishes explicit
  core-runtime readiness after vision/audio initialization;
- startup readiness is bounded to 120 seconds so hardware/model initialization can
  complete without treating mere control-channel connection as readiness;
- keep a second PowerShell terminal open for the injector.

### A. Unexpected child crash

From the second terminal:

```powershell
python -m jarvis.self_repair.fault_injection crash
```

Expected supervisor evidence:
- the runtime child exits unexpectedly;
- exactly the registered same-version crash policy is selected;
- the restart budget is consulted before execution;
- the child restarts at the same Git revision;
- startup readiness is confirmed;
- repeated authenticated liveness probes stabilize;
- the RepairAttempt ends as `RECOVERED`.

A successful recovery resets the crash-policy budget baseline only after
verification.

### B. Alive-but-unresponsive runtime

After JARVIS has stabilized again:

```powershell
python -m jarvis.self_repair.fault_injection hang
```

Expected supervisor evidence:
- the production runtime remains present but stops responding;
- one failed liveness probe is insufficient;
- the configured consecutive-failure threshold is reached;
- an additional confirmation probe fails;
- the distinct runtime-unresponsive policy is selected;
- the suspended child is stopped and replaced by the same local revision;
- readiness plus liveness stabilization is required before `RECOVERED`.

Emergency manual undo, only if the supervisor itself is intentionally stopped
before it can recover the suspended child:

```powershell
python -m jarvis.self_repair.fault_injection resume
```

### C. Negative controls

Do not intentionally exhaust a paid provider quota for acceptance. The negative
control is deterministic repository coverage: provider quota/degradation has no
registered runtime-restart action.

Do not alter the Git revision during a live owner acceptance run merely to test
the revision guard. That guard is covered deterministically in the repository
suite.

## Pass criteria

Phase 5 passes only when:
- the repository acceptance suite and normal CI are green;
- owner crash injection recovers under the bounded crash policy;
- owner hang injection recovers under the bounded liveness policy;
- no unexpected second restart owner appears;
- no provider/dependency health signal is used as liveness truth;
- persisted incident/RepairAttempt history records the attempted repair and final
  verification outcome.

The deterministic Self-Repair foundation remains bounded to registered R1/R2
policies. RepairKnowledge, DiagnosticModelRouter and sandbox curriculum remain
separate later layers and cannot expand execution authority.


## Owner-machine acceptance result — PASS

Final accepted revision: `6a0ba73f46f68d9d0c2e8fa2c20c5fccaed8378a`.

### Crash recovery

Owner-machine crash injection passed before the final hang retest:
- the supervised runtime exited unexpectedly;
- the registered same-version crash policy performed the bounded restart;
- the replacement published startup readiness;
- repeated authenticated liveness probes stabilized;
- the durable RepairAttempt completed as `RECOVERED`.

### Hang recovery

The final Windows owner-machine hang test used the corrected process-tree injector and
reported that two runtime processes were suspended: the venv launcher and the
underlying Python interpreter.

Observed supervisor sequence:
- liveness probe failed `1/3`;
- liveness probe failed `2/3`;
- liveness probe failed `3/3`;
- the confirmation probe failed;
- the registered `supervisor-runtime-unresponsive-v1` policy became eligible;
- graceful shutdown timed out, as expected for the fully suspended runtime;
- exactly two runtime-tree processes were force-terminated;
- a same-revision replacement child started;
- startup readiness completed;
- repeated authenticated liveness stabilization completed;
- the supervisor reported `JARVIS liveness recovery succeeded`.

Durable incident evidence completed with:
- `execution_result = unresponsive child restart stabilized`;
- `verifier_result = readiness_and_liveness_stable:6_probes`;
- `verdict = recovered`.

### Windows process-tree finding

The acceptance run exposed an important Windows-specific behavior: launching the
runtime through the virtual-environment executable creates a launcher process plus
the underlying Python interpreter. Earlier hang injections suspended only the
launcher, so the real interpreter remained responsive and the watchdog correctly
treated the runtime as healthy.

PR #84 corrected the acceptance injector to operate on only the selected supervised
runtime tree. PR #85 applied the same process-tree ownership model to forced recovery
cleanup so a frozen interpreter cannot survive as an orphan.

### Final status

Self-Repair Phase 5 / the deterministic R1/R2 foundation is accepted on the owner
machine. Issue #65 may be closed.

This acceptance does not expand authority beyond the already documented registered
R1/R2 repair boundary. Source mutation, autonomous PR creation, protected-main
changes, Authority modification, and model-selected effectors remain outside this
foundation.
