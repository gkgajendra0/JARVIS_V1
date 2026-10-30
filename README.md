# JARVIS V1

**Current memory workstream — 31 October 2026:** [Project conversations and personal memory](docs/PROJECT_CONVERSATION_MEMORY.md) defines the owner-selected design, goals and acceptance contract. [Current Plan](docs/CURRENT_PLAN.md) owns the next task. Implementation has started with the transport/archive foundation; project integration and live acceptance remain open. It is not activated.

**Current integration:** [implemented behavior and remaining limits](docs/reference/IMPLEMENTATION_STATUS.md). This status page supersedes older dated candidate statements; [Windows recovery recipes](docs/reference/WINDOWS_E_DRIVE_RECOVERY.md) are preserved in the repository.

JARVIS V1 is a personal, voice-first intelligent assistant built research-first around explicit JARVIS-owned truth, authority, memory, and execution boundaries, with an owner-approved north star of becoming a governed autonomous self-managing personal intelligence runtime.

The previous `gkgajendra0/JARVIS` repository is engineering reference only. JARVIS V1 does not import it or depend on it at runtime.

## Current production status

This section is a brief guide, not the acceptance ledger:

- Core conversation, wake/audio, vision, identity and safe capability runtime have
  accepted bounded foundations.
- Step 4 personal memory is **BOUNDED**: encrypted storage and explicit memory
  operations work; automatic durable admission remains **disabled**. The normal
  voice app now provides an opt-in, owner-consented context path.
- Durable Work/DBOS, Hands, Self-Awareness and deterministic repair foundations
  have accepted scopes. Autonomous engineering Phases 2–10A are accepted to their
  documented boundaries; this does **not** mean fully autonomous production JARVIS.
- The owner-facing personalized, naturally context-aware assistant (CAP-053)
  is **PARTIAL**: saved-preference recall, natural correction and restart
  persistence have bounded owner acceptance. Broader advice quality, natural
  learning and seamless owner-speaking follow-ups remain open.
- Step 8 remains next in the numbered product sequence.

For exact accepted, deferred and production state, consult
[Project State](docs/PROJECT_STATE.md) and
[Current Architecture](docs/CURRENT_ARCHITECTURE.md). Research/draft PRs do not
change production reality.

### Opt-in personal context (owner acceptance, 21 October 2026)

PR #294 supplies the first active personal-context path **inside the normal voice
app**. The owner confirmed recall, correction, restart and restoration in the
[bounded acceptance record](docs/acceptance/PERSONAL_MEMORY_OWNER_ACCEPTANCE_2026-10-21.md).
This is a partial personal-intelligence release. See the
[implementation and acceptance report](docs/research/PERSONAL_INTELLIGENCE_RUNTIME_2026-10-20.md).

Using the existing configured Windows installation:

```powershell
.\.venv\Scripts\jarvis-voice.exe --personal-context apply
```

Ordinary personal questions can use current eligible saved facts without saying
"search memory". Each personal request requires fresh Windows Hello consent.
After one personal answer or explicit memory change, JARVIS returns to wake mode;
wake it again for the next request. This release does not promote speaker-shadow
scores into identity authority. Remember/correct/forget remain explicit commands.
Empty memory produces no invented personal profile. English, Hindi and Hinglish
are priority forms; broader spoken usefulness still needs qualification.

Use `--personal-context off` to disable this new automatic path. Default is OFF.
APPLY enables canonical memory and suppresses transcript logging/SDK recording for
that process without editing the saved machine profile. It reuses the configured
realtime provider and encrypted canonical database; no extra HTTP selector model
or new dependency is needed. Existing explicit memory behavior remains available
under its existing configuration when automatic context is OFF.

## Setup

Python 3.11 or newer is required. In Windows PowerShell:

