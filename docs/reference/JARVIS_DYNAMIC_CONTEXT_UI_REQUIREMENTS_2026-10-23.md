# JARVIS Dynamic Context UI — Owner Requirements and Implementation Contract

Status: **OWNER-DIRECTED IMPLEMENTATION — candidate, not production accepted**
Date: 2026-10-23
Scope: UI shell, context-stage rendering, animated presence, and narrowly integrated runtime events. This document authorizes an implementation candidate, **not** protected-main promotion, weakening Authority, or claiming new backend capabilities.

## Owner's requirements (verbatim intent, normalized)

1. **Dynamic, not a static dashboard:** the main canvas is usually calm and mostly empty; no grid showing every capability all the time.
2. **Futuristic and alive:** premium dark/glass HUD, a continuously animated central JARVIS energy orb, responsive voice visualization, smooth transitions.
3. **Explicit visual commands:** "Jarvis, show/open/bring up X" should reveal the appropriate visual panel when an existing authorized capability can supply X.
4. **Implicit, conversation-context-driven visuals:** while discussing a topic, Jarvis may proactively bring up relevant visual evidence (a map for a route, sources for research, progress for development, camera for an authorized camera request) without clutter.
5. **Small always-present shell:** JARVIS identity, listening/thinking/speaking/idle state, current focus/active work and important alerts, plus a discoverable manual access path.
6. **Panels appear, update, minimize, pin, and disappear:** user-pinned content persists until unpinned; ephemeral context has freshness and lifecycle rules.
7. **One interface for current and future capabilities:** reusable typed renderers, not bespoke permanently visible dashboards for every integration.
8. **Owner hardware:** high-quality presentation on a Windows PC including 34-inch ultrawide, without starving 8-GB GPU vision, gaming, or local inference.

## Current capability truth (2026-10-23 `main`)

Source of truth: `docs/PRODUCT.md`, `docs/PROJECT_STATE.md`, `docs/CURRENT_ARCHITECTURE.md` and actual runtime modules; UI cannot invent capabilities.

| Domain | Existing accepted/bounded substrate | Initial visual affordance | Product limitation |
| --- | --- | --- | --- |
| Conversation/voice | LiveKit voice, wake lifecycle, canonical accepted turns | Orb state, transcript/answer **only when authorized and available** | Do not claim robust speaker attribution |
| Vision | Camera/OWNER tracking, diagnostics, switchable Lenovo/Pocket 3 | Camera/vision summary/status from trusted runtime | Camera frames require explicit UI camera source integration, never simulated live |
| Work | DBOS/WorkStore durable WorkItem, progress, delivery, priorities | Work progress/context panel driven by canonical Work records | Background automation != recurring scheduling |
| Hands | Governed Windows app, browser, files, bounded device actions | Action preview, progress/outcomes, capability availability | UI never bypasses Authority for execution |
| Research/files | Exa research; approved docs/files, code inspection | Source cards, document/code previews with provenance | Only show actual fetched results |
| Memory | Encrypted governed memory, limited opt-in personal context | Opt-in private context inspector with redaction | No automatic memory dump, no implicit learning |
| Self-awareness | Component health, diagnostics, incidents, repair foundation | Health/degradation/recovery cards | No unsupported autonomous repair claims |
| Calendar/email/notes/recurring automation | Formally planned product features | Typed future slots disabled/unavailable | Never show fabricated real appointments, emails or weather |
| Universal knowledge/discovery | Advanced north star | Later renderer extensions | Research intent, not current deployment |

## UX state machine

- **AMBIENT**: quiet animated orb with minimal rails. The screen must not fill itself with default dashboards. State is sourced from runtime evidence, otherwise `offline / demo` prominently labeled.
- **LISTENING**: orb/ring waveform reactive to incoming audio amplitude *only when the audio signal is actually available*. No false listening indicator.
- **THINKING / WORKING**: dynamic orb motion changes, relevant work card may appear.
- **SPEAKING**: brightness/waveform react to real playback signal if connected.
- **CONTEXT STAGE**: at most two large transient panels by default; newest relevant topic replaces stale unpinned content. Pinned panels survive topic changes.
- **ATTENTION / APPROVAL**: material failure or pending owner approval can interrupt low-priority context, with plain-language explanation and exact authority semantics.
- **DEGRADED / OFFLINE**: explicitly show no live connection; never generate pretend real-time events.

### Orb

