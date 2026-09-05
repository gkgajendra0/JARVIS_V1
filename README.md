# JARVIS V1

JARVIS V1 is a clean implementation of a personal, voice-first JARVIS assistant.

The previous `gkgajendra0/JARVIS` repository is engineering reference only. JARVIS
V1 does not import it or depend on it at runtime.

Steps 1, 2, 2.5, and 3 are accepted. Step 4 — Live Context and Personal Memory — is
active. See `docs/CURRENT_PLAN.md` for the current implementation phase.

## Setup

Python 3.11 or newer is required. In Windows PowerShell:

```powershell
winget install LiveKit.LiveKitCLI
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

Production JARVIS uses **one active cloud-AI provider/account at a time**. Configure
that provider once, then keep only its required API key available. For example, with
Gemini:

```powershell
$env:JARVIS_AI_PROVIDER = "gemini"
$env:GOOGLE_API_KEY = "your-google-ai-studio-key"
```

Or with OpenAI:

```powershell
$env:JARVIS_AI_PROVIDER = "openai"
$env:OPENAI_API_KEY = "your-openai-api-key"
```

Different capability roles may use different model IDs within the selected provider
family (for example realtime voice versus structured extraction), but production
subsystems may not independently select a second cloud-AI provider. Research bake-offs
may compare providers without changing this production rule.

API keys must stay local. Do not commit `.env` or paste keys into source code. Normal
machine settings are persisted by `jarvis-setup`; secrets remain in the Windows
user/process environment. `.env.example` is a reference and `.env` is not loaded
automatically.

Existing installations that still contain `JARVIS_REALTIME_PROVIDER` remain readable
for migration compatibility. New configuration must use `JARVIS_AI_PROVIDER`.

## Run the Step-0 baseline

```powershell
python -m jarvis
```

## Run Step-1 voice mode

```powershell
lk agent console src/jarvis/voice/entrypoint.py
```

The local console uses the computer microphone and speakers. Voice mode fails before
session start if the active provider's API key is absent. JARVIS does not silently
fall back between OpenAI and Gemini.

## Run the production wake runtime

Normal installed-machine startup is:

```powershell
jarvis-voice
```

Run `jarvis-setup` to persist the wake model, stable audio selectors, active cloud-AI
provider, and other non-secret machine settings. Idle audio remains local; cloud
realtime conversation begins only after an accepted wake detection. `lk agent console`
remains available as a diagnostic harness.

## Run the development supervisor

`jarvis-dev` is a development-only wrapper around the accepted `jarvis-voice`
runtime. It keeps JARVIS running, watches the configured remote branch, and requires
one explicit owner approval before applying a fast-forward update and restarting the
runtime.

```powershell
jarvis-dev
```

The normal default is `origin/main`. A temporary branch can be selected while testing
the supervisor itself:

```powershell
$env:JARVIS_DEV_BRANCH = "feature/jarvis-dev-supervisor"
jarvis-dev
```

When an update becomes available, JARVIS speaks a fixed approval question through a
dedicated scripted-TTS adapter, while the realtime session is used only to capture and
transcribe the owner's response. A narrow deterministic parser accepts an explicit Yes
or No at the start of a natural finalized reply, such as `Yes, sir. I will do it.` or
`No, leave it.`, while ambiguous or contradictory speech, timeout, or an unavailable
voice-control channel means No. The realtime model does not generate the approval
wording and never decides whether the update was approved.

The supervisor uses an authenticated loopback-only control channel, refuses dirty
working trees and non-fast-forward updates, requests a clean in-process shutdown
before OS-level fallbacks, and does not continuously restart a crashing child process.

## Validate

```powershell
python -m pytest
ruff check .
ruff format --check .
```

Hardware-dependent owner-PC acceptance is recorded under `docs/research/` rather than
being inferred from CI.

## Documentation

- [Product definition](docs/PRODUCT.md)
- [Current plan](docs/CURRENT_PLAN.md)
- [Roadmap](docs/ROADMAP.md)
- [Current architecture](docs/CURRENT_ARCHITECTURE.md)
- [Quality gates](docs/QUALITY_GATES.md)
- [Research records](docs/research/README.md)
- [Architecture decisions](docs/decisions/README.md)
