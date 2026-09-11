# JARVIS Generic Desktop Agent Implementation

Status: **IMPLEMENTED ON `feat/governed-jarvis-hands-v1` — OWNER-MACHINE ACCEPTANCE PENDING**

Date: 2026-09-11

## Goal

JARVIS Hands must not grow as a collection of app-specific scripts. The owner should be
able to state a computer outcome naturally through voice; JARVIS should discover the
relevant capability, use the strongest available control substrate, observe the result,
and adapt without requiring the owner to provide selectors or click-by-click steps.

This implementation therefore treats Apple Music, VS Code, Calculator and future desktop
applications as instances of the same generic desktop-control problem.

The product target is broad control of normal owner-requested Windows workflows, not
unrestricted machine authority. Credential/secret handling, security or permission changes,
arbitrary terminal/shell execution, destructive/irreversible work and other critical domains
remain dedicated governed capabilities or truthful refusal boundaries.

## Research basis

The implementation follows patterns used by current production-oriented computer agents:

- Microsoft Research UFO2 (May 2026) combines a host/task coordinator with native APIs,
  Windows UI Automation and vision-based parsing instead of relying on screenshots alone:
  https://www.microsoft.com/en-us/research/publication/ufo2-the-desktop-agentos/
- Microsoft `winapp` exposes Windows UI Automation as a machine-readable application UI
  substrate suitable for inspection, search and structured interaction:
  https://learn.microsoft.com/en-us/windows/apps/dev-tools/winapp-cli/ui-automation
- LiveKit documents that normal tools continue running when the user interrupts and that
  duplicate calls default to `allow`; mutation cancellation is intentionally opt-in because
  stopping a write midway can be unsafe:
  https://docs.livekit.io/agents/logic/tools/async/
- LiveKit's tool-loop guidance recommends keeping correctness and loop bounds in code rather
  than relying on nondeterministic model behavior:
  https://docs.livekit.io/agents/logic/tools/design/
- OpenAI's Responses platform supports computer-use actions and screenshot feedback, giving
  JARVIS a provider-backed visual fallback when structured control is insufficient:
  https://platform.openai.com/docs/api-reference/responses-streaming

## Implemented control hierarchy

For a natural-language computer goal JARVIS prefers, in order:

1. native operating-system or application semantics where already available;
2. dedicated integrations/connectors;
3. Playwright for web/browser tasks;
4. Windows UI Automation for generic desktop application UI;
5. active-provider visual Computer Use only after structured desktop evidence is
   insufficient for the same bounded task;
6. truthful failure or owner clarification when no safe path can proceed.

Visual control is not an app-specific fallback. It is a generic substrate behind the same
capability and Authority boundaries.

## Generic desktop loop

```text
voice request
    |
    v
canonical USER utterance generation
    |
    v
turn transaction / lease
    |
    v
semantic Hands routing
    |
    v
native / browser / UIA executor
    |
    v
observe result
    |
    +--> verified goal complete --> return truthful result
    |
    +--> insufficient UIA evidence --> window-scoped visual Computer Use
    |                                  |
    |                                  v
    |                         target-window screenshot
    |                                  |
    |                           bounded input action
    |                                  |
    |                         target-window re-observe
    |                                  |
    +----------------------------------+
    |
    v
bounded replanning or truthful stop
```

## Voice-turn transaction guarantees

Realtime provider timing must never decide which spoken command owns a mutation.

The canonical conversation assigns monotonically increasing USER utterance generations when
user speech begins. Pending generations are queued FIFO so a delayed provider transcript is
attached to the utterance that actually produced it rather than to whichever utterance is
newest when the transcript arrives.

The voice Hands tool then:

- waits briefly for the canonical transcript belonging to the current speech generation;
- never reuses the previous USER turn merely because the current transcript is late;
- claims a generation at most once, so duplicate Hands calls cannot execute the same spoken
  command twice;
- serializes Hands goals within a voice session;
- treats older work as `superseded` when a newer USER utterance begins;
- checks the lease before cloud routing, after cloud routing, before/after planning and
  immediately before each local action;
- does not cancel an atomic local mutation that has already started; newer speech prevents
  the next action from starting instead.

This removes the class of failure where a volume action from turn N can leak into an
unrelated turn N+1.

## Efficient structured desktop planning

Desktop application handling remains observation-first, but one observation no longer forces
one cloud round trip per click.

The Hands planner is instructed to inspect/search the live accessibility tree instead of
guessing unseen selectors. Once the current UIA observation grounds several immediately
dependent controls, the planner may return one bounded micro-plan containing multiple local
steps plus a final observation/verification step. The micro-plan stops at the first point
where a genuinely new UI state must be observed before the next target can be chosen.

This preserves the generic observe -> act -> observe -> verify architecture while reducing
latency, provider token traffic and unnecessary cloud calls.

## Generic UIA and visual recovery

Visual Computer Use is withheld from the planner before the first structured UI observation.
After UIA has produced an observation, the visual operation becomes available for the same
bounded app goal. The planner may switch to it when UIA is empty, sparse, inaccessible or
fails to make verified progress.

There is no Apple Music, Spotify, VS Code or other per-application fallback condition in this
transaction layer.

The visual fallback is now **window-scoped rather than whole-desktop-scoped**:

- the active provider receives a screenshot of the resolved target application's current
  top-level window rather than the complete virtual desktop;
- the local executor stores the HWND and rectangle that produced each screenshot;
- coordinate actions must remain inside that rectangle;
- the same HWND/rectangle must still own the action when input executes;
- the target must remain foreground for keyboard or pointer input;
- Windows-key shortcuts, Alt-Tab, Task Manager and secure-attention shortcuts are rejected;
- if the app moves, resizes, changes top-level window identity or loses safe focus between
  observation and action, execution fails closed and requires a fresh observation.

