# JARVIS Hands Runtime — Architecture Proposal

Status: **PROPOSED — OWNER REVIEW REQUIRED BEFORE BROAD IMPLEMENTATION**

Date: 2026-09-09

## 1. Product goal

JARVIS Hands is not synonymous with mouse/keyboard automation.

The product goal is:

> The owner states the desired outcome. JARVIS selects the appropriate computer capability, chooses the best available executor, obtains proportional authority, performs the work, verifies the result, and asks for manual intervention only when the machine or an external system genuinely cannot proceed.

The owner should not need to know capability names, tools, APIs, UI selectors, or execution backends.

## 2. Core design rule

Separate three concepts:

1. **Capability = WHAT JARVIS can do.**
2. **Executor/adapter = HOW JARVIS does it.**
3. **Workflow = how multiple capabilities are composed to achieve one user goal.**

A capability must represent a stable semantic domain, not one app and not one button.

Examples:

- `media.playback` is a capability;
- Windows Global System Media Transport Controls is one executor for it;
- Apple Music UI automation may be a fallback executor for a missing media operation;
- `play a song in Apple Music and set volume to 25%` is a workflow combining app/media/audio capabilities.

## 3. Mandatory executor preference

For every capability, JARVIS must prefer the highest-quality available execution substrate in this order:

1. **Native / semantic API**
2. **Dedicated integration / connector / App Action**
3. **Structured specialist automation**
4. **Visual Computer Use fallback**
5. **Human intervention**

A lower layer must not be used merely because it is easier to implement if a mature higher-quality path is available.

## 4. Capability map

The first Hands architecture should recognize these semantic families. Not every family must be implemented in the first PR; the map exists so future work lands in the correct owner.

### 4.1 System

#### `system.status`
Operations:
- CPU/RAM/disk/uptime/basic machine state
- running-process metadata

Current executor:
- `psutil`

Status:
- already accepted through Step 7

#### `system.audio`
Operations:
- get/set master volume
- mute/unmute
- later per-session/app volume
- active/default audio endpoint information

Preferred executor:
- Windows Core Audio (`IAudioEndpointVolume`, `ISimpleAudioVolume` where appropriate)

#### `system.display`
Operations:
- monitor inventory
- brightness where hardware/API supports it
- resolution/orientation/display mode later

Preferred executor:
- Windows display/monitor APIs

Important: DDC/CI/MCCS brightness is hardware-dependent and must be verified per monitor rather than assumed.

#### `system.power_session`
Operations:
- lock
- sleep
- sign-out
- restart
- shutdown

Preferred executor:
- Windows native APIs

Authority:
- consequence-dependent; restart/shutdown/sign-out require stronger approval than ordinary UI changes

#### `system.clipboard`
Operations:
- read text
- set text
- clear clipboard

Preferred executor:
- Windows clipboard API

Private clipboard reads remain private data and must use canonical authority.

### 4.2 Media

#### `media.playback`
Operations:
- current session
- current track/media metadata
- play
- pause
- toggle
- stop
- next
- previous
- seek where supported
- playback state

Preferred executor:
- Windows `GlobalSystemMediaTransportControlsSessionManager` / `GlobalSystemMediaTransportControlsSession`

Fallback:
- app-specific structured UI only when native media session capability cannot satisfy the requested operation

### 4.3 Applications and windows

#### `app.lifecycle`
Operations:
- discover installed/approved app
- launch
- focus
- close
- later minimize/maximize where appropriate

Preferred executor:
- native application activation/process/window APIs

The app catalogue must be JARVIS-owned and must not become arbitrary shell execution.

#### `app.ui`
Operations:
- inspect structured accessibility/UI tree
- search element
- invoke/click approved control
- type/set bounded text
- read values
- wait for UI state
- verify UI state

Primary executor:
- Microsoft `winapp` structured UI Automation

Fallback:
- provider-neutral visual Computer Use

Important:
- `app.ui` is the general UI hand, not the owner of system/media/files/browser/email/etc.;
- it must not silently broaden a user goal into Save/Print/Share/Delete/Open/Install or another consequential operation;
- plan parameters must remain bound to the canonical user request.

#### `window.management`
Operations:
- enumerate top-level windows
- focus
- minimize/maximize/restore
- move/resize
- move to monitor
- tile/arrange later

Preferred executor:
- Win32 window-management APIs (`SetWindowPos`, placement/foreground APIs)

Structured UI is fallback where native operations are insufficient.

### 4.4 Files and documents

#### `files.read`
Operations:
- approved-root metadata/list/search/read/document conversion

Current executors:
- direct filesystem/Git/ripgrep
- isolated MarkItDown sidecar

Status:
- accepted Step 7

#### `files.write`
Operations:
- create
- write/update
- copy
- move
- rename
- mkdir
- delete to recoverable location where possible

