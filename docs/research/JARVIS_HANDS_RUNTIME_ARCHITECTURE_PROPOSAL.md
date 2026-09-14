# JARVIS Hands Runtime — Accepted Architecture Record

Status: **ORIGINAL PROPOSAL ACCEPTED IN IMPLEMENTED SUBSET THROUGH PR #30; FUTURE CAPABILITY MAP REMAINS ROADMAP GUIDANCE**

Original proposal date: 2026-09-09

## Product goal

JARVIS Hands is not synonymous with mouse/keyboard automation. The owner states a desired outcome; JARVIS selects the appropriate semantic capability and strongest suitable executor, obtains proportional authority, performs bounded work, verifies the result, and asks for intervention only when the system cannot safely proceed.

## Core design rule

Keep three concepts separate:

1. **Capability = WHAT JARVIS can do.**
2. **Executor/adapter = HOW it is done.**
3. **Workflow = bounded composition of capabilities for one owner goal.**

Capabilities represent stable semantic domains, not app names or buttons.

## Accepted executor preference

1. native / semantic OS or application API;
2. dedicated integration / connector;
3. specialist structured automation — Playwright for browser, Microsoft `winapp` UI Automation for desktop;
4. target-window-scoped visual Computer Use fallback;
5. truthful stop / human intervention.

A lower-quality substrate is not chosen merely because it is easier to implement.

## Implemented Hands capability families

The following bounded foundations are accepted in production through PR #30 and later stability work:

- `system.status` / Step-7 system reads;
- `system.audio`;
- `system.display` bounded inventory/brightness surfaces where supported;
- `system.clipboard` bounded operations;
- `media.playback` through native Windows media semantics where available;
- `app.lifecycle`;
- `app.ui` through `winapp` structured UI Automation;
- `window.management`;
- approved-root `files.read`;
- bounded `files.write` and structured document creation/editing;
- `browser.navigation_execution` through Playwright;
- bounded Bluetooth/device discovery/control surfaces;
- bounded software discovery through WinGet;
- bounded Git/development operations without arbitrary shell;
- `visual.computer` as explicit opt-in, target-window-scoped fallback.

These are foundations for later roadmap steps, not proof that every future capability in those domains is complete.

## Capability families still future/formal roadmap work

- full notes/task/reminder semantics — Step 8;
- complete application/device product slice — Step 9;
- complete browser/web-interaction product slice — Step 10;
- calendar/email/external communication — Step 11;
- complete file/document/coding project operations — Step 12;
- LAN/smart-home device ecosystem expansion;
- unrestricted software/system mutation, which remains separately governed and is not a generic Hands right.

## Production routing

```text
canonical USER goal
 -> one Hands transaction / generation lease
 -> semantic capability routing
 -> strongest safe executor
 -> PreparedCapability / bounded plan
 -> canonical ActionProposal
 -> AuthorityService
 -> one-time permit
 -> execute
 -> postcondition / observation verification
 -> truthful result or bounded replan
```

The owner does not need to know capability names, selectors, tools or backends.

## Authority update from implementation

The original proposal assumed T2 was globally unavailable and ordinary non-routine work would repeatedly bridge through T3. Production Hands refined that UX without weakening authority:

- successful direct-user Windows Hello/T3 may create an in-memory same-session absolute 30-minute T2 `CORROBORATED_OWNER` convenience window;
- the window is non-sliding and disappears with the authority broker/session;
- proactive/model-suggested work cannot inherit it;
- CRITICAL/RESTRICTED_DEV_ONLY actions remain at their stronger floor;
- every action still has a fresh proposal/policy/permit/verification/audit path.

This **does not** mean general biometric/voice T2 is solved. CAM++, LR-ASD and OWNER presence remain non-authoritative shadow/context evidence; turn-specific spoken actor binding remains deferred.

## Generic desktop safety boundary

Generic UIA and visual control do not own unrelated high-consequence domains.

Visual fallback:

- becomes available only after structured evidence is insufficient;
- receives only the target application's active top-level window;
- binds actions to observed HWND/geometry/focus;
- rejects stale/out-of-window/global app-switch actions;
- carries a deterministic CRITICAL risk floor;
- remains explicit owner opt-in.

It does not grant arbitrary terminal/PowerShell/Registry, security/permission, credential/secret, destructive deletion, package installation or self-modification authority.

Browser work remains on Playwright because DOM/browser semantics are stronger than generic desktop input.

## Workflow rule

A request may compose multiple capabilities, but a workflow is never permission to improvise unrelated work. Example: launch app -> locate/play media -> adjust volume -> verify final states. Each consequential component remains grounded, bounded and governed.

## Current disposition

The earlier status “proposed — owner review required before broad implementation” is obsolete. The core architecture was implemented, tested, owner-accepted and merged in PR #30. PR #38 later hardened generation reconciliation, app-hint normalization and structured-UI stagnation fallback without replacing this architecture.

The broader capability map remains design guidance for future formal roadmap slices and does not pre-authorize their implementation.

See `JARVIS_HANDS_H1_H5_OWNER_ACCEPTANCE.md`, `JARVIS_GENERIC_DESKTOP_AGENT_IMPLEMENTATION.md`, and `POST_STEP_7_INTEGRATION_ACCEPTANCE.md`.
