# JARVIS Hands H1 Owner Acceptance — Historical Sub-Gate

Status: **H1 REPRESENTATIVE SUB-GATES PASSED; SUPERSEDED BY FINAL H1-H5 / PR #30 ACCEPTANCE**

This document preserves early owner-machine H1 evidence. It is not the current merge gate. Final Hands acceptance is recorded in `JARVIS_HANDS_H1_H5_OWNER_ACCEPTANCE.md`, and PR #30 is accepted/merged.

## Representative H1 results

1. `jarvis-hands-smoke --readiness` — **PASS**
   - platform/dependency/resolver readiness;
   - zero mutations;
   - zero cloud model calls.
2. `jarvis-hands-smoke` structured UI scenario — **PASS**
   - Microsoft `winapp` structured UI execution;
   - Notepad text write + readback verification;
   - launcher + canonical authority + permit + verification.
3. `jarvis-hands-smoke --native --volume 30` — **PASS after owner-machine corrections**
   - approved Calculator launch;
   - maximize;
   - Windows master volume 30%;
   - bounded clipboard write;
   - all actions verified; no raw shell.

## Real-machine defects found and fixed

The H1 gate was useful because it exposed platform assumptions that synthetic tests had missed:

- pywin32 on the owner machine did not provide the assumed `IsZoomed` surface; the adapter moved to `GetWindowPlacement()` / `showCmd` state and gained a regression for that real module shape;
- the owner-machine pycaw `AudioDevice` did not provide the assumed `volume_percent` convenience property; the adapter moved to the Windows Core Audio endpoint-volume scalar interface and gained a matching regression.

The corrected native H1 scenario then passed all representative actions with `verification_passed=true`.

## Authority note — historical vs current

At the time of this early H1 record, reversible local actions were still going through repeated exact-action Windows Hello/T3 because the later Hands convenience window had not yet been accepted.

Current production authority is recorded in the final H1-H5 acceptance document: successful direct-user T3 may create the bounded same-session T2 convenience window for eligible non-critical direct-user work. That later change does not make biometric/voice-derived T2 authoritative.

## Final disposition

The original statements that “final live voice is pending,” “H1 is not owner accepted,” and “PR #30 stays draft/unmerged” are historical and no longer current.

PR #30 subsequently passed final live/CI acceptance and merged. Later PR #38 hardened cross-subsystem generation, Hands fallback and runtime stability behavior.

Use `JARVIS_HANDS_H1_H5_OWNER_ACCEPTANCE.md` and `POST_STEP_7_INTEGRATION_ACCEPTANCE.md` for current truth.