Preferred executor:
- direct filesystem APIs

Requirements:
- approved roots
- overwrite/replace semantics
- rollback/recycle-bin strategy where possible
- exact action proposal
- stronger authority as persistence/destructiveness increases

#### `documents.edit`
Operations:
- create/edit structured documents and spreadsheets
- convert/export
- preserve document semantics where possible

Preferred executor:
- mature file-format/document libraries or application APIs

Fallback:
- structured UI, then visual CUA

### 4.5 Browser and web execution

#### `browser.navigation_execution`
Operations:
- open/navigate
- search
- inspect page
- click
- fill forms
- upload/download
- later authenticated workflows

Preferred executor:
- browser-native structured automation such as Playwright

Fallback:
- visual Computer Use

Browser execution must remain separate from desktop UI control because DOM/browser semantics are superior to generic screen/UI automation.

### 4.6 Devices and connectivity

#### `device.bluetooth`
Operations:
- discover
- inspect pairing state
- pair/unpair under approval
- later connect/disconnect where supported

Preferred executor:
- Windows device enumeration/Bluetooth APIs

#### `device.local`
Operations:
- approved camera/microphone/peripheral controls
- device-specific capabilities

Preferred executor:
- mature device/native APIs first; current DJI PTZ integration remains a specialist executor for the Pocket 3

#### `device.network_smart`
Operations:
- future LAN/smart-home/device service actions

Preferred executor:
- device/service-specific APIs or standards, not generic desktop UI

### 4.7 Productivity and communication

These capabilities are semantically part of the eventual Hands experience even when they are implemented in later roadmap slices.

#### `notes`
- create/read/update/delete notes

#### `tasks.reminders`
- create/edit/cancel reminders and scheduled work

#### `calendar`
- read availability/events
- create/update/cancel events under authority

#### `communication.email`
- search/read
- draft
- reply
- send under explicit authority

#### `communication.messaging`
- future supported messaging/Teams/Slack-style actions

Preferred executors:
- service APIs/connectors first
- structured UI only as fallback

### 4.8 Development and software management

#### `development.project`
Operations:
- inspect repository
- edit code
- run bounded tests/builds
- Git operations
- GitHub issue/PR workflows

This must never become arbitrary model shell authority. Development execution needs a dedicated command/tool policy and project boundary.

#### `software.management`
Operations:
- inspect installed software
- install/update/uninstall approved packages

Preferred executor:
- package managers/native deployment APIs

Authority:
- high; executable/system changes are critical under existing risk classification

### 4.9 Visual fallback

#### `visual.computer`
Purpose:
- operate software that has no usable native, connector, browser, or structured UI executor

Executors:
- Gemini Computer Use
- OpenAI Computer Use
- future provider-neutral replacements

Rules:
- never primary when a better semantic executor exists;
- inherits the same JARVIS ActionProposal/AuthorityService boundary;
- provider safety signals supplement but do not replace JARVIS authority;
- bounded step count and screenshots;
- post-action verification required when the result can be observed.

## 5. Capability resolution

The brain may reason about the user's goal, but capability ownership and authority remain JARVIS-owned.

Proposed flow:

```text
canonical USER goal
        |
        v
Goal / Task Planner
        |
        v
Capability Resolver
        |
        +-> one capability
        |      or
        +-> bounded workflow of capabilities
        |
        v
Executor Resolver for each capability
        |
        +-> native/API
        +-> connector/App Action
        +-> structured specialist
        +-> visual fallback
        |
        v
PreparedCapability / PreparedWorkflow
        |
        v
canonical ActionProposal(s)
        |
        v
AuthorityService
        |
        v
one-time permit(s)
        |
        v
execute
        |
        v
verify observable outcome
        |
        v
return truthful result
```

## 6. Workflow model

A user request may require more than one capability.

Example:

`Open Apple Music, play Kesariya, and set volume to 25%.`

Possible workflow:

1. `app.lifecycle.launch(apple_music)`
2. if a semantic media-search executor exists, use it; otherwise `app.ui` searches/selects Kesariya
3. `media.playback` verifies/controls playback
4. `system.audio.set_volume(25)`
5. verify playback state and final volume

The user never needs to know this decomposition.

Workflow execution must remain bounded. A workflow is not permission to improvise unrelated steps.

## 7. Authority model

The existing Step-3/Step-7 authority system remains canonical.

Examples:

- routine status read: T0 where existing policy permits;
- private reads: current strong Windows Hello/T3 bridge while T2 is disabled;
- reversible local UI changes: current strong Windows Hello/T3 bridge while T2 is disabled;
- persistent writes/external sends: explicit/strong approval according to canonical risk policy;
- destructive/security/executable changes: critical hard floor;
- self-modification/authority/audit changes: restricted development-only path.