A real continuously rendered animated orb, **not a static image or prerecorded loop**; subtle idle breathing/particle motion; clearer transitions listening/thinking/speaking/error. Orb reduces/moves aside while high-value content is on stage. Respect reduced motion, visibility throttling, reduced GPU modes and battery/performance constraints. Initial renderer can be offline-capable Canvas2D; future WebGL shaders may replace it behind the same state contract, benchmarked before adoption.

### Context panels

Typed schema: `id`, `type`, `title`, `summary`, `data`, `source`, `scope`, `observed_at`, `freshness`, `priority`, `expires_at`, `sensitivity`, `pin`, `provenance`. Supported initial safe types: work, research, document, vision-status, system-health, alert, generic info. Future types: map, rich media, calendar, email, home automation, private memory, approvals, source-cited web cards.

The model may propose an **intent** or **typed card request**, never arbitrarily inject HTML/JS, model-authored approval success, credentials, fabricated links or authority. The trusted backend resolves and validates the request against registered capability/data sources. Use textContent, not innerHTML for provider/user data.

Default lifecycle: owner-requested explicit card takes precedence; context-relevant card can replace *unpinned* card after a topic change; stale cards visibly degrade/disappear; `pin`/`dismiss`/`clear` are owner controls. Automatic popups are throttled/debounced and visually bounded. The UI is an observation surface, not a second source of truth.

## Security/privacy and trust boundaries

- UI is a presentation adapter. Canonical conversation, memory, Work, health, capabilities, identity and Authority stay in their current owners.
- Bind HTTP locally to `127.0.0.1`; read-only default. Reject non-loopback Host and cross-origin mutation attempts.
- No raw personal history, face templates, API keys, OS controls, camera streams, audio samples or secrets in default UI payload.
- Privileged/private panel must be separately approved and identity-bound; `pin` cannot extend data-release permits.
- All action requests still go through canonical CapabilityRuntime/Authority, never direct command execution from browser JavaScript.
- User commands and provider data must not create arbitrary UI code, browser navigations, hidden recording or persistence.
- Demo data must have explicit **DEMO** indicators. Never present samples as actual current state.
- UI disconnect or failure must never crash JARVIS voice or background Work.

## Runtime integration

Use a **single narrow presentation/event adapter** beside existing runtime ownership, not a second router/brain/memory store. Initial implementation:
1. Standalone, zero-cloud UI at localhost, responsive dark design and animated orb.
2. A typed bounded event/state feed with replay snapshot and monotonic sequence so browser reconnection is deterministic.
3. Optional integration with canonical voice/session state through observer callbacks and safe Work/health snapshots; no circular model calls.
4. Normal click controls for pin, dismiss, manual panels and visible mode switching.
5. Events of type `state`, `panel.show`, `panel.dismiss`, `panel.clear`, `work.update`, `system.alert` use validated schemas; no HTML payload injection.
6. Deferred: screenshot/camera streaming, model context suggestions, real media, private memory view, map/calendar/email connectors, desktop overlay/always-on-top packaging. Do not advertise them as implemented without proof.

## Visual design

- 16:9 and **3440x1440 ultrawide** layouts; right-side context stage; center orb as landmark when idle, relocates to a compact presence dock when stage is occupied.
- Futuristic midnight navy/near-black, restrained cyan/blue and violet highlights, thin glass borders; glow should highlight state, not every border.
- Use legible type, real contrast, keyboard access, focus styles, usable control targets, mobile/browser resize behavior; no animated text that hides important alerts.
- `prefers-reduced-motion` and frame throttling; no hard dependency on CDN or third-party fonts.
- Animation target: smooth 60fps on normal foreground hardware if available, lower FPS offscreen/idle; never run continuously in hidden tabs.

## Phase 1 (current implementation candidate)

Acceptance criteria:
- Running `python -m jarvis.ui` launches a loopback-only visual UI; no secrets, external services, paid models or DB required to start.
- Orb is continuously animated; reacts accurately to synthetic **test** state events and offline/live connection; reduced-motion fallback is present.
- Default ambient mode has **no large dashboard widgets**. One dynamic stage renders only requested or current events.
- Safe typed events support live context replacement, multiple panels, pin/unpin, dismiss and priority alerts, escaping any supplied text.
- A localhost-only status/events interface reports offline/connected truth, and a **developer-only** demo switch may populate labeled demo cards.
- Automated Python tests cover state validation, limits, invalid host, path traversal, event ordering, freshness and server endpoints.
- Browser smoke validates presentation, no JS errors, keyboard/pin/dismiss actions, reduced motion, 3440x1440 layout when available.
- No modifications to protected `main` before required verification/owner promotion. CI + actual owner-machine acceptance are distinct.

