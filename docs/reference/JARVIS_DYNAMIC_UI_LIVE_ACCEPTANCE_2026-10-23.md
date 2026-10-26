# JARVIS Orb-first UI — Integrated live acceptance

Status: **GitHub candidate**; the presence of code/CI does not constitute Windows microphone, camera, or performance acceptance.
Date: 2026-10-23

## Runtime truth

The optional local UI runs on `127.0.0.1` and has no privileged mutation endpoint. It shows **read-only** projections of existing Jarvis runtime evidence, never a parallel brain, implicit permission grant, or source of truth.

| Visual behavior | Real origin | What is intentionally NOT exposed |
| --- | --- | --- |
| Animated listening / thinking / speaking orb | LiveKit agent/user lifecycle callbacks | No PCM, audio history or automatic transcription publication |
| Automatic visual topic hint | Accepted canonical USER turns (bounded topic match, no transcript retention) | No general generative recommendation engine yet |
| Work cards and task states | `WorkRuntime.store.list_recent` | No Work request body, secrets, internal step payload |
| Vision panel | `VisionService.report` and `VisionService.running` | No camera frames, tracked faces, enrollment templates or coordinates |
| System health panel | `SelfAwarenessRuntime.system_snapshot(health_surface_only=True)` | No incident details, log records, environment variables or exact sensitive evidence |
| Research result panels | `ResearchAgentTools.research` completed tool payload | No raw user query, excerpts, URL query parameters or non-public links |
| Action outcome indicator | Existing governed `CapabilityResult` observer | No tool arguments, action payload, private documents, authority modification |
| Manually projected info/visual panel | Browser-local selection from typed UI controls | Does not execute Jarvis tools or feed untrusted text to the LLM |

Future integration (not claimed working by this candidate): camera video streaming, document preview release decisions, interactive maps, private-memory viewer, approval dialogs, true microphone-amplitude waveform, a generative relevance agent or calendar/email integration. These require explicit source and Authority/privacy contracts; do not fabricate live content to fill a widget.

## Isolated Windows smoke test (do NOT disrupt the Gemini fallback branch)

**Important:** Do not run two live JARVIS voice processes simultaneously (microphone, camera and WorkStore ownership). Stop any old standalone UI process bound to `8765` first. Confirm the original Gemini development branch has its own clean commit/push before changing it; these commands do not touch that branch.

Open a fresh PowerShell in `C:\Users\gkgaj\Desktop\jarvis_v1_ui_preview`:

```powershell
cd C:\Users\gkgaj\Desktop\jarvis_v1_ui_preview
git status --short
git fetch origin
git switch --detach origin/feat/dynamic-context-ui-phase1-20261023
$env:PYTHONPATH = (Resolve-Path .\src).Path
$env:JARVIS_UI_ENABLED = "true"
$env:JARVIS_UI_PORT = "8765"
& ..\jarvis_v1\.venv\Scripts\python.exe -m jarvis.voice.production_runtime
```

If the virtual environment does not exist, locate and activate the actual Jarvis environment first. **Do not** install dependencies globally into Python 3.14 or alter the Gemini fallback checkout just to make this UI work.

In a browser, open `http://127.0.0.1:8765/`. The badge must say **JARVIS RUNTIME LINKED** (not **UI PREVIEW • NO RUNTIME**). If it remains in preview mode, verify that the voice process is active, `JARVIS_UI_ENABLED` is set *in that process*, and another standalone server does not own port 8765.

## Owner acceptance sequence

1. **Ambient:** no large cards; orb stays centered with subtle real animation; avoid permanently shown dashboards.
2. **Visual only:** select PREVIEW; observe panels materialize outward from orb, connect by energy beams and retract on dismiss. Test radial palette, pin, clear, Cinematic/Balanced/Eco, reduced motion, resizing.
3. **Connected truth:** while voice runtime is alive, status badge says RUNTIME LINKED and shows actual idle/listening/thinking/speaking states; never falsely claims live audio levels.
4. **Work:** ask Jarvis about background work; after an accepted canonical USER turn, work context is projected. Work states must match actual WorkStore, never fabricated.
5. **Research:** explicitly request current web research; after the real research tool completes with qualifying HTTPS sources, a source panel should materialize. Research is untrusted evidence; opening a source requires an owner click.
6. **Vision:** request/show camera diagnostics; UI shows whether vision is running and which source is selected. It must **not** claim to show a camera feed.
7. **System:** request health/status; UI shows sanitized Self Model component states. Unavailable diagnostics should be marked unavailable, not healthy.
8. **Hands/capabilities:** initiate a harmless, already-authorized action via the normal voice tools; a bounded status card may appear, but UI must never execute the action itself.
9. **Failures and reconnection:** stop the voice process; status reverts to offline, no raw browser exception or stale 'live' state. Restart and observe recovery.
10. **Performance:** measure frame rate, CPU/GPU utilization and voice interruption on the actual owner's 34-inch ultrawide, Ryzen/Intel/RTX configuration. The WebGL/Canvas rendering should be throttled when hidden. Prefer Eco if GPU competition is observed.
11. **Privacy:** check no user transcript, raw research query, camera image, personal memory, credential or tool result payload appears in developer network response. UI must not circumvent owner Authority.

## Verification levels and merge policy

- **Unit/browser CI:** deterministic local projections, escaped text, browser rendering, screen geometry, animation and pin/dismiss regression, result-source filtering, Linux/Windows suites where the CI runner permits.
- **Owner-machine hardware:** a separate required acceptance gate. CI cannot prove camera/microphone drivers, Gemini model/realtime handoff, animation smoothness or Windows overlay/window capture on this PC.
- **Cross-branch integration:** Gemini Free/Paid fallback and UI currently live on separate branches. Do not replace the owner's Gemini code, hard reset or forcibly merge unreviewed changes. Reconcile branches once their individual tests pass.
- **Promotion:** Keep PR #297 in draft until a live Windows visual + runtime session passes and ownership boundaries are reviewed. Never silently merge protected main.