```powershell
winget install LiveKit.LiveKitCLI
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

When pulling a revision that changes `pyproject.toml`, refresh the editable install in the existing virtual environment before running the new code. For functionality that uses local semantic retrieval, install the retrieval extra as well:

```powershell
python -m pip install -e ".[dev,retrieval]"
```

Production JARVIS uses **one active cloud-AI provider/account at a time** through `JARVIS_AI_PROVIDER`. Keep only the required secret locally in the Windows environment. Example:

```powershell
$env:JARVIS_AI_PROVIDER = "gemini"
$env:GOOGLE_API_KEY = "your-google-ai-studio-key"
```

or:

```powershell
$env:JARVIS_AI_PROVIDER = "openai"
$env:OPENAI_API_KEY = "your-openai-api-key"
```

Different capability roles may use different model IDs inside the selected provider family. Production subsystems do not silently select a second cloud provider on failure.

Bounded provider-assisted semantic recall is opt-in, for example:

```powershell
$env:JARVIS_MEMORY_ENABLED = "true"
$env:JARVIS_MEMORY_SEMANTIC_RECALL_MODEL = "gemini-3.5-flash"
```

This enables the governed explicit `recall_memory` path; it does **not** enable automatic semantic-memory injection into normal conversation.

API keys must stay local. Do not commit `.env` or paste secrets into source. Normal machine settings are persisted by `jarvis-setup`; `.env.example` is reference only.

## Run

Baseline:

```powershell
python -m jarvis
```

Diagnostic LiveKit voice harness:

```powershell
lk agent console src/jarvis/voice/entrypoint.py
```

Normal production runtime:

```powershell
jarvis-voice
```

Run `jarvis-setup` to persist the wake model, stable audio selectors, active cloud-AI provider, and other non-secret machine settings. Idle wake detection remains local; cloud realtime conversation starts only after an accepted wake.

## Optional visual companion — dynamic context stage (candidate)

An experimental **read-only, local-only** interface lives in `src/jarvis/ui/`.
It is a feature-branch candidate and not Step-13 HUD acceptance. By default
it opens in a quiet ambient state: an animated JARVIS orb, a minimal shell,
and **no permanent dashboard grid**. Use the left rail or the local display
field to bring up a Work, Research, Files, Vision or System context panel;
panels can be pinned or dismissed. The **PREVIEW** button displays explicitly
labeled fictional examples and never claims live data.

Standalone launch (no API key, cloud call or Jarvis voice process required):

```powershell
python -m jarvis.ui --open-browser
# Or, after pip install -e ".[dev]":
jarvis-ui --open-browser
```

Open `http://127.0.0.1:8765/` in your desktop browser.

To run the same visual companion inside an existing `jarvis-voice` process
and see **real bounded** voice lifecycle, accepted-turn topic hints and
redacted WorkItem states, opt in in the same PowerShell session:

```powershell
$env:JARVIS_UI_ENABLED = "true"
$env:JARVIS_UI_PORT = "8765"
jarvis-voice
```

Do **not** also start `jarvis-ui` on the same port. No camera frames, raw
voice/audio, personal memory, unapproved computer actions, fake email/calendar
events or sensitive Work descriptions are sent to the visual companion.
The browser is an observation and panel-selection surface, **not** a text
command channel to the Jarvis AI. For actual actions, use normal governed
Jarvis voice/tools. A missing UI must not disrupt voice or Work.

Now connected (when enabled in the actual voice process): lifecycle state,
canonical Work status, sanitized vision-camera diagnostics, Self Model component
health, completed real-web research source links and governed capability
outcomes. These are **observation-only** channels: camera video, private
documents, personal memory and browser-origin execution are NOT enabled.

For the actual owner's Windows live acceptance sequence (including how to
avoid colliding with ongoing Gemini-fallback development), see the
[live UI acceptance runbook](docs/reference/JARVIS_DYNAMIC_UI_LIVE_ACCEPTANCE_2026-10-23.md).
The animated central orb now projects outward into left/right holograms with
energy beams, reversible collapse, a radial panel selector, and Cinematic /
Balanced / Eco performance settings.

See [owner requirements and phased UI acceptance](docs/reference/JARVIS_DYNAMIC_CONTEXT_UI_REQUIREMENTS_2026-10-23.md).
Real Windows visual/performance acceptance and source-grounded topic-specific
panel integration are further work; green CI is not an owner-machine pass.

## Development supervisor

`jarvis-dev` is a development-only wrapper around `jarvis-voice`:

```powershell
jarvis-dev
```

It watches `origin/main`, requires explicit owner approval before a fast-forward update/restart, verifies the restarted runtime reaches readiness, and restores the previous last-known-good revision if the update fails readiness. It does not give normal JARVIS autonomous repository-update authority.

## Validate

Local baseline:

```powershell
python -m pytest
ruff check .
ruff format --check .
```

Protected CI additionally covers Playwright Chromium provisioning/smoke, Windows Hands dependencies/regressions, Windows DPAPI, and Windows Hello normal/self-contained helper contracts. Hardware/provider behavior that CI cannot prove still requires real owner-machine acceptance.

## Documentation

**Start with [Documentation Index and Product Audit](docs/README.md).**
It identifies the canonical product documents, supporting technical designs,
current research, exact archival records, and the source of truth for each
kind of decision.

- [Product and personal intelligence contract](docs/PRODUCT.md)
- [Autonomous and personal intelligence North Star](docs/AUTONOMOUS_SELF_MANAGEMENT_MASTER_PLAN.md)
- [Roadmap](docs/ROADMAP.md)
- [Current execution plan](docs/CURRENT_PLAN.md)
- [Accepted runtime architecture](docs/CURRENT_ARCHITECTURE.md)
- [Accepted/deferred state and historical evidence](docs/PROJECT_STATE.md)
- [Quality and promotion gates](docs/QUALITY_GATES.md)

Historical documents are preserved by exact Git objects under
`docs/archive/` and navigable from the index, rather than competing with
the current product plan.
