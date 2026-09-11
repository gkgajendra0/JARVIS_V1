# JARVIS Hands H1-H5 owner acceptance

Status: **INTEGRATED OWNER-MACHINE ACCEPTANCE PASSED — LIVE VOICE + GENERIC VISUAL + LATENCY GATE PENDING**

Date: 2026-09-11

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

## Generic desktop expansion after representative acceptance

The integrated H1-H5 run intentionally did not exercise provider-backed screenshot Computer Use. That substrate has since been hardened and broadened for the final live voice gate.

The new generic fallback contract is:

- UIA remains preferred and can execute bounded multi-action micro-plans after live observation;
- visual fallback becomes available only after structured UI evidence is insufficient;
- the provider receives only the resolved target application's active top-level window, not the full desktop;
- local enforcement binds input to the HWND/rectangle used for the screenshot and rejects stale geometry, out-of-window coordinates and global app-switch shortcuts;
- generic visual Computer Use has a deterministic `generic_visual_control` CRITICAL risk floor, so strong owner verification is required for each bounded visual goal regardless of wording/language;
- normal app-local workflows such as save/export/send/share/print/upload/download may use this fallback after authorization;
- arbitrary shell/terminal, Registry, software installation, security/permission, credential/secret and destructive deletion work remains outside generic visual authority;
- browser tasks remain on Playwright, while File Explorer and Windows Settings require dedicated governed semantics;
- the visual substrate is a persisted explicit owner opt-in controlled with:

```powershell
jarvis-hands-smoke --enable-visual
jarvis-hands-smoke --show-visual
jarvis-hands-smoke --disable-visual
```

Automated tests cover target-window capture, HWND/geometry enforcement, coordinate containment, global shortcut blocking, the CRITICAL Authority floor, critical-task rejection and persisted configuration.

## Hands latency optimization pass

A dedicated production latency pass was completed after the first OpenAI live Hands run exposed excessive serial cloud-planner work on otherwise simple local actions.

The optimization deliberately preserves the same typed contracts, canonical USER grounding, entity resolution, Authority, one-time permits, executor verification and audit. It does not introduce a second ungoverned execution path.

Implemented latency contract:

- the realtime voice brain may optionally attach one semantic operation hint to the existing `use_computer` handoff when one simple bounded operation fully satisfies the request;
- the hint is never trusted directly: JARVIS independently validates operation allowlisting, typed parameters, canonical USER grounding and entity resolution before local execution;
- persistent writes, browser/UI plans, visual Computer Use, package mutation, power/session actions, Bluetooth pairing and development mutation are excluded from the fast path;
- eligible read/reversible local actions can therefore complete with zero additional Hands routing/planning cloud calls when the hint is valid;
- pre-execution fast-hint rejection falls back to the normal semantic planner;
- once a fast-path local action has started, JARVIS never silently falls back and replays that mutation merely because verification was inconclusive;
- verified single-route terminal actions on the normal Hands planner path complete deterministically instead of requiring a final cloud `goal_complete` round trip;
- OpenAI structured Hands routing/planning explicitly uses low reasoning effort for the bounded semantic planning role;
- after two consecutive unverified `execute_windows_plan` attempts, the voice orchestrator stops repeatedly spending structured-UI planner turns and can promote the generic visual candidate when configured;
- implicit non-durable memory-candidate extraction is deferred by five seconds so background provider work does not compete with the foreground voice/Hands transaction;
- stage telemetry now records semantic route latency, per-step planner latency, executor latency, fast-path execution latency and total Hands goal latency.

### Multilingual numeric grounding safety correction

CI found an important issue while the fast path was being hardened: the previous voice-only numeric recovery could make a planner-supplied percentage appear grounded by appending that same model value to synthetic grounding text.

That recovery path was removed.

Current contract:

