# Hybrid JARVIS HUD (owner visual review candidate)

This is a **new visual surface**, not a replacement assistant. It combines the
3D reactor visual from `thisisreyy/jarvis` with the angular HUD treatment of
`Navaneeth1324/jarvis-ai-assistant` under their MIT licenses. The original
Python/LiveKit JARVIS continues to own voice, memory, Work, identity, vision
and all capability authority. The previous PR #297 UI was later merged into
`main` through a Windows synchronization, so the old UI files and their
UI-only tests are explicitly replaced rather than layered underneath this HUD.

The UI is **not production/Windows accepted** until the owner inspects it.
It is opt-in and bound to loopback. It cannot send commands or retrieve audio,
transcripts, owner data, passwords, memory, work payloads or camera frames.

## Contextual hybrid integration (26 October 2026 candidate)

The read-only bridge now projects version 2 telemetry from the **original**
runtime. It is not an alternate assistant and does not perform actions.

| Panel | Canonical source | Actual display |
| --- | --- | --- |
| Reactor/status | Voice runtime lifecycle | Standby, activating, listening, thinking, speaking, recovering, offline; no fabricated audio input |
| Work Matrix | SQLite WorkItem + `estimate_work` + durable routing decisions | Type, state, approximate progress/milestone, available ETA, last chosen route target |
| Owner attention | Work state `waiting_for_owner` | Highlighted mission and banner advising use of the existing voice interaction |
| Live Activity | In-memory allowlisted observer of accepted conversation turns, capability outcomes and interactive research results | Fixed labels/status/timestamps, up to 12; no user text or result bodies |
| Vision | VisionService diagnostics | Camera running, **frame freshness**, tracked person count and target **visible/following/searching** only from a fresh frame; never claims a verified owner lock |
| Intelligence | Current runtime configuration/presence | Voice model, research provider, Work route configuration, optional feature states |
| Health | SelfAwarenessRuntime | Bounded component IDs and allowed health states |

`connected` now describes a live **runtime link**, not a currently working
realtime voice conversation. Voice can be offline while durable Work or other
health remains visible. Missing Work/vision reads become degraded rather than
false idle success. The browser checks v2 types/limits and displays a safe
preview if the API is missing, malformed, or stale for ten seconds.

The activity feed holds only approved event kinds, fixed labels, allowed
outcome states, and UTC timestamps. It is a bounded **ephemeral** projection;
canonical conversation, Work, audit, memory and owner identity still live in
their original services. Work descriptions, private documents, URLs, search
queries, credentials, raw memory and camera frames never enter the JSON API.

Work models in the sidebar are marked **configured**. A per-mission **route
decision** is presented separately if a durable model-routing decision exists;
neither means the model has finished executing. Progress is approximate unless
the canonical estimator marks it exact.

**No typing, Execute, Pause, Cancel, Approve or Deny API exists.** Adding these
would require a separately tested authenticated owner-bound local session,
CSRF defense, replay/currentness checks, and existing Authority/Windows Hello
permit consumption. A localhost browser page by itself is not owner authority.

## Mark I arc reactor visual direction

The owner chose the original *Iron Man* (2008) cave-built **Mark I** look:
ten copper winding packs, stepped and blackened metal rings, exposed rivets,
three structural braces and a screened, blue-white concentric emitter. The
metal housing no longer spins; JARVIS listening/thinking/speaking affects the
light output only. GPU: LOW has a matching static schematic. All details
are procedurally modeled and ship inside the existing offline frontend bundle.
Visual fidelity and frame rate still require owner-machine review.

## Preview the HUD without a running JARVIS

After checking out this feature branch and updating the Python install in the
existing virtual environment:

```powershell
python -m pip install -e ".[dev]"
jarvis-ui --open-browser
```

Visit `http://127.0.0.1:8765` in Edge or Chrome. The preview is intentionally
labeled **PREVIEW / NO RUNTIME**. Work, health and voice indicators cannot
claim live data without an actual connection.

## Run HUD alongside the original voice runtime

```powershell
$env:JARVIS_UI_ENABLED = "true"
$env:JARVIS_UI_PORT = "8765" # optional
jarvis-voice
```

Open `http://127.0.0.1:8765` in a browser. Turn the UI off by removing or
setting `JARVIS_UI_ENABLED=false`. An unavailable UI port is a logged warning;
JARVIS voice runs as normal. The standalone preview and integrated voice
runtime cannot own the same UI port simultaneously.

Use **GPU: LOW** for the lightweight, CSS-only reactor. **FOCUS MODE** hides
status sidebars. Those buttons alter only local display state; no original
JARVIS capability is called. Browsers with `prefers-reduced-motion` automatically
use the CSS reactor. There is no frontend microphone or speaker subsystem.

If Work, Vision, personal context, memory or learning is disabled by your local
`JarvisConfig`, the HUD must report the disabled/unavailable state rather than
simulating a running subsystem. `reminder` is an internal Work type, not proof
that the planned reminder/calendar/email product features are available.

## Develop or rebuild the frontend

```powershell
cd frontend\jarvis-hud
npm ci
npm test
npm run build
```

The Vite build emits an offline static bundle directly into
`src/jarvis/ui/assets/`. Commit those built assets with source changes because
the Windows end-user install does **not** require Node.js. The MIT license
notices are in `frontend/jarvis-hud/public/THIRD_PARTY_NOTICES.txt` and copied
into the bundle. Running Vite dev mode proxies `/api` to the Python server.

Python checks:

```powershell
python -m pytest tests/test_hybrid_ui.py
ruff check src/jarvis/ui tests/test_hybrid_ui.py
```

## Owner-machine acceptance checklist

- [ ] At 3440 × 1440, reactor is centered and visible; panels are peripheral.
- [ ] At 1920 × 1080, nothing overlaps and interactions remain readable.
- [ ] At a narrow viewport, reactor and cards stack without horizontal clipping.
- [ ] WebGL and LOW-GPU fallback both look intentional, with no flashing.
- [ ] Wake, listen, think, respond, recover and standby mirror **actual** LiveKit state.
- [ ] Voice/audio, provider, Work, memory, Windows Hello and all existing
      JARVIS owner capabilities behave exactly as before with HUD enabled.
- [ ] A disabled Work service is labeled disabled, not an empty success list.
- [ ] A voice outage leaves active Work/health visible; any adapter outage does
      not stop the original runtime.
- [ ] A real Research or Hands action produces bounded event metadata without
      exposing private text, arguments, Windows paths or credentials.
- [ ] A Work item requiring owner input is highlighted but cannot be approved
      from the browser; Windows Hello and original Authority behavior remain intact.
- [ ] With HUD disabled or the port occupied, original JARVIS remains usable.
- [ ] Windows resource impact and UI GPU consumption are acceptable.

Do not merge the protected `main` branch based on source/tests alone; the
Windows visual and hardware acceptance is deliberately still open.