No capability family may invent its own approval system.

## 8. Discovery strategy

JARVIS should combine:

1. built-in stable capability descriptors;
2. runtime discovery of available native executors;
3. Microsoft winapp schema discovery;
4. Windows App Actions when consumable on the owner machine;
5. Windows ODR/MCP connectors when the owner OS exposes them;
6. explicitly installed provider/service connectors later.

Research finding 2026-09-09:

- Windows App Actions provide atomic app functionality that can be registered for consumption by other Windows experiences;
- Windows MCP/ODR provides a secure registry for discoverable MCP connectors and includes Windows connectors such as File Explorer, but Microsoft documentation still marks this area prerelease;
- therefore ODR/App Actions are future-compatible discovery/executor sources, not required foundations for the current owner machine.

## 9. Implementation strategy

Do not attempt to implement every capability in one giant PR.

Implement **one common Hands architecture**, then add mature specialist executors in capability waves.

### Wave H0 — Architecture and contracts

Deliver:
- stable semantic capability taxonomy
- executor ranking contract
- workflow plan/result model
- capability/executor availability registry
- authority binding unchanged
- explicit fallback semantics
- verification contract

Acceptance:
- planner cannot bypass capability/executor resolver
- executor cannot broaden authority
- visual fallback is never selected when a higher-priority suitable executor is available

### Wave H1 — Core local hands

Implement/prove:
- `app.lifecycle`
- `app.ui` via Microsoft winapp
- `window.management`
- `system.audio`
- `media.playback`
- `system.clipboard`

Why first:
- these produce immediate daily value;
- they cover Apple Music/media, volume, ordinary Windows app use, clipboard, and window management;
- mature Windows APIs already exist.

Owner acceptance examples:
- `Open Notepad and type JARVIS has hands.`
- `Move Notepad to the second monitor.`
- `Set volume to 25 percent.`
- `Pause the current music.`
- `What song is playing?`
- `Copy this exact text to my clipboard.`

### Wave H2 — Files and documents

Implement/prove:
- `files.write`
- `documents.edit`

Acceptance examples:
- create a folder/file in an approved root;
- rename/move a file;
- edit a document/spreadsheet through the best semantic backend;
- verify persistence and rollback/recovery behavior.

### Wave H3 — Browser

Implement/prove:
- Playwright-backed browser execution
- downloads/uploads/forms with bounded authority
- visual fallback only when structured browser semantics fail

### Wave H4 — Devices/connectivity

Implement/prove:
- Bluetooth discovery/pairing state
- approved peripheral controls
- additional smart/network device adapters

### Wave H5 — Productivity/communication/development

Integrate specialist capabilities already assigned to later product slices:
- tasks/reminders
- calendar
- email/messages
- coding/project operations
- package/software management

These should plug into the same Hands workflow architecture rather than create new control planes.

## 10. PR #30 disposition

PR #30 is useful work but must not be represented as complete JARVIS Hands.

Keep and reshape it as the first implementation of:

- `app.lifecycle`
- `app.ui`
- visual desktop fallback adapter
- shared authority/verification integration

Before merge:

1. rename/reframe capability ownership away from `windows:desktop.control` as the universal hand;
2. complete deterministic plan grounding so model-generated steps cannot broaden the user's request;
3. keep shell/browser/file-write/security/save/send/delete/install/coding actions outside this executor;
4. add H0 contracts needed for executor selection;
5. run automated tests and owner-machine acceptance;
6. merge only as **Hands H0/H1 app-control foundation**, not as completion of the full Hands goal.

## 11. Definition of Hands completion

Hands is not complete merely because Notepad can be controlled.

The broader Hands initiative is mature when:

- the owner can express goals naturally rather than name tools;
- common computer actions resolve to appropriate semantic capabilities;
- native/specialist executors are preferred over UI imitation;
- multiple capabilities compose into bounded workflows;
- authority is proportional and canonical;
- execution is verified before success is claimed;
- unsupported operations fail truthfully rather than hallucinating completion;
- new apps/devices/services can add adapters without changing the core brain/authority architecture;
- daily computer use can be delegated to JARVIS with manual intervention becoming the exception rather than the normal path.

## 12. Immediate next action after owner approval

1. Finish H0 contracts on `feat/governed-jarvis-hands-v1`.
2. Refactor PR #30 into `app.lifecycle` + `app.ui` rather than universal desktop control.
3. Implement native H1 adapters for media playback, audio, clipboard, and window management.
4. Add capability/executor resolution and bounded multi-capability workflow execution.
5. Run CI.
6. Run owner-machine H1 acceptance scenarios.
7. Correct failures.
8. Reconcile docs and merge only after explicit owner acceptance.
