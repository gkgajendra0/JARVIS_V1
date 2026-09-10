# JARVIS Hands H1-H5 owner acceptance

Status: **INTEGRATED OWNER-MACHINE ACCEPTANCE PASSED — LIVE VOICE GATE PENDING**

Date: 2026-09-10

PR: #30 (`feat/governed-jarvis-hands-v1` -> `main`)

## Purpose

This document records the representative real-Windows-machine acceptance of the governed JARVIS Hands H1-H5 implementation. It supplements the earlier H1-only acceptance history in `JARVIS_HANDS_H1_OWNER_ACCEPTANCE.md`.

The owner-machine strategy remains representative rather than primitive-by-primitive. Broad operation, authority, grounding, executor, and failure behavior is covered by automated tests and CI; the real-machine gate proves that the actual Windows execution substrates cooperate end to end.

## Accepted test command

The owner updated the branch, installed the unified Hands extra, and ran:

```powershell
git pull --ff-only origin feat/governed-jarvis-hands-v1
python -m pip install -e ".[hands]"
jarvis-hands-smoke --integrated
```

The branch updated to `e561c23165880a9d612217fd1e479c86673c8599` before the run.

## Readiness result

`governed_hands_h1_h5_readiness` returned `ok=true`, `read_only=true`, `mutations_performed=0`, and `cloud_model_calls=0`.

The owner machine positively resolved/probed:

- OPA 1.20.1;
- managed `Jarvis.WindowsHelloVerifier.exe` JSON contract;
- Send2Trash;
- python-docx;
- openpyxl;
- python-pptx;
- Playwright;
- Dulwich;
- screen-brightness-control;
- WinRT Foundation Collections;
- WinRT device enumeration;
- WinRT Bluetooth;
- Microsoft `winapp`;
- a real Playwright Chromium headless launch;
- Microsoft WinGet;
- governed local write roots `documents, downloads`;
- governed development repository alias `jarvis`;
- all registered Hands operations required by the integrated acceptance map.

The unified `hands` extra also installed the previously missing `winrt-Windows.Foundation.Collections==3.2.1` dependency successfully on the owner machine.

## Representative H1-H5 execution result

The consolidated acceptance executed 13 representative actions. All 13 returned `status=succeeded`, `ok=true`, and `verification_passed=true`.

| Wave | Label | Operation | Capability | Result |
| --- | --- | --- | --- | --- |
| H1 | `h1_system` | `system_status` | `local:system.read` | PASS |
| H1 | `h1_audio` | `get_master_volume` | `system:audio` | PASS |
| H1 | `h1_windows` | `list_windows` | `window:management` | PASS |
| H1 | `h1_app` | `open_app` | `app:lifecycle` | PASS |
| H2 | `h2_text_file` | `create_text_file` | `local:files.write` | PASS |
| H2 | `h2_docx` | `create_docx` | `local:documents.edit` | PASS |
| H2 | `h2_xlsx` | `create_xlsx` | `local:documents.edit` | PASS |
| H2 | `h2_pptx` | `create_pptx` | `local:documents.edit` | PASS |
| H3 | `h3_browser` | `execute_browser_plan` | `browser:playwright` | PASS |
| H4 | `h4_displays` | `list_displays` | `system:display` | PASS |
| H4 | `h4_bluetooth` | `list_bluetooth_devices` | `device:bluetooth` | PASS |
| H4 | `h4_software` | `search_software` | `software:winget` | PASS |
| H5 | `h5_git` | `git_status` | `development:git` | PASS |

Final summary:

- `operation=governed_hands_h1_h5_owner_acceptance`;
- `actions_completed=13`;
- `actions_expected=13`;
- `verification_passed=true`;
- `write_root=downloads`;
- acceptance folder `JARVIS_Hands_Acceptance_12bb52cf`;
- `cloud_model_calls=0`;
- `raw_shell=false`;
- `arbitrary_browser_javascript=false`;
- `package_mutations=false`;
- `power_session_mutations=false`;
- `bluetooth_pairing_mutations=false`;
- `jarvis_self_modification=false`.

Acceptance artifacts were intentionally left for owner inspection at:

`C:\Users\gkgaj\Downloads\JARVIS_Hands_Acceptance_12bb52cf`

## Authority UX correction validated before this run

Before integrated owner acceptance, the authority bridge was corrected so ordinary governed actions do not require a fresh Windows Hello challenge on every execution.

Accepted implementation contract:

- ROUTINE actions remain T0 where canonical policy allows;
- the first qualifying direct-user non-routine action may require strong Windows Hello/T3;
- a successful direct-user strong verification establishes an in-memory, same-session, absolute 30-minute `CORROBORATED_OWNER` (T2) trust window;
- non-critical direct-user work may reuse T2 while still receiving a fresh proposal-bound approval, canonical policy evaluation, one-time permit, execution verification, and audit;
- the trust window is not sliding and is cleared when the authority broker closes;
- proactive/model-suggested actions cannot inherit the direct-user convenience path;
- CRITICAL and RESTRICTED_DEV_ONLY actions never consume cached T2 as a substitute for their stronger floor;
- exact-action strong approval remains required wherever the canonical risk/policy floor demands T3.

Automated regression tests prove same-session reuse, expiry, session isolation, proactive-origin exclusion, persistent-write approval semantics, and the critical-action T3 floor.

The owner terminal transcript does not expose Windows Hello UI prompt count, so this document does not infer a popup count from console output. Human-facing prompt frequency remains an explicit UX observation for the final live voice acceptance session.

## Postcondition-verification hardening after representative acceptance

The H5 Git executor was tightened after the representative owner-machine run so mutating Git operations cannot claim success merely because a backend call returned without an exception. The pure-Python Dulwich path remains in place; no Git shell execution was introduced.

Automated failure-injection regressions now require these postconditions:

- branch creation succeeds only when the created local branch ref resolves to the original HEAD OID;
- staging succeeds only when every requested path no longer remains unstaged or untracked;
- commit succeeds only when the returned commit OID is the repository HEAD;
- push succeeds only when the remote branch OID equals local HEAD after the push.

The existing representative integration matrix was updated to model the same Git verification contract. A real owner-repository Git mutation is intentionally not required merely for certification; the owner-machine integrated gate already proved real Dulwich `git status`, while deterministic tests cover mutation postconditions and failure behavior.

## Safety observations

The representative real-machine test deliberately avoided performing dangerous actions merely for proof. It did not install/uninstall software, pair/unpair Bluetooth, sleep/restart/shutdown/sign out, permanently delete acceptance artifacts, execute arbitrary shell, run arbitrary browser JavaScript, or mutate the JARVIS repository.

Those primitive paths remain covered by deterministic unit/contract/authority/grounding tests and canonical risk floors.

## Remaining gate

The integrated owner-machine H1-H5 gate is complete.

PR #30 must remain draft and unmerged until all of the following are complete:

1. one live `jarvis-voice` multi-capability owner session demonstrates natural-language goal routing through production `HandsGoalAgentTools`;
2. the live session confirms success speech matches verified tool results and that unrelated/ambient speech does not gain authority;
3. owner-facing Windows Hello frequency is acceptable under the bounded-session trust model;
4. permanent product/architecture/quality-gate documentation is reconciled to the final accepted Hands scope;
5. final exact-head CI is green;
6. the owner explicitly accepts the Hands release for merge.