- a numeric mutation such as volume or brightness must still match the canonical USER transcript;
- ordinary digit/English-number grounding continues through the core deterministic Hands grounding implementation;
- supported Hindi/Urdu transliterated number words are recovered from the actual transcript text with Unicode-aware matching;
- a model-supplied `80` cannot validate against a transcript that said `30`, including transliterated speech;
- if the number cannot be independently recovered from the canonical transcript, the fast hint is rejected before execution and normal planner handling resumes.

### Latency-pass automated certification

Exact implementation head before this documentation-only update:

`0b961eff835368735a37c395f2bd73572f9f4901`

GitHub Actions run:

`34567823631`

Results:

- Ruff format + lint: PASS;
- full pytest suite: PASS;
- Playwright Chromium provision/smoke inside the pytest job: PASS;
- unified Windows Hands dependency install/probe + DPAPI smoke: PASS;
- Windows Hello normal build + JSON contract probe: PASS;
- Windows Hello production self-contained publish + JSON contract probe: PASS.

Dedicated regressions cover:

- a grounded reversible voice hint executes locally without invoking the Hands planner;
- high-risk operations cannot enter the voice fast path;
- an ungrounded parameter hint is rejected before any local execution;
- an executed-but-unverified fast action is returned once and is not replayed through planner fallback;
- OpenAI Hands planning pins low reasoning effort;
- multilingual/transliterated numeric grounding remains accepted only when the actual spoken value matches;
- spoken `30` / hinted `80` is rejected before execution.

Automated certification proves the optimized control-flow contracts. It does not claim a real-world millisecond improvement until owner-machine live telemetry is captured; provider/network latency and Windows executor latency must be measured on the production machine.

## Safety observations

The representative real-machine test deliberately avoided performing dangerous actions merely for proof. It did not install/uninstall software, pair/unpair Bluetooth, sleep/restart/shutdown/sign out, permanently delete acceptance artifacts, execute arbitrary shell, run arbitrary browser JavaScript, or mutate the JARVIS repository.

Those primitive paths remain covered by deterministic unit/contract/authority/grounding tests and canonical risk floors.

## Remaining gate

The integrated owner-machine H1-H5 gate is complete. The broader generic desktop fallback and optimized live-voice latency path still require live owner-machine acceptance.

PR #30 must remain draft and unmerged until all of the following are complete:

1. the owner pulls the exact accepted branch head, reinstalls `.[hands]`, enables visual fallback with `jarvis-hands-smoke --enable-visual`, and confirms `--show-visual` reports enabled;
2. one live `jarvis-voice` multi-capability owner session demonstrates natural-language goal routing through production `HandsGoalAgentTools`;
3. simple eligible commands such as volume/media/app-lifecycle are repeated and the logs confirm the optimized path is actually used where appropriate, including `Hands fast path` / latency telemetry and no unnecessary extra Hands planner round trips;
4. at least one simple command is also allowed to use the normal planner path so deterministic verified-terminal completion and its total latency can be observed;
5. at least three unrelated desktop applications are exercised so acceptance is not app-specific;
6. at least one task succeeds entirely through native/UIA semantics and at least one deliberately difficult/custom-rendered task forces UIA -> window-scoped visual fallback;
7. the visual test confirms only the target application is operated, a strong Windows Hello/T3 challenge occurs for the bounded generic visual goal, and JARVIS returns a truthful failure rather than escaping the target window when containment blocks an action;
8. rapid correction/supersession is exercised while Hands is planning so an older spoken command cannot start another local action;
9. success speech matches verified tool results and unrelated/ambient speech does not gain authority;
10. owner-facing Windows Hello frequency is acceptable under the bounded-session trust model for normal non-critical work and the stronger per-goal visual fallback floor;
11. captured route/planner/execution/total latency is reviewed before any further optimization so additional work targets measured bottlenecks rather than speculation;
12. final product/architecture/quality-gate documentation is reconciled to the accepted Hands scope;
13. final exact-head CI is green;
14. the owner explicitly accepts the Hands release for merge.
