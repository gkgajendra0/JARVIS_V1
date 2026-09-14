# JARVIS Generic Desktop Agent Implementation

Status: **ACCEPTED THROUGH PR #30; LATER STABILITY HARDENING ACCEPTED THROUGH PR #38**

Initial implementation date: 2026-09-11

## Goal

JARVIS Hands must solve generic computer goals rather than accumulate app-specific scripts. The owner states the desired outcome; JARVIS selects the strongest safe executor, obtains proportional authority, performs the work, observes the result, and stops truthfully when no safe path can continue.

## Accepted executor hierarchy

1. native OS/application semantics;
2. dedicated bounded integration/connector;
3. Playwright for browser workflows;
4. Microsoft `winapp` UI Automation for generic desktop UI;
5. target-window-scoped visual Computer Use only after structured evidence is insufficient;
6. truthful failure/clarification.

Apple Music, VS Code, Calculator and future apps are instances of the same architecture, not special hardcoded control paths.

## Canonical voice transaction

```text
voice request
 -> canonical USER generation
 -> one claimed Hands transaction / lease
 -> semantic routing
 -> governed executor
 -> observe / verify
 -> bounded replan or truthful completion
```

Accepted guarantees:

- delayed provider transcripts cannot make a new command reuse an older USER turn;
- a generation can be claimed for Hands at most once;
- a newer USER utterance supersedes stale pending work;
- a stale goal cannot begin another local action;
- an atomic mutation already started is not blindly cancelled/replayed;
- final-empty realtime transcription cleanup added later in PR #38 retires one abandoned generation without changing genuine FIFO transcript ordering.

## Structured desktop and visual fallback

UI Automation is observation-first and may execute bounded micro-plans when several immediate controls are already grounded. Mutations are not considered verified merely because input was accepted; follow-up observation/postcondition evidence is required where practical.

Visual Computer Use is withheld until structured UI evidence has been attempted. Its accepted containment contract is:

- explicit persisted owner opt-in;
- selected provider receives only the resolved target application's current top-level window;
- screenshot HWND/rectangle is bound to subsequent input;
- stale/moved windows and out-of-window coordinates fail closed;
- global app-switch/secure-attention style shortcuts are rejected;
- the target remains foreground for pointer/keyboard input;
- each newly active top-level/modal window requires a fresh observation;
- `generic_visual_control` has a deterministic CRITICAL risk floor independent of language/model wording.

Generic visual authority still excludes arbitrary shell/terminal/Registry work, package installation, security/permission changes, credentials/secrets, destructive deletion, direct browser control, broad File Explorer/System Settings authority and self-modification.

Browser tasks remain owned by Playwright.

## Grounding and latency

Accepted PR #30 improvements include:

- generic multilingual script-to-Latin normalization and conservative phonetic/string matching for human-facing entities;
- strict treatment of URLs, paths, package IDs and machine identifiers;
- actual canonical USER transcript must independently ground numeric mutation values;
- simple eligible reads/reversible actions may use a locally validated fast hint without another Hands planning call;
- high-risk/persistent/browser/UI/development mutations remain outside the fast path;
- executed-but-unverified fast actions are returned once and are not silently replayed;
- verified terminal actions can complete locally without an unnecessary final cloud completion turn;
- planner/route/executor/total latency telemetry is retained.

## Authority

Canonical JARVIS Authority remains the only permission path. Generic desktop control does not imply unrestricted machine authority.

A successful direct-user Windows Hello/T3 verification may establish the accepted bounded same-session T2 convenience window for eligible non-critical direct-user work. CAM++, LR-ASD or OWNER presence do not independently create that window, and T3 remains mandatory where the risk floor requires it.

## Post-PR #30 stability correction

PR #38 preserved this architecture and fixed two generic Hands reliability issues discovered during integrated use:

- bounded realtime hints using `app_name` safely normalize to the typed `app` field for `open_app`/`close_app`, with conflicting aliases rejected;
- when an identical structured UI action is already attempted/unverified, Hands may remove that failed structured route and allow the existing governed visual candidate once rather than repeatedly issuing the same action.

The duplicate-action guard, authority boundary and no-raw-shell rule remain intact.

## Acceptance state

The previous “owner-machine acceptance pending” status is obsolete.

PR #30 passed the required automated matrix and real owner-machine acceptance, including live multilingual application interaction, and was explicitly accepted/merged. PR #38 later passed integrated owner-machine acceptance and final exact-head CI before merge.

This implementation is therefore an **accepted production foundation**, while the full future Step 9/10/12 product slices remain formally incomplete.

See `JARVIS_HANDS_H1_H5_OWNER_ACCEPTANCE.md` and `POST_STEP_7_INTEGRATION_ACCEPTANCE.md` for acceptance/disposition evidence.
