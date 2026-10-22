# JARVIS V1

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

[Personal-intelligence enablement and validation guide](docs/PERSONAL_INTELLIGENCE_ENABLEMENT.md) records defaults, the earlier accepted opt-in test, normal-app launch modes and the required enabled testing for dependent milestones.

### Automatic learning candidate — not yet accepted

Ordinary conversational learning is implemented in the normal app on draft PR#295 and software-verified (all7checks on c03666b7 passed). The owner directed development to move forward and extended quota-bound provider qualification is deferred. Learning remains OFF by default and unpromoted; full quality/resource and normal-app owner acceptance are still open. See the [implementation handoff](docs/research/PERSONAL_AUTO_LEARNING_IMPLEMENTED_HANDOFF_2026-10-22.md) and [preserved results](docs/research/PERSONAL_AUTO_LEARNING_QUALIFICATION_2026-10-22.md).

For a later reviewed candidate test, the whole normal app command is:

```powershell
.\.venv\Scripts\jarvis-voice.exe --personal-learning apply
```

One Windows Hello opens a private owner-operated session for at most 15 minutes, with 5-minute idle expiry. Important eligible standard facts can be learned without per-fact questions. This does not verify every later speaker. Fresh wakes can reuse an active grant, but private provider history still retires after one personal answer. Forget suppresses automatic learning of that category until separately re-enabled.

Stop JARVIS to revoke the grant. Use `--personal-learning off --personal-context apply` to retain accepted exact-consent context behavior. Schema 3 requires a compatible build; do not downgrade or delete memory data. Existing production settings were not changed.

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
