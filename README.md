# JARVIS V1

JARVIS V1 is a personal, voice-first intelligent assistant built research-first around explicit JARVIS-owned truth, authority, memory, and execution boundaries.

The previous `gkgajendra0/JARVIS` repository is engineering reference only. JARVIS V1 does not import it or depend on it at runtime.

## Current production status

- Steps 0–3: **DONE**.
- Step 4 memory/context: **BOUNDED**.
- Step 5 provider resilience: **BOUNDED**.
- Step 6 current research/truthfulness: **BOUNDED**.
- Step 7 governed capability runtime + safe local reads: **DONE**.
- JARVIS Hands / browser / file / device foundations: **PARTIAL** for later Steps 9/10/12.
- Pocket 3 native OWNER tracking/recovery: **ACCEPTED** for the current defined scope.
- Self-Awareness: **ACCEPTED FOUNDATION**.
- Persistent Concurrent Work Orchestration: **ACCEPTED FOUNDATION**.
- Deterministic repair framework + R2 runtime crash/hang recovery: **ACCEPTED FOUNDATION**.
- Self-Repair / Self-Evolution program: **ACTIVE — Phase 1H foundation hardening precedes Phase 2 RepairKnowledge**.
- Step 8 notes/tasks/reminders/scheduling remains the **next numbered product slice** when numbered roadmap work resumes.

Current accepted/deferred/superseded/rejected truth is centralized in
`docs/PROJECT_STATE.md`.

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

Current documentation is intentionally small:

- [Product definition and capability catalogue](docs/PRODUCT.md)
- [Roadmap](docs/ROADMAP.md)
- [Current accepted architecture](docs/CURRENT_ARCHITECTURE.md)
- [Current active plan](docs/CURRENT_PLAN.md)
- [Canonical project-state ledger](docs/PROJECT_STATE.md)
- [Quality gates](docs/QUALITY_GATES.md)
- [Self-Repair and Self-Evolution master plan](docs/SELF_REPAIR_AND_EVOLUTION_MASTER_PLAN.md)

Detailed old experiments, superseded ADRs, benchmark notes and acceptance transcripts
remain available through Git history rather than competing with current truth.
