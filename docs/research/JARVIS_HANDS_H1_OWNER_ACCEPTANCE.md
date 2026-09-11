# JARVIS Hands H1 owner acceptance

Status: acceptance runbook for draft PR #30. This document does not mark H1 DONE.

## Acceptance strategy

Owner-machine acceptance is representative, not exhaustive. We do not manually certify every primitive computer operation. Each owner scenario proves an execution substrate/capability family end to end on the real Windows machine; the broader operation matrix is covered by automated unit, contract, authority, grounding, and CI tests.

Representative owner scenarios:

1. `jarvis-hands-smoke --readiness` — PASSED
   - read-only platform/dependency/resolver readiness
   - zero mutations
   - zero cloud model calls
   - no Windows Hello prompt
2. `jarvis-hands-smoke` — PASSED
   - representative structured application-UI execution through Microsoft `winapp`
   - exact Notepad text write + readback verification
   - proves structured UI + launcher + canonical authority + permit + verification
3. `jarvis-hands-smoke --native --volume 30` — PASSED
   - one combined representative native Windows scenario
   - approved Calculator launch
   - Calculator maximize
   - Windows master volume set to 30%
   - clipboard set to `JARVIS native clipboard acceptance`
   - proves app lifecycle + Win32 window management + Core Audio + clipboard through the governed runtime
   - this does NOT imply separate owner runs for minimize/restore/focus/mute/unmute/clear-clipboard/etc.; those belong in automated coverage
4. Final live `jarvis-voice` representative scenario — PENDING
   - one natural-language end-to-end session exercising semantic native routing, current-media control, and structured app UI
   - media acceptance is folded into this final live session rather than requiring a separate mandatory `--media` owner run
   - `jarvis-hands-smoke --media` remains available only as a diagnostic if live media behavior fails or needs isolation
   - no authority from unrelated/ambient meeting speech
   - success claims must match verified tool state

Future Hands families follow the same rule: add automated operation coverage broadly, then require only a small representative owner scenario for a genuinely new execution substrate, security boundary, device class, or external side-effect class. We must not create a manual test checklist proportional to the number of operations.

## Owner-machine findings

- Structured Notepad acceptance passed on the owner machine with verified readback.
- The first native H1 run proved `open_app` and then exposed a pywin32 portability defect during Calculator maximize: the installed `win32gui` module does not export `IsZoomed`.
- Research confirmed `win32gui.GetWindowPlacement()` is the supported pywin32 surface for retrieving `showCmd`; the native window adapter now derives minimized/maximized state from `SW_SHOWMINIMIZED` / `SW_SHOWMAXIMIZED` instead of relying on `IsZoomed`.
- A regression now exercises the same condition with a fake pywin32 GUI module that deliberately has no `IsZoomed` attribute.
- The second native H1 run proved `open_app` and `maximize_window`, then exposed a pycaw adapter assumption: the returned `AudioDevice` on the owner machine has no `volume_percent` convenience property.
- Current pycaw examples and the Windows Core Audio contract use the endpoint-volume interface. The adapter now reads `EndpointVolume.GetMasterVolumeLevelScalar()` and writes `EndpointVolume.SetMasterVolumeLevelScalar()` with normalized values, avoiding the unsupported convenience property. A contract regression exercises an AudioDevice shape with only `FriendlyName` and `EndpointVolume`.
- The corrected native representative run then PASSED all four governed actions on the owner machine: Calculator launch, Calculator maximize, master volume to 30%, and fixed clipboard marker. All four returned `status=succeeded` and `verification_passed=true`; summary reported `actions_completed=4/4`, `cloud_model_calls=0`, and `raw_shell=false`.

## Approval rule

Every non-routine action remains an immutable `ActionProposal` routed through the canonical `AuthorityService`. The current H1 owner machine still uses exact-action Windows Hello/T3 for reversible local changes while T2 admission remains intentionally disabled. One permit cannot authorize a different action or different material parameters.

Human-facing Windows Hello summaries must identify the material action being approved. Examples include the target volume percentage, target application/window, media transition, or a bounded clipboard-text preview. The proposal fingerprint remains bound to the complete exact parameters even when a long clipboard value is previewed rather than fully displayed.

## Completion rule

H1 is not owner accepted until the representative readiness, structured UI, native core, and final live voice scenario pass on the owner Windows machine. PR #30 stays draft and unmerged until owner acceptance, documentation reconciliation, and final exact-head CI are complete.
