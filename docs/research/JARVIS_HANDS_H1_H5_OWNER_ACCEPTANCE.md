# JARVIS Hands H1-H5 Owner Acceptance

Status: **ACCEPTED AND MERGED — PR #30; LATER RUNTIME HARDENING ACCEPTED IN PR #38**

Initial representative owner acceptance: 2026-09-11

## Purpose

This record captures the real-Windows owner-machine acceptance of the governed JARVIS Hands foundation. It supersedes the earlier wording that PR #30 was still waiting for final acceptance/merge.

## Representative H1-H5 acceptance

Readiness proved the expected local substrates were available without mutating the machine: OPA, Windows Hello helper, Send2Trash, document libraries, Playwright, Dulwich, display/Bluetooth WinRT dependencies, Microsoft `winapp`, real Chromium launch, WinGet, governed write roots and the registered Hands operation set.

The representative run executed 13 actions. All returned `status=succeeded`, `ok=true`, and `verification_passed=true`:

| Wave | Operation | Capability | Result |
| --- | --- | --- | --- |
| H1 | `system_status` | `local:system.read` | PASS |
| H1 | `get_master_volume` | `system:audio` | PASS |
| H1 | `list_windows` | `window:management` | PASS |
| H1 | `open_app` | `app:lifecycle` | PASS |
| H2 | `create_text_file` | `local:files.write` | PASS |
| H2 | `create_docx` | `local:documents.edit` | PASS |
| H2 | `create_xlsx` | `local:documents.edit` | PASS |
| H2 | `create_pptx` | `local:documents.edit` | PASS |
| H3 | `execute_browser_plan` | `browser:playwright` | PASS |
| H4 | `list_displays` | `system:display` | PASS |
| H4 | `list_bluetooth_devices` | `device:bluetooth` | PASS |
| H4 | `search_software` | `software:winget` | PASS |
| H5 | `git_status` | `development:git` | PASS |

The acceptance intentionally did not perform dangerous actions merely for proof: no arbitrary shell, arbitrary browser JavaScript, package installation/removal, destructive deletion, power/session mutation, Bluetooth pairing mutation, or JARVIS self-modification.

## Accepted authority UX

Ordinary governed work does not require a fresh Windows Hello challenge for every eligible action.

Accepted contract:

- ROUTINE work can remain T0 where policy allows;
- a qualifying direct-user non-routine action may require Windows Hello/T3;
- successful direct-user T3 may establish an in-memory, same-session, absolute 30-minute T2 `CORROBORATED_OWNER` convenience window;
- the window is not sliding and disappears when the authority broker/session closes;
- eligible non-critical direct-user work may reuse T2, but still receives fresh proposal binding, policy evaluation, one-time permit, execution verification and audit;
- proactive/model-suggested actions cannot inherit this convenience;
- CRITICAL and RESTRICTED_DEV_ONLY work never uses cached T2 as a substitute for required T3.

This is distinct from the still-deferred general biometric/voice-derived T2 problem. CAM++, LR-ASD or OWNER presence do not independently create this Hands trust window.

## Generic desktop control accepted in PR #30

The accepted generic desktop architecture is not app-script based:

1. native/semantic operation when available;
2. dedicated bounded integration;
3. Playwright for browser tasks;
4. Microsoft `winapp` UI Automation for generic desktop tasks;
5. target-window visual Computer Use only when structured evidence is insufficient;
6. truthful stop/clarification when no safe route exists.

Visual fallback is explicit machine opt-in, sends only the resolved target application's top-level window to the selected provider, validates HWND/geometry/focus, rejects out-of-window coordinates and global app-switch shortcuts, and receives a deterministic `generic_visual_control` CRITICAL risk floor.

Arbitrary shell/terminal, Registry, software installation, security/permission changes, credential/secret handling and destructive deletion remain outside generic visual authority.

## Multilingual grounding and latency acceptance

PR #30 also accepted:

- canonical USER-generation transaction/lease handling;
- stale-goal supersession and duplicate suppression;
- generic multilingual entity/value grounding without app-specific alias tables;
- strict numeric grounding so model-supplied values cannot override the spoken canonical transcript;
- a locally validated fast path for eligible simple reads/reversible actions;
- low-reasoning bounded Hands planning;
- verified terminal actions completing without unnecessary cloud completion round-trips;
- postcondition verification for Git and other mutations where practical.

The final PR #30 exact head passed the required CI matrix and owner-machine testing confirmed live Hindi/Hinglish Hands could resolve/open/operate Apple Music through the generic architecture. The owner explicitly accepted PR #30 and it merged to `main`.

## Later PR #38 stabilization

After Hands was accepted, integrated runtime testing found additional cross-subsystem faults. PR #38 corrected them without replacing the Hands architecture:

- final-empty realtime transcription no longer leaves a ghost canonical USER generation;
- bounded `app_name -> app` normalization fixes realtime app-lifecycle schema mismatch;
- repeated structured UI stagnation can remove the failed structured route and allow the existing governed visual fallback once instead of aborting on a duplicate loop;
- near-silent assistant audio and immediate standby behavior were restored;
- the same integrated owner session also validated Pocket 3 leave/re-enter recovery.

PR #38 passed final exact-head CI and owner-machine acceptance before merge.

## Final disposition

**Hands is an accepted production foundation.** There is no remaining PR #30 merge gate.

This does not mean every later product slice is complete. Full Step 9 app/device control, Step 10 browser product behavior and Step 12 document/coding operations remain formal future roadmap slices with accepted partial Hands foundations already available.

For the current consolidated production/disposition record, see `POST_STEP_7_INTEGRATION_ACCEPTANCE.md`.
