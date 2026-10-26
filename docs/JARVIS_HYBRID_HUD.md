# Hybrid JARVIS HUD (owner visual review candidate)

This is a **new visual surface**, not a replacement assistant. It combines the
3D reactor visual from `thisisreyy/jarvis` with the angular HUD treatment of
`Navaneeth1324/jarvis-ai-assistant` under their MIT licenses. The original
Python/LiveKit JARVIS continues to own voice, memory, Work, identity, vision
and all capability authority. The old unmerged UI experiment (PR #297) was
not reused.

The UI is **not production/Windows accepted** until the owner inspects it.
It is opt-in and bound to loopback. It cannot send commands or retrieve audio,
transcripts, owner data, passwords, memory, work payloads or camera frames.

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
- [ ] With HUD disabled or the port occupied, original JARVIS remains usable.
- [ ] Windows resource impact and UI GPU consumption are acceptable.

Do not merge the protected `main` branch based on source/tests alone; the
Windows visual and hardware acceptance is deliberately still open.
