# JARVIS Hybrid Holographic HUD — Design

Status: owner-directed implementation candidate; **not** production/Windows accepted.

## Intent

Replace the rejected visual design in draft PR #297 with a useful, cinematic
JARVIS interface adapted from MIT-licensed `thisisreyy/jarvis` (3D reactor)
and `Navaneeth1324/jarvis-ai-assistant` (HUD shell). Keep `JARVIS_V1`'s
Python/LiveKit voice, canonical turns, memory, Work, identity, and Authority
unchanged and authoritative. The older repository `gkgajendra0/JARVIS` is
reference-only. PR #297's old UI code subsequently arrived in `main` via the
Windows sync; this replacement deliberately removes its assets, adapter and
associated UI-only tests while retaining all unrelated newer runtime changes.

## Experience

- Desktop-first, local Windows viewport with a centered 3D reactor, breathing
  idle animation, and truthful listening/thinking/speaking/recovery states.
- Ambient view remains uncluttered; translucent side rails and context cards
  show only confirmed available information or explicitly labeled preview data.
- Adapt #2's top HUD, geometric glass-card treatment and restrained cyan/gold
  palette around #1's orbitable reactor; never run two reactor renderers.
- Usable at 3440x1440, 1920x1080 and a narrow viewport. Offer an accessible
  CSS fallback, reduced motion and a low-GPU visual mode.
- Local display controls (panel toggle, visualization quality) cannot trigger
  JARVIS capability execution or extend an approval.

## Runtime boundary

- React/Vite/TypeScript frontend is packaged as local static assets by Python.
- A small opt-in `jarvis.ui` read-only HTTP bridge binds to `127.0.0.1`.
  `/api/snapshot` contains an allowlisted, bounded status projection; there
  are no action or data-mutation endpoints.
- Voice state comes from existing lifecycle/agent-state observations;
  Work and health snapshots come from existing canonical stores/observers.
- No browser microphone, speaker/TTS, provider calls, credentials, canonical
  transcript export, private memory, camera frames or arbitrary tool output.
- Standalone `jarvis-ui --open-browser` works with no cloud key, marked
  `PREVIEW / NO RUNTIME`. Production integration is opt-in with
  `JARVIS_UI_ENABLED=true jarvis-voice` and cannot block voice startup/failure.
- Reject forged Host headers, path traversal, browser mutations, and nonlocal
  access. Add restrictive CSP. Limit API values and never expose private text.

## Non-goals

No replacement assistant engine, remote/mobile access, voice-command input
from the browser, new memory/advice behavior, unapproved work execution,
calendar/email/notes, public hosting, or Windows overlay packaging in this
candidate. Owner-machine visual/performance/live acceptance is still required
before protected-main merge.

## Approaches and decision

1. **Chosen:** Vite React SPA + local read-only Python bridge. Minimal runtime
   coupling; #1's GPU scene remains optional and #2's HUD is portable.
2. Full Next.js application from #2: adds a second server/runtime with no
   value for the local UI and risks replacing JARVIS's existing authority.
3. Electron first: desktop overlay possible later, but adds process and
   lifecycle overhead before core UI quality is accepted.

## Acceptance

Build/test frontend; Python unit/HTTP integration tests; packaged CLI smoke;
desktop/narrow screenshot checks; no backend behavior regression; MIT license
notices retained. Live microphone/hardware tests remain owner-machine gates.