Modal/top-level transitions can still proceed safely across provider turns: after one action
changes the target application's active top-level window, the next screenshot establishes a
new HWND/rectangle before another input action is accepted.

## Risk handling for unknown GUI workflows

JARVIS does not ask the model to classify the risk of an unknown visual GUI action.

Generic visual fallback is conservatively classified as **persistent/external** through
JARVIS-owned `ActionAttributes`, even when a particular visual task might only be a private
read or reversible local change. This gives the canonical Authority service a deterministic
hard floor before any provider-backed Computer Use begins.

That fallback can therefore support ordinary explicitly requested app-local workflows such
as save, export, send, share, print, upload and download when UIA cannot complete them.

The generic visual substrate still rejects critical/destructive domains such as:

- arbitrary PowerShell/Terminal/Command Prompt or Registry operation;
- software installation/uninstallation;
- security/permission changes;
- credentials, passwords, API keys, access tokens or secret material;
- destructive/permanent deletion and comparable irreversible operations;
- direct browser control, which remains owned by the dedicated Playwright capability;
- File Explorer and Windows Settings targets, whose broad system reach requires dedicated
  governed semantics rather than generic visual authority.

## Verification semantics

Verification remains stricter for mutation than observation:

- a successful read-only UIA plan (`inspect`, `search`, `get_value`, `verify_value`) is valid
  evidence for a read/inspection goal;
- clicking, invoking, typing or changing state is not considered verified merely because an
  input command was accepted;
- a mutating UIA micro-plan may become verified when successful observation steps follow its
  final mutation in the same bounded local plan;
- naked mutations without post-action observation remain unverified;
- window focus uses bounded eventual-state polling because Windows foreground activation is
  not reliably observable in the same instant as the focus request;
- an identical unverified action may not be repeated indefinitely; the bounded planner must
  re-observe, change substrate, clarify, or stop truthfully.

## Safety and privacy boundaries

Generic computer control does **not** mean unrestricted shell authority.

Existing JARVIS Authority/Windows Hello rules remain canonical. Dedicated governed
capabilities continue to own file writes, documents, software management, development
operations, browser workflows and other consequential domains.

Screenshot-based Computer Use remains an explicit machine-level opt-in because the selected
cloud provider receives visual evidence for the target application window. The setting is now
persisted in the non-secret JARVIS machine profile rather than depending on one shell session:

```text
JARVIS_VISUAL_COMPUTER_USE_ENABLED=true
```

Owner controls:

```powershell
jarvis-hands-smoke --enable-visual
jarvis-hands-smoke --show-visual
jarvis-hands-smoke --disable-visual
```

When enabled, target-window screenshots required by a visual task may be sent to the currently
selected cloud AI provider. With `JARVIS_AI_PROVIDER=openai`, that means OpenAI. When disabled,
native, Playwright and UIA paths remain available but JARVIS stops truthfully if a desktop task
cannot progress without visual fallback.

The unified `jarvis[hands]` extra includes the Windows screenshot/input dependencies used by
this fallback, so a separate computer-use dependency install is not required.

## Realtime token and latency controls

The voice boundary now returns a compact Hands result to the realtime model rather than the
full multi-step execution trace. Final useful result/observation evidence is retained while
older internal trace material stays inside JARVIS.

The OpenAI Realtime adapter also uses the provider's retention-ratio truncation mechanism to
bound long-session context growth. Provider rate-limit classification recognizes token-rate
failures even when the surrounding LiveKit exception lacks an HTTP status code.

JARVIS intentionally does not blindly replay a whole voice turn after a token-rate failure:
a replay could duplicate a local mutation. Retry behavior must remain bounded to operations
whose idempotency is explicitly known.

## Automated regression coverage

The branch covers these generic invariants in CI:

- delayed current transcript cannot cause Hands to reuse an older USER command;
- a newer speech generation supersedes stale pending work;
- duplicate Hands calls for one generation execute at most once;
- a stale goal cannot start another local action;
- a new utterance arriving during a cloud planning boundary invalidates the old result;
- visual desktop control is hidden until structured desktop observation has been attempted;
- semantic route selection is not re-inflated with unrelated operation groups at the voice
  planner boundary;
- successful structured reads become verified observation evidence;
- a mutating UIA micro-plan with trailing successful observation can become verified;
- naked unverified structured mutations remain unverified;
- transliterated multilingual numeric speech can ground reversible local controls without
  relaxing strict high-risk grounding;
- desktop/screen inspection routes to Hands rather than physical Pocket3 camera vision;
- window-scoped Computer Use captures only the target app rectangle;
- out-of-window coordinates, stale/moved windows and global app-switch shortcuts fail closed;
- generic visual fallback is authority-classified persistent/external;
- ordinary save/export/send-style visual goals are allowed while critical/destructive visual
  intents remain blocked;
- the visual opt-in round-trips through persisted machine configuration;
- existing provider, authority, Hands, browser, Windows dependency, DPAPI and Windows Hello
  regression suites remain part of the full repository CI.

## Completion boundary

The generic desktop-agent implementation is code-complete only when the exact branch head
passes all automated repository gates. Product acceptance still requires owner-machine voice
tests because real Windows applications expose different accessibility trees, window/modal
transitions and visual states.

Owner-machine acceptance should deliberately use multiple unrelated applications and rapid
follow-up/interrupt scenarios, plus at least one workflow that forces UIA -> window-scoped
visual fallback. A result is not evidence of genericity if it only proves one app-specific
workflow.
