# JARVIS V1

JARVIS V1 is a clean implementation of a personal, voice-first JARVIS assistant.

The previous `gkgajendra0/JARVIS` repository is engineering reference only. JARVIS
V1 does not import it or depend on it at runtime.

Current active work: **Step 1 — Natural Conversational Core (implementation and
human-testing stage)**.

## Setup

Python 3.11 or newer is required. In Windows PowerShell:

```powershell
winget install LiveKit.LiveKitCLI
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
$env:OPENAI_API_KEY = "your-api-key"
```

The API key must stay local. Do not commit `.env` or paste the key into source code.
The application reads process environment variables directly; `.env.example` is a
reference and `.env` is not loaded automatically.

## Run the Step-0 baseline

```powershell
python -m jarvis
```

## Run Step-1 voice mode

```powershell
lk agent console src/jarvis/voice/entrypoint.py
```

The local console uses the computer microphone and speakers. OpenAI remains the
default provider. For cost-optimized development with Gemini Live, configure:

```powershell
$env:JARVIS_REALTIME_PROVIDER = "gemini"
$env:GOOGLE_API_KEY = "your-google-ai-studio-key"
lk agent console src/jarvis/voice/entrypoint.py
```

Optional settings are documented in `.env.example`. Voice mode fails before session
start if the selected provider's API key is absent. Provider selection is explicit;
JARVIS does not silently fall back between OpenAI and Gemini.

## Validate

```powershell
python -m pytest
ruff check .
ruff format --check .
```

Step 1 is not complete until the documented real Windows English/Hindi/Hinglish,
interruption, failure, and shutdown tests pass.

## Documentation

- [Product definition](docs/PRODUCT.md)
- [Current plan](docs/CURRENT_PLAN.md)
- [Roadmap](docs/ROADMAP.md)
- [Current architecture](docs/CURRENT_ARCHITECTURE.md)
- [Quality gates](docs/QUALITY_GATES.md)
- [Research records](docs/research/README.md)
- [Architecture decisions](docs/decisions/README.md)
