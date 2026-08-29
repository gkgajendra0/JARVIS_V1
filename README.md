# JARVIS V1

JARVIS V1 is a clean implementation of a personal, voice-first JARVIS assistant.

The previous `gkgajendra0/JARVIS` repository is engineering reference only. JARVIS
V1 does not import it or depend on it at runtime.

Steps 1 and 2 are accepted. Current active work: **Step 3 — Identity, Graduated Trust,
Authority, and Observability Foundation (research only)**.

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

## Run the Step-2 wake runtime

Step 2 uses one roomless local microphone/speaker runtime. It requires a trained
LiveKit-compatible `JARVIS` ONNX classifier; no unverified model is committed.

```powershell
$env:JARVIS_WAKE_MODEL_PATH = "C:\path\to\jarvis.onnx"
$env:JARVIS_AUDIO_INPUT_DEVICE = "index:57"
$env:JARVIS_AUDIO_OUTPUT_DEVICE = "index:45"
$env:JARVIS_REALTIME_PROVIDER = "gemini"
$env:GOOGLE_API_KEY = "your-google-ai-studio-key"
jarvis-voice
```

Use a unique device name or `index:<PortAudio index>` from the local
`rtc.MediaDevices` enumeration. Indices shown by `lk agent console --list-devices` use
a different enumeration and must not be copied into Step-2 configuration. Explicit
indices are necessary when Windows exposes the same device name through multiple host
APIs and may need to be rechecked after audio-driver or device changes.
Idle audio remains local; the selected realtime provider starts only after an accepted
wake detection. `lk agent console` remains available as a Step-1 diagnostic harness.

## Validate

```powershell
python -m pytest
ruff check .
ruff format --check .
```

Step 2 is accepted after automated validation and successful real Windows wake,
conversation, idle, and re-wake use. Extended TV/endurance/device-failure trials were
explicitly waived and remain documented as unverified residual risks.

## Documentation

- [Product definition](docs/PRODUCT.md)
- [Current plan](docs/CURRENT_PLAN.md)
- [Roadmap](docs/ROADMAP.md)
- [Current architecture](docs/CURRENT_ARCHITECTURE.md)
- [Quality gates](docs/QUALITY_GATES.md)
- [Research records](docs/research/README.md)
- [Architecture decisions](docs/decisions/README.md)
