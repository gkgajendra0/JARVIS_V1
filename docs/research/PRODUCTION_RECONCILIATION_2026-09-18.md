# Production Repository Reconciliation — 2026-09-18

## Purpose

Before resuming PR #41 Self-Awareness acceptance, the owner requested a wider repository scan to make sure no working/resolved capability or bug fix remained stranded outside protected `main`.

This audit therefore checked more than the obvious open PRs. It covered:

- every open pull request;
- closed but unmerged pull requests;
- all surviving repository branches;
- branches with no pull request;
- known deferred issues;
- current production architecture/plan/acceptance documentation;
- whether historical branch functionality exists on main under the same or newer implementation.

## Production baseline entering the audit

At the start of the reconciliation, protected `main` was:

`9571b7fb13016e13003f87a01d89022136f73153`

That baseline included owner-accepted work through PR #42 but did not yet include the accepted fixes developed during the subsequent runtime-stability investigation.

## Accepted work found outside main

The scan found exactly three accepted runtime/safety changes still waiting outside protected main.

### PR #43 — realtime conversation grounding and semantic standby

Accepted behavior:

- raw VAD/user-state activity is activity only;
- only accepted canonical USER turns advance executable USER generation;
- Hands grounds to canonical USER generations;
- semantic `enter_standby` replaces hardcoded phrase lists;
- JARVIS, not the model, owns lifecycle transition;
- standby returns to local wake detection and stays distinct from Windows power/session intent;
- realtime output is isolated before the deterministic acknowledgement path.

Merged production commit:

`f40e4dc352c64c14835d9f5365b58d6dd3f60410`

Known separate residual: cloud scripted-TTS quota can still prevent startup/standby fixed phrases from playing. This is tracked as issue #50 rather than weakening the accepted standby lifecycle.

### PR #49 — operation-specific power/session safety

Accepted behavior:

- exact latest canonical USER evidence must explicitly support the proposed Windows power/session operation and local-computer target;
- standby/sleep language directed at JARVIS cannot become Windows sleep/restart/shutdown evidence;
- `intent_operation` and bounded `intent_evidence` are bound into the immutable proposal fingerprint and Windows Hello material;
- the native power executor rejects unbound calls and operation substitution;
- Authority audit records bounded power intent evidence.

Owner-machine acceptance proved:

`Restart my computer` -> `restart_workstation` -> Windows Hello -> owner cancel -> `user_canceled` -> no restart.

Merged production commit:

`7599ed3f83b01cbc6d3de24ad408550f07e5e9c6`

Issue #47 was thereby resolved/closed.

### PR #48 — Pocket 3 native transport liveness recovery

Accepted behavior:

- transport last-RX freshness is explicit;
- cached native `active=True` cannot indefinitely mask dead/stale transport;
- stale transport/native state cannot reset recovery progress without fresh evidence;
- stale sessions reuse the bounded existing native-session rebuild path;
- fresh A6/native evidence restores healthy OWNER lock.

The original branch was based on an older #43 state. It was retargeted to the consolidated main, brought fully up to date using GitHub's clean merge tree, and revalidated before merge. Its final diff remained restricted to six Pocket recovery/test files.

Merged production commit:

`e2ff21e78480a09eb243cdd2c121b39e47620d0f`

## Historical branches reviewed and intentionally not merged

### PR #18 / issue #14

PR #18 contained extensive Step-3 identity and conversation-ownership research, including multiple candidates that were explicitly rejected or deferred. It is not current architecture.

Disposition:

- PR #18 closed historical/unmerged;
- issue #14 closed not planned because its old text incorrectly said Step 3 blocked later roadmap work;
- issue #19 remains the specific future production voice-isolation/turn-ownership research track.

### PR #27

Superseded by accepted Step-7 PR #28. No separate merge required.

### PRs #31 / #32

Historical performance branches. Accepted pieces were selectively recovered in PR #36 and later stability work.

Verified on current main:

- `src/jarvis/performance/runtime_profile.py` exists;
- `src/jarvis/voice/silent_audio_recovery.py` exists and matched the accepted historical implementation;
- later production implementations supersede old branch versions where files evolved.

The old research documents themselves are historical evidence; their absence does not represent missing accepted runtime capability.

### Phase 4.5E branches

`implementation/step-4-phase45e-context-injection`:
- functional shadow retrieval passed on the owner machine;
- resource-profile acceptance was explicitly deferred;
- therefore not fully production-accepted.

`implementation/step-4-phase45e2-utility-gate`:
- Qwen utility/influence classifier failed the multilingual safety/utility holdout;
- unsafe false influence remained and ESSENTIAL recall collapsed;
- candidate rejected;
- no automatic provider-context memory injection authorized.

These branches are experimental evidence, not forgotten accepted features.

### Other no-PR branches

Jarvis-dev experiments, Pocket reacquisition/recenter branches, CI branches, raw test branches and temporary runtime-stability branches were compared against main. They were either fully behind/identical to main or represented rejected/superseded experiments. No unique accepted production functionality was found.

## Deferred issues preserved intentionally

The repository scan leaves these open because they are known future work, not merge omissions:

- **#19** production-grade conversation voice isolation / turn ownership;
- **#44** volume fast-path alias + relative-delta semantics;
- **#45** false-interruption resume configured when production output cannot pause;
- **#46** intermittent LiveKit AudioMixer timeout investigation;
- **#50** fixed lifecycle/system speech depends on cloud TTS quota.

## Open pull requests after reconciliation

Only:

- **PR #41 — Self-Awareness Foundation: evidence, health and incident core**

PR #41 is implementation-complete but remains draft/unmerged pending owner-machine acceptance and explicit final merge approval.

## Final production state

Accepted runtime-code baseline after the accepted merges:

`e2ff21e78480a09eb243cdd2c121b39e47620d0f`

Protected `main` may advance beyond this SHA through documentation-only reconciliation without changing the accepted runtime code.

The accepted heads of PRs #43, #49 and the updated #48 branch are all ancestors of this main baseline.

## Conclusion

The repository-wide audit found no additional owner-accepted runtime/capability fix stranded outside main.

What remains outside main is intentionally one of:

- PR #41 awaiting acceptance;
- explicitly deferred future work;
- rejected experiment;
- superseded/historical branch;
- research-only evidence.

This is the clean baseline from which PR #41 should now be reconciled and tested.
