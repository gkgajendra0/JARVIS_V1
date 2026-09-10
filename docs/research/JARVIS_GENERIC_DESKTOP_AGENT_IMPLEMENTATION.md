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
    +--> insufficient UIA evidence --> visual Computer Use fallback
    |                                  |
    |                                  v
    |                            screenshot -> act -> re-observe
    |                                  |
    +----------------------------------+
    |
    v
bounded replanning or truthful stop
```

## Voice-turn transaction guarantees

Realtime provider timing must never decide which spoken command owns a mutation.

The canonical conversation now assigns monotonically increasing USER utterance generations
when user speech begins. Pending generations are queued FIFO so a delayed provider transcript
is attached to the utterance that actually produced it rather than to whichever utterance is
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

## Generic UIA and visual recovery

Desktop application handling is observation-first.

The Hands planner is instructed to inspect/search the live accessibility tree instead of
guessing unseen selectors. After a structured observation it may perform a small grounded
UI action and re-observe/verify the result.

Visual Computer Use is withheld from the planner before the first structured UI observation.
After UIA has produced an observation, the visual operation becomes available for the same
bounded app goal. The planner may switch to it when UIA is empty, sparse, inaccessible or
fails to make verified progress.

There is no Apple Music, Spotify, VS Code or other per-application fallback condition in this
transaction layer.

## Verification semantics

Verification remains stricter for mutation than observation:

- a successful read-only UIA plan (`inspect`, `search`, `get_value`, `verify_value`) is valid
  evidence for a read/inspection goal;
- clicking, invoking, typing or changing state is not considered verified merely because an
  input command was accepted;
- mutations still require post-action evidence before JARVIS may claim the requested result
  completed;
- an identical unverified action may not be repeated indefinitely; the bounded planner must
  re-observe, change substrate, clarify, or stop truthfully.

## Safety and privacy boundaries

Generic computer control does **not** mean unrestricted shell authority.

Existing JARVIS Authority/Windows Hello rules remain canonical. Dedicated governed
capabilities continue to own file writes, documents, software management, development
operations, browser workflows and other consequential domains.

Screenshot-based visual Computer Use remains explicit opt-in through:

`JARVIS_VISUAL_COMPUTER_USE_ENABLED=true`

When enabled, desktop screenshots required by a visual task may be sent to the currently
selected cloud AI provider. With `JARVIS_AI_PROVIDER=openai`, that means OpenAI. When the flag
is disabled, native, Playwright and UIA paths remain available but JARVIS stops truthfully if
a desktop task cannot progress without visual fallback.

The unified `jarvis[hands]` extra now includes the Windows screenshot/input dependencies used
by this fallback, so a separate computer-use dependency install is not required.

## Automated regression coverage

The branch now covers these generic invariants in CI:

- delayed current transcript cannot cause Hands to reuse an older USER command;
- a newer speech generation supersedes stale pending work;
- duplicate Hands calls for one generation execute at most once;
- a stale goal cannot start another local action;
- a new utterance arriving during a cloud planning boundary invalidates the old result;
- visual desktop control is hidden until structured desktop observation has been attempted;
- successful structured reads become verified observation evidence;
- unverified structured mutations remain unverified;
- existing provider, authority, Hands, browser, Windows dependency, DPAPI and Windows Hello
  regression suites remain part of the full repository CI.

## Completion boundary

The generic desktop-agent implementation is code-complete when the exact branch head passes
all automated repository gates. Product acceptance still requires owner-machine voice tests
because real Windows applications expose different accessibility trees and visual states.

The owner-machine acceptance phase should deliberately use multiple unrelated applications
and rapid follow-up/interrupt scenarios. A result is not evidence of genericity if it only
proves one app-specific workflow.