## Phase 2+ (after phase-1 evaluation)

- Wire canonical voice observer events (without accepting false turns) and Work/Health projections into adapter.
- Expose actual source-grounded research/document/camera visuals via existing capability contracts.
- Establish user-intent and discussion-context visual suggestions from canonical, permitted evidence, with relevance and hallucination tests.
- Add drag, resize, monitor placement and optional desktop always-on-top packaging after Windows acceptance.
- Follow capability milestones for Notes/Tasks, calendar, email, device controls, autonomous engineering and universal knowledge without static-dashboard rewrites.

## Non-goals / prohibitions

Not a replacement for the voice brain, Global Brain Router, capability registry, permission system or memory. Not a proof of automatic personal intelligence, scheduled automation, smart-home/calendar integrations, unrestricted shell access, and not a reason to permanently occupy several gigabytes of VRAM.


## Owner visual-direction correction — 2026-10-23 (UI-first)

The owner reviewed the first real browser preview and **rejected the lateral dashboard-like composition** where the orb shrinks and moves left and ordinary cards appear to its right. That composition is superseded. The correct visual contract is:

- **Orb-first center of gravity:** at desktop/ultrawide widths the orb's horizontal center must remain within 12 CSS px of the workspace center before and after projecting panels. The orb is never replaced by a card grid.
- **Materialization from the orb itself:** every new contextual panel originates visibly at the orb center as a bright point, extends into a narrow energy line, unfolds a holographic frame, then resolves its content with a glow/scan pass. Dismissals reverse toward that same origin. Pinned panels remain while other topics change.
- **Spatial arrangement:** one primary panel projects to the right; a second to the left, balanced around the central orb. Up to four pinned/priority panels may be displayed without becoming a standing dashboard. On narrow screens use a centered orb above a vertically scrollable panel stack rather than overflow.
- **Connected energy trails:** dynamically measured/positioned paths link the outer orb radius to the projected panel edges; they animate subtly rather than cluttering the content. Paths update on resize and do not pretend to represent network activity.
- **Interactive orb:** clicking/keyboard activation reveals optional radial quick controls for local visual presentation. These are not privileged execution tools or a second conversation brain.
- **Content-first presentation:** demo visuals include graphical structure, telemetry shapes, activity bands, and believable spatial layering. Every invented preview value remains explicitly marked SAMPLE / DEMO / NOT LIVE.
- **Frame-time awareness:** Cinematic/Balanced/Eco visual quality settings; `prefers-reduced-motion` disables projection travel and repeating decorative motion. Hidden tabs must not continuously redraw an expensive effect. Preview must not claim a real microphone waveform unless actual audio amplitude is supplied by an authorized adapter.
- **One coordinated owner preview at the end:** do not require the owner to reload/test every small commit. CI captures ambient and projected screenshots at 3440×1440 and 1920×1080 for visual review before final Windows-owner acceptance.

### UI-only freeze / explicit sequencing

The **current development priority is visual and interaction design only**: orb, spatial composition, animations, transitions, keyboard navigation, pin/dismiss lifecycle, adaptive sizes, accessibility and performance. Do not expand camera streaming, private-memory display, hands execution, personal learning, provider failover or autonomous orchestration in this workstream. Existing bounded opt-in adapters in the phase-1 branch remain isolated and must not silently activate. Full live Jarvis integration is a **separate phase after owner acceptance of UI quality**.

### Visual acceptance checkpoints

1. At 3440×1440 and 1920×1080, ambient scene has no large panel and the orb is horizontally centered; this stays true after opening two panels.
2. A fresh UI panel creates an orb-origin animation and connected beam, never a direct right-column pop-in.
3. Removing an unpinned panel retracts it; pin/unpin retains expected state and a change of topic does not erase pinned content.
4. The radial orb palette is keyboard and mouse accessible and never executes a real capability action.
5. On mobile/narrow width the presentation remains readable and scrollable, with no fullscreen overflow or controls obstructed.
6. Reduced-motion and Eco modes omit elaborate transitions, while all semantic content remains available.
7. Browser errors, failed network updates and reconnects leave Jarvis core unaffected; sample data remains visibly labeled.
8. Complete automated/UI smoke and GitHub checks, then exactly one owner-machine visual acceptance session before reopening deeper integration.
